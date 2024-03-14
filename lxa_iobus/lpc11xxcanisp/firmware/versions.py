import os

from lxa_iobus.node_drivers import EthernetMuxDriver, Iobus4Do3Di3AiDriver, PTXIOMuxDriver

FIRMWARE_DIR = os.path.dirname(__file__)

FIRMWARE_VERSIONS = {
    PTXIOMuxDriver: (
        (0, 3, 0),
        os.path.join(FIRMWARE_DIR, "ptxtac-S03_CAN_GPIO.bin"),
    ),
    Iobus4Do3Di3AiDriver: (
        (0, 5, 0),
        os.path.join(FIRMWARE_DIR, "lxatac_can_io-t01.bin"),
    ),
    EthernetMuxDriver: (
        (0, 5, 0),
        os.path.join(FIRMWARE_DIR, "ethmux-S01.bin"),
    ),
}
