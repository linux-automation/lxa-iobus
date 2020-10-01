from concurrent.futures import CancelledError
from functools import partial
from pprint import pformat
from queue import Queue
import concurrent
import asyncio
import logging
import signal
import json
import os

from canopen import Network
from aiohttp.web import FileResponse, Response, HTTPFound
from aiohttp_json_rpc import JsonRpc

from lxa_iobus.server.canopen import LXAIOBusCanopenListener, setup_async
from lxa_iobus.lpc11xxcanisp.can_isp import CanIsp
from lxa_iobus.server.node_drivers import drivers
from lxa_iobus.server.nodes import Node

STATIC_ROOT = os.path.join(os.path.dirname(__file__), 'static')
logger = logging.getLogger('LXAIOBusServer')


class LXAIOBusServer:
    def __init__(self, app, loop, interface, firmware_directory):
        self.app = app
        self.loop = loop
        self.interface = interface
        self.firmware_directory = firmware_directory

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
            ('firmware',),
            ('isp_console',),
        )

        app.router.add_route(
            '*', '/static/{path_info:.*}', self.static)

        app.router.add_route('*', '/', self.index)
        self.app.router.add_route('*', '/rpc/', self.rpc)

        # rest api
        app.router.add_route('GET', '/nodes/{node}/pins/{pin}/', self.get_pin)
        app.router.add_route('POST', '/nodes/{node}/pins/{pin}/', self.set_pin)
        app.router.add_route('GET', '/nodes/{node}/pins/', self.get_pins)

        app.router.add_route('POST', '/nodes/{node}/toggle-locator/',
                             self.toggle_locator)

        app.router.add_route('GET', '/nodes/{node}/pin-info/',
                             self.get_pin_info)

        app.router.add_route('GET', '/nodes/', self.get_nodes)

        # firmware urls
        app.router.add_route(
            'POST',
            '/nodes/{node}/flash-firmware/{source}/{file_name}',
            self.firmware_flash,
        )

        app.router.add_route(
            'POST',
            '/firmware/upload/',
            self.firmware_upload,
        )

        app.router.add_route(
            'POST',
            '/firmware/delete/{file_name}',
            self.firmware_delete,
        )

        # flush initial state
        self.loop.create_task(self.flush_state())

        # setup canopen
        self.canopen_listener = LXAIOBusCanopenListener()
        self.canopen_network = Network()
        self.can_isp_node = self.canopen_network.add_node(125)
        self.can_isp = CanIsp(self, self.can_isp_node)

        setup_async(loop, self.canopen_listener, self.canopen_network,
                    channel=self.interface, bustype='socketcan')

        self.canopen_bus_worker_start()
        self.loop.create_task(self._canopen_bus_management())

        # discover firmware files in firmware directory
        self.loop.create_task(self.discover_firmware_files())

        # flash worker
        self._running = True
        self.flash_jobs = asyncio.Queue()
        self.loop.create_task(self.flash_worker())

    def shutdown(self):
        self.canopen_bus_worker_stop()

        self.flash_jobs.put_nowait(
            (True, None, None, )
        )

        self._running = False

    async def discover_firmware_files(self):
        local_files = []

        for i in os.listdir(self.firmware_directory):
            if i.startswith('.'):
                continue

            local_files.append(i)

        await self.rpc.notify('firmware', {
            'local_files': local_files,
        })

    async def flash_worker(self):
        while self._running:
            try:
                shutdown, node, file_name = await self.flash_jobs.get()

                if shutdown:
                    return

                self.can_isp.console_log('Invoking isp')
                await node.invoke_isp()

                self.can_isp.console_log('Start flashing')
                await self.canopen_serialize(
                    self.can_isp.write_flash,
                    file_name,
                )

                self.can_isp.console_log('Reseting node')
                await self.canopen_serialize(
                    self.can_isp.reset,
                )

                self.can_isp.console_log('Flashing done')

                node.invalidate_info_cache()

            except CancelledError:
                return

            except Exception:
                logger.exception('flashing failed')

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

    async def get_pin_info(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            node_name = request.match_info['node']
            node_driver = self.state['nodes'][node_name]

            pin_info = {
                'locator': await node_driver.node.get_locator_state(),
                'inputs': {},
                'outputs': {},
                'adcs': {},
            }

            for pin_name, pin in node_driver.pins.items():
                value = await pin.read()

                if pin.pin_type == 'input':
                    pin_info['inputs'][pin_name] = value

                elif pin.pin_type == 'output':
                    pin_info['outputs'][pin_name] = value

                elif pin.pin_type == 'adc':
                    pin_info['adcs'][pin_name] = value

            response['result'] = pin_info

        except Exception as e:
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
            pin_name = request.match_info['pin']
            post = await request.post()
            value = post['value']

            pin = self.state['nodes'][node].pins[pin_name]

            if value == 'toggle':
                value = await pin.read()
                value = 1 - value

            else:
                value = int(value)

            response['result'] = await pin.write(value)

        except Exception as e:
            logger.exception("set_pin failed")
            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    async def toggle_locator(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            node_address = request.match_info['node']
            node_driver = self.state['nodes'][node_address]

            state = await node_driver.node.get_locator_state()

            if state == 1:
                new_state = 0

            else:
                new_state = 1

            await node_driver.node.set_locator_state(new_state)

        except Exception as e:
            logger.exception('toggle locator failed')

            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    # firmware views ##########################################################
    async def firmware_upload(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            data = await request.post()

            filename = data['file'].filename
            file_content = data['file'].file.read()

            abs_filename = os.path.join(self.firmware_directory, filename)

            with open(abs_filename, 'wb+') as f:
                f.write(file_content)

            await self.discover_firmware_files()

            return HTTPFound('/#firmware-files')

        except Exception as e:
            logger.exception('firmware upload failed')

            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    async def firmware_delete(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            filename = os.path.join(self.firmware_directory,
                                    request.match_info['file_name'])

            os.remove(filename)

            await self.discover_firmware_files()

        except Exception as e:
            logger.exception('firmware delete failed')

            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    async def firmware_flash(self, request):
        response = {
            'code': 0,
            'error_message': '',
            'result': None,
        }

        try:
            node_address = request.match_info['node']
            source = request.match_info['source']
            file_name = request.match_info['file_name']

            node_driver = self.state['nodes'][node_address]
            node = node_driver.node

            # find firmware file
            if source == 'local':
                file_name = os.path.join(self.firmware_directory, file_name)

            else:
                raise ValueError

            await self.flash_jobs.put(
                (False, node, file_name, )
            )

        except Exception as e:
            logger.exception('firmware delete failed')

            response = {
                'code': 1,
                'error_message': str(e),
                'result': None,
            }

        return Response(text=json.dumps(response))

    # state (rpc) #############################################################
    async def flush_state(self):
        state = []
        node_ids = sorted(self.state['nodes'].keys())

        for node_id in node_ids:
            node_driver = self.state['nodes'][node_id]

            try:
                node_info = await node_driver.node.get_info()

            except Exception:
                node_info = {}

            state.append([
                node_id, {
                    'is_alive': node_driver.is_alive,
                    'driver': node_driver.__class__.__name__,
                    'info': node_info,
                },
            ])

        await self.rpc.notify('state', state)

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
        try:
            await self._canopen_bus_management_worker()

        except OSError as e:
            logging.error(e, exc_info=True)

            os.kill(os.getpid(), signal.SIGTERM)

    async def _canopen_bus_management_worker(self):
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
