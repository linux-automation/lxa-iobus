Linux Automation GmbH lxa-iobus
===============================

.. image:: https://img.shields.io/pypi/l/lxa-iobus.svg
    :alt: pypi.org
    :target: https://pypi.org/project/lxa-iobus
.. image:: https://img.shields.io/pypi/pyversions/lxa-iobus.svg
    :alt: pypi.org
    :target: https://pypi.org/project/lxa-iobus
.. image:: https://img.shields.io/pypi/v/lxa-iobus.svg
    :alt: pypi.org
    :target: https://pypi.org/project/lxa-iobus


lxa-iobus-server
----------------

REST API
""""""""

Examples
''''''''

::

    # get nodes
    >>> curl http://localhost:8080/nodes/
    <<< {"code": 0, "error_message": "", "result": ["IOMux-5a6ecbea", "00000000.0c0ce935.534d0000.5c12ca96"]}

    # get pins
    >>> curl http://localhost:8080/nodes/IOMux-5a6ecbea/pins/
    <<< {"code": 0, "error_message": "", "result": ["led"]}

    # get pin
    >>> curl http://localhost:8080/nodes/IOMux-5a6ecbea/pins/led/
    <<< {"code": 0, "error_message": "", "result": 0}

    # set pin
    >>> curl -d "value=0" -X POST http://localhost:8080/nodes/IOMux-5a6ecbea/pins/led/
    <<< {"code": 0, "error_message": "", "result": null}


lpc11xxcanisp
-------------

This is a Prototyp implementation.

This python module provides accsess to the LPC11C24 CAN ISP.


Setup
"""""

::

    python3 -m venv venv
    source venv/bin/activate
    pip install canopen


Read firmware
'''''''''''''

::

    $ python can_isp.py read filename


Write firmware
''''''''''''''

::

    $ python can_isp.py write filename

Execute binary from RAM
'''''''''''''''''''''''

::

    $ python can_isp.py exec filename

In loader you find two binary:
 * reset.bin to reset the MCU after flashing the firmware
 * soft_reset to jump into the application in flash
   This is needed in case you jumpered the Boot0/Bootsel pin

::

    $ python can_isp.py exec loader/reset.bin
    $ python can_isp.py exec loader/soft_reset.bin


Reboot into bootloader
''''''''''''''''''''''

If the user code is already running and it uses our bootloader endpoint, you
can reboot it into bootloader mode with.


::

    python invoke_isp.py

Please note that the will switch every node on the CAN bus into bootloader
mode. So make sure you have only one connected.
