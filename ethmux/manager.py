import canopen 
import thread
from time import time

class Node():
    def __init__(self, lss_address, node_id, canopen):
        self._lss_address = lss_address
        self._node_id = node_id
        self.last_seen = time()

    @property
    def lss_address(self):
        return self._lss_address

    @property
    def node_id(self):
        return self._node_id

class Manager(canopen.network.MessageListener):
    """keeps track of all nodes in the network
      Listens for the following messages:
     - Heartbeat (0x700)
     - SDO response (0x580)
     - TxPDO (0x180, 0x280, 0x380, 0x480)
     - EMCY (0x80)  
    """

    SERVICES = (0x700, 0x580, 0x180, 0x280, 0x380, 0x480, 0x80)

    def __init__(self):
        self.nodes = {}
        self.last_seen = {}

    def connect(self, network ):
        
        self.network = network
        self.network.listeners.append(self)
        self.network.listeners.append(self)

    def on_message_received(self, msg):
        """Lissen to the can bus and note down all nodes that have been seen"""
        cob_id = msg.arbitration_id

        print(" # res", msg)

        service = cob_id & 0x780
        if service in self.SERVICES:
            node_id = cob_id & 0x1f
            print(" # seen node", node_id)
            self.last_seen[node_id] = time()

    def cleanup_nodes(self, age=1):
        """remove all node that have not been seen for age amout of time"""
        pass

    def get_free_node_id(self):
        """Returns an unused node id or None if none is awailable"""
        for i in range(1,128):
            if not i in self.nodes:
                return i

    def get_node_by_lss(self, lss_address):
        """Returns node ifi a node with given lss_address is on the bus"""
        for node_id, node in self.nodes.items():
            if lss_address == nodes.lss_address:
                return node
        return None

    def get_node_list(self):
        return self.nodes.keys()

    def inquier_lss_non_config_node(self):
        """Returns true if an unconfigured node is on the network"""
        if self.network is None:
            raise Exception("CANOpen Manger not connected to network")
        return self.network.lss._LssMaster__send_fast_scan_message(0,128,0,0)

    def setup_new_node(self):
        if self.network is None:
            raise Exception("CANOpen Manger not connected to network")

        # looking for on configuerd nodes
        # TODO
        # * Check if unconfigured node is in network
        # * scan network to get all activ node_ids
        #   or call the part of management that keeps track of the nodes
        # * switch network into stop state
        # * do fastscan
        # * setup node id
        # * switch network back into operational

        print("huhu")
        # Check for unconfigured nodes
        found = self.network.lss._LssMaster__send_fast_scan_message(0,128,0,0)

        if not found:
            return

        # Switch network to Stopped to stop PDO messages
        self.network.nmt.state="STOPPED"

        # Switch all LSS Clients to waiting
        self.network.lss.send_switch_state_global(self.network.lss.WAITING_STATE)

        while True:
            found, lss_address = self.network.lss.fast_scan()
            if not found:
                break

            node_id = self.get_free_node_id()
            print("Give {} node_id: {}".format(lss_address, node_id))
            self.network.lss.configure_node_id(node_id)
            self.network.lss.send_switch_state_global(self.network.lss.WAITING_STATE)

            node = self.network.add_node(node_id)

            self.nodes[node_id] = Node(lss_address, node_id, node)
            #print(node.sdo.upload(0x1018,4))

        # Start bus back up
        self.network.nmt.state="OPERATIONAL"


network = canopen.Network()
control = Manager()


@thread.add_call
def setup(channel='can0', bustype='socketcan'):
    network.connect(channel=channel, bustype=bustype)
    control.connect(network)


thread.add_call(control.inquier_lss_non_config_node)
thread.add_call(control.setup_new_node)
thread.add_call(control.get_node_list)
