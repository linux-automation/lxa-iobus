import canopen
from time import sleep
import struct

class CanOpen:
    """Minimal Setup to controll one ethmux"""
    def __init__(self, channel="can0", node_id=1):
        self.node_id = node_id
        self.network = canopen.Network()
        self.network.connect(channel=channel, bustype='socketcan')
        self.node = self.network.add_node(self.node_id)

    def setup(self):
        """Setup one node with a new node_id"""
        """Warning this expects only one CANOpen node on the network!"""
        self.network.lss.send_switch_state_global(self.network.lss.CONFIGURATION_STATE)
        self.network.lss.configure_node_id(1)
        self.network.lss.send_switch_state_global(self.network.lss.WAITING_STATE)

    def reset(self):
        """Setup one node with a new node_id"""
        """Warning this expects only one CANOpen node on the network!"""
        self.network.lss.send_switch_state_global(self.network.lss.CONFIGURATION_STATE)
        try:
            self.network.lss.configure_node_id(255)
        except:
            pass
        self.network.lss.send_switch_state_global(self.network.lss.WAITING_STATE)

    def invoke_isp(self):
        """set port state"""
        self.node.sdo.download(0x2b07, 0, struct.pack("I", 0x12345678))

    def get_chip_id(self):
        """Connect to Port A"""
        out = [0,0,0,0]
        for i in range(len(out)):
            out[i] = struct.unpack( "<I", self.node.sdo.upload(0x2c1d, i))[0]
        return out



def test():
    can = CanOpen()
    can.setup()
    print("chip id:", [hex(i) for i in can.get_chip_id()])

    print("Reboot into bootloader")
    try:
        can.invoke_isp()
    except canopen.sdo.exceptions.SdoCommunicationError:
        pass

if __name__ == "__main__":
    test()
