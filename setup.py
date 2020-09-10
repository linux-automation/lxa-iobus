#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

import lxa_iobus

setup(
    include_package_data=True,
    name='lxa-iobus',
    version=lxa_iobus.VERSION_STRING,
    author='Linux Automation GmbH',
    url='https://github.com/linux-automation/lxa-iobus',
    author_email='python@pengutronix.de',
    license='Apache License 2.0',
    packages=find_packages(),
    install_requires=[],
    extras_require={},
    scripts=[],
    entry_points={},
)
