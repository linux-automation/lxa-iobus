from functools import partial
from pprint import pformat
from queue import Queue
import concurrent
import asyncio
import logging
import json
import os

from canopen import Network
from aiohttp.web import FileResponse, Response
from aiohttp_json_rpc import JsonRpc

from remotelab_io.server.canopen import RemoteLabIOCanopenListener, setup_async
from remotelab_io.server.node_drivers import drivers
from remotelab_io.server.nodes import Node

STATIC_ROOT = os.path.join(os.path.dirname(__file__), 'static')
logger = logging.getLogger('RemoteLabIOServer')


class RemoteLabIOServer:
    def __init__(self, app, loop, interface):
        self.app = app
        self.loop = loop
        self.interface = interface

        self.state = {
            'low_level_nodes': {},
            'low_level_nodes_state': {},
            'nodes': {}
        }

        # setup aiohttp
        self.rpc = JsonRpc(loop=self.loop, max_workers=6)
        self.worker_pool = self.rpc.worker_pool
        app['rpc'] = self.rpc

        self.rpc.add_topics(
            ('state',),
        )

        app.router.add_route(
            '*', '/static/{path_info:.*}', self.static)

        app.router.add_route('*', '/', self.index)
        self.app.router.add_route('*', '/rpc/', self.rpc)

        # rest api
        app.router.add_route('GET', '/nodes/{node}/pins/{pin}/', self.get_pin)
        app.router.add_route('POST', '/nodes/{node}/pins/{pin}/', self.set_pin)
        app.router.add_route('GET', '/nodes/{node}/pins/', self.get_pins)
        app.router.add_route('GET', '/nodes/', self.get_nodes)

        # flush initial state
        self.loop.create_task(self.flush_state())

        # setup canopen
        self.canopen_listener = RemoteLabIOCanopenListener()
        self.canopen_network = Network()

        setup_async(loop, self.canopen_listener, self.canopen_network,
                    channel=self.interface, bustype='socketcan')

        self.canopen_bus_worker_start()
        self.loop.create_task(self._canopen_bus_management())

    def shutdown(self):
        self.canopen_bus_worker_stop()

    # views ###################################################################
    async def index(self, request):
        return FileResponse(os.path.join(STATIC_ROOT, 'index.html'))

    async def static(self, request):
        path = os.path.join(
            STATIC_ROOT,
            os.path.relpath(request.path, '/static/'),
        )

        if not os.path.exists(path):
            return Response(text='404: not found', status=404)

        return FileResponse(path)

    async def get_nodes(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': list(k for k, v in self.state['nodes'].items() if v.is_alive),
        }

        return Response(text=json.dumps(response))

    async def get_pins(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': [],
        }

        try:
            node = request.match_info['node']
            response['result'] = list(self.state['nodes'][node].pins.keys())

        except Exception as e:
            logger.exception("get_pins failed")
            response = {
                'code': 1,
                'error_message': str(e),
                'result': [],
            }

        return Response(text=json.dumps(response))

    async def get_pin(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            node = request.match_info['node']
            pin = request.match_info['pin']

            response['result'] = \
                await self.state['nodes'][node].pins[pin].read()

        except Exception as e:
            logger.exception("get_pin failed")
            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    async def set_pin(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            node = request.match_info['node']
            pin = request.match_info['pin']
            post = await request.post()
            value = post['value']

            response['result'] = \
                await self.state['nodes'][node].pins[pin].write(int(value))

        except Exception as e:
            logger.exception("set_pin failed")
            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    # state (rpc) #############################################################
    async def flush_state(self):
        await self.rpc.notify('state', pformat(self.state))

    def flush_state_sync(self, wait=True):
        self.rpc.worker_pool.run_sync(
            partial(self.rpc.notify, 'state', pformat(self.state)), wait=wait)

    # canopen #################################################################
    def canopen_bus_worker_start(self):
        self._canopen_bus_worker_start = True
        self._canopen_bus_worker_queue = Queue()

        self.worker_pool.executor.submit(self._canopen_bus_worker)

    def canopen_bus_worker_stop(self):
        self._canopen_bus_worker_start = False

    def canopen_serialize(self, func, *args, **kwargs):
        func = partial(func, *args, **kwargs)
        concurrent_future = concurrent.futures.Future()
        future = asyncio.futures.wrap_future(concurrent_future)

        self._canopen_bus_worker_queue.put((func, concurrent_future, ))

        return future

    def _canopen_bus_worker(self):
        while self._canopen_bus_worker_start:
            func, future = self._canopen_bus_worker_queue.get()

            try:
                ret = func()
                future.set_result(ret)

            except Exception as e:
                future.set_exception(e)

    async def _canopen_bus_management(self):
        """
        Search for new nodes and cleanup old ones.
        """

        await self.canopen_serialize(self.canopen_listener.reset_all_nodes)

        while True:
            new_nodes = await self.canopen_serialize(
                self.canopen_listener.setup_new_node)

            for node in new_nodes:
                logger.info("Found Node: %s", node)
                node_config = self.state['low_level_nodes'].get(node, None)

                if node_config is not None:
                    node_config.is_alive = True
                    logger.info("New Node already known")

                    continue

                node_config = Node(node, self)

                try:
                    await node_config.get_config()

                except BaseException as e:
                    logger.exception(
                        "Requesting the config from node %s failed", node)

                finally:
                    self.state['low_level_nodes'][node] = node_config
                    logger.info("Node %s has been added", node)

            dead_nodes = await self.canopen_serialize(
                self.canopen_listener.cleanup_old_nodes)

            for dead in dead_nodes:
                node_config = self.state['low_level_nodes'].get(dead, None)

                if node_config is None:
                    continue

                node_config.is_alive = False

            # node infos
            self.state['low_level_nodes_state'] = {}

            for address, node in self.state['low_level_nodes'].items():
                self.state['low_level_nodes_state'][address] = node.info()

                # find driver
                for driver_class in drivers:
                    name = driver_class.match(node)
                    if name is None:
                        continue

                    if name in self.state['nodes']:
                        # we already have a driver for this node
                        break

                    driver = driver_class(node)
                    self.state['nodes'][name] = driver

                    break

            await self.flush_state()
            await asyncio.sleep(1)
