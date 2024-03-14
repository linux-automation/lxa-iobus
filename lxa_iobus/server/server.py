import asyncio
import json
import logging
import os
from concurrent.futures import CancelledError
from datetime import datetime
from functools import partial
from pprint import pformat

from aiohttp.web import FileResponse, HTTPFound, Response, json_response
from aiohttp_json_rpc import JsonRpc

from lxa_iobus.lpc11xxcanisp.can_isp import CanIsp
from lxa_iobus.lpc11xxcanisp.firmware.versions import (
    FIRMWARE_DIR,
    FIRMWARE_VERSIONS,
)

STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")
logger = logging.getLogger("LXAIOBusServer")


class LXAIOBusServer:
    def __init__(self, app, loop, network, firmware_directory, allow_custom_firmware):
        self.app = app
        self.loop = loop
        self.network = network
        self.firmware_directory = firmware_directory
        self.allow_custom_firmware = allow_custom_firmware

        self.state = {"low_level_nodes": {}, "low_level_nodes_state": {}, "nodes": {}}

        self.started = datetime.now()

        # setup aiohttp
        self.rpc = JsonRpc(loop=self.loop, max_workers=6)
        self.worker_pool = self.rpc.worker_pool
        app["rpc"] = self.rpc

        self.rpc.add_topics(
            ("state",),
            ("firmware",),
            ("isp_console",),
        )

        app.router.add_route("*", "/static/{path_info:.*}", self.static)

        app.router.add_route("*", "/", self.index)
        self.app.router.add_route("*", "/rpc/", self.rpc)

        # rest api
        app.router.add_route("GET", "/server-info/", self.get_server_info)
        app.router.add_route("GET", "/nodes/{node}/pins/{pin}/", self.get_pin)
        app.router.add_route("POST", "/nodes/{node}/pins/{pin}/", self.set_pin)
        app.router.add_route("GET", "/nodes/{node}/pins/", self.get_pins)

        app.router.add_route("POST", "/nodes/{node}/toggle-locator/", self.toggle_locator)

        app.router.add_route("GET", "/nodes/{node}/pin-info/", self.get_pin_info)

        app.router.add_route("GET", "/nodes/", self.get_nodes)
        app.router.add_route("GET", "/nodes/{node}/", self.get_node)

        # firmware urls
        app.router.add_route(
            "POST",
            "/nodes/{node}/flash-firmware/{source}/{file_name}",
            self.firmware_flash,
        )

        app.router.add_route(
            "POST",
            "/nodes/{node}/update/",
            self.firmware_update,
        )

        app.router.add_route(
            "GET",
            "/firmware/",
            self.get_firmware_files,
        )

        app.router.add_route(
            "POST",
            "/firmware/upload/",
            self.firmware_upload,
        )

        app.router.add_route(
            "POST",
            "/firmware/delete/{file_name}",
            self.firmware_delete,
        )

        # flush initial state
        self.loop.create_task(self.flush_state())

        # setup can isp
        self.can_isp = CanIsp(
            server=self,
            network=network,
        )

        # flash worker
        self._running = True
        self.flash_jobs = asyncio.Queue()
        self.loop.create_task(self.flash_worker())

    def shutdown(self):
        self._running = False

    async def flash_worker(self):
        while self._running:
            try:
                shutdown, node, file_name = await self.flash_jobs.get()

                if shutdown:
                    return

                self.can_isp.console_log(
                    "Flashing {} ({})".format(
                        node.name,
                        node.address,
                    )
                )

                self.can_isp.console_log("Invoking isp")
                await node.invoke_isp()

                self.can_isp.console_log("Start flashing")
                callback = partial(self.can_isp.write_flash, file_name)
                await self.loop.run_in_executor(None, callback)

                self.can_isp.console_log("Reseting node")
                await self.loop.run_in_executor(None, self.can_isp.reset)

                self.can_isp.console_log("Flashing done")

            except CancelledError:
                return

            except Exception:
                logger.exception("flashing failed")

    # views ###################################################################
    async def get_server_info(self, request):
        response = {
            "hostname": os.uname()[1],
            "started": str(self.started),
            "can_interface": self.network.interface,
            "can_interface_is_up": self.network.interface_is_up(),
            "lss_state": self.network.lss_state.value,
            "can_tx_error": self.network.tx_error,
        }
        headers = {"Access-Control-Allow-Origin": "*"}

        return json_response(response, headers=headers)

    async def index(self, request):
        return FileResponse(os.path.join(STATIC_ROOT, "index.html"))

    async def static(self, request):
        path = os.path.join(
            STATIC_ROOT,
            os.path.relpath(request.path, "/static/"),
        )

        if not os.path.exists(path):
            return Response(text="404: not found", status=404)

        return FileResponse(path)

    async def get_nodes(self, request):
        nodes = []

        for node_id, node in self.network.nodes.copy().items():
            if node_id == 125:  # ISP
                continue

            nodes.append(node.name)

        response = {
            "code": 0,
            "error_message": "",
            "result": nodes,
        }
        headers = {"Access-Control-Allow-Origin": "*"}

        return json_response(response, headers=headers)

    async def get_node(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": {},
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)
            response["result"] = {
                "locator": node.locator_state,
                "driver": node.driver.__class__.__name__,
                "info": await node.get_info(),
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

    async def get_pins(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": [],
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            for name, _ in node.driver.pins.items():
                response["result"].append(name)

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

            response["result"] = await node.driver.pins[pin_name].read()
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

    async def get_pin_info(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            node = self.network.get_node_by_name(node_name)

            pin_info = {
                "locator": node.locator_state,
                "inputs": {},
                "outputs": {},
                "adcs": {},
            }

            for pin_name, pin in node.driver.pins.items():
                value = await pin.read()

                if pin.pin_type == "input":
                    pin_info["inputs"][pin_name] = value

                elif pin.pin_type == "output":
                    pin_info["outputs"][pin_name] = value

                elif pin.pin_type == "adc":
                    pin_info["adcs"][pin_name] = "{:.3f}".format(value)

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

        return Response(text=json.dumps(response))

    async def set_pin(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        try:
            node_name = request.match_info["node"]
            pin_name = request.match_info["pin"]
            post = await request.post()
            value = post["value"]

            node = self.network.get_node_by_name(node_name)
            pin = node.driver.pins[pin_name]

            if value == "toggle":
                value = await pin.read()
                value = 1 - value

            else:
                value = int(value)

            response["result"] = await pin.write(value)
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

    # firmware views ##########################################################
    async def get_firmware_files(self, request):
        upstream_files = []
        local_files = []

        for _, (_, path) in FIRMWARE_VERSIONS.items():
            upstream_files.append(os.path.basename(path))

        if self.allow_custom_firmware:
            for i in os.listdir(self.firmware_directory):
                if i.startswith("."):
                    continue
                local_files.append(i)

        response = {
            "upstream_files": upstream_files,
            "local_files": local_files,
            "allow_custom_firmware": self.allow_custom_firmware,
        }

        return Response(text=json.dumps(response))

    async def firmware_upload(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        if not self.allow_custom_firmware:
            logger.exception("Firmware upload not possible if allow-custom-firmware is not set.")
            response = {
                "code": 1,
                "error_message": "Firmware upload not possible if allow-custom-firmware is not set.",
                "result": None,
            }
            return Response(text=json.dumps(response))

        try:
            data = await request.post()

            filename = data["file"].filename
            file_content = data["file"].file.read()

            abs_filename = os.path.join(self.firmware_directory, filename)

            with open(abs_filename, "wb+") as f:
                f.write(file_content)

            return HTTPFound("/#firmware-files")

        except Exception as e:
            logger.exception("firmware upload failed")

            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))

    async def firmware_delete(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        if not self.allow_custom_firmware:
            logger.exception("Firmware delete not possible if allow-custom-firmware is not set.")
            response = {
                "code": 1,
                "error_message": "Firmware delete not possible if allow-custom-firmware is not set.",
                "result": None,
            }
            return Response(text=json.dumps(response))

        try:
            filename = os.path.join(self.firmware_directory, request.match_info["file_name"])

            os.remove(filename)

        except Exception as e:
            logger.exception("firmware delete failed")

            response = {
                "code": 1,
                "error_message": str(e),
                "result": None,
            }

        return Response(text=json.dumps(response))

    async def firmware_flash(self, request):
        response = {
            "code": 0,
            "error_message": "",
            "result": None,
        }

        if not self.allow_custom_firmware:
            logger.exception("Custom firmware flashing not possible if allow-custom-firmware is not set.")
            response = {
                "code": 1,
                "error_message": "Custom firmware flashing not possible if allow-custom-firmware is not set.",
                "result": None,
            }
            return Response(text=json.dumps(response))

        try:
            node_name = request.match_info["node"]
            source = request.match_info["source"]
            file_name = request.match_info["file_name"]

            node = self.network.get_node_by_name(node_name)

            # find firmware file
            if source == "local":
                file_name = os.path.join(self.firmware_directory, file_name)

            elif source == "upstream":
                file_name = os.path.join(FIRMWARE_DIR, file_name)

            else:
                raise ValueError("unknown mode")

            await self.flash_jobs.put(
                (
                    False,
                    node,
                    file_name,
                )
            )

        except Exception as e:
            logger.exception("Firmware flashing failed")

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

            file_name = FIRMWARE_VERSIONS[node.driver.__class__][1]

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

    # state (rpc) #############################################################
    async def flush_state(self):
        state = []
        nodes = self.network.nodes.copy()
        node_ids = sorted(nodes.keys())

        for node_id in node_ids:
            if node_id == 125:  # ISP
                continue

            node = nodes[node_id]
            node_driver = node.driver

            # get node info
            try:
                node_info = await node.get_info()

            except Exception as e:
                logger.warning("Exception during get_info() for node {}: {}".format(node, repr(e)))
                node_info = {}

            state.append(
                [
                    node.name,
                    {
                        "locator": node.locator_state,
                        "driver": node_driver.__class__.__name__,
                        "info": node_info,
                    },
                ]
            )

        await self.rpc.notify("state", state)

    def flush_state_sync(self, wait=True):
        self.rpc.worker_pool.run_sync(partial(self.rpc.notify, "state", pformat(self.state)), wait=wait)

    async def flush_state_periodicly(self):
        while self._running:
            await self.flush_state()
            await asyncio.sleep(1)
