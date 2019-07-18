import manager
import thread
import nodes
import service

import logging

import json

import asyncio
import concurrent.futures
from aiohttp import web

logging.basicConfig(level=logging.ERROR, format='%(threadName)s %(levelname)s %(name)s: %(message)s')

activ_nodes = {}

logger = logging.getLogger("controller")
logger.setLevel( logging.DEBUG )

async def await_terminate(aws, terminate_furure):
    """Takes an aws and a future. If the future is set it returns None"""
    done, pending = await asyncio.wait((aws, terminate_furure), return_when=asyncio.FIRST_COMPLETED)
    if terminate_furure in done:
        return None
    return await aws


async def bus_management(interface="can0"):
    try:
        await thread.cmd.setup(interface, "socketcan")
    except OSError as e:
        logger.exception("OSError when setting up CAN interface")
        return

    await thread.cmd.reset_all_nodes()
    while True:
        new_nodes = await thread.cmd.setup_new_node()
        if len(new_nodes) > 0:
            logger.info("New_node found %s", new_nodes)
        for node in new_nodes:
            logger.info("add %s", node)
            activ_nodes[node] = nodes.Node(node)
            await activ_nodes[node].get_config()

        dead_nodes = await thread.cmd.cleanup_old_nodes()
        await asyncio.sleep(1)

async def get_index(request):
    nodes = await thread.cmd.get_node_list()
    html = "<html><body>\n"
    html += '<table style="width:100%">\n'
    for node in nodes:
        html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>\n'.format(node["lss"], node["node_id"], node["age"])
    html += '</table>\n'
    html += "</body></html>"
    return web.Response(body=html.encode('utf-8'), content_type="text/html")

async def get_nodes(request):
    html = "<html><body>\n"
    html += '<table>\n'
    for address, node in activ_nodes.items():
        html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(address, "", "")
        for ch in node.inputs:
            state = await ch.read()
            check = ""
            for pin in range(ch.pins):
                check += '<input type="checkbox" name="{}", {}>'.format(pin+1, "checked=1" if 1&(state>>pin) else "")

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(state, "Input", check)
        for ch in node.outputs:
            state = await ch.read()
            check = ""
            for pin in range(ch.pins):
                check += '<input type="checkbox" name="{}", {}>'.format(pin+1, "checked=1" if 1&(state>>pin) else "")

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(state, "Output", check)
        for ch in node.adcs:
            state = await ch.read()
            check = "{}".format(state)

            html += '  <tr><th>{}</th><th>{}</th><th>{}</th></tr>'.format(state, "ADC", check)

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

    print(resp)
    out = ",".join(["0x{:X}".format(i) for i in resp])
    return web.Response(body=out.encode('utf-8'), content_type="text/html")

async def get_node_list():
    """Returns list of all nodes and there interface"""
    print(activ_nodes)
    out = {}
    for addr, node in activ_nodes.items():
        print(addr, node)
        out[addr] = node.info()
    return out
service.api_mapping["get_node_list"] = get_node_list

async def get_channel_state(address, channel, interface="Input"):
    node = activ_nodes.get(address, None)
    if node is None:
        raise Exception("address not on bus: {}".format(address))

    try:
        channel = int(channel)
        if interface == "Input":
            state = await node.inputs[channel].read()
        elif interface == "ADC":
            state = await node.adcs[channel].read()
        else:
            state = await node.outputs[channel].read()

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
        print(channel,mask,data)
    except IndexError:
        raise Exception("Output channel not on node: {}, {}".format(channel, len(node.outputs)) )

    state = node.outputs[channel]
    return await state.write(mask, data)

service.api_mapping["set_output_masked"] = set_output_masked


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Controll domain for the CANOpen bus')
    parser.add_argument('interface', default="can0", type=str)

    unix_socket_path = "/tmp/foobar"

    args = parser.parse_args()

    logger.debug("test %x",0)


    loop = asyncio.get_event_loop()

    thread.start() #Start the thread running sync code
    
    management = asyncio.ensure_future(bus_management(args.interface))

    ipc = service.startup_socket(unix_socket_path, loop)
    
    app=web.Application()
    app.router.add_route('GET', "/", get_index)
    app.router.add_route('GET', "/nodes", get_nodes)
    app.router.add_route('GET', "/upload", upload)

    srv = loop.create_server(app.make_handler(),
            '127.0.0.1', 8080)

    
    logger.info("Starting async loop")
    try:
        loop.run_until_complete(srv)
        loop.run_until_complete(management)
    except KeyboardInterrupt:
        print("Received exit, exiting")

    logger.info("Stopping async loop")

    thread.stop()
    ipc.shutdown()

    loop.run_forever()

    import os
    os.remove(unix_socket_path) 
