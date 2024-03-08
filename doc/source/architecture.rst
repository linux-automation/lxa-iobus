System Architecture
-------------------

The ``lxa-iobus-server`` is a gateway between a lab automation
software (e.g. labrid) and
the actual LXA IOBus devices connected to the bus.

This chapter gives introduces the architecture used to
in the LXA IOBus system.

Network Layers
..............

The following figure shows the structure of the LXA IOBus system:

.. code-block:: text

        LXA IOBus Server
   ╭───────────┬───────────╮
   │ REST-     │ HTML/Web- │
   │ Interface │ Interface │
   │           │           │
   ├───────────┴───────────┤             IOBus Node 1                IOBus Node 2
   │                       │      ╭───────────────────────╮     ╭───────────────────────╮
   │ Transport and Control │      │  Node-specific        │     │  Node-specific        │
   │                       │      │  electrical Interface │     │  electrical Interface │
   ╰───────────┬───────────╯      │                       │     │                       │
   ╭───────────┴───────────╮      ├───────────────────────┤     ├───────────────────────┤
   │                       │      │                       │     │                       │
   │  Linux SocketCAN      │      │ Transport and Control │     │ Transport and Control │
   │                       │      │                       │     │                       │
   ╰───────────┬───────────╯      ╰───────────┬───────────╯     ╰───────────┬───────────╯
               │                              │                             │
               │                              │                             │
               ╰──────────────────────────────┴─────────────────────────────╯
                                 CAN-Bus with Power supply


* **REST-Interface**:
  Using this communication interface external software is able to interact with
  the nodes connected to the IOBus.
* **Web-Interface**:
  This interface provides the information available on the REST-Interface in a
  human-readable form.
* **Transport and Control**:
  This part implements the CANopen-inspired protocol and keeps track of the
  current state of the bus and connected devices.
* **Linux SocketCAN**:
  The LXA IOBus Server uses `SocketCAN <https://en.wikipedia.org/wiki/SocketCAN>`_
  to interact with the CAN-bus.
* **Node-specific electrical interface**:
  Every LXA IOBus node has an application-specific specialised electrical interface
  that is designed to perform different automation tasks.
* **CAN-Bus**:
  This is the actual electrical interface that connects server and nodes.
  This is the same CAN bus interface you may know from many automotive applications.
