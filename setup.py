#!/usr/bin/env python3

import fastentrypoints

from setuptools import setup

setup(
    name="lpc11xxcanisp",
    version="0.1.0",
    description="Tool for programming LPC11xx-CPUs via CAN",
    packages=['lpc11xxcanisp'],
    entry_points={
        'console_scripts': [
            'lpc11xxcanisp_invoke = lpc11xxcanisp.invoke_isp:main',
            'lpc11xxcanisp_program = lpc11xxcanisp.can_isp:main',
        ],
    },
)
