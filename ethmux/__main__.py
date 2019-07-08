import manager
import thread

import asyncio
import concurrent.futures
from aiohttp import web

async def fast_scan(request):
    test = "a"
    return web.Response(body=str(test).encode('utf-8'))

async def get_info(request):
    test = str(await thread.cmd.get_node_list())
    return web.Response(body=test.encode('utf-8'))

async def bus_management(interface="can0"):
    print(await thread.cmd.setup(interface, "socketcan"))
    while True:
        print("test pass", await thread.cmd.echo("bla", foo="bar"))
        print(await thread.cmd.setup_new_node())
        await asyncio.sleep(10)



if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Controll domain for the CANOpen bus')
    parser.add_argument('interface', default="can0", type=str)

    args = parser.parse_args()

    thread.start() #Start the thread running sync code

    loop = asyncio.get_event_loop()
    
    asyncio.ensure_future(bus_management(args.interface))
    
    app=web.Application()
    app.router.add_route('GET', "/info", get_info)
    app.router.add_route('GET', "/fastscan", fast_scan)
    
    web.run_app(app)
    thread.stop()
