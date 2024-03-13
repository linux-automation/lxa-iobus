#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import asyncio
import logging

from lxa_iobus.lpc11xxcanisp.can_isp import CanIsp
from lxa_iobus.network import LxaNetwork

from . import async_main


@async_main
async def main():
    parser = argparse.ArgumentParser("lxa-iobus-lpc11xxcanisp-program")
    parser.add_argument(
        "function",
        help="Function to perform",
        choices=["readflash", "writeflash", "readconfig", "writeconfig", "info", "reset"],
    )
    parser.add_argument("--interface", "-i", type=str, help="CAN interface to use", default="can0")
    parser.add_argument(
        "--file",
        "-f",
        help="File to use as flash or config",
    )
    parser.add_argument(
        "-v",
        help="Be verbose",
        action="store_true",
    )
    parser.add_argument(
        "-s",
        help="Skip info section at startup",
        action="store_true",
    )
    args = parser.parse_args()

    if args.function in ["readflash", "writeflash", "readconfig", "writeconfig"] and args.file is None:
        parser.error("file is required for this function")
        exit(1)

    if args.v:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARN)

    network = LxaNetwork(loop=asyncio.get_running_loop(), interface=args.interface)
    asyncio.create_task(network.run(with_lss=False))
    isp = CanIsp(network.isp_node)

    await network.await_running()

    if not args.s:
        device_type = await isp.read_device_type()
        part_id = await isp.read_part_id()
        serial_number = await isp.read_serial_number()
        bootloader_version = await isp.read_bootloader_version()

        print("device_type:", device_type.decode())
        print("partID: 0x{:08X} {}".format(*part_id))
        print("serial_number: {:08X} {:08X} {:08X} {:08X}".format(*serial_number))
        print("bootloader_version: {:08X}".format(bootloader_version))
        print()

    if args.function == "readflash":
        await isp.read(args.file, "flash")
    elif args.function == "readconfig":
        await isp.read(args.file, "config")
    elif args.function == "writeflash":
        await isp.write(args.file, "flash")
    elif args.function == "writeconfig":
        await isp.write(args.file, "config")
    elif args.function == "reset":
        await isp.reset()

    network.shutdown()


if __name__ == "__main__":
    main()
