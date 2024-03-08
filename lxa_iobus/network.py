import asyncio
import enum
import errno
import itertools
import json
import logging
import os
import signal
import time
from copy import deepcopy

from can import Bus, CanError
from janus import Queue, SyncQueueEmpty

from lxa_iobus.canopen import (
    LSS_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER,
    SDO_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER,
    LssMode,
    gen_invalidate_node_ids_message,
    gen_lss_configure_node_id_message,
    gen_lss_fast_scan_message,
    gen_lss_switch_mode_global_message,
    parse_sdo_message,
)
from lxa_iobus.node import LxaNode

logger = logging.getLogger("lx-iobus.network")


class LxaShutdown(Exception):
    pass


class LxaNetwork:
    node_drivers = []

    class LssStates(enum.Enum):
        """States of the LSS subsystem"""

        IDLE = "Idle"
        SCANNING = "Scanning"

    def __init__(self, loop, interface, bustype="socketcan", bitrate=100000, lss_address_cache_file=None):
        self.loop = loop
        self.interface = interface
        self.bustype = bustype
        self.bitrate = bitrate  # muss so: festgelegt durch lpc11c24 bootloader

        self.lss_address_cache_file = lss_address_cache_file
        self.lss_address_cache = []
        self.lss_state = LxaNetwork.LssStates.SCANNING

        self.tx_error = False

        self._running = False

    # interface checker code ##################################################
    def interface_is_up(self):
        path = os.path.join("/sys/class/net/", self.interface, "operstate")

        if os.path.exists(path):
            with open(path, "r") as fd:
                state = fd.read()

            if state.strip() in ["up", "unknown"]:
                return True

        return False

    async def await_interface_is_up(self):
        def _await_interface_is_up():
            while self._running:
                if self.interface_is_up():
                    self._interface_state = True

                    logger.debug("interface_is_up")

                    return

                logger.debug("interface is down")

                time.sleep(1)

        await self.loop.run_in_executor(None, _await_interface_is_up)

    async def update_interface_state(self):
        def _update_interface_state():
            while self._running:
                self._interface_state = self.interface_is_up()

                if not self._interface_state:
                    return

                time.sleep(1)

        await self.loop.run_in_executor(None, _update_interface_state)

    # lss node address cache ##################################################
    async def load_lss_address_cache(self):
        def _load_lss_address_cache():
            if not self.lss_address_cache_file:
                logger.info("no lss address cache file set. skip loading")

                return

            # create file if not present
            if not os.path.exists(self.lss_address_cache_file):
                try:
                    with open(self.lss_address_cache_file, "w+") as f:
                        f.write("[]")

                except Exception:
                    logger.error(
                        "exception raised while creating %s",
                        self.lss_address_cache_file,
                        exc_info=True,
                    )

            # reading file
            file_content = ""

            try:
                with open(self.lss_address_cache_file, "r") as f:
                    file_content = f.read()

            except FileNotFoundError:
                logger.error(
                    "lss node cache file %s does not exist",
                    self.lss_address_cache_file,
                )

            try:
                self.lss_address_cache = json.loads(file_content)

            except Exception:
                logger.error("exception raised while reading %s", self.lss_address_cache_file, exc_info=True)

        self.loop.run_in_executor(None, _load_lss_address_cache)

    async def write_lss_address_cache(self):
        def _write_lss_address_cache():
            if not self.lss_address_cache_file:
                logger.debug("no lss address cache file set. skip writing")

                return

            try:
                with open(self.lss_address_cache_file, "w") as f:
                    f.write(json.dumps(self.lss_address_cache))

            except Exception:
                logger.error(
                    "exception raised while writing %s",
                    self.lss_address_cache_file,
                    exc_info=True,
                )

        self.loop.run_in_executor(None, _write_lss_address_cache)

    # CAN send and receive threads ############################################
    def send(self):
        while True:
            try:
                message = self._outgoing_queue.sync_q.get(timeout=0.2)

                logger.debug("tx: %s", str(message))

                self.bus.send(message)

                if self.tx_error:
                    self.tx_error = False
                    logger.warn("tx: TX-buffer recovered.")

            except SyncQueueEmpty:
                if not self._running or not self._interface_state:
                    return

            except CanError as e:
                # FIXME: python-can does currently (in 3.3.4) not set e.errno
                # so we have to fall back to __context__.
                # A fix has already been placed in the development-branch:
                # https://github.com/hardbyte/python-can/commit/0e0c64fd7104774dbcfe3641bd9a362ff54b2641
                # But the latest 4.0-dev2 release does not contain this fix
                # yet.
                if e.__context__.errno == errno.ENOBUFS:
                    # Send buffer is full. This can happen if there is no other
                    # device on the bus.
                    # Thus this is something normal to happen.
                    # We will just wait for the bus to recover.
                    if not self.tx_error:
                        logger.warn("tx: TX-buffer full. " "Maybe there is a problem with the bus?")
                        self.tx_error = True
                    else:
                        logger.debug("tx: TX-buffer full. " "Maybe there is a problem with the bus?")
                else:
                    logger.error("tx: Unhandled CAN error: %s", e)
                    break

            except Exception as e:
                logger.error("tx: Unhandled CAN error: %s", e)
                break

        logger.error("tx: shutdown! Stopping application.")
        # ask async to stop our application
        os.kill(os.getpid(), signal.SIGTERM)

    def recv(self):
        while True:
            try:
                message = self.bus.recv(timeout=0.2)

                # timeout
                if message is None:
                    if not self._running or not self._interface_state:
                        break

                    else:
                        continue

                logger.debug("rx: %s", str(message))

                # lss messages
                if message.arbitration_id == LSS_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER:
                    self._lss_set_response(message)

                # sdo message
                elif message.arbitration_id in SDO_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER:
                    sdo_message = parse_sdo_message(message)
                    node_id = sdo_message.node_id

                    try:
                        if node_id in self.nodes:
                            self.nodes[node_id].set_sdo_response(sdo_message)

                    except KeyError:
                        # this fails when the node disappears during a running
                        # sdo request

                        pass

            except Exception as e:
                logger.exception("rx: crashed with unhandled error %s", e)
                logger.error("rx: shutdown! Stopping application.")
                # ask async to stop our application
                os.kill(os.getpid(), signal.SIGTERM)

    # Canopen LSS #############################################################
    def _lss_set_response(self, response):
        async def __lss_set_response():
            if not self._pending_lss_request.done() and not self._pending_lss_request.cancelled():
                self._pending_lss_request.set_result(response)

        asyncio.run_coroutine_threadsafe(
            __lss_set_response(),
            loop=self.loop,
        )

    async def lss_request(self, message, timeout=0.2):
        if not self._running or not self._interface_state:
            raise LxaShutdown

        self._pending_lss_request = asyncio.Future()
        self._outgoing_queue.sync_q.put(message)

        try:
            await asyncio.wait_for(self._pending_lss_request, timeout=timeout)

            return self._pending_lss_request.result()

        except asyncio.TimeoutError:
            if not self._pending_lss_request.done() and not self._pending_lss_request.cancelled():
                self._pending_lss_request.set_result(None)

            return None

    async def fast_scan_request(self, lss_id, bit_checked, lss_sub, lss_next):
        # TODO: check if we got the correct response

        # FIXME: sleep is required because RX may not be clean
        # and we may still get replies from the previous request.

        response = await self.lss_request(
            gen_lss_fast_scan_message(lss_id, bit_checked, lss_sub, lss_next),
        )

        if not response:
            return False

        await asyncio.sleep(0.1)

        return True

    def create_mask_from_list(self, lss_ids):
        """
        Takes a list of LSS addresses and generates a mask representing all
        bits that are different between them. Returns known bits (that are the
        same between all addresses) and a mask indication the differences
        """

        mask = [0, 0, 0, 0]

        for a, b in itertools.combinations(lss_ids, 2):
            for i in range(len(mask)):
                mask[i] |= a[i] ^ b[i]

        known_bits = [0, 0, 0, 0]

        for i in range(len(mask)):
            known_bits[i] = lss_ids[0][i] & (0xFFFFFFFF ^ mask[i])

        return known_bits, mask

    async def _fast_scan(self, start=None, mask=None):
        """
        Implements the fast scan algorithm.

        fast_scan_request: fast_scan_request method
        start: Start value for the LSS address (default: [0, 0, 0, 0])
        mask: Only bits that are 0 are going to be tested.
              (default: [0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff])

        returns:
          None: No node could be selected
          LSS Address
        """

        if start is None:
            start = [0, 0, 0, 0]

        if mask is None:
            mask = [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]

        # Check if node on Bus
        if not await self.fast_scan_request(0, 0x80, 0, 0):
            logger.debug("fast_scan: no unconfigured node")

            return None

        lss_id = start

        for lss_sub in range(0, 4):
            for bit_checked in range(31, -1, -1):
                # check if we need to even test this bit
                if not mask[lss_sub] & 1 << bit_checked:
                    continue  # No we don't

                # check if the new bit matches
                response = await self.fast_scan_request(
                    lss_id[lss_sub],
                    bit_checked,
                    lss_sub,
                    lss_sub,
                )

                if not response:
                    lss_id[lss_sub] |= 1 << bit_checked

            # Got to next round
            if lss_sub != 3:
                response = await self.fast_scan_request(lss_id[lss_sub], 0, lss_sub, lss_sub + 1)

                if not response:
                    logger.debug("fast_scan: No next round")

                    return None

        # Final select
        if not await self.fast_scan_request(lss_id[3], 0, 3, 0):
            logger.debug("fast_scan: Final round fail")

            return None

        return lss_id

    async def fast_scan_known_range_all(self, known_nodes=None, start=None, mask=None):
        """
        Implements a fast scan that first tries to search for nodes from a list.
        Then in a range and then all addresses
        """

        # Check if node on Bus
        if not await self.fast_scan_request(0, 0x80, 0, 0):
            logger.debug("fast_scan: no unconfigured node")
            self.lss_state = LxaNetwork.LssStates.IDLE

            return None

        self.lss_state = LxaNetwork.LssStates.SCANNING

        # Try to find a node from the known node list
        if known_nodes is not None and len(known_nodes) > 0:
            known_start, known_mask = self.create_mask_from_list(known_nodes)

            response = await self._fast_scan(known_start, known_mask)

            if response:
                return response

        # Try to find a node from start mask
        if start is not None and mask is not None:
            response = await self._fast_scan(start, mask)

            if response:
                return response

        # Do the complete fast scan algorithm
        return await self._fast_scan()

    def _gen_canopen_node_id(self):
        for i in range(1, 129):
            if i == 125:  # reserved for ISP
                continue

            if i in self.nodes:
                continue

            return i

    async def lss_fast_scan(self):
        try:
            response = await self.lss_request(
                gen_lss_switch_mode_global_message(LssMode.CONFIGURATION),
            )

            if not response:
                logger.debug("fast_scan: No response to switch_mode_global")

            response = await self.lss_request(
                gen_invalidate_node_ids_message(),
            )

            if not response:
                logger.debug("fast_scan: No response to invalidate_node_IDs")

            response = await self.lss_request(
                gen_lss_switch_mode_global_message(LssMode.OPERATION),
            )

            if not response:
                logger.debug("fast_scan: No response to switch_mode_global")

            # List of old node
            await self.load_lss_address_cache()
            old_nodes = deepcopy(self.lss_address_cache)

            while self._running and self._interface_state:
                await asyncio.sleep(1)

                logger.debug("Nodes: %s", self.nodes)

                lss = await self.fast_scan_known_range_all(
                    known_nodes=self.lss_address_cache,
                    start=[0, 0, 0, 0],
                    mask=[0x00000000, 0x000000FF, 0x000000FF, 0x0000FFFF],
                )

                if lss is None:
                    continue

                if lss not in self.lss_address_cache:
                    self.lss_address_cache.append(lss)
                    self.loop.create_task(self.write_lss_address_cache())

                logger.debug("fast_scan: lss: %s", lss)

                # we dont need to search for nodes we already found
                if lss in old_nodes:
                    old_nodes.remove(lss)

                node_id = self._gen_canopen_node_id()

                response = await self.lss_request(
                    gen_lss_configure_node_id_message(node_id),
                )

                if not response:
                    logger.debug("fast_scan: Setting node ID not working")

                self.nodes[node_id] = LxaNode(
                    lxa_network=self,
                    lss_address=lss,
                    node_id=node_id,
                )

                logger.info("fast_scan: Created new node with id {} for {}".format(node_id, lss))

                self._sdo_queues[node_id] = Queue()

                response = await self.lss_request(gen_lss_switch_mode_global_message(LssMode.OPERATION))

                if not response:
                    logger.debug("fast_scan: Setting node ID not working")

        except LxaShutdown:
            logger.debug("fast_scan: shutdown")

    async def lss_ping(self):
        try:
            while self._running and self._interface_state:
                for node_id, node in self.nodes.copy().items():
                    if node_id == 125:  # ISP
                        continue

                    if not await node.ping():
                        logger.warning("lss_ping: node %s does not respond", node)

                        self.nodes.pop(node_id)

                await asyncio.sleep(2)

        except Exception:
            logger.debug("lss_ping: shutdown")

    # Canopen SDO #############################################################
    async def send_message(self, message):
        await self._outgoing_queue.async_q.put(message)

    # public api ##############################################################
    async def shutdown(self):
        self._running = False

    async def run(self):
        self._running = True

        while self._running:
            self.nodes = {
                125: LxaNode(  # ISP node
                    lxa_network=self,
                    lss_address=[0, 0, 0, 0],
                    node_id=125,
                ),
            }

            self._outgoing_queue = Queue()
            self._pending_lss_request = None
            self._sdo_queues = {}

            await self.await_interface_is_up()

            if not self._running:
                break

            self.bus = Bus(
                channel=self.interface,
                bustype=self.bustype,
                bitrate=self.bitrate,
            )

            await asyncio.gather(
                self.update_interface_state(),
                self.lss_fast_scan(),
                self.lss_ping(),
                self.loop.run_in_executor(None, self.send),
                self.loop.run_in_executor(None, self.recv),
            )

            self.bus.shutdown()

    def get_isp_node(self):
        return self.nodes[125]

    def get_node_by_name(self, name):
        for _, node in self.nodes.copy().items():
            if node.name == name:
                return node

        raise ValueError("unknown node name '{}'".format(name))
