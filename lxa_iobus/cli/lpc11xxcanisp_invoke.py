#!/usr/bin/env python
# -*- coding: utf-8 -*-

import contextlib
import struct

import canopen
from canopen.sdo.exceptions import SdoCommunicationError


class CanOpen:
    """Minimal Setup to control one ethmux"""

    def __init__(self, channel="can0", node_id=1):
        self.node_id = node_id
        self.network = canopen.Network()
        self.network.connect(channel=channel, bustype="socketcan")
        self.node = self.network.add_node(self.node_id)

    def setup(self):
        """Setup one node with a new node_id"""
        """Warning this expects only one CANOpen node on the network!"""
        self.network.lss.send_switch_state_global(self.network.lss.CONFIGURATION_STATE)
        self.network.lss.configure_node_id(1)
        self.network.lss.send_switch_state_global(self.network.lss.WAITING_STATE)

    def invoke_isp(self):
        """set port state"""
        self.node.sdo.download(0x2B07, 0, struct.pack("I", 0x12345678))


def main():
    can = CanOpen()
    can.setup()

    with contextlib.suppress(SdoCommunicationError):
        can.invoke_isp()


if __name__ == "__main__":
    main()