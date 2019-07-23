#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name = "ethmux",
    version = "0.1.0",
    description = "CANOpen open control domain",
    packages = ["ethmux"],
    install_requires = ["canopen"],
    entry_points = {
        'console_scripts': [
            'remotelab_canopen = ethmux.__main__:main'
        ]

    },
)
