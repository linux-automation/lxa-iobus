import os

from lxa_iobus.node_drivers import PTXIOMuxDriver, IOMuxDriver, EthMuxDriver

FIRMWARE_DIR = os.path.dirname(__file__)

FIRMWARE_VERSIONS = {
    PTXIOMuxDriver: (
        (0, 3, 0),
        os.path.join(FIRMWARE_DIR, 'ptxtac-S03_CAN_GPIO.bin'),
    ),
    IOMuxDriver: (
        (0, 4, 0),
        os.path.join(FIRMWARE_DIR, 'lxatac_can_io-t01.bin'),
    ),
    EthMuxDriver: (
        (0, 3, 0),
        os.path.join(FIRMWARE_DIR, 'ethmux-S01.bin'),
    ),
}
