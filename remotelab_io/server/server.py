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
from remotelab_io.server.nodes import Node

STATIC_ROOT = os.path.join(os.path.dirname(__file__), 'static')
logger = logging.getLogger('RemoteLabIOServer')


class RemoteLabIOServer:
    def __init__(self, app, loop):
        self.state = {
            'active_nodes': {},
        }

        self.app = app
        self.loop = loop

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
        app.router.add_route(
            '*', '/nodes/{node}/{type}/{channel}/{pin}/', self.pin_read_write)

        app.router.add_route('*', '/nodes/{node}/', self.get_node_info)

        app.router.add_route('*', '/nodes/', self.get_nodes)

        # flush initial state
        self.loop.create_task(self.flush_state())

        # setup canopen
        self.canopen_listener = RemoteLabIOCanopenListener()
        self.canopen_network = Network()

        setup_async(loop, self.canopen_listener, self.canopen_network,
                    channel='can0', bustype='socketcan')

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
        return Response(
            text=json.dumps(list(self.state['active_nodes'].keys())))

    async def get_node_info(self, request):
        node = request.match_info['node']

        if node not in self.state['active_nodes']:
            return Response(text='{}')

        return Response(
            text=json.dumps(self.state['active_nodes'][node].info()))

    async def pin_read_write(self, request):
        response = {
            'return_code': 0,
            'message': '',
            'return_value': None,
        }

        def gen_response():
            return Response(text=json.dumps(response))

        try:
            node = request.match_info['node']  # '00000000.0000049a.00000001.5a6ecbea'  # NOQA
            type = request.match_info['type']  # 'input'
            channel = int(request.match_info['channel'])  # '0'
            pin = int(request.match_info['pin'])  # '0'

            node = self.state['active_nodes'][node]
            new_value = request.query.get('set', '')

            if type not in ('inputs', 'outputs', 'adcs', ):
                response['return_code'] = 1
                response['message'] = 'invalid type'

                return gen_response()

            if new_value and not type == 'outputs':
                response['return_code'] = 1
                response['message'] = 'only outputs are writeable'

                return gen_response()

            # set
            if new_value:
                value = int(new_value) << pin
                mask = 1 << pin

                await node.outputs[channel].write(mask, value)

            # get
            if type == 'input':
                channel_state = await node.inputs[channel].read()
                response['return_value'] = (channel_state >> pin) & 1

            elif type == 'outputs':
                channel_state = await node.outputs[channel].read()
                response['return_value'] = (channel_state >> pin) & 1

            elif type == 'adcs':
                response['return_value'] = await node.adcs[channel].read()

        except Exception as e:
            response['return_code'] = 1
            response['message'] = str(e)

        return gen_response()

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

    async def _canopen_bus_management(self, interface="can0"):
        """
        Search for new nodes and cleanup old ones.
        """

        await self.canopen_serialize(self.canopen_listener.reset_all_nodes)

        while True:
            new_nodes = await self.canopen_serialize(
                self.canopen_listener.setup_new_node)

            for node in new_nodes:
                logger.info("Found Node: %s", node)
                node_config = self.state['active_nodes'].get(node, None)

                if node_config is not None:
                    node_config.is_alive = True
                    logger.info("New Node alread known")

                    continue

                node_config = Node(node, self)

                try:
                    await node_config.get_config()

                except BaseException as e:
                    logger.exception(
                        "Requesting the config from node %s failed", node)

                finally:
                    self.state['active_nodes'][node] = node_config
                    logger.info("Node %s has been added", node)

            dead_nodes = await self.canopen_serialize(
                self.canopen_listener.cleanup_old_nodes)

            for dead in dead_nodes:
                node_config = self.state['active_nodes'].get(dead, None)

                if node_config is None:
                    continue

                node_config.is_alive = False

            # node infos
            self.state['nodes'] = {}

            for address, node in self.state['active_nodes'].items():
                self.state['nodes'][address] = node.info()

            await self.flush_state()
            await asyncio.sleep(1)
