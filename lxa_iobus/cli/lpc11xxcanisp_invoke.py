#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import asyncio
import logging

from lxa_iobus.network import LxaNetwork

from . import async_main


@async_main
async def main():
    parser = argparse.ArgumentParser("lxa-iobus-lpc11xxcanisp-invoke")
    parser.add_argument("--interface", "-i", type=str, help="CAN interface to use", default="can0")
    parser.add_argument(
        "-v",
        help="Be verbose",
        action="store_true",
    )
    args = parser.parse_args()

    if args.v:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARN)

    network = LxaNetwork(loop=asyncio.get_running_loop(), interface=args.interface)
    asyncio.create_task(network.run(with_lss=False))
    await network.await_running()

    node = await network.setup_single_node()
    await node.invoke_isp()

    network.shutdown()


if __name__ == "__main__":
    main()
