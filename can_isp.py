import canopen
import struct
import sys
import time

class CAN_ISP:
    DATA_SIZES = {8: "B", 16: "H", 32: "I"}
    def __init__(self, node):
        self.node = node

    @staticmethod
    def unpack(size, data):
        form = CAN_ISP.DATA_SIZES[size]
        return struct.unpack(form, data)

    @staticmethod
    def pack(data, size=None):
        if size is None:
            return data
        form = CAN_ISP.DATA_SIZES[size]
        return struct.pack(form, data)

    def send(self, index: int, subindex: int, size, num: int):
        self.node.sdo.download(index, subindex, self.pack(num, size=size))

    def unlock(self):
        """Unlocks write to flash"""
        self.send(0x5000, 0, 16, 23130)

    def write_to_ram(self, addr: int, data: bytes):
        """Writes data to RAM at addr"""
        # TODO: Check if we override the bootloader area
        # TODO: Check RAM Size
        self.send(0x5015, 0, 32, addr)
#        self.node.sdo.open(0x1F50, 1, "wb").write(data)
        self.send(0x1F50, 1, None, data)
    
    def prepare_flash_sectors(self, start, stop):
        """Prepare sectors for write operation"""
        # TODO: Check for allingement
        self.send(0x5020, 0, 16, ( (start&0xff) | ((stop&0xff)<<8) ) )

    def copy_ram_to_flash(self, ram_addr, flash_addr, length):
        """Copies RAM range to flash"""
        # TODO: Check for allingement
        # TODO: Check FLASH size
        self.send(0x5050, 1, 32, flash_addr )
        self.send(0x5050, 2, 32, ram_addr )
        self.send(0x5050, 3, 16, length )

    def go(self, addr):
        """Jumps to given addresse"""
        self.send(0x5070, 1, 32, addr)
        self.send(0x1f51, 1, 8, 1)

    def erase_flash_secotrs(self, start, stop):
        """Clear given flash range"""
        # TODO: Check for allingement
        self.send(0x5030, 0, 16, ( (start&0xff) | ((stop&0xff)<<8) ) )


    def read_memory(self, addr: int, length: int) -> bytes:
        self.send(0x5010, 0, 32, addr)
        self.send(0x5011, 0, 32, length)
        return self.node.sdo.upload(0x1F50, 1)

    def read_partID(self) -> int:
        raise NotImplementedError
        #[0x1018, 2] 32

    def read_bootloader_version(self) -> int:
        raise NotImplementedError
        #[0x1018, 3] 32

    def read_serial_number(self) -> int:
        raise NotImplementedError
        #[0x5100, 1 to 4] 32

    def read_device_type(self) -> str:
        raise NotImplementedError
        #[0x1000, 0] 32 (ASCII)

    def compare(self, addr_1, addr_2, lenght):
        raise NotImplementedError


    def flash_image(self, data):
        print("Data to be writen:", len(data), "Byte")

        block_size = 4096
        
        #data must be multiple of 4
        stuffing = len(data)%block_size
        if stuffing != 0:
            print("Data is extended by", stuffing)
            data += b"\xff"*(block_size-stuffing)

        print("Data to be writen:", len(data), "Byte")

        sectors = len(data)//block_size
        if (len(data)%block_size) != 0:
            print(" # need to erease extra sector to fit data")
            sectors += 1
        print("need to erase", sectors, "sectors")
        self.unlock()
        self.prepare_flash_sectors(0, sectors-1)
        self.erase_flash_secotrs(0, sectors-1)

        for block_num in range(sectors):
            print("# Send block", block_num)
            i = block_size*block_num

            block = data[i:i+block_size]
            print(" #Block length", len(block))
            self.write_to_ram(0x10000500, block)

            print("  Copy to flash")
            self.prepare_flash_sectors(block_num, block_num)
            self.copy_ram_to_flash(0x10000500, i, block_size)


# 

def fix_checksum(data):
    """This generate the checksum in the vectro table"""
    """This is needed for the LPC11CXX und probebly all Cortex-M0"""
    """and is normaly done somewhere in the swd programming chain"""
    """For more info see: UM10398 26.3.3 Criterion for Valid User Code"""

    vector_table = data[0:4*7] # First 7 entrys
    vector_table = struct.unpack("iiiiiii", vector_table)

    checksum = 0-(sum(vector_table))
    checksum = struct.pack("i", checksum)

    data = data[0:4*7] + checksum + data[4*8:]
    return data



def isp_write(filename):
    data = open(filename, "rb").read()

    data = fix_checksum(data)

    network = canopen.Network()
    network.connect(channel='can0', bustype='socketcan')
    node = network.add_node(125)
    isp = CAN_ISP(node)

    print("Writing new Image")
    start_t = time.time()
    isp.flash_image(data)
    stop_t = time.time()
    print("Write", len(data), "in", stop_t-start_t, ":", len(data)/(stop_t-start_t),"Bytes/sec")

    #stack, reset = struct.unpack("II", data[0:8])
    #print("Stack", stack, ", Rest", reset)
    #isp.go(reset & 0xfffffffe)

def isp_read(filename):
    network = canopen.Network()
    network.connect(channel='can0', bustype='socketcan')
    node = network.add_node(125)
    isp = CAN_ISP(node)


    print("Reading old Image")
    start_t = time.time()

    length = 16*1024
    data = isp.read_memory(0, length)

    stop_t = time.time()
    print("Read", length, "in", stop_t-start_t, ":", length/(stop_t-start_t),"Bytes/sec")
    open(filename, "wb").write(data)

if __name__ == "__main__":

    if len(sys.argv) != 3:
        print(" tool.py [read | write] file")

    if sys.argv[1] == "read":
        isp_read(sys.argv[2])
    if sys.argv[1] == "write":
        isp_write(sys.argv[2])

def read_write():

    network = canopen.Network()
    network.connect(channel='can0', bustype='socketcan')
    node = network.add_node(125)
    isp = CAN_ISP(node)


    isp.write_to_ram(0x10000300, b"asdfasdf")

    print("Reading old Image")
    start_t = time.time()

    length = 32*1024
    data = isp.read_memory(0, length)

    stop_t = time.time()
    print("Read", length, "in", stop_t-start_t, ":", length/(stop_t-start_t),"Bytes/sec")
    open("pre_update.bin", "wb").write(data)

    data = open("test.bin", "rb").read()

    print("Writing new Image")
    start_t = time.time()
    isp.flash_image(data)
    stop_t = time.time()
    print("Write", length, "in", stop_t-start_t, ":", length/(stop_t-start_t),"Bytes/sec")

    print("Reading new Image")
    start_t = time.time()

    length = 32*1024
    data = isp.read_memory(0, length)

    stop_t = time.time()
    print("Read", length, "in", stop_t-start_t, ":", length/(stop_t-start_t),"Bytes/sec")
    open("post_update.bin", "wb").write(data)
