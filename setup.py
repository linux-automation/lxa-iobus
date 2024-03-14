#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

import lxa_iobus

EXTRAS_REQUIRE = {
    "server": [
        "aiohttp~=3.8",
        "aiohttp-json-rpc==0.13.3",
    ],
    "shell": [
        "ipython<7",
    ],
}

EXTRAS_REQUIRE["full"] = sum([v for k, v in EXTRAS_REQUIRE.items()], [])

setup(
    include_package_data=True,
    name="lxa-iobus",
    version=lxa_iobus.VERSION_STRING,
    author="Linux Automation GmbH",
    url="https://github.com/linux-automation/lxa-iobus",
    author_email="python@pengutronix.de",
    license="Apache License 2.0",
    packages=find_packages(),
    install_requires=[
        "python-can",
        "janus",
    ],
    extras_require=EXTRAS_REQUIRE,
    scripts=[
        "bin/lxa-iobus-server",
        "bin/lxa-iobus-can-setup",
        "bin/lxa-iobus-lpc11xxcanisp-invoke",
        "bin/lxa-iobus-lpc11xxcanisp-program",
    ],
)
