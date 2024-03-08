class Pin:
    def __init__(self, node, pin_type, channel, bit):
        self.node = node
        self.pin_type = pin_type
        self.channel = channel
        self.bit = bit

    async def read(self):
        if self.pin_type == "input":
            channel_state = await self.node.inputs[self.channel].read()
            pin_state = (channel_state >> self.bit) & 1

        elif self.pin_type == "output":
            channel_state = await self.node.outputs[self.channel].read()
            pin_state = (channel_state >> self.bit) & 1

        elif self.pin_type == "adc":
            pin_state = await self.node.adcs[self.channel].read()

        return pin_state

    async def write(self, value):
        if self.pin_type != "output":
            raise RuntimeError("Attempted to write to an {} channel".format(self.pin_type))

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
        driver_addr = [cls.LSS_VENDOR, cls.LSS_PRODUCT, cls.LSS_REVISION]

        # Construct a human-readable device name from a driver
        # specific prefix and the zero-padded decimal serial number
        if node.lss_address[:3] == driver_addr:
            serial = "{:05}".format(node.lss_address[3])
            return cls.NAME_PREFIX + serial

        return None

    @property
    def pins(self):
        if not hasattr(self, "_pins"):
            self._pins = {}

        if not self._pins:
            self._pins = self._get_pins()

        return self._pins


class Iobus4Do3Di3AiDriver(NodeDriver):
    """LXA IOBus 4DO-3DI-3AI driver

    The following pins are provided by this driver:

      - OUT0-OUT3: Digital outputs
      - IN0-IN2: Digital inputs
      - VIN: IOBus supply voltage
      - AIN0-AIN2: Analog inputs
    """

    LSS_VENDOR = 0x507
    LSS_PRODUCT = 2
    LSS_REVISION = 3
    NAME_PREFIX = "4DO-3DI-3AI-00005."

    def _get_pins(self):
        return {
            "OUT0": Pin(self.node, "output", 0, 0),
            "OUT1": Pin(self.node, "output", 0, 1),
            "OUT2": Pin(self.node, "output", 0, 2),
            "OUT3": Pin(self.node, "output", 0, 3),
            "IN0": Pin(self.node, "input", 0, 0),
            "IN1": Pin(self.node, "input", 0, 1),
            "IN2": Pin(self.node, "input", 0, 2),
            "VIN": Pin(self.node, "adc", 0, None),
            "AIN0": Pin(self.node, "adc", 1, None),
            "AIN1": Pin(self.node, "adc", 2, None),
            "AIN2": Pin(self.node, "adc", 3, None),
        }


class PTXIOMuxDriver(NodeDriver):
    """PTXTAC CAN IO extender Driver

    This board is deprecated by the 4DO-3DI-3AI and does
    not get any firmware upgrades.

    The following pins are provided by this driver:

      - OUT0-OUT3: Digital outputs
      - IN4-IN6: Digital inputs
      - AIN0-AIN2: Analog inputs
      - VIN: IOBus supply voltage
    """

    LSS_VENDOR = 0
    LSS_PRODUCT = 4
    LSS_REVISION = 1
    NAME_PREFIX = "PTXIOMux-00004."

    def _get_pins(self):
        return {
            "OUT0": Pin(self.node, "output", 0, 0),
            "OUT1": Pin(self.node, "output", 0, 1),
            "OUT2": Pin(self.node, "output", 0, 2),
            "OUT3": Pin(self.node, "output", 0, 3),
            "IN4": Pin(self.node, "input", 0, 0),
            "IN5": Pin(self.node, "input", 0, 1),
            "IN6": Pin(self.node, "input", 0, 2),
            "AIN0": Pin(self.node, "adc", 0, None),
            "AIN1": Pin(self.node, "adc", 1, None),
            "AIN2": Pin(self.node, "adc", 2, None),
            "VIN": Pin(self.node, "adc", 3, None),
        }


class EthernetMuxDriver(NodeDriver):
    """LXA Ethernet-Mux node driver

    The following pins are provided by this driver:

      - SW: Switch between Ethernet port A and B
      - SW_EXT: Status of the GPIO override input
      - VIN: IOBus supply voltage
    """

    LSS_VENDOR = 0x507
    LSS_PRODUCT = 1
    LSS_REVISION = 4
    NAME_PREFIX = "Ethernet-Mux-00012."

    def _get_pins(self):
        return {
            "SW": Pin(self.node, "output", 0, 0),
            "SW_IN": Pin(self.node, "input", 0, 0),
            "SW_EXT": Pin(self.node, "input", 0, 1),
            "AIN0": Pin(self.node, "adc", 0, None),
            "VIN": Pin(self.node, "adc", 1, None),
        }


class DummyDriver(NodeDriver):
    """Catch-all dummy driver

    This driver does not provide any pins and matches on any address.
    """

    NAME_PREFIX = "Dummy-"

    @classmethod
    def match(cls, node):
        return cls.NAME_PREFIX + node.address


drivers = [
    Iobus4Do3Di3AiDriver,
    PTXIOMuxDriver,
    EthernetMuxDriver,
    DummyDriver,
]
