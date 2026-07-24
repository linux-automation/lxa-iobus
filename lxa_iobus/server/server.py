import asyncio
import json
import logging
import math
import os
from concurrent.futures import CancelledError
from datetime import datetime

from aiohttp import ClientConnectionResetError
from aiohttp.web import HTTPBadRequest, HTTPForbidden, HTTPNotFound, Response, StreamResponse, json_response

from lxa_iobus.lpc11xxcanisp.can_isp import CanIsp
from lxa_iobus.lpc11xxcanisp.firmware import FIRMWARE_DIR

STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")
logger = logging.getLogger("LXAIOBusServer")

# Server and node status are relatively cheap to fetch because they contain cacheable data.
# Getting the pin information from the node does however involve multiple roundtrips on the CAN bus.
# Do the former at 10Hz and the latter at 1Hz.
EVENT_DELAY_STATUS = 1.0 / 10.0
EVENT_DELAY_PINS = 1.0 / 1.0


class MaybeJsonEventStream:
    """Serve a single JSON response or an event stream based on user request

    If the user sent a normal GET request: respond with a single JSON response.
    If the user connected via `new EventSource` respond with an event stream
    of one JSON line each.

    This de-duplicates messages that encode to the same JSON to reduce network
    traffic.
    """

    def __init__(self, request, headers=None):
        accept = request.headers.get("Accept")
        self.event_stream = accept == "text/event-stream"
        self.prev_data = None
        self.response = StreamResponse()
        self.request = request

        if headers:
            self.response.headers.update(headers)

        if self.event_stream:
            self.response.content_type = "text/event-stream"
            self.response.headers["Cache-Control"] = "no-cache"
            self.response.headers["Connection"] = "keep-alive"
            self.response.headers["X-Accel-Buffering"] = "no"
        else:
            self.response.content_type = "application/json"

    async def push(self, message):
        if not self.response.prepared:
            await self.response.prepare(self.request)

        data = json.dumps(message).encode()

        if data == self.prev_data:
            return False

        self.prev_data = data

        if self.event_stream:
            data = b"data: " + data + b"\n\n"

        try:
            await self.response.write(data)
        except ClientConnectionResetError:
            return True

        return not self.event_stream


class LXAIOBusServer:
    def __init__(self, app, loop, network):
        self.app = app
        self.loop = loop
        self.network = network
        self._isp_console = list()
        self._isp_console_queues = list()

        self.state = {"low_level_nodes": {}, "low_level_nodes_state": {}, "nodes": {}}

        self.started = datetime.now()

        # rest api
        app.router.add_route("GET", "/server-info/", self.get_server_info)
        app.router.add_route("GET", "/nodes/{node}/pins/{pin}/", self.get_pin)
        app.router.add_route("POST", "/nodes/{node}/pins/{pin}/", self.set_pin)
        app.router.add_route("GET", "/nodes/{node}/pins/", self.get_pins)

        app.router.add_route("POST", "/nodes/{node}/toggle-locator/", self.toggle_locator)

        app.router.add_route("GET", "/nodes/{node}/pin-info/", self.get_pin_info)

        app.router.add_route("POST", "/nodes/{node}/update/", self.firmware_update)

        app.router.add_route("GET", "/nodes/", self.get_nodes)
        app.router.add_route("GET", "/nodes/{node}/", self.get_node)

        app.router.add_route("GET", "/api/v2/status", self.get_status)
        app.router.add_route("GET", "/api/v2/isp_log", self.get_isp_console)

        app.router.add_route("GET", "/api/v2/node/{node}/raw_sdo/{index}/{sub_index}", self.get_sdo_raw)
        app.router.add_route("POST", "/api/v2/node/{node}/raw_sdo/{index}/{sub_index}", self.send_sdo_raw)

        # static files
        app.router.add_static("/static", STATIC_ROOT)

        # setup can isp
        self.can_isp = CanIsp(node=network.isp_node, logging_callback=self._isp_logging_callback)

        # flash worker
        self._running = True
        self.flash_jobs = asyncio.Queue()
        self.loop.create_task(self.flash_worker())

    def shutdown(self):
        self._running = False

    async def _isp_logging_callback(self, message):
        for line in message.split("\n"):
            prev_id = "0"
            if self._isp_console:
                prev_id, _ = self._isp_console[-1]

            entry = (str(int(prev_id) + 1), line)

            self._isp_console = self._isp_console[-99:] + [entry]

            for queue in self._isp_console_queues:
                await queue.put(entry)

    def _isp_console_queue(self, last_id=None):
        queue = asyncio.Queue()

        for id, line in self._isp_console:
            if id == last_id:
                last_id = None

            if last_id is None:
                queue.put_nowait((id, line))

        self._isp_console_queues.append(queue)

        return queue

    async def flash_worker(self):
        while self._running:
            try:
                shutdown, node, file_name = await self.flash_jobs.get()

                if shutdown:
                    return

                await self.can_isp.console_log(
                    "Flashing {} ({})".format(
                        node.name,
                        node.address,
                    )
                )

                await self.can_isp.console_log("Invoking isp")
                await node.invoke_isp()

                await self.can_isp.console_log("Start flashing")
                await self.can_isp.write_flash(file_name)

                await self.can_isp.console_log("Resetting node")
                await self.can_isp.reset()

                await self.can_isp.console_log("Flashing done")

            except CancelledError:
                return

            except Exception:
                logger.exception("flashing failed")

    # views ###################################################################
    def _get_server_info_once(self):
        return {
            "hostname": os.uname()[1],
            "started": str(self.started),
            "can_interface": self.network.interface,
            "can_interface_is_up": self.network.interface_is_up(),
            "lss_state": self.network.lss_state.value,
            "can_tx_error": self.network.tx_error,
        }

    async def get_server_info(self, request):
        headers = {"Access-Control-Allow-Origin": "*"}
        response = MaybeJsonEventStream(request, headers)

        while self._running:
            info = self._get_server_info_once()
            stop = await response.push(info)
            if stop:
                break

            await asyncio.sleep(EVENT_DELAY_STATUS)

        return response.response

    async def get_nodes(self, request):
        headers = {"Access-Control-Allow-Origin": "*"}
        response = MaybeJsonEventStream(request, headers)

        while self._running:
            node_names = sorted(node.name for node in self.network.nodes.values())
            message = {
                "code": 0,
                "error_message": "",
                "result": node_names,
            }
            stop = await response.push(message)
            if stop:
                break

            await asyncio.sleep(EVENT_DELAY_STATUS)

        return response.response

    async def get_node(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": {},
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            driver = node.product.__class__.__name__ + "Driver"
            info = await node.info()

            response["result"] = {
                "locator": node.locator_state,
                "driver": driver,
                "info": info,
            }

        except ValueError as e:
            logger.info(
                "get_node: user requested unknown node '%s'.",
                node_name,
            )
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        except Exception as e:
            logger.exception("get_node failed")
            response = {
                "code": 1,
                "error_message": str(e),
                "result": [],
            }

        headers = {"Access-Control-Allow-Origin": "*"}

        return json_response(response, headers=headers)

    async def get_status(self, request):
        server = request.query.get("server")
        nodes = request.query.get("nodes")
        pins = request.query.getall("pins", [])
        server_interval = request.query.get("server_interval", "0")
        nodes_interval = request.query.get("nodes_interval", "0")
        pins_interval = request.query.get("pins_interval", "0")

        # If the request did not contain any request parameters
        # return a default set of server status info and node list.
        if server is None and nodes is None and not pins:
            server = "true"
            nodes = "true"

        server = (server is not None) and server != "false"
        nodes = (nodes is not None) and nodes != "false"
        server_interval = max(EVENT_DELAY_STATUS, float(server_interval))
        nodes_interval = max(EVENT_DELAY_STATUS, float(nodes_interval))
        pins_interval = max(EVENT_DELAY_PINS, float(pins_interval))

        response = MaybeJsonEventStream(request)

        server_delay = 0.0 if server else math.inf
        nodes_delay = 0.0 if nodes else math.inf
        pin_delay = 0.0 if pins else math.inf

        message = dict()

        while self._running:
            if server_delay <= 0.0:
                server_delay += server_interval
                message["server"] = self._get_server_info_once()

            if nodes_delay <= 0:
                nodes_delay += nodes_interval

                message["nodes"] = dict()

                for node in self.network.nodes.values():
                    message["nodes"][node.name] = {
                        "locator": node.locator_state,
                        "driver": f"{node.product.__class__.__name__}Driver",
                        "info": await node.info(),
                    }

            if pin_delay <= 0.0:
                pin_delay += pins_interval

                message["pins"] = dict()

                for node_name in pins:
                    message["pins"][node_name] = await self._get_pin_info_once(node_name)

            stop = await response.push(message)
            if stop:
                break

            delay = min(server_delay, nodes_delay, pin_delay)
            await asyncio.sleep(delay)
            server_delay -= delay
            nodes_delay -= delay
            pin_delay -= delay

        return response.response

    async def get_isp_console(self, request):
        accept = request.headers.get("Accept")

        if accept != "text/event-stream":
            return Response(text="\n".join(line for _id, line in self._isp_console))

        response = StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["X-Accel-Buffering"] = "no"
        await response.prepare(request)

        last_id = request.headers.get("Last-Event-ID")
        queue = self._isp_console_queue(last_id)

        try:
            while self._running:
                id, line = await queue.get()
                await response.write(f"id: {id}\ndata: {line}\n\n".encode())
        except ClientConnectionResetError:
            pass
        finally:
            self._isp_console_queues.remove(queue)

        return response

    async def get_pins(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": [],
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            if "outputs" in node.od:
                response["result"].extend(node.od.outputs.pins)

            if "inputs" in node.od:
                response["result"].extend(node.od.inputs.pins)

            if "adc" in node.od:
                response["result"].extend(node.od.adc.channel_names)

        except ValueError as e:
            logger.info(
                "get_pins: user requested pins from unknown node '%s'.",
                node_name,
            )
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        except Exception as e:
            logger.exception("get_pins failed")
            response = {
                "code": 1,
                "error_message": str(e),
                "result": [],
            }

        return Response(text=json.dumps(response))

    async def get_pin(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            pin_name = request.match_info["pin"]
            node = self.network.get_node_by_name(node_name)

            if "outputs" in node.od and pin_name in node.od.outputs.pins:
                response["result"] = int(await node.od.outputs.get(pin_name))

            elif "inputs" in node.od and pin_name in node.od.inputs.pins:
                response["result"] = int(await node.od.inputs.get(pin_name))

            elif "adc" in node.od and pin_name in node.od.adc.channel_names:
                response["result"] = await node.od.adc.read(pin_name)

            else:
                raise KeyError()

            logger.info(
                "get_pin: read pin %s on node %s: %s",
                pin_name,
                node_name,
                response["result"],
            )

        except ValueError as e:
            logger.info(
                "get_pin: user requested pin from unknown node '%s'.",
                node_name,
            )
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        except KeyError:
            logger.info(
                "get_pin: user requested unknown pin '%s' from node '%s'.",
                pin_name,
                node_name,
            )
            response = {
                "code": 1,
                "error_message": f"unknown pin '{pin_name}' for node '{node_name}'",
                "result": None,
            }

        except Exception as e:
            logger.exception("get_pin failed")
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))

    async def _get_pin_info_once(self, node_name):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node = self.network.get_node_by_name(node_name)

            pin_info = {
                "locator": node.locator_state,
                "inputs": {},
                "outputs": {},
                "adcs": {},
            }

            if "inputs" in node.od:
                inputs = await node.od.inputs.get_all()

                # The API exposes the output state as integers, not booleans.
                # Convert between the types.
                pin_info["inputs"] = dict((name, int(value)) for name, value in inputs.items())

            if "outputs" in node.od:
                outputs = await node.od.outputs.get_all()

                # The API exposes the output state as integers, not booleans.
                # Convert between the types.
                pin_info["outputs"] = dict((name, int(value)) for name, value in outputs.items())

            if "adc" in node.od:
                adcs = await node.od.adc.read_all()

                # The API exposes the ADC values as strings for historic reasons.
                # This should be changed in a v2 API.
                pin_info["adcs"] = dict((name, f"{value:.4}") for name, value in adcs.items())

            response["result"] = pin_info

            # This view is polled by the web-interface.
            # To keep the log nice and clean we will only log this to debug.
            logger.debug(
                "get_pin_info: requested pin info for for node %s",
                node_name,
            )

        except TimeoutError:
            response = {
                "code": 1,
                "error_message": "timeout",
                "result": None,
            }

        except ValueError:
            response = {
                "code": 1,
                "error_message": "unknown node",
                "result": None,
            }

        except IndexError:
            response = {
                "code": 1,
                "error_message": "unknown pin",
                "result": None,
            }

        except Exception as e:
            logger.exception("get_pin_info failed")
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return response

    async def get_pin_info(self, request):
        node_name = request.match_info["node"]

        response = MaybeJsonEventStream(request)

        while self._running:
            info = await self._get_pin_info_once(node_name)
            stop = await response.push(info)
            if stop:
                break

            await asyncio.sleep(EVENT_DELAY_PINS)

        return response.response

    async def set_pin(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            pin_name = request.match_info["pin"]

            content_type = request.headers.get("Content-Type")
            post = await (request.json() if content_type == "application/json" else request.post())
            value = post["value"]

            node = self.network.get_node_by_name(node_name)

            if value == "toggle":
                await node.od.outputs.toggle(pin_name)

            elif int(value):
                await node.od.outputs.set_high(pin_name)

            else:
                await node.od.outputs.set_low(pin_name)

            logger.info(
                "set_pin: set pin %s on node %s to %s",
                pin_name,
                node_name,
                value,
            )

        except ValueError as e:
            logger.info(
                "set_pin: user wanted to set pin on unknown node '%s'.",
                node_name,
            )
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        except KeyError:
            logger.info(
                "set_pin: user wanted to set unknown pin '%s' on node '%s'.",
                pin_name,
                node_name,
            )
            response = {
                "code": 1,
                "error_message": f"unknown pin '{pin_name}' for node '{node_name}'",
                "result": None,
            }

        except Exception as e:
            logger.exception("set_pin failed")
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))

    async def get_sdo_raw(self, request):
        node_name = request.match_info["node"]
        index = request.match_info["index"]
        sub_index = request.match_info["sub_index"]

        try:
            # Allow users to specify the sdo indices as hex (with 0x prefix)
            # or as decimal.
            index = int(index, base=0)
            sub_index = int(sub_index, base=0)
        except ValueError as e:
            raise HTTPBadRequest(body="Malformed index/sub index") from e

        if index < 0x1000 or index >= 0x3000:
            raise HTTPForbidden(body="Raw SDO access for non-standard, non-vendor indices is not allowed")

        if sub_index < 0 or sub_index > 255:
            raise HTTPBadRequest(body="SDO sub index outside of valid range")

        try:
            node = self.network.get_node_by_name(node_name)
        except ValueError as e:
            raise HTTPNotFound(body="Node ID not found") from e

        # This can throw a whole suite of exceptions, that should likely
        # be handled and mapped to HTTP status codes.
        result = await node.sdo_read(index, sub_index)

        # Respond with the raw byte stream
        return Response(body=result)

    async def send_sdo_raw(self, request):
        node_name = request.match_info["node"]
        index = request.match_info["index"]
        sub_index = request.match_info["sub_index"]

        try:
            # Allow users to specify the sdo indices as hex (with 0x prefix)
            # or as decimal.
            index = int(index, base=0)
            sub_index = int(sub_index, base=0)
        except ValueError as e:
            raise HTTPBadRequest(body="Malformed index/sub index") from e

        if index < 0x1000 or index >= 0x3000:
            raise HTTPForbidden(body="Raw SDO access for non-standard, non-vendor indices is not allowed")

        if sub_index < 0 or sub_index > 255:
            raise HTTPBadRequest(body="SDO sub index outside of valid range")

        try:
            node = self.network.get_node_by_name(node_name)
        except ValueError as e:
            raise HTTPNotFound(body="Node ID not found") from e

        # Get the body as raw bytes
        data = await request.read()

        # This can throw a whole suite of exceptions, that should likely
        # be handled and mapped to HTTP status codes.
        await node.sdo_write(index, sub_index, data)

        # No Content
        return Response(status=204)

    async def toggle_locator(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            # The locator state is updated by periodic pings
            # The current state may thus be stale by up to a second or so.
            new_state = not node.locator_state
            await node.set_locator_state(new_state)
            logger.info(
                "toggle_locator: set locator on node %s to %s",
                node_name,
                new_state,
            )

        except ValueError as e:
            logger.info(
                "toggle_locator: user wanted to toggle the locator on unknown node '%s'.",
                node_name,
            )
            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        except Exception as e:
            logger.exception("toggle locator failed")

            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))

    async def firmware_update(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            file_name = node.product.FIRMWARE_FILE
            file_name = os.path.join(FIRMWARE_DIR, file_name)

            await self.flash_jobs.put(
                (
                    False,
                    node,
                    file_name,
                )
            )

        except Exception as e:
            logger.exception("Firmware update failed")

            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))
