import socket
import time
import sys

import json
import collections

import argparse

arg_epilog = """
get 00000000.0c0ce935.534d0000.5c12ca96:Input-0,Input-0.1,Output-0.0,adc-0,Input-0.2,output-0
"""

class ServerException(Exception):
    pass

class UnixSocketIPC:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.sock.connect(path)

    def __del__(self):
        self.sock.close()

    def send_request(self, command, args):
        request = {"cmd": command, "args": args}

        self.sock.send(json.dumps(request).encode())
        answer = self.sock.recv(4096).decode()

        answer = json.loads(answer)
        if answer["error"]:
            if len(answer["error_msg"]) != 0:
                raise ServerException(answer["error_msg"])
            raise Exception("Unknown remote error")

        return answer["resulte"]

    def __getattr__(self, command):
        def tmp(*args, **dicts):
            return self.send_request(command, [args, dicts])
        return tmp


class Nodes:
    def __init__(self, comm):
        nodes = comm.get_node_list()
        self.nodes = collections.OrderedDict( sorted( nodes.items() ) )

    def show(self):
        for address, interface in self.nodes.items():
            print("  Inputs:")
            for interface_input in interface["inputs"]:
                print("    {}: {} Pins".format(interface_input["channel"], interface_input["pins"]))

            print("  Outputs:")
            for interface_output in interface["outputs"]:
                print("    {}: {} Pins".format(interface_output["channel"], interface_output["pins"]))

            print("  ADCs:")
            for interface_adc in interface["adcs"]:
                print("    {}:".format(interface_adc["channel"]))

    def is_node_online(self, address):
        config = self.nodes.get(address, None)
        if config is None:
            return False
        if config["alive"]:
            return True
        return False
    

def get_state(comm, address, interface, channel):
    response = comm.get_channel_state(address, interface, channel)
    print("{}: {}, {}: {}".format(address, channel, interface, response))

def set_output(comm, address, channel, mask, data):
    response = comm.set_output_masked(address, channel, mask, data)

def parse(string):

    address, requests = string.split(":", 1)
    
    requests = requests.split(",")

    channels_get = collections.OrderedDict()
    channels_set = collections.OrderedDict()
    for requ in requests:
        interface, command = requ.split("-", 1)
        interface = interface.lower()

        if not interface in ["input", "output", "adc"]:
            raise Exception("{} is not a valid interface", interface)

        command = command.split("=", 1)
        if len(command) == 1:
            command = command[0]
            value = None
            write = False
        else:
            command, value = command
            write = True

        command = command.split(".", 1)
        if len(command) == 1:
            channel = int(command[0])
            pin = "all"
        else:
            channel, pin = command
            channel, pin = int(channel), int(pin)


        cmd = { "interface": interface,
                "channel": int(channel),
                "pin": pin,
                "write": write,
                "value": value}

        key = "{}:{}".format(channel, interface)
        if write:
            tmp = channels_set.get(key, [])
            tmp.append(cmd)
            channels_set[key] = tmp
        else:
            tmp = channels_get.get(key, [])
            tmp.append(cmd)
            channels_get[key] = tmp

    return address, channels_get, channels_set

def format_input(address, cmd, state):
    if cmd["pin"] == "all":
        print("{}:{}-{}={}".format(
            address,
            cmd["interface"],
            cmd["channel"],
            state))
    else:
        pin_state = ( state & (1<<int(cmd["pin"])) ) != 0
        print("{}:{}-{}.{}={}".format(
            address,
            cmd["interface"],
            cmd["channel"],
            cmd["pin"],
            pin_state))
def main():
    parser = argparse.ArgumentParser(
        epilog=arg_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-s",
        "--socket",
        help="Overrides the default socket for client mode.",
        default="/tmp/canopen_master.sock")

    parser.add_argument(
        "command",
        help="The command to be execute",
        choices=["list", "cmd"],
        type=str.lower)

    parser.add_argument(
        "cmds",
        help="Node address and list of requests",
        type=str.lower,
        nargs="?",
        default=""
    )

    args = parser.parse_args()

    try:
        ipc = UnixSocketIPC(args.socket)
    except:
        print("CANOpen service not found")
        exit(1)

    if args.command == "list":
        nodes = Nodes(ipc)
        nodes.show()

    if args.command == "cmd":
        nodes = Nodes(ipc)

        try:
            address, sorted_cmd_get, sorted_cmd_set = parse(args.cmds)
        except ValueError as e:
            print("Error parsing command line: {}".format(str(e)))
            exit(1)

        if not nodes.is_node_online(address):
            print("Node address {} not online".format(address))
            exit(1)

        # Read data from node
        for _, cmds in sorted_cmd_get.items():
            cmd = cmds[0]
            state = ipc.get_channel_state(address, cmd["channel"], cmd["interface"])
            for cmd in cmds:
                if cmd["interface"] in ["adc", "input", "output"]:
                    format_input(address, cmd, state)

        # Write data to node
        for _, cmds in sorted_cmd_set.items():
            mask = 0
            data = 0
            for cmd in cmds:
                if cmd["interface"] in ["output"]:
                    if cmd["pin"] == "all":
                        mask = 0xffff
                        data = int(cmd["value"])
                    else:
                        pin_mask = 1<<(int(cmd["pin"]))
                        mask |= pin_mask
                        value = cmd["value"]

                        value = {'false': 0, 'true': 1, '0': 0, '1': 1}[value.lower()]

                        data = ( data & (~pin_mask) ) | ( value<<int(cmd["pin"]) )
                else:
                    print("Can't write to {}:{}.{}".format(
                        cmd["interface"],
                        cmd["channel"],
                        cmd["pin"]))
            cmd = cmds[0]
            set_output(ipc, address, cmd["channel"], mask, data)

    exit(0)

    adr = "00000001.00000001.00000001.00000d10"
    adr = "00000000.0c0ce935.534d0000.5c12ca96"
    get_state(ipc,  adr, 0, "Input")
    set_output(ipc, adr, 0, 3, 3)
    get_state(ipc,  adr, 0, "Output")
    set_output(ipc, adr, 0, 3, 0)
    get_state(ipc,  adr, 0, "Output")
    get_state(ipc,  adr, 0, "ADC")
    get_state(ipc,  adr, 1, "ADC")
    set_output(ipc, adr, 0, 3, 3)
    set_output(ipc, adr, 0, 3, 0)


if __name__ == "__main__":
    main()
