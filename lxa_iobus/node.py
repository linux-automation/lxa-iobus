import asyncio
import concurrent
import contextlib
import logging
import os
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
from lxa_iobus.lpc11xxcanisp.firmware.versions import FIRMWARE_VERSIONS
from lxa_iobus.node_drivers import drivers
from lxa_iobus.node_input import ADC, Input, Output
from lxa_iobus.utils import array2int

DEFAULT_TIMEOUT = 1

logger = logging.getLogger("lxa_iobus.node")

VENDOR_VERSION_FIELDS = (
    (0x2001, 0, "protocol_version", int),
    (0x2001, 1, "board_version", int),
    (0x2001, 2, "serial_string", str),
    (0x2001, 3, "vendor_name", str),
    (0x2001, 5, "notes", str),
)


class LxaNode:
    def __init__(self, lxa_network, lss_address, node_id):
        self.lxa_network = lxa_network
        self.lss_address = lss_address
        self.node_id = node_id

        self._pending_message = None
        self._lock = asyncio.Lock()

        self.address = ".".join(["{:08x}".format(i) for i in self.lss_address])

        self.inputs = []
        self.outputs = []
        self.adcs = []
        self.locator_state = False

        for driver_class in drivers:
            name = driver_class.match(self)

            if name:
                self.name = name
                self.driver = driver_class(self)

                break

    def __repr__(self):
        return "<LxaNode(address={}, node_id={}, driver={})>".format(
            self.address,
            self.node_id,
            repr(self.driver),
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
            #  * normal(Segment) transfare > 4 byte: multiple transactions
            #  * expedited <= 4 byte: one transaction

            if len(data) <= 4:
                #######################################
                # expedited transfare
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
            # Segment transfare
            transfer_size = len(data)

            # Send the length of the transfare
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

    # public API ##############################################################
    async def ping(self, timeout=DEFAULT_TIMEOUT):
        try:
            raw_state = await self.sdo_read(
                index=0x210C,
                sub_index=1,
                timeout=timeout,
            )

            self.locator_state = array2int(raw_state) != 0

            return True

        except TimeoutError:
            return False

    async def get_info(self):
        if hasattr(self, "_info") and self._info is not None:
            return self._info

        # node info ###########################################################
        device_name = await self.sdo_read(0x1008, 0)
        hardware_version = await self.sdo_read(0x1009, 0)
        software_version = await self.sdo_read(0x100A, 0)

        # check for updates
        update_name = ""

        firmware = FIRMWARE_VERSIONS.get(self.driver.__class__)
        if firmware:
            raw_version = software_version.decode().split(" ")[1]
            version_tuple = tuple([int(i) for i in raw_version.split(".")])

            if version_tuple < firmware[0]:
                update_name = os.path.basename(firmware[1])
                logger.info("Found firmware update for {} to {}".format(self, ".".join(str(x) for x in firmware[0])))

        self._info = {
            "device_name": device_name.decode(),
            "address": str(self.address),
            "hardware_version": hardware_version.decode(),
            "software_version": software_version.decode(),
            "update_name": update_name,
        }

        # pin info ############################################################
        protocol_count = await self.sdo_read(0x2000, 0)
        protocol_count = array2int(protocol_count)
        protocols = []

        for i in range(protocol_count):
            tmp = await self.sdo_read(0x2000, i + 1)
            tmp = array2int(tmp)
            protocols.append(tmp)

        # Vendor-Specific version information
        if 0x2001 in protocols:
            for sdo, sub_idx, field_name, field_type in VENDOR_VERSION_FIELDS:
                # Do not fail when one of the reads to these
                # vendor-specific fields fails.
                try:
                    value = await self.sdo_read(sdo, sub_idx)
                except SdoAbort:
                    continue

                if field_type is int:
                    value = array2int(value)
                elif field_type is str:
                    value = value.decode()

                self._info[field_name] = value

        # Inputs
        if 0x2101 in protocols:
            channel_count = await self.sdo_read(0x2101, 0)

            channel_count = array2int(channel_count) // 2

            for i in range(channel_count):
                channel = Input(self.address, i, self)
                await channel.get_pin_count()

                self.inputs.append(channel)

        # Output
        if 0x2100 in protocols:
            channel_count = await self.sdo_read(0x2100, 0)
            channel_count = array2int(channel_count) // 2

            for i in range(channel_count):
                channel = Output(self.address, i, self)
                await channel.get_pin_count()

                self.outputs.append(channel)

        # ADCs
        if 0x2ADC in protocols:
            channel_count = await self.sdo_read(0x2ADC, 0)
            channel_count = array2int(channel_count)

            for i in range(channel_count):
                channel = ADC(self.address, i, self)
                await channel.get_config()
                self.adcs.append(channel)

        return self._info

    async def set_locator_state(self, state):
        cmd = b"\x01\x00\x00\x00" if state else b"\x00\x00\x00\x00"

        await self.sdo_write(0x210C, 1, cmd)
        self.locator_state = state

    async def invoke_isp(self):
        with contextlib.suppress(TimeoutError):
            await self.sdo_write(0x2B07, 0, struct.pack("I", 0x12345678))
