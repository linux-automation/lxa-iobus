import asyncio
import logging
import os
import struct
import time
from datetime import datetime
from functools import partial

from lxa_iobus.lpc11xxcanisp import loader

basepath = os.path.dirname(os.path.dirname(loader.__file__))


class ExceptionCanIsp(Exception):
    pass


class IspSdoAbortedError(Exception):
    abort_codes = {
        0x0F00000D: "ADDR_ERROR",
        0x0F00000E: "ADDR_NOT_MAPPED",
        0x0F00000F: "CMD_LOCKED",
        0x0F000013: "CODE_READ_PROTECTION_ENABLED",
        0x0F00000A: "COMPARE_ERROR",
        0x0F000006: "COUNT_ERROR",
        0x0F000003: "DST_ADDR_ERROR",
        0x0F000005: "DST_ADDR_NOT_MAPPED",
        0x0F000010: "INVALID_CODE",
        0x0F000001: "INVALID_COMMAND",
        0x0F000007: "INVALID_SECTOR",
        0x0F00000C: "PARAM_ERROR",
        0x0F000008: "SECTOR_NOT_BLANK",
        0x0F000009: "SECTOR_NOT_PREPARED_FOR_WRITE_OPERATION",
        0x0F000002: "SRC_ADDR_ERROR",
        0x0F000004: "SRC_ADDR_NOT_MAPPED",
    }

    def __init__(self, code):
        self.code = code

    @classmethod
    def is_known(cls, code):
        return code in cls.abort_codes

    def str(self):
        return self.abort_codes.get(self.code, None)

    def __str__(self):
        text = "Code 0x{:08X}".format(self.code)
        reason = self.str()

        if reason is not None:
            text += ", " + reason

        return text


class IspCompareError(Exception):
    def __init__(self, offset):
        self.offset = offset

    def __str__(self):
        text = "Memory compare failed at 0x{:08X}".format(self.offset)

        return text


class CanIsp:
    DATA_SIZES = {8: "B", 16: "H", 32: "I"}
    ram_offset = 0x10000500  # Offset to safely usable RAM

    object_directory = {
        "Device Type": [0x1000, 0, 32],
        "Vendor ID": [0x1018, 1, 32],  # Not used: should be 0
        "Part Identification Number": [0x1018, 2, 32],
        "Boot Code Version Number": [0x1018, 3, 32],
        "Program Area": [0x1F50, 1, None],  # DOMAIN
        "Program Control": [0x1F51, 1, 8],
        "Unlock Code": [0x5000, 0, 16],
        "Memory Read Address": [0x5010, 0, 32],
        "Memory Read Length": [0x5011, 0, 32],
        "RAM Write Address": [0x5015, 0, 32],
        "Prepare Sectors for Write": [0x5020, 0, 16],
        "Erase Sectors": [0x5030, 0, 16],
        "Check sectors": [0x5040, 1, 16],
        "Copy Flash Address": [0x5050, 1, 32],
        "Copy RAM Address": [0x5050, 2, 32],
        "Copy Length": [0x5050, 3, 16],
        "Compare Address 1": [0x5060, 1, 32],
        "Compare Address 2": [0x5060, 2, 32],
        "Compare Length": [0x5060, 3, 16],
        "Compare mismatch": [0x5060, 4, 32],
        "Execution Address": [0x5070, 1, 32],
        "Serial Number 1": [0x5100, 1, 32],
        "Serial Number 2": [0x5100, 2, 32],
        "Serial Number 3": [0x5100, 3, 32],
        "Serial Number 4": [0x5100, 4, 32],
    }

    part_ids = {
        0x041E502B: "LPC1111FHN33/101",
        0x2516D02B: "LPC1111FHN33/102",
        0x0416502B: "LPC1111FHN33/201",
        0x2516902B: "LPC1111FHN33/202",
        0x00010013: "LPC1111FHN33/103",
        0x00010012: "LPC1111FHN33/203",
        0x042D502B: "LPC1112FHN33/101",
        0x2524D02B: "LPC1112FHN33/102",
        0x0425502B: "LPC1112FHN33/201",
        0x2524902B: "LPC1112FHI33/202",
        0x00020023: "LPC1112FHN33/103",
        0x00020022: "LPC1112FHI33/203",
        0x0434502B: "LPC1113FHN33/201",
        0x2532902B: "LPC1113FHN33/202",
        0x0434102B: "LPC1113FBD48/301",
        0x2532102B: "LPC1113FBD48/302",
        0x00030032: "LPC1113FHN33/203",
        0x00030030: "LPC1113FHN33/303",
        0x0444502B: "LPC1114FHN33/201",
        0x2540902B: "LPC1114FHN33/202",
        0x0444102B: "LPC1114FBD48/301",
        0x00040042: "LPC1114FHN33/203",
        0x00040060: "LPC1114FBD48/323",
        0x00040070: "LPC1114FHN33/333",
        0x00040040: "LPC1114FHI33/303",
        0x2540102B: "LPC11D14FBD100/302",
        0x00050080: "LPC1115FBD48/303",
        0x1421102B: "LPC11C12FBD48/301",
        0x1440102B: "LPC11C14FBD48/301",
        0x1431102B: "LPC11C22FBD48/301",
        0x1430102B: "LPC11C24FBD48/301",
    }

    def __init__(self, server, network):
        self.server = server
        self.network = network

        self._console = []

    def console_log(self, *message):
        console_max_len = 100

        message = "{}: {}".format(str(datetime.now()), " ".join([str(i) for i in message]))

        self._console.append(message)

        if len(self._console) > console_max_len:
            self._console = self._console[len(self._console) - console_max_len :]

        self.server.rpc.worker_pool.run_sync(
            partial(self.server.rpc.notify, "isp_console", self._console),
            wait=False,
        )

    @staticmethod
    def unpack(data: bytes, size: int = None):
        """converts binary data to in depending on number of bits"""

        if size is None:
            return data

        form = CanIsp.DATA_SIZES[size]

        return struct.unpack(form, data)[0]

    @staticmethod
    def pack(data, size=None):
        """converts ints to binary"""

        if size is None:
            return data

        form = CanIsp.DATA_SIZES[size]

        return struct.pack(form, data)

    def _send(self, index: int, subindex: int, size, num: int):
        """Sends data to the MCU and converts it"""

        isp_node = self.network.get_isp_node()

        coroutine = isp_node.sdo_write(
            index,
            subindex,
            self.pack(num, size=size),
        )

        future = asyncio.run_coroutine_threadsafe(
            coroutine,
            loop=self.network.loop,
        )

        return future.result()

    def send(self, name, value):
        self._send(*self.object_directory[name], value)

    def _get(self, index: int, subindex: int, size):
        """Gets data from the MCU and converts it"""

        isp_node = self.network.get_isp_node()
        coroutine = isp_node.sdo_read(index, subindex)

        future = asyncio.run_coroutine_threadsafe(
            coroutine,
            loop=self.network.loop,
        )

        result = future.result()

        return self.unpack(result)

    def get(self, name):
        return self._get(*self.object_directory[name])

    def unlock(self):
        """
        Unlocks write operations
        Needs to be called before writing to RAM or Flash
        """

        self.send("Unlock Code", 23130)

    def write_to_ram(self, addr: int, data: bytes):
        """Writes data to RAM at addr"""

        # TODO: Check if we override the bootloader area
        # TODO: Check RAM Size

        self.send("RAM Write Address", addr)
        self.send("Program Area", data)

    def prepare_flash_sectors(self, start: int, stop: int):
        """
        Prepare sectors for write operation.
        Sectors are always 4kByte so sector 0 is address
        0x0000_0000 - 0x0000_0FFF and so on.
        The sector range is inclusive so prepare_flash_sectors(0, 0)
        prepares the first sector.
        """

        if stop < start:
            raise ExceptionCanIsp("Sector range not ascending")

        if start > 8 or stop > 8:
            raise ExceptionCanIsp("Sector out of range")

        self.send("Prepare Sectors for Write", ((start & 0xFF) | ((stop & 0xFF) << 8)))

    def copy_ram_to_flash(self, ram_addr, flash_addr, length):
        """Copies RAM range to flash"""

        # TODO: Check for alignment
        # TODO: Check FLASH size

        self.send("Copy Flash Address", flash_addr)
        self.send("Copy RAM Address", ram_addr)
        self.send("Copy Length", length)

    def go(self, addr):
        """Jumps to given address"""

        self.send("Execution Address", addr)
        self.send("Program Control", 1)  # Trigger jump

    def erase_flash_sectors(self, start, stop):
        """Clear given flash range"""

        if stop < start:
            raise ExceptionCanIsp("Sector range not ascending")

        if start > 8 or stop > 8:
            raise ExceptionCanIsp("Sector out of range")

        self.send("Erase Sectors", ((start & 0xFF) | ((stop & 0xFF) << 8)))

    def read_memory(self, addr: int, length: int) -> bytes:
        """Dumps part of the MCUs memory"""

        self.send("Memory Read Address", addr)
        self.send("Memory Read Length", length)

        return self.get("Program Area")

    def read_part_id(self) -> int:
        """
        Returns a tuple with the part id and the part name if known
        otherwise None
        """

        part_id = self.get("Part Identification Number")
        part_name = self.part_ids.get(part_id, None)

        return (part_id, part_name)

    def read_bootloader_version(self) -> int:
        """Returns bootloader version as an 32-bit unsigned integers"""

        return self.get("Boot Code Version Number")

    def read_serial_number(self) -> [int]:
        """
        returns MCU serial number as an array with 4 32-bit
        unsigned integers
        """

        return [
            self.get("Serial Number 1"),
            self.get("Serial Number 2"),
            self.get("Serial Number 3"),
            self.get("Serial Number 4"),
        ]

    def read_device_type(self) -> bytes:
        """The device type should always be 'LPC1'"""

        obj = self.object_directory["Device Type"]

        return self._get(obj[0], obj[1], None)  # Get uint32 as bytearray

    def compare(self, addr_1, addr_2, length):
        """
        Takes two addresses and a length and compare the data.
        Raises IspCompareError if a mismatch is found.
        """

        try:
            self.send("Compare Address 1", addr_1)
            self.send("Compare Address 2", addr_2)
            self.send("Compare Length", length)

        except IspSdoAbortedError as e:
            if e.str() == "COMPARE_ERROR":
                offset = self.get("Compare mismatch")

                raise IspCompareError(offset) from e

    def flash_image(self, start, data):
        logging.info("Data to be written: %d Byte", len(data))

        block_size = 4096

        if (start % block_size) != 0:
            raise Exception("Start must be a multiple of 4096!")

        start_sector = start // block_size

        # data must be multiple of block size
        # TODO add option for smaller block size
        #      Supported are: 256, 512, 1024, 4096.

        stuffing = len(data) % block_size

        if stuffing != 0:
            logging.info("Date buffer is extended by %d", stuffing)
            data += b"\xff" * (block_size - stuffing)

        logging.info("Data to be written %d Bytes", len(data))
        logging.info("Start sector %d", start_sector)

        sectors = len(data) // block_size

        assert (len(data) % block_size) == 0, "Need to erase extra sector to fit date: %d" % len(data)

        logging.info("Sectors to write %d", sectors)

        if start_sector + sectors > 8:
            raise Exception("Data to write does not fit into flash are of 32k")

        logging.info(
            "Erasing blocks %d to %d",
            start_sector,
            start_sector + sectors - 1,
        )

        # TODO: Add check if we need to erase block use Blank check sectors
        self.unlock()  # Unlock writes
        self.prepare_flash_sectors(start_sector, start_sector + sectors - 1)
        self.erase_flash_sectors(start_sector, start_sector + sectors - 1)

        blocks = sectors

        for block_num in range(start_sector, start_sector + blocks):
            logging.info("Send block %d", block_num)

            start_offset = block_size * (block_num - start_sector)

            block = data[start_offset : start_offset + block_size]
            logging.info("Block length %d", len(block))

            # Transfer data block to the RAM of the MCU
            self.write_to_ram(self.ram_offset, block)

            logging.info("Copy to Flash")
            self.prepare_flash_sectors(block_num, block_num)

            # Copy block from MCU RAM to MCU Flash
            self.copy_ram_to_flash(
                self.ram_offset,
                block_size * block_num,
                block_size,
            )

    # helper methods ##########################################################
    def fix_checksum(self, data):
        """
        This generate the checksum in the vector table.
        This is needed for the LPC11CXX und probably all Cortex-M0.
        and is normally done somewhere in the swd programming chain.
        For more info see: UM10398 26.3.3 Criterion for Valid User Code.
        """
        # First 7 entries:
        vector_table = data[0 : 4 * 7]

        vector_table = struct.unpack("iiiiiii", vector_table)

        checksum = 0 - (sum(vector_table))
        checksum = struct.pack("i", checksum)

        data = data[0 : 4 * 7] + checksum + data[4 * 8 :]

        return data

    def write(self, filename, section):
        assert section in ["config", "flash"]

        with open(filename, "rb") as fd:
            data = fd.read()

        if section == "flash":
            data = self.fix_checksum(data)

        if section == "flash":
            length = 28 * 1024
            start = 0
        else:
            # config
            length = 4 * 1024
            start = 28 * 1024

        if len(data) > length:
            self.console_log(
                "Supplied Image is too long for section. Allowed {} bytes, is {} bytes".format(length, len(data))
            )

            exit(1)

        self.console_log("Writing section {}".format(section))
        start_t = time.time()

        self.flash_image(start, data)

        stop_t = time.time()

        self.console_log(
            "Write",
            len(data),
            "in",
            stop_t - start_t,
            ":",
            len(data) / (stop_t - start_t),
            "Bytes/sec",
        )

    def read(self, filename, section):
        assert section in ["config", "flash"]

        if section == "flash":
            length = 28 * 1024
            start = 0

        else:
            # config
            length = 4 * 1024
            start = 28 * 1024

        self.console_log("Reading section {}".format(section))
        start_t = time.time()

        data = self.read_memory(start, length)

        stop_t = time.time()

        self.console_log(
            "Read",
            length,
            "in",
            stop_t - start_t,
            ":",
            length / (stop_t - start_t),
            "Bytes/sec",
        )

        with open(filename, "wb") as fd:
            fd.write(data)

    def write_flash(self, filename):
        self.write(filename, "flash")

    def isp_exec(self, filename):
        with open(filename, "rb") as fd:
            data = fd.read()

        self.unlock()
        self.write_to_ram(0x10000500, data)
        self.go(0x10000500)

    def reset(self):
        self.isp_exec(os.path.join(basepath, "loader/reset.bin"))
