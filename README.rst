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

This packages provides a daemon which connects iobus-devices from Linux Automation
with test-automation tools like `labgrid <https://github.com/labgrid-project/labgrid>`__.
iobus is a CANopen-inspired communications protocol on top of CAN.

This packages provides the following features:

* lxa-iobus-server: This is the central daemon that manages the nodes on the bus.
  * It provides a (human-readable) web interface and a REST API for remote control of the nodes.
  * It is able to update the firmware running on the devices on the bus.
* The most recent firmware for all available iobus devices.
* And in case something went really wrong: Tooling to manually flash new firmware onto an iobus node.

System requirements
"""""""""""""""""""

The lxa-iobus-server has been developed to work on a modern Linux-based distribution.
Additional to this the following requirements need to be meet to run the lxa-iobus-server:

* Python 3.7 or later
* on Debian: python3-virtualenv
* SocketCAN
* Compatible CAN device
* git
* optional: ``systemd`` to setup a service for lxa-iobus-server
* optional: ``systemd`` >= 239 to bring up your CAN-device on boot
* optional: ``make`` for easy setup of the lxa-iobus-server

Quickstart
""""""""""

If you have ``make`` installed on your system you can follow this section to
start the server.
Make sure you have at least one CAN device on your bus an that your bus is
terminated.
If you connect a node to a not managed bus (as the server is not jet started)
the network LED will blink until the node has been initialized.

With this instructions you will first set up your SocketCAN device to work with
the lxa-iobus-server.
Afterwards you will clone this repository.
The last step is to call ``make server`` which will create a ``python venv`` inside
the directory and start a server that binds to ``http://localhost:8080/``.

::

   $ sudo ip l set can0 down && sudo ip link set can0 type can bitrate 100000 && sudo ip l set can0 up
   $ git clone https://github.com/linux-automation/lxa-iobus.git
   Cloning into 'lxa-iobus'...
   remote: Enumerating objects: 476, done.
   remote: Counting objects: 100% (476/476), done.
   remote: Compressing objects: 100% (227/227), done.
   remote: Total 476 (delta 257), reused 448 (delta 229), pack-reused 0
   Receiving objects: 100% (476/476), 1.04 MiB | 2.48 MiB/s, done.
   Resolving deltas: 100% (257/257), done.
   $ cd lxa-iobus/
   $ make server
   rm -rf env && \
   python3.7 -m venv env && \
   . env/bin/activate && \
   pip install -e .[full] && \
   date > env/.created
   Obtaining file:///home/chris/tmp/lxa-iobus
   [...]
   Successfully installed aenum-2.2.4 aiohttp-3.5.4 aiohttp-json-rpc-0.12.1 async-timeout-3.0.1 attrs-20.2.0 backcall-0.2.0 canopen-1.1.0 chardet-3.0.4 decorator-4.4.2 idna-2.10 ipython-6.5.0 ipython-genutils-0.2.0 jedi-0.17.2 lxa-iobus multidict-4.7.6 parso-0.7.1 pexpect-4.8.0 pickleshare-0.7.5 prompt-toolkit-1.0.18 ptyprocess-0.6.0 pygments-2.7.2 python-can-3.3.4 simplegeneric-0.8.1 six-1.15.0 traitlets-5.0.5 typing-extensions-3.7.4.3 wcwidth-0.2.5 wrapt-1.12.1 yarl-1.6.2
   . env/bin/activate && \
   lxa-iobus-server can0
   starting server on http://localhost:8080/

After this step the lxa-iobus-server will start to scan the bus for connected
iobus-compatible nodes. Depending on the number of nodes this can take up to
30 seconds.
Observe the status of the network LED on your iobus compatible node.
Once the node has been initialized by the server the LED stops blinking.

Now navigate your web browser to ``http://localhost:8080/``.
Your node should be listed under ``nodes``.
Your lxa-iobus-server is now ready for use.

If you want the server to be started at system startup take a look into the
installation section.

Installation
""""""""""""

The permanent installation of the lxa-iobus-server consists of two parts:

1) Bring up the SocketCAN-device at system start.
2) Setup the lxa-iobus-server and make it start at system start.

For both steps clone this repository:

::

   $ git clone https://github.com/linux-automation/lxa-iobus.git
   Cloning into 'lxa-iobus'...
   remote: Enumerating objects: 476, done.
   remote: Counting objects: 100% (476/476), done.
   remote: Compressing objects: 100% (227/227), done.
   remote: Total 476 (delta 257), reused 448 (delta 229), pack-reused 0
   Receiving objects: 100% (476/476), 1.04 MiB | 2.48 MiB/s, done.
   Resolving deltas: 100% (257/257), done.
   $ cd lxa-iobus/

Afterwards you can continue with the following chapters.

Setup SocketCAN device with systemd-networkd
''''''''''''''''''''''''''''''''''''''''''''

In this step ``systemd-networkd`` is used to set up the SocketCAN device at
system startup.
If you are not using ``systemd-networkd`` skip to the next chapter.

This installation method requires you to have systemd with a version of at
least 239 on your system and a SocketCAN device must be available.

You can check the status using:

::

   $ ip link
   1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
       link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
   [...]
   185: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 qdisc pfifo_fast state UP mode DEFAULT group default qlen 10
       link/can

In this example the SocketCAN device is ``can0``.

To setup the interface using ``systemd-networkd`` copy the rules
``80_can0-iobus.link`` and ``80_can0-iobus.network``
from ``./contrib/systemd/`` to ``/etc/systemd/network/``.
Make sure to update the ``[Match]`` sections in both files and the ``[Link]``
section in the ``.link`` file to match the name of your SocketCAN device.

This files will do the following:

* Use the SocketCAN device ``can0``
* Rename it to ``can0-iobus``. Especially on
  systems with multiple interfaces this makes it a lot easier to identify
  the interface used for the lxa-iobus-server.
* Set the bitrate to 100.000 bit/s.
* Bring the interface up.

To apply this changes restart ``systemd-networkd`` using
``systemctl restart systemd-networkd``.
Afterwards make sure your device has been renamed and is up using ``ip link``.

Setup SocketCAN device manually
'''''''''''''''''''''''''''''''

If you are using another way of setting up your network you may skip this
step and make sure you meet the following requirements instead:

* Set the bitrate to 100.000 bit/s
* Bring the interface up
* Optionally: Rename the interface with the suffix ``-iobus``. Especially on
  systems with multiple interfaces this makes it a lot easier to identify
  the interface used for the lxa-iobus-server.

Setup lxa-iobus-server
''''''''''''''''''''''

In this chapter ``systemd`` will be used to start the lxa-iobus-server.

To setup a systemd-service use the example ``.service`` -unit provided
in ``./contrib/systemd/lxa-iobus.service``.
To install the service copy this file to ``/etc/systemd/system/``.

Make sure to set the correct SocketCAN interface in the service file.

Afterwards the service can be started using ``systemctl start lxa-iobus.service``.
If no errors are shown in ``systemctl status lxa-iobus.service`` the web interface
should be available on ``http://localhost:8080``.


REST API
""""""""

The REST API can be used to build your own lab automation on top of the lxa-iobus.
Take a look at the following examples for all the available endpoints.

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

Contributing
""""""""""""

Thank you for considering a contribution to this project!
Changes should be submitted via a
`Github pull request <https://github.com/linux-automation/lxa-iobus/pulls>`_.

This project uses the `Developer's Certificate of Origin 1.1
<https://developercertificate.org/>`_ with the same `process
<https://www.kernel.org/doc/html/latest/process/submitting-patches.html#sign-your-work-the-developer-s-certificate-of-origin>`_
as used for the Linux kernel:

  Developer's Certificate of Origin 1.1

  By making a contribution to this project, I certify that:

  (a) The contribution was created in whole or in part by me and I
      have the right to submit it under the open source license
      indicated in the file; or

  (b) The contribution is based upon previous work that, to the best
      of my knowledge, is covered under an appropriate open source
      license and I have the right under that license to submit that
      work with modifications, whether created in whole or in part
      by me, under the same open source license (unless I am
      permitted to submit under a different license), as indicated
      in the file; or

  (c) The contribution was provided directly to me by some other
      person who certified (a), (b) or (c) and I have not modified
      it.

  (d) I understand and agree that this project and the contribution
      are public and that a record of the contribution (including all
      personal information I submit with it, including my sign-off) is
      maintained indefinitely and may be redistributed consistent with
      this project or the open source license(s) involved.

Then you just add a line (using ``git commit -s``) saying:

  Signed-off-by: Random J Developer <random@developer.example.org>

using your real name (sorry, no pseudonyms or anonymous contributions).

Troubleshooting
"""""""""""""""

You may see the ``lxa-iobus-server`` fail with messages like:

``Server dies with can.CanError: Failed to transmit: [Errno 105] No buffer space available``

Have a look at `TROUBLESHOOTING.rst <TROUBLESHOOTING.rst>`_ for solutions to common
CAN related issues.
