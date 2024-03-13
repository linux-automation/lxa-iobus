import asyncio
import concurrent
import contextlib
import json
import logging
import struct

from lxa_iobus.canopen import (
    SDO_TRANSFER_TYPE_DATA_WITH_SIZE,
    SDO_TRANSFER_TYPE_SIZE,
    SdoAbort,
    gen_sdo_initiate_download,
    gen_sdo_initiate_upload,
    gen_sdo_segment_download,
    gen_sdo_segment_upload,
)

from .object_directory import ObjectDirectory
from .products import find_product

DEFAULT_TIMEOUT = 1

logger = logging.getLogger("lxa_iobus.node")


class LxaNode:
    def __init__(self, lxa_network, lss_address, node_id):
        self.lxa_network = lxa_network
        self.lss_address = lss_address
        self.node_id = node_id

        self._pending_message = None
        self._lock = asyncio.Lock()

        self.address = ".".join(["{:08x}".format(i) for i in self.lss_address])
        self.product = find_product(lss_address)
        self.name = self.product.name()

        self.locator_state = False

    def __repr__(self):
        return f"<LxaBusNode(address={self.address}, node_id={self.node_id})>"

    async def setup_object_directory(self):
        self.od = await ObjectDirectory.scan(
            self,
            self.product.ADC_NAMES,
            self.product.INPUT_NAMES,
            self.product.OUTPUT_NAMES,
        )

    def set_sdo_response(self, message):
        if self._pending_message and not self._pending_message.done() and not self._pending_message.cancelled():
            self._pending_message.set_result(message)

    async def _send_sdo_message(self, message, timeout=DEFAULT_TIMEOUT):
        self._pending_message = concurrent.futures.Future()
        async_fut = asyncio.futures.wrap_future(self._pending_message)

        await self.lxa_network.send_message(message)

        try:
            await asyncio.wait_for(
                async_fut,
                timeout=timeout,
            )

            return async_fut.result()

        except asyncio.TimeoutError:
            return None

    async def sdo_read(self, index, sub_index, timeout=DEFAULT_TIMEOUT):
        async with self._lock:
            # Depending on the answer we do:
            #  * normal(Segment) transfer > 4 byte: multiple transactions
            #  * expedited <= 4 byte: one transaction
            message = gen_sdo_initiate_upload(
                node_id=self.node_id,
                index=index,
                sub_index=sub_index,
            )

            response = await self._send_sdo_message(message, timeout=timeout)

            if response is None:
                raise TimeoutError

            # Something went wrong on the node side
            if response.type == "abort":
                raise SdoAbort(
                    node_id=response.node_id,
                    index=response.index,
                    sub_index=response.subindex,
                    error_code=response.error_code,
                )
            # Not the packet we were expecting
            if not response.type == "initiate_upload":
                raise Exception("Got wrong answer: {}".format(response.type))

            if response.index != index or response.subindex != sub_index:
                raise Exception(
                    "Got answer to the wrong data object: Is: {}-{} , Should: {}-{}".format(
                        response.index,
                        response.subindex,
                        index,
                        sub_index,
                    ),
                )

            # We get a packet where the size field is used
            if response.readable_transfer_type == "DataWithSize":
                return response.data[0 : 4 - response.number_of_bytes_not_used]

            # We got a packet data uses the packet length as size
            # Is not used in the firmware
            if response.readable_transfer_type == "DataNoSize":
                return response.data

            # Segmented transfer
            # We get the size of data to come
            if not response.readable_transfer_type == "Size":
                raise Exception("Unknown transfer type")

            transfer_size = struct.unpack("<L", response.data)[0]

            logger.debug("Long SDO read: size {}".format(transfer_size))

            PACKET_SIZE = 7
            collected_data = b""
            toggle = False

            while transfer_size > 0:
                message = gen_sdo_segment_upload(
                    node_id=self.node_id,
                    toggle=toggle,
                )

                response = await self._send_sdo_message(
                    message,
                    timeout=timeout,
                )

                if response is None:
                    raise TimeoutError

                if response.type == "abort":
                    raise SdoAbort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == "upload_segment":
                    raise Exception("Got wrong answer: {}".format(response.type))

                if toggle != response.toggle:
                    Exception(
                        "Toggle bit does not match: is: {}, should: {}".format(
                            response.toggle,
                            toggle,
                        ),
                    )

                # Flip toggle
                toggle ^= True

                seg_data_end = PACKET_SIZE - response.number_of_bytes_not_used
                seg_data = response.seg_data[0:seg_data_end]
                collected_data += seg_data
                transfer_size -= len(seg_data)

                if response.complete:
                    break

            return collected_data

    async def sdo_write(self, index, sub_index, data, timeout=DEFAULT_TIMEOUT):
        async with self._lock:
            #  * normal(Segment) transfer > 4 byte: multiple transactions
            #  * expedited <= 4 byte: one transaction

            if len(data) <= 4:
                #######################################
                # expedited transfer
                message = gen_sdo_initiate_download(
                    node_id=self.node_id,
                    index=index,
                    sub_index=sub_index,
                    data=data,
                    type=SDO_TRANSFER_TYPE_DATA_WITH_SIZE,
                )

                response = await self._send_sdo_message(
                    message,
                    timeout=timeout,
                )

                if response is None:
                    raise TimeoutError

                if response.type == "abort":
                    raise SdoAbort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == "initiate_download":
                    raise Exception("Got wrong answer: {}".format(response.type))

                return

            ########################################
            # Segment transfer
            transfer_size = len(data)

            # Send the length of the transfer
            message = gen_sdo_initiate_download(
                node_id=self.node_id,
                index=index,
                sub_index=sub_index,
                data=struct.pack("<L", transfer_size),
                type=SDO_TRANSFER_TYPE_SIZE,
            )

            response = await self._send_sdo_message(
                message,
                timeout=timeout,
            )

            if response is None:
                raise TimeoutError

            if response.type == "abort":
                raise SdoAbort(
                    node_id=response.node_id,
                    index=response.index,
                    sub_index=response.subindex,
                    error_code=response.error_code,
                )

            if not response.type == "initiate_download":
                raise Exception("Got wrong answer: {}".format(response.type))

            PACKET_SIZE = 7
            segment = 0
            toggle = False

            while transfer_size > 0:
                offset = segment * PACKET_SIZE
                length = min(transfer_size, PACKET_SIZE)

                # Is this last packet
                complete = False

                if length < PACKET_SIZE:
                    complete = True

                if len(data) == offset + length:
                    complete = True

                message = gen_sdo_segment_download(
                    node_id=self.node_id,
                    toggle=toggle,
                    complete=complete,
                    seg_data=data[offset : offset + length],
                )

                response = await self._send_sdo_message(
                    message,
                    timeout=timeout,
                )

                if response is None:
                    raise TimeoutError

                if response.type == "abort":
                    raise SdoAbort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == "download_segment":
                    raise Exception("Got wrong answer: {}".format(response.type))

                if complete:
                    return

                segment += 1
                toggle ^= True
                transfer_size -= length

            # Maybe the complete flag is not correctly set
            raise Exception("Something went wrong with segmented download")

    async def ping(self):
        try:
            if "locator" in self.od:
                self.locator_state = await self.od.locator.active()
            else:
                # The device does not advertise having an IOBus locator.
                # Try a CANopen standard endpoint instead
                await self.od.manufacturer_device_name.name()

            return True

        except TimeoutError:
            return False

    async def info(self):
        device_name = await self.od.manufacturer_device_name.name()
        hardware_version = await self.od.manufacturer_hardware_version.version()
        software_version = await self.od.manufacturer_software_version.version()

        # check for updates
        update_name = ""

        bundled_firmware_version = self.product.FIRMWARE_VERSION
        bundled_firmware_file = self.product.FIRMWARE_FILE

        if (bundled_firmware_version is not None) and (bundled_firmware_file is not None):
            raw_version = software_version.split(" ")[1]
            version_tuple = tuple([int(i) for i in raw_version.split(".")])

            if version_tuple < bundled_firmware_version:
                update_name = bundled_firmware_file

        info = {
            "device_name": device_name,
            "address": self.address,
            "hardware_version": hardware_version,
            "software_version": software_version,
            "update_name": update_name,
        }

        if "version_info" in self.od:
            info["protocol_version"] = await self.od.version_info.protocol()
            info["board_version"] = await self.od.version_info.board()
            info["serial_string"] = await self.od.version_info.serial()
            info["vendor_name"] = await self.od.version_info.vendor_name()
            info["notes"] = await self.od.version_info.notes()

            # If the json is not valid we just leave it as string instead
            with contextlib.suppress(json.decoder.JSONDecodeError):
                info["notes"] = json.loads(info["notes"])

        return info

    async def set_locator_state(self, state):
        if state:
            await self.od.locator.enable()
        else:
            await self.od.locator.disable()

        self.locator_state = state

    async def invoke_isp(self):
        # The node will enter the bootloader immediately,
        # so we will not receive a response and waiting for it will timeout.
        with contextlib.suppress(TimeoutError):
            await self.od.bootloader.enter()
