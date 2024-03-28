class Node(object):
    def __init__(self, serial):
        self.serial = serial

    def name(self):
        """Construct a human-readable device name from a driver
        specific prefix and the zero-padded decimal serial number
        """

        return f"{self.NAME_PREFIX}{self.serial:05}"

    @classmethod
    def try_match(cls, lss_address):
        driver_addr = [cls.LSS_VENDOR, cls.LSS_PRODUCT, cls.LSS_REVISON]

        if lss_address[:3] == driver_addr:
            return cls(lss_address[3])

        return None


class Iobus4Do3Di3Ai(Node):
    """LXA IOBus 4DO-3DI-3AI driver

    The following pins are provided by this driver:

      - OUT0-OUT3: Digital outputs
      - IN0-IN2: Digital inputs
      - VIN: IOBus supply voltage
      - AIN0-AIN2: Analog inputs
    """

    LSS_VENDOR = 0x507
    LSS_PRODUCT = 2
    LSS_REVISON = 3

    NAME_PREFIX = "4DO-3DI-3AI-00005."
    FIRMWARE_FILE = "lxatac_can_io-t01.bin"
    FIRMWARE_VERSION = (0, 6, 0)

    ADC_NAMES = ["VIN", "AIN0", "AIN1", "AIN2"]
    INPUT_NAMES = [["IN0", "IN1", "IN2"]]
    OUTPUT_NAMES = [["OUT0", "OUT1", "OUT2", "OUT3"]]


class PTXIOMux(Node):
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
    LSS_REVISON = 1

    NAME_PREFIX = "PTXIOMux-00004."
    FIRMWARE_FILE = "ptxtac-S03_CAN_GPIO.bin"
    FIRMWARE_VERSION = (0, 3, 0)

    ADC_NAMES = ["AIN0", "AIN1", "AIN2", "VIN"]
    INPUT_NAMES = [["IN4", "IN5", "IN6"]]
    OUTPUT_NAMES = [["OUT0", "OUT1", "OUT2", "OUT3"]]


class EthernetMux(Node):
    """LXA Ethernet-Mux node driver

    The following pins are provided by this driver:

      - SW: Switch between Ethernet port A and B
      - SW_EXT: Status of the GPIO override input
      - VIN: IOBus supply voltage
    """

    LSS_VENDOR = 0x507
    LSS_PRODUCT = 1
    LSS_REVISON = 4

    NAME_PREFIX = "Ethernet-Mux-00012."
    FIRMWARE_FILE = "ethmux-S01.bin"
    FIRMWARE_VERSION = (0, 6, 0)

    ADC_NAMES = ["AIN0", "VIN"]
    INPUT_NAMES = [["SW_IN", "SW_EXT"]]
    OUTPUT_NAMES = [["SW"]]


class Optick(Node):
    """LXA Optick node driver

    The following pins are provided by this driver:

      - OUT0, OUT1: Digital outputs
      - IN0, IN1: Digital inputs
      - IN0_RAW, IN1_RAW: Analog inputs
    """

    LSS_VENDOR = 0x507
    LSS_PRODUCT = 3
    LSS_REVISON = 1

    NAME_PREFIX = "Optick-00043."
    FIRMWARE_FILE = "optick-t01.bin"
    FIRMWARE_VERSION = (0, 6, 0)

    ADC_NAMES = ["IN0_RAW", "IN1_RAW", "VIN"]
    INPUT_NAMES = [["IN0", "IN1"]]
    OUTPUT_NAMES = [["OUT0", "OUT1"]]


class Unknown(Node):
    """Catch-all for all other nodes

    Uses default names for all inputs, outputs and adc channels
    """

    NAME_PREFIX = "Unknown-"
    FIRMWARE_FILE = None
    FIRMWARE_VERSION = None

    ADC_NAMES = None
    INPUT_NAMES = None
    OUTPUT_NAMES = None

    @classmethod
    def try_match(cls, node):
        return cls.NAME_PREFIX + node.address


def find_product(lss_address):
    for node_cls in [Iobus4Do3Di3Ai, PTXIOMux, EthernetMux, Optick]:
        node = node_cls.try_match(lss_address)

        if node is not None:
            return node

    return Unknown(lss_address[3])
