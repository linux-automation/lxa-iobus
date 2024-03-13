import contextlib
import json
import logging

from .object_directory import ObjectDirectory
from .products import find_product

logger = logging.getLogger("lxa_iobus.base_node")


class LxaBaseNode(object):
    def __init__(self, lss_address):
        self.lss_address = lss_address
        self.product = find_product(lss_address)
        self.name = self.product.name()
        self.address = ".".join(["{:08x}".format(i) for i in lss_address])

        self.locator_state = False

    async def setup_object_directory(self):
        self.od = await ObjectDirectory.scan(
            self,
            self.product.ADC_NAMES,
            self.product.INPUT_NAMES,
            self.product.OUTPUT_NAMES,
        )

    async def ping(self):
        try:
            if "locator" in self.od:
                self.locator_state = await self.od.locator.active()
            else:
                # The device does not advertise having an IOBus locator.
                # Try a CANopen standard endpoint instead
                await self.od.manufacturer_device_name.name()

            return True

        except TimeoutError:
            return False

    async def set_locator_state(self, state):
        if state:
            await self.od.locator.enable()
        else:
            await self.od.locator.disable()

        self.locator_state = state

    async def invoke_isp(self):
        # The node will enter the bootloader immediately,
        # so we will not receive a response.
        with contextlib.suppress(TimeoutError):
            await self.od.bootloader.enter()

    async def info(self):
        device_name = await self.od.manufacturer_device_name.name()
        hardware_version = await self.od.manufacturer_hardware_version.version()
        software_version = await self.od.manufacturer_software_version.version()

        # check for updates
        update_name = ""

        bundled_firmware_version = self.product.FIRMWARE_VERSION
        bundled_firmware_file = self.product.FIRMWARE_FILE

        if (bundled_firmware_version is not None) and (bundled_firmware_file is not None):
            raw_version = software_version.split(" ")[1]
            version_tuple = tuple([int(i) for i in raw_version.split(".")])

            if version_tuple < bundled_firmware_version:
                update_name = bundled_firmware_file

        info = {
            "device_name": device_name,
            "address": self.address,
            "hardware_version": hardware_version,
            "software_version": software_version,
            "update_name": update_name,
        }

        if "version_info" in self.od:
            info["protocol_version"] = await self.od.version_info.protocol()
            info["board_version"] = await self.od.version_info.board()
            info["serial_string"] = await self.od.version_info.serial()
            info["vendor_name"] = await self.od.version_info.vendor_name()
            info["notes"] = await self.od.version_info.notes()

            # If the json is not valid we just leave it as string instead
            with contextlib.suppress(json.decoder.JSONDecodeError):
                info["notes"] = json.loads(info["notes"])

        return info
