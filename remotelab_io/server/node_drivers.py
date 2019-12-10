class Pin:
    def __init__(self, node, pin_type, channel, bit):
        self.node = node
        self.pin_type = pin_type
        self.channel = channel
        self.bit = bit

    async def read(self):
        if self.pin_type == 'input':
            channel_state = await self.node.inputs[self.channel].read()
            pin_state = (channel_state >> self.bit) & 1

        elif self.pin_type == 'output':
            channel_state = await self.node.outputs[self.channel].read()
            pin_state = (channel_state >> self.bit) & 1

        elif self.pin_type == 'adc':
            pin_state = await self.node.adcs[channel].read()

        return pin_state

    async def write(self, value):
        value = value << self.bit
        mask = 1 << self.bit

        await self.node.outputs[self.channel].write(mask, value)


class NodeDriver:
    def __init__(self, node):
        self.node = node

    @property
    def pins(self):
        if not hasattr(self, '_pins'):
            self._pins = {}

        if not self._pins:
            self._pins = self.get_pins()

        return self._pins

    # public api ##############################################################
    @classmethod
    def match(cls, node):
        return True

    def get_name(self):
        return self.node.address

    def get_pins(self):
        return {}


class IOMuxDriver(NodeDriver):
    @classmethod
    def match(cls, node):
        if node.address.startswith('00000000.0000049a.00000001.'):
            return True

        return False

    def get_name(self):
        return 'IOMux-{}'.format(self.node.address.split('.')[-1])

    def get_pins(self):
        return {
            'led-0': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=0,
            ),
            'led-1': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=1,
            ),
        }


drivers = [
    IOMuxDriver,
    NodeDriver,  # catch all
]
