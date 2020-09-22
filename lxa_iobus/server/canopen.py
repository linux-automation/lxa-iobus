from time import monotonic
import logging

import canopen


logger = logging.getLogger('lxa-iobus.canopen')


def node_adr_to_lss(adr):
    """
    Takes a node addresse formatet like this:
    00000001.00000001.00000001.00001151 and returns an array
    """

    return [int(i, 16) for i in adr.split(".")]


def lss_to_node_adr(lss):
    """Takes an array of ints and returns it as node address string"""
    return ".".join(["{:08x}".format(i) for i in lss])


class CanNode():
    PASSIVE_TIMEOUT = 1
    ACTIVE_TIMEOUT = 5

    def __init__(self, lss_address, node_id, node):
        self._lss_address = lss_address
        self._node_id = node_id
        self.node = node
        self.last_seen = monotonic()

    @property
    def lss_address(self):
        return self._lss_address

    @property
    def node_id(self):
        return self._node_id

    def update_node_id(self, node_id, node):
        self._node_id = node_id
        self.node = node
        self.seen()

    def seen(self):
        self.last_seen = monotonic()

    def age(self):
        """Time since last seen"""
        return monotonic() - self.last_seen

    def poke_node(self):
        """Send request to node to check if its is still there"""
        try:
            self.node.sdo.upload(0x2000, 0)
            # self.seen() # if this works we got a response
            # (this is to make sure is_alive() gets an up-to-date age)

            # FIXME seen() might not be needed here
        except canopen.sdo.exceptions.SdoCommunicationError:
            logger.debug("poke Failed")
            pass

    def is_alive(self):
        """If node has not been seen for ACTIVE_TIMEOUT returns false"""
        # Have we heard of the node?
        # if not send a request
        if self.age() > self.PASSIVE_TIMEOUT:
            self.poke_node()

        # Have we heard something after the requests?
        if self.age() > self.ACTIVE_TIMEOUT:
            return False
        return True

    def __str__(self):
        return "{}, {:x} {:x} {:x} {:x}".format(self._node_id,
                                                *self._lss_address)


class CanNodes():
    """Holds the Mappings from LSS address to CANOpen bus address"""
    def __init__(self, network):
        self.nodes = []
        self.network = network

    def add_node(self, node_id, lss):
        """
        If node does not exist its added a node_id LSS mapping else update
        mapping
        """

        if len(lss) != 4:
            raise Exception("Not a valid LSS address")

        # Is this mapping already up-to-date?
        old_node_map = self.get_node_by_lss(lss)
        if old_node_map is not None:
            if old_node_map.node_id == node_id:
                return

        # Fail if node id already taken
        if not self.get_node_by_id(node_id) is None:
            raise Exception(
                "Node ID {} already in Database. Can't add {},{},{},{}".format(
                    node_id, lss[0], lss[1], lss[2], lss[3]))

        # Look for old mappings for this Node
        if old_node_map is not None:
            logger.info(
                "New node already in DB %d, %x %x %x %X",
                node_id,
                *lss
            )

            # TODO this needs to be known by the driver to bring back
            # the old state
            old_node_map.update_node_id(node_id)
        else:
            logger.info("Add new Node Mapping %d, %x %x %x %X", node_id, *lss)
            node = self.network.add_node(node_id)
            self.nodes.append(CanNode(lss, node_id, node))

    def get_free_node_id(self, lss):
        """Returns an unused node id or None if none is available"""
        # Do we already know this node?

        node = self.get_node_by_lss(lss)
        if node is not None:
            return node.node_id

        used_ids = []
        for node in self.nodes:
            used_ids.append(node.node_id)

        # TODO: Send CANopen Packet to id to verify if its free
        for i in range(1, 128):
            if i not in used_ids:
                return i

    def get_node_by_lss(self, lss_address):
        """Returns node if a node with given lss_address is on the bus"""
        for node in self.nodes:
            a = lss_address
            b = node.lss_address

            if isinstance(a, list):
                a = lss_to_node_adr(a)

            if isinstance(b, list):
                b = lss_to_node_adr(b)

            if a == b:
                return node
        return None

    def get_node_by_id(self, node_id):
        """Returns node if a node with given node_id is on the bus else None"""
        for node in self.nodes:
            if node_id == node.node_id:
                return node
        return None

    def seen_node_id(self, node_id):
        """
        Call when node_id has been seen on the bus. here to update last seen
        """

        # TODO: Maybe this is overdoing it, maybe just send out requests
        node = self.get_node_by_id(node_id)
        if node is None:
            logger.error("Node id: %d is not in DB but on the Bus", node_id)
            return
        node.seen()

    def get_list(self):
        """
        Returns a list with a dict for every node on the bus containing its
        mapping and age
        """

        out = []
        for node in self.nodes:
            out.append({
                "node_id": node.node_id,
                "lss": lss_to_node_adr(node.lss_address),
                "age": node.age(),
            })
        return out

    def cleanup_nodes(self):
        """remove all node that have not been seen for ACTIVE_TIMEOUT"""
        dead_nodes = []
        for node in self.nodes:
            if not node.is_alive():
                logger.info("Node %s not responding. Remove Mapping",
                            node.node_id)

                dead_nodes.append(node)
        for node in dead_nodes:
            logger.info("Removing %s", node.node_id)
            self.nodes.remove(node)
        return dead_nodes

    def upload(self, lss, index, subindex):
        """SDO upload. Node->Server"""
        node = self.get_node_by_lss(lss)
        if node is None:
            raise Exception("No mapping for address: {}".format(lss))
        return node.node.sdo.upload(index, subindex)

    def download(self, lss, index, subindex, data):
        """SDO download. Server->Node"""
        node = self.get_node_by_lss(lss)
        if node is None:
            raise Exception("No mapping for address: {}".format(lss))
        return node.node.sdo.download(index, subindex, bytearray(data))


class LXAIOBusCanopenListener(canopen.network.MessageListener):
    """keeps track of all nodes in the network
      Listens for the following messages:
     - Heartbeat (0x700)
     - SDO response (0x580)
     - TxPDO (0x180, 0x280, 0x380, 0x480)
     - EMCY (0x80)
    """

    SERVICES = (0x700, 0x580, 0x180, 0x280, 0x380, 0x480, 0x80)

    def __init__(self):
        self.nodes = CanNodes(None)

    def connect(self, network):
        self.network = network
        self.nodes.network = network
        self.network.listeners.append(self)

    def reset_all_nodes(self):
        """
        Resets all nodes back to unconfigured state. Does probably not work for
        other node Implementation
        """

        # TODO: Send NMT Reset to get everything back to normal
        logger.info("Unconfigure all nodes")

        try:
            self.network.lss.send_switch_state_global(
                self.network.lss.CONFIGURATION_STATE)

            self.network.lss.configure_node_id(0xff)

            self.network.lss.send_switch_state_global(
                self.network.lss.WAITING_STATE)

        except:
            pass

    def on_message_received(self, msg):
        """Listen to the can bus and note down all nodes that have been seen"""
        cob_id = msg.arbitration_id

        service = cob_id & 0x780
        if service in self.SERVICES:
            node_id = cob_id & 0x1f
            self.nodes.seen_node_id(node_id)

    def get_node_list(self):
        return self.nodes.get_list()

    def cleanup_old_nodes(self):
        dead_nodes = self.nodes.cleanup_nodes()
        for i in range(len(dead_nodes)):
            dead_nodes[i] = lss_to_node_adr(dead_nodes[i].lss_address)
        return dead_nodes

    def inquier_lss_non_config_node(self):
        """Returns true if an unconfigured node is on the network"""
        if self.network is None:
            raise Exception("CANOpen Manger not connected to network")

        return self.network.lss._LssMaster__send_fast_scan_message(
            0, 128, 0, 0)

        # TODO: this function should not be used. How to do this in a save way

    def setup_new_node(self):
        """Search for new nodes and adds them to the mapping"""
        if self.network is None:
            raise Exception("CANOpen Manger not connected to network")

        nodes_found = []

        # Switch all LSS Clients to waiting
        self.network.lss.send_switch_state_global(
            self.network.lss.WAITING_STATE)

        # Check for unconfigured nodes
        # FIXME: this is probably not stable
        found = self.network.lss._LssMaster__send_fast_scan_message(
            0, 128, 0, 0)

        if not found:
            return nodes_found

        logger.debug("Found unconfigured Node")

        # Switch network to Stopped to stop PDO messages
        # This is probably not needed
        self.network.nmt.state = "STOPPED"

        found, lss_address = self.network.lss.fast_scan()

        if not found:
            return []

        node_id = self.nodes.get_free_node_id(lss_address)

        logger.debug(
            "Found %x: [0x%x, 0x%x, 0x%x, 0x%x]",
            node_id,
            *lss_address
        )

        self.network.lss.configure_node_id(node_id)

        self.network.lss.send_switch_state_global(
            self.network.lss.WAITING_STATE)

        self.nodes.add_node(node_id, lss_address)
        nodes_found.append(lss_to_node_adr(lss_address))

        # Start bus back up
        self.network.nmt.state = "OPERATIONAL"
        return nodes_found

    def upload(self, lss, index, subindex):
        logger.debug("upload %s %d %d", lss, index, subindex)
        return self.nodes.upload(node_adr_to_lss(lss), index, subindex)

    def download(self, lss, index, subindex, data):
        return self.nodes.download(node_adr_to_lss(lss), index, subindex, data)


def setup_async(loop, listener, network, channel='can0', bustype='socketcan'):
    """Setup the CAN/CANOpen interface"""
    async_network_connect(network, loop, channel=channel, bustype=bustype)
    listener.connect(network)


def async_network_connect(self, loop, *args, **kwargs):
    """
    Nearly the same as network.connect() but uses the async event loop to
    receive CAN packages
    """

    if "bitrate" not in kwargs:
        for node in self.nodes.values():
            if node.object_dictionary.bitrate:
                kwargs["bitrate"] = node.object_dictionary.bitrate
                break

    self.bus = canopen.network.can.interface.Bus(*args, **kwargs)
    logger.info("Connected to '%s'", self.bus.channel_info)
    self.notifier = canopen.network.can.Notifier(self.bus, self.listeners, 1,
                                                 loop=loop)

    return self
