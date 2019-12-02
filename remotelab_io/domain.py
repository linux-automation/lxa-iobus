from . import manager
from . import thread
from . import nodes
from . import service

import logging

import json

import asyncio
import concurrent.futures
from aiohttp import web

logging.basicConfig(
    level=logging.ERROR,
    format='%(threadName)s %(levelname)s %(name)s: %(message)s',
)

activ_nodes = {}

logger = logging.getLogger('controller')
logger.setLevel(logging.DEBUG)


async def await_terminate(aws, terminate_furure):
    """Takes an aws and a future. If the future is set it returns None"""
    done, pending = await asyncio.wait(
        (aws, terminate_furure),
        return_when=asyncio.FIRST_COMPLETED,
    )

    if terminate_furure in done:
        return None
    return await aws


async def bus_management(interface="can0"):
    """Search for new nodes and cleanup old ones."""
    await thread.cmd.reset_all_nodes()
    while True:
        new_nodes = await thread.cmd.setup_new_node()
        for node in new_nodes:
            logger.info("Found Node: %s", node)
            node_config = activ_nodes.get(node, None)
            if node_config is not None:
                node_config.is_alive = True
                logger.info("New Node alread known")
                continue

            node_config = nodes.Node(node)
            try:
                await node_config.get_config()
            except BaseException as e:
                logger.exception("Requesting the config from node %s failed",
                                 node)
            finally:
                activ_nodes[node] = node_config
                logger.info("Node %s has been added", node)

        dead_nodes = await thread.cmd.cleanup_old_nodes()
        for dead in dead_nodes:
            node_config = activ_nodes.get(dead, None)
            if node_config is None:
                continue
            node_config.is_alive = False
        await asyncio.sleep(1)


async def get_index(request):
    nodes = await thread.cmd.get_node_list()
    html = "<html><body>\n"
    html += '<table style="width:100%">\n'

    for node in nodes:
        html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>\n'.format(
            node["lss"],
            node["node_id"],
            node["age"],
        )

    html += '</table>\n'
    html += "</body></html>"

    return web.Response(body=html.encode('utf-8'), content_type="text/html")


async def get_nodes(request):
    html = "<html><body>\n"
    html += '<table>\n'

    for address, node in activ_nodes.items():
        html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(
            address,
            "",
            "",
        )

        for ch in node.inputs:
            state = await ch.read()
            check = ""
            for pin in range(ch.pins):
                check += '<input type="checkbox" name="{}", {}>'.format(
                    pin+1,
                    "checked=1" if 1 & (state >> pin) else "",
                )

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(
                state,
                "Input",
                check,
            )

        for ch in node.outputs:
            state = await ch.read()
            check = ""

            for pin in range(ch.pins):
                check += '<input type="checkbox" name="{}", {}>'.format(
                    pin+1,
                    "checked=1" if 1 & (state >> pin) else "",
                )

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(
                state,
                "Output",
                check,
            )

        for ch in node.adcs:
            state = await ch.read()
            check = "{}".format(state)

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(
                state,
                "ADC",
                check,
            )

    html += '</table>\n'
    html += "</body></html>"

    return web.Response(body=html.encode('utf-8'), content_type="text/html")


async def upload(request):
    lss = request.rel_url.query['lss']
    index = int(request.rel_url.query['index'])
    subindex = int(request.rel_url.query['subindex'])

    try:
        resp = await thread.cmd.upload(lss, index, subindex)
    except canopen.sdo.exceptions.SdoAbortedError as e:
        out = str(e)
        return web.Response(body=out.encode('utf-8'), content_type="text/html")

    out = ",".join(["0x{:X}".format(i) for i in resp])
    return web.Response(body=out.encode('utf-8'), content_type="text/html")


async def get_node_list():
    """Returns list of all nodes and there interface"""
    out = {}
    for addr, node in activ_nodes.items():
        out[addr] = node.info()
    return out
service.api_mapping["get_node_list"] = get_node_list


async def get_channel_state(address, channel, interface="Input"):
    node = activ_nodes.get(address, None)
    if node is None:
        raise Exception("address not on bus: {}".format(address))

    try:
        channel = int(channel)
        interface = interface.lower()
        if interface == "input":
            state = await node.inputs[channel].read()
        elif interface == "adc":
            state = await node.adcs[channel].read()
        elif interface == "output":
            state = await node.outputs[channel].read()
        else:
            raise Exception("{} is an invalide interface".format(interface))

    except IndexError:
        raise Exception("Input channel not on node: {}".format(channel))

    return state

service.api_mapping["get_channel_state"] = get_channel_state


async def set_output_masked(address, channel, mask, data):
    node = activ_nodes.get(address, None)
    if node is None:
        raise Exception("address not on bus: {}".format(address))

    try:
        channel = int(channel)
        mask = int(mask)
        data = int(data)
    except IndexError:
        raise Exception("Output channel not on node: {}, {}".format(
            channel, len(node.outputs)))

    state = node.outputs[channel]
    return await state.write(mask, data)

service.api_mapping["set_output_masked"] = set_output_masked


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Control domain for ethmux, usw over CANOpen',
    )

    parser.add_argument(
            'interface',
            default="can0",
            type=str)

    parser.add_argument(
            '-s',
            '--socket',
            help="Overrides the default socket.",
            default="/tmp/canopen_master.sock",
            type=str)

    parser.add_argument(
            '--web',
            help="Start with webserver",
            action='store_true')

    parser.add_argument(
            '--port',
            help="Port to launch the webserver on",
            default=8080,
            type=int)

    args = parser.parse_args()
    unix_socket_path = args.socket

    loop = asyncio.get_event_loop()

    thread.start()  # Start the thread running sync code

    management = asyncio.ensure_future(bus_management(args.interface))

    try:
        ipc = service.startup_socket(unix_socket_path, loop)
    except OSError as e:
        logger.error("Could not setup communication socket: %s", e)

    if args.web:
        app = web.Application()
        app.router.add_route('GET', "/", get_index)
        app.router.add_route('GET', "/nodes", get_nodes)
        app.router.add_route('GET', "/upload", upload)

        srv = loop.create_server(
            app.make_handler(),
            '127.0.0.1', 8080,
        )

    try:
        manager.setup_async(loop, args.interface, "socketcan")

        logger.info("Starting async loop")
        if args.web:
            loop.run_until_complete(srv)

        loop.run_until_complete(management)
    except KeyboardInterrupt:
        logger.info("Strg+c recived")
    except OSError:
        logger.exception("OSError")

    logger.info("Stopping async loop")

    thread.stop()
    ipc.shutdown()

    try:
        loop.run_forever()
    finally:
        import os
        os.remove(unix_socket_path)


if __name__ == "__main__":
    main()
