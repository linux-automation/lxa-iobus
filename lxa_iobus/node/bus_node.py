import asyncio
import concurrent
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

from .base_node import LxaBaseNode

DEFAULT_TIMEOUT = 1

logger = logging.getLogger("lxa_iobus.bus_node")


class LxaBusNode(LxaBaseNode):
    def __init__(self, lxa_network, lss_address, node_id):
        super().__init__(lss_address)

        self.lxa_network = lxa_network
        self.node_id = node_id

        self._pending_message = None
        self._lock = asyncio.Lock()

    def __repr__(self):
        return f"<LxaBusNode(address={self.address}, node_id={self.node_id})>"

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
