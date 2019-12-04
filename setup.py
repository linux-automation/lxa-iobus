#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name='remotelab_io',
    version='0.1.0',
    description='CANOpen open control domain',
    packages=find_packages(),
    install_requires=[
        'canopen',
        'aiohttp-json-rpc==0.12.1',
        'ipython<7',
    ],
    entry_points={
        'console_scripts': [
            'remotelab_canopen = remotelab_io.domain:main',
            'remotelab_canopen_cmd = remotelab_io.client:main'
        ]
    },
    scripts=[
        'bin/remotelab-io-server',
    ],
)
