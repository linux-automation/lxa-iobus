
Welcome to Linux Automation GmbH lxa-iobus-server's documentation!
==================================================================

This packages provides a daemon which interfaces IOBus-devices from Linux Automation GmbH
with test-automation tools like `labgrid <https://github.com/labgrid-project/labgrid>`__.
IOBus is a CANopen-inspired communications protocol on top of CAN.

This packages provides the following features:

* lxa-iobus-server: This is the central daemon that manages the nodes on the bus.
  It provides a (human-readable) web interface and a REST API for remote control of the nodes.
  It also updates the firmware running on the devices on the bus.
* The most recent firmware for all available IOBus devices.

If you want to get in touch with us feel free to do so:

* IRC channel ``#lxa`` on libera.chat
  (bridged to the Matrix channel
  `#lxa:matrix.org <https://app.element.io/#/room/#lxa:matrix.org>`__)
* If our :ref:`Troubleshooting` guide doesn't solve your problem or if you found
  a bug feel free to open an
  `issue on github <https://github.com/linux-automation/lxa-iobus/issues>`__.
* You can send us an email to info@linux-automation.com.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   architecture
   can_canopen
   upgrade
   web
   rest
   troubleshooting
   contributing
   glossary


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
