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
            pin_state = await self.node.adcs[self.channel].read()

        return pin_state

    async def write(self, value):
        value = value << self.bit
        mask = 1 << self.bit

        await self.node.outputs[self.channel].write(mask, value)


class NodeDriver:
    def __init__(self, node):
        self.node = node

    def _get_pins(self):
        return {}

    # public api ##############################################################
    @classmethod
    def match(cls, node):
        return node.address

    @property
    def pins(self):
        if not hasattr(self, '_pins'):
            self._pins = {}

        if not self._pins:
            self._pins = self._get_pins()

        return self._pins

    @property
    def is_alive(self):
        return self.node.is_alive


class IOMuxDriver(NodeDriver):
    def _get_pins(self):
        return {
            'OUT0': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=0,
            ),
            'OUT1': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=1,
            ),
            'OUT2': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=2,
            ),
            'OUT3': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=3,
            ),
            'LED': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=4,
            ),
            'IN0': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=0,
            ),
            'IN1': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=1,
            ),
            'IN2': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=2,
            ),
            'AIN0': Pin(
                node=self.node,
                pin_type='adc',
                channel=0,
                bit=None,
            ),
            'AIN1': Pin(
                node=self.node,
                pin_type='adc',
                channel=1,
                bit=None,
            ),
            'AIN2': Pin(
                node=self.node,
                pin_type='adc',
                channel=2,
                bit=None,
            ),
            'VIN': Pin(
                node=self.node,
                pin_type='adc',
                channel=3,
                bit=None,
            ),
        }

    @classmethod
    def match(cls, node):
        if node.address.startswith('00000000.00000002.00000002.'):
            return 'IOMux-{}'.format(node.address.split('.')[-1])
        return None


class PTXIOMuxDriver(NodeDriver):
    def _get_pins(self):
        return {
            'OUT0': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=0,
            ),
            'OUT1': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=1,
            ),
            'OUT2': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=2,
            ),
            'OUT3': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=3,
            ),
            'IN4': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=0,
            ),
            'IN5': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=1,
            ),
            'IN6': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=2,
            ),
            'AIN0': Pin(
                node=self.node,
                pin_type='adc',
                channel=0,
                bit=None,
            ),
            'AIN1': Pin(
                node=self.node,
                pin_type='adc',
                channel=1,
                bit=None,
            ),
            'AIN2': Pin(
                node=self.node,
                pin_type='adc',
                channel=2,
                bit=None,
            ),
            'VIN': Pin(
                node=self.node,
                pin_type='adc',
                channel=3,
                bit=None,
            ),
        }

    @classmethod
    def match(cls, node):
        if node.address.startswith('00000000.00000004.00000001.'):
            return 'PTXIOMux-{}'.format(node.address.split('.')[-1])
        return None


class EthMuxDriver(NodeDriver):
    def _get_pins(self):
        return {
            'SW': Pin(
                node=self.node,
                pin_type='output',
                channel=0,
                bit=0,
            ),
            'SW_IN': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=0,
            ),
            'SW_EXT': Pin(
                node=self.node,
                pin_type='input',
                channel=0,
                bit=1,
            ),
            'AIN0': Pin(
                node=self.node,
                pin_type='adc',
                channel=0,
                bit=None,
            ),
            'VIN': Pin(
                node=self.node,
                pin_type='adc',
                channel=1,
                bit=None,
            ),
        }

    @classmethod
    def match(cls, node):
        if node.address.startswith('00000000.00000003.00000004.'):
            return 'EthMux-{}'.format(node.address.split('.')[-1])
        return None


drivers = [
    IOMuxDriver,
    EthMuxDriver,
    PTXIOMuxDriver,
    NodeDriver,  # catch all
]
