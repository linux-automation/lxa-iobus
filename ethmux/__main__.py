import manager
import thread

import logging

import asyncio
import concurrent.futures
from aiohttp import web

logging.basicConfig(level=logging.ERROR, format='%(threadName)s %(levelname)s %(name)s: %(message)s')

class LoggingFilter(logging.Filter):
    def filter(self, record):
        return True


logger = logging.getLogger("controller")
logger.setLevel( logging.DEBUG )

async def fast_scan(request):
    test = "a"
    return web.Response(body=str(test).encode('utf-8'))

async def get_info(request):
    test = str(await thread.cmd.get_node_list())
    return web.Response(body=test.encode('utf-8'))

async def bus_management(interface="can0"):
    print(await thread.cmd.setup(interface, "socketcan"))
    await thread.cmd.reset_all_nodes()
    while True:
        try:
            new_nodes = await thread.cmd.setup_new_node()
            if len(new_nodes) > 0:
                logger.info("New_node found %s", new_nodes)
        except:
            pass
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

async def upload(request):
    print(request)
    print(request.rel_url.query)
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

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Controll domain for the CANOpen bus')
    parser.add_argument('interface', default="can0", type=str)

    args = parser.parse_args()

    logger.debug("test %x",0)

    thread.start() #Start the thread running sync code

    loop = asyncio.get_event_loop()
    
    asyncio.ensure_future(bus_management(args.interface))
    
    app=web.Application()
    app.router.add_route('GET', "/", get_index)
    app.router.add_route('GET', "/upload", upload)
    app.router.add_route('GET', "/info", get_info)
    app.router.add_route('GET', "/fastscan", fast_scan)
    
    web.run_app(app)
    thread.stop()
