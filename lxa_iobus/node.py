import concurrent
import asyncio
import logging
import struct
import os

from lxa_iobus.lpc11xxcanisp.firmware.versions import FIRMWARE_VERSIONS
from lxa_iobus.node_input import Input, Output, ADC
from lxa_iobus.node_drivers import drivers
from lxa_iobus.utils import array2int

from lxa_iobus.canopen import (
    SDO_TRANSFER_TYPE_DATA_WITH_SIZE,
    gen_sdo_initiate_download,
    gen_sdo_segment_download,
    gen_sdo_initiate_upload,
    SDO_TRANSFER_TYPE_SIZE,
    gen_sdo_segment_upload,
    SDO_Abort,
)

DEFAULT_TIMEOUT = 1

logger = logging.getLogger('lxa_iobus.node')


class LxaNode:
    def __init__(self, lxa_network, lss_address, node_id):
        self.lxa_network = lxa_network
        self.lss_address = lss_address
        self.node_id = node_id

        self._pending_message = None
        self._lock = asyncio.Lock()

        self.address = '.'.join(
            ['{0:08}'.format(i) for i in self.lss_address]
        )

        self.inputs = []
        self.outputs = []
        self.adcs = []

        for driver_class in drivers:
            name = driver_class.match(self)

            if name:
                self.name = name
                self.driver = driver_class(self)

                break

    def __repr__(self):
        return '<LxaNode(address={}, node_id={}, driver={})>'.format(
            self.address,
            self.node_id,
            repr(self.driver),
        )

    def set_sdo_response(self, message):
        if(self._pending_message and
           not self._pending_message.done() and
           not self._pending_message.cancelled()):

            self._pending_message.set_result(message)

    async def _send_sdo_message(self, message, timeout=DEFAULT_TIMEOUT):
        self._pending_message = concurrent.futures.Future()
        async_fut = asyncio.futures.wrap_future(self._pending_message)

        await self.lxa_network.send_message(message)

        try:
            await asyncio.wait_for(
                async_fut,
                timeout=timeout,
                loop=self.lxa_network.loop,
            )

            return async_fut.result()

        except asyncio.TimeoutError:
            return None

    async def sdo_read(self, index, sub_index, timeout=DEFAULT_TIMEOUT):
        async with self._lock:
            # Depending on the answer we do:
            #  * normal(Segment) transfare > 4 byte: multiple transactions
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
            if response.type == 'abort':
                raise SDO_Abort(
                    node_id=response.node_id,
                    index=response.index,
                    sub_index=response.subindex,
                    error_code=response.error_code
                )
            # Not the package we were expecting
            if not response.type == 'initiate_upload':
                raise Exception('Got wrong answer: {}'.format(response.type))

            if response.index != index or response.subindex != sub_index:
                raise Exception(
                    'Got answer to the wrong data object: Is: {}-{} , Should: {}-{}'.format(  # NOQA
                        response.index,
                        response.subindex,
                        index,
                        sub_index,
                    ),
                )

            # We get a package where the size field is used
            if response.readable_transfer_type == 'DataWithSize':
                return response.data[0:4-response.number_of_bytes_not_used]

            # We got a package data uses the package length as size
            # Is not used in the firmware
            if response.readable_transfer_type == 'DataNoSize':
                return response.data

            # Segmented transfare
            # We get the size of data to come
            if not response.readable_transfer_type == 'Size':
                raise Exception('Unknown transfare type')

            transfer_size = struct.unpack('<L', response.data)[0]

            logger.debug('Long SDO read: size {}'.format(transfer_size))

            PACKAGE_SIZE = 7
            collected_data = b''
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

                if response.type == 'abort':
                    raise SDO_Abort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == 'upload_segment':
                    raise Exception(
                        'Got wrong answer: {}'.format(response.type))

                if not toggle == response.toggle:
                    Exception(
                        'Toggle bit does not match: is: {}, should: {}'.format(
                            response.toggle,
                            toggle,
                        ),
                    )

                # Flip toggle
                toggle ^= True

                seg_data_end = PACKAGE_SIZE-response.number_of_bytes_not_used
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

                if response.type == 'abort':
                    raise SDO_Abort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == 'initiate_download':
                    raise Exception(
                        'Got wrong answer: {}'.format(response.type))

                return

            ########################################
            # Segment transfare
            transfer_size = len(data)

            # Send the length of the transfare
            message = gen_sdo_initiate_download(
                node_id=self.node_id,
                index=index,
                sub_index=sub_index,
                data=struct.pack('<L', transfer_size),
                type=SDO_TRANSFER_TYPE_SIZE,
            )

            response = await self._send_sdo_message(
                message,
                timeout=timeout,
            )

            if response is None:
                raise TimeoutError

            if response.type == 'abort':
                raise SDO_Abort(
                    node_id=response.node_id,
                    index=response.index,
                    sub_index=response.subindex,
                    error_code=response.error_code,
                )

            if not response.type == 'initiate_download':
                raise Exception('Got wrong answer: {}'.format(response.type))

            PACKAGE_SIZE = 7
            segment = 0
            toggle = False

            while transfer_size > 0:
                offset = segment*PACKAGE_SIZE
                length = min(transfer_size, PACKAGE_SIZE)

                # Is this last package
                complete = False

                if length < PACKAGE_SIZE:
                    complete = True

                if len(data) == offset+length:
                    complete = True

                message = gen_sdo_segment_download(
                    node_id=self.node_id,
                    toggle=toggle,
                    complete=complete,
                    seg_data=data[offset:offset+length],
                )

                response = await self._send_sdo_message(
                    message,
                    timeout=timeout,
                )

                if response is None:
                    raise TimeoutError

                if response.type == 'abort':
                    raise SDO_Abort(
                        node_id=response.node_id,
                        index=response.index,
                        sub_index=response.subindex,
                        error_code=response.error_code,
                    )

                if not response.type == 'download_segment':
                    raise Exception(
                        'Got wrong answer: {}'.format(response.type))

                if complete:
                    return

                segment += 1
                toggle ^= True
                transfer_size -= length

            # Maybe the complete flag is not corectly set
            raise Exception('Something went wrong with segmented download')

    # public API ##############################################################
    async def ping(self, timeout=DEFAULT_TIMEOUT):
        return await self.sdo_read(
            index=0x2000,
            sub_index=0,
            timeout=timeout,
        )

    async def get_info(self):
        if hasattr(self, '_info') and self._info is not None:
            return self._info

        # node info ###########################################################
        device_name = await self.sdo_read(0x1008, 0)
        hardware_version = await self.sdo_read(0x1009, 0)
        software_version = await self.sdo_read(0x100a, 0)

        # check for updates
        update_name = ''

        if(self.driver.__class__ in FIRMWARE_VERSIONS):
            raw_version = software_version.decode().split(' ')[1]
            version_tuple = tuple([int(i) for i in raw_version.split('.')])

            if version_tuple < FIRMWARE_VERSIONS[self.driver.__class__][0]:
                update_name = os.path.basename(
                    FIRMWARE_VERSIONS[self.driver.__class__][1])

        self._info = {
            'device_name': device_name.decode(),
            'address': str(self.address),
            'hardware_version': hardware_version.decode(),
            'software_version': software_version.decode(),
            'update_name': update_name,
        }

        # pin info ############################################################
        protocol_count = await self.sdo_read(0x2000, 0)
        protocol_count = array2int(protocol_count)
        protocols = []

        for i in range(protocol_count):
            tmp = await self.sdo_read(0x2000, i+1)
            tmp = array2int(tmp)
            protocols.append(tmp)

        # Inputs
        if 0x2101 in protocols:
            channel_count = await self.sdo_read(0x2101, 0)

            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Input(self.address, i, self)
                await channel.get_pin_count()

                self.inputs.append(channel)

        # Output
        if 0x2100 in protocols:
            channel_count = await self.sdo_read(0x2100, 0)
            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Output(self.address, i, self)
                await channel.get_pin_count()

                self.outputs.append(channel)

        # ADCs
        if 0x2adc in protocols:
            channel_count = await self.sdo_read(0x2adc, 0)
            channel_count = int(array2int(channel_count))

            for i in range(channel_count):
                channel = ADC(self.address, i, self)
                await channel.get_config()
                self.adcs.append(channel)

        return self._info

    async def get_locator_state(self):
        raw_locator_state = await self.sdo_read(0x210c, 1)

        return array2int(raw_locator_state)

    async def set_locator_state(self, state):
        if state:
            state = b'\x01\x00\x00\x00'

        else:
            state = b'\x00\x00\x00\x00'

        await self.sdo_write(0x210c, 1, state)

    async def invoke_isp(self):
        try:
            await self.sdo_write(0x2b07, 0, struct.pack('I', 0x12345678))

        except TimeoutError:
            pass
