import os

from lxa_iobus.server.node_drivers import PTXIOMuxDriver

FIRMWARE_DIR = os.path.dirname(__file__)

FIRMWARE_VERSIONS = {
    PTXIOMuxDriver: (
        (0, 1, 0),
        os.path.join(FIRMWARE_DIR, 'ptxtac-S03_CAN_GPIO.bin'),
    ),
}
