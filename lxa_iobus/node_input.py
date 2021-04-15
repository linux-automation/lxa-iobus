import struct

from lxa_iobus.utils import array2int, int2array


class Input:
    INDEX = 0x2101

    def __init__(self, address, channel, node):
        self.address = address
        self.channel = channel
        self.node = node

    async def get_pin_count(self):
        pin_count = await self.node.sdo_read(self.INDEX, (self.channel*2)+1)
        pin_count = array2int(pin_count)
        self.pins = pin_count

    async def read(self):
        tmp = await self.node.sdo_read(self.INDEX, (self.channel*2+2))

        return array2int(tmp)

    def info(self):
        return {
            "channel": self.channel,
            "pins": self.pins,
        }


class Output(Input):
    INDEX = 0x2100

    def __init__(self, address, channel, node):
        self.address = address
        self.channel = channel
        self.node = node
        self.output_state = 0

    async def write(self, mask, data):
        self.output_state = (self.output_state & (~mask)) | (data & mask)
        data = int2array(((mask & 0xffff) << 16) | (data & 0xffff))
        data = bytearray(data)

        await self.node.sdo_write(self.INDEX, (self.channel*2+2), data)

    async def restore_state(self):
        await self.write(0xffff, self.output_state)


class ADC:
    INDEX = 0x2adc

    def __init__(self, address, channel, node):
        self.address = address
        self.channel = channel
        self.node = node
        self.scale = 1
        self.offset = 0

    async def get_config(self):
        scale = await self.node.sdo_read(
            self.INDEX, ((self.channel+1) << 2)+2)

        scale = struct.unpack("<f", scale)[0]

        offset = await self.node.sdo_read(
            self.INDEX, ((self.channel+1) << 2)+1)

        offset = struct.unpack("<i", offset)[0]

        self.offset = offset
        self.scale = scale

    async def read(self):
        tmp = await self.node.sdo_read(self.INDEX, ((self.channel+1) << 2))
        tmp = struct.unpack("<H", tmp)[0]

        return (tmp+self.offset)*self.scale

    def info(self):
        return {
            "channel": self.channel,
            "scale": self.scale,
            "offset": self.offset,
        }
