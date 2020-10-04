import struct

from canopen.sdo.exceptions import SdoCommunicationError


def array2int(a):
    out = 0

    for i in range(len(a)):
        out |= a[i] << (i*8)

    return out


def int2array4(c):
    out = [0]*4

    for i in range(4):
        out[i] = 0xff & (c >> (i*8))

    return out


class Input:
    INDEX = 0x2101

    def __init__(self, address, channel, server):
        self.address = address
        self.channel = channel
        self.server = server

    async def get_pin_count(self):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        upload = self.server.canopen_listener.nodes.upload
        # end FIXME

        pin_count = await canopen_serialize(
            upload,
            self.address,
            self.INDEX,
            (self.channel*2)+1,
        )

        pin_count = array2int(pin_count)
        self.pins = pin_count

    async def read(self):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        upload = self.server.canopen_listener.nodes.upload
        # end FIXME

        tmp = await canopen_serialize(
            upload,
            self.address,
            self.INDEX,
            (self.channel*2+2),
        )

        return array2int(tmp)

    def info(self):
        return {
            "channel": self.channel,
            "pins": self.pins,
        }


class Output(Input):
    INDEX = 0x2100

    def __init__(self, address, channel, server):
        self.address = address
        self.channel = channel
        self.server = server
        self.output_state = 0

    async def write(self, mask, data):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        download = self.server.canopen_listener.nodes.download
        # end FIXME

        self.output_state = (self.output_state & (~mask)) | (data & mask)
        data = int2array4(((mask & 0xffff) << 16) | (data & 0xffff))

        await canopen_serialize(
            download,
            self.address,
            self.INDEX,
            (self.channel*2+2),
            data,
        )

    async def restore_state(self):
        await self.write(0xffff, self.output_state)


class ADC:
    INDEX = 0x2adc

    def __init__(self, address, channel, server):
        self.address = address
        self.channel = channel
        self.server = server
        self.scale = 1
        self.offset = 0

    async def get_config(self):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        upload = self.server.canopen_listener.nodes.upload
        # end FIXME

        scale = await canopen_serialize(
            upload,
            self.address,
            self.INDEX,
            ((self.channel+1)<<2)+2,
        )
        scale = struct.unpack( "<f", scale)[0]

        offset = await canopen_serialize(
            upload,
            self.address,
            self.INDEX,
            ((self.channel+1)<<2)+1,
        )
        offset = struct.unpack( "<i", offset)[0]

        self.offset = offset
        self.scale = scale

    async def read(self):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        upload = self.server.canopen_listener.nodes.upload
        # end FIXME

        tmp = await canopen_serialize(
            upload,
            self.address,
            self.INDEX,
            ((self.channel+1)<<2),
        )

        tmp = struct.unpack( "<H", tmp)[0]

        return (tmp+self.offset)*self.scale

    def info(self):
        return {
            "channel": self.channel,
            "scale": self.scale,
            "offset": self.offset,
        }


class Node:
    def __init__(self, address, server):
        self.address = address
        self.server = server
        self.inputs = []
        self.outputs = []
        self.adcs = []
        self.is_alive = True

    async def get_config(self):
        # FIXME: we need better architecture here!
        canopen_serialize = self.server.canopen_serialize
        upload = self.server.canopen_listener.nodes.upload
        # end FIXME

        protocol_count = await canopen_serialize(
            upload, self.address, 0x2000, 0)

        protocol_count = array2int(protocol_count)
        protocols = []

        for i in range(protocol_count):
            tmp = await canopen_serialize(upload, self.address, 0x2000, i+1)
            tmp = array2int(tmp)
            protocols.append(tmp)

        # Inputs
        if 0x2101 in protocols:
            channel_count = await canopen_serialize(
                upload, self.address, 0x2101, 0)

            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Input(self.address, i, self.server)
                await channel.get_pin_count()

                self.inputs.append(channel)

        # Output
        if 0x2100 in protocols:
            channel_count = await canopen_serialize(
                upload, self.address, 0x2100, 0)

            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Output(self.address, i, self.server)
                await channel.get_pin_count()

                self.outputs.append(channel)

        # ADCs
        if 0x2adc in protocols:
            channel_count = await canopen_serialize(
                upload, self.address, 0x2adc, 0)

            channel_count = int(array2int(channel_count))

            for i in range(channel_count):
                channel = ADC(self.address, i, self.server)
                await channel.get_config()
                self.adcs.append(channel)

    def info(self):
        inputs = []
        outputs = []
        adcs = []

        for ch in self.inputs:
            inputs.append(ch.info())

        for ch in self.outputs:
            outputs.append(ch.info())

        for ch in self.adcs:
            adcs.append(ch.info())

        return {
            "inputs": inputs,
            "outputs": outputs,
            "adcs": adcs,
            "alive": self.is_alive,
        }

    def invalidate_info_cache(self):
        self._info = None

    async def get_info(self):
        if hasattr(self, '_info') and self._info is not None:
            return self._info

        device_name = await self.server.canopen_serialize(
            self.server.canopen_listener.nodes.upload,
            self.address, 0x1008, 0,
        )

        hardware_version = await self.server.canopen_serialize(
            self.server.canopen_listener.nodes.upload,
            self.address, 0x1009, 0,
        )

        software_version = await self.server.canopen_serialize(
            self.server.canopen_listener.nodes.upload,
            self.address, 0x100a, 0,
        )

        self._info = {
            'device_name': device_name.decode(),
            'address': str(self.address),
            'hardware_version': hardware_version.decode(),
            'software_version': software_version.decode(),
        }

        return self._info

    # locator #################################################################
    async def get_locator_state(self):
        raw_locator_state = await self.server.canopen_serialize(
            self.server.canopen_listener.nodes.upload,
            self.address, 0x210c, 1)

        return array2int(raw_locator_state)

    async def set_locator_state(self, state):
        if state:
            state = b'\x01\x00\x00\x00'

        else:
            state = b'\x00\x00\x00\x00'

        await self.server.canopen_serialize(
            self.server.canopen_listener.nodes.download,
            self.address, 0x210c, 1, state)

    # isp #####################################################################
    async def invoke_isp(self):
        try:
            await self.server.canopen_serialize(
                self.server.canopen_listener.nodes.download,
                self.address, 0x2b07, 0, struct.pack('I', 0x12345678)
            )

        except SdoCommunicationError:
            pass
