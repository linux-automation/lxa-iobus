#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import errno
import logging
import os
import signal
import sys
import threading
import traceback
from argparse import ArgumentParser

from aiohttp.web import Application, run_app

from lxa_iobus.network import LxaNetwork
from lxa_iobus.server.server import LXAIOBusServer


def trace_handler(num, frame):
    print("\nDumping all stacks:\n")

    for th in threading.enumerate():
        print(th)
        traceback.print_stack(sys._current_frames()[th.ident])
        print()

    for task in asyncio.all_tasks():
        if not task.done():
            task.print_stack()
            print()


signal.signal(signal.SIGQUIT, trace_handler)


def exit_handler(num, frame):
    print("\nExiting...\n")

    os.kill(os.getpid(), signal.SIGKILL)


signal.signal(signal.SIGINT, exit_handler)


def main():
    # parse command line arguments
    parser = ArgumentParser()

    parser.add_argument("interface")
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to serve on. Defaults to 8080",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind to. Defaults to 'localhost'",
    )
    parser.add_argument(
        "--lss-address-cache-file",
        type=str,
        default="",
        help="LSS addresses cache as json. Reduces startup time for known nodes.",
    )

    parser.add_argument(
        "-l",
        "--log-level",
        choices=["DEBUG", "INFO", "WARN", "ERROR", "FATAL"],
        default="WARN",
    )

    args = parser.parse_args()

    # setup logging
    log_level = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARN,
        "ERROR": logging.ERROR,
        "FATAL": logging.FATAL,
    }[args.log_level]

    logging.basicConfig(level=log_level)

    # setup server
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = Application()

    # setup lxa network
    network = LxaNetwork(
        loop=loop,
        interface=args.interface,
        lss_address_cache_file=args.lss_address_cache_file,
    )

    app["network"] = network

    async def shutdown_network(app):
        app["network"].shutdown()

    app.on_shutdown.append(shutdown_network)
    loop.create_task(network.run())

    # start server
    try:
        server = LXAIOBusServer(
            app,
            loop,
            network,
        )

    except OSError as e:
        if e.errno == errno.ENODEV:  # can interface not available
            exit("interface {} not available".format(args.interface))

    print("starting server on http://{}:{}/".format(args.host, args.port))

    try:
        kwargs = {}
        if args.log_level != "DEBUG":
            kwargs["access_log"] = None
        run_app(
            app=app,
            host=args.host,
            port=args.port,
            handle_signals=False,
            print=lambda *args, **kwargs: None,
            loop=loop,
            **kwargs,
        )

    except KeyboardInterrupt:
        server.shutdown()
        os.kill(os.getpid(), signal.SIGTERM)

    except OSError:
        server.shutdown()
        exit("ERROR: can not bind to port {}".format(args.port))

    print("\rshutting down server")

    server.shutdown()
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    main()
