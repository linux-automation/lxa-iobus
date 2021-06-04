Troubleshooting
===============

This section lists common problems and possible solutions.
If you experience other problems or would like to add a solution for a problem
feel free to open an issue in our
`Github project <https://github.com/linux-automation/lxa-iobus/issues>`__
or send us an email to info@linux-automation.com.

For assistance you can also join our IRC channel ``#lxa`` on libera.chat
(bridged to the Matrix channel
`#lxa:matrix.org <https://app.element.io/#/room/#lxa:matrix.org>`__).

.. _troubleshoot-sjw:

Bitrate-Intolerant CAN Bus
--------------------------

**Problem:** The host-side CAN-interface sends an error-frame for
every CAN packet sent by the Ethernet-Mux.

The CAN-Bus protocol is designed to allow bitrate offsets of a few percent
between bus nodes. This is especially relevant when a bus contains nodes without
precise crystal-based clock sources.
Synchronization is performed on the receiving side of a CAN-frame by
monitoring the actual and expected timing of bit transitions seen on the bus,
and adjusting the bit-sampling of subsequent bits accordingly.

The generation of CAN-timings is based on a base clock, that is sub-divided
using counters, to determine the sample points for reception and the
signal transition points for sending. These counter timings make use of units of time called
time quanta ``tq``, on Linux these time quanta are given in nanoseconds.

One parameter that is specified in terms of time quanta is the synchronization jump
width (``sjw``), a parameter determining the maximum amount of bitrate synchronization
performed during reception of a CAN-frame.
Currently SocketCAN initializes every device with a synchronization jump width (``sjw``)
of 1 time quantum.

As the length of a time quantum ``tq`` varies widely between different CAN-controllers
this results in maximum amount of bitrate-synchronization performed by default also
varying widely between CAN-controllers. On some CAN-controllers the amount of synchronization
allowed by the default setup is not sufficient to use LXA IOBus devices, leading to
frames being rejected by the CAN-controller.

**Solution**: Use a ``sjw`` relative the other bit-timings instead of a fixed value of 1.

LXA IOBus devices are tested at a ``sjw`` of 5% of one bit-time.
To determine the current bit-timings the ``can0`` interface should first
be configured to the desired bitrate of 100 kbit/s, e.g. by using systemd-networkd.
The resulting bit timings are calculated automatically by the Linux kernel
and can then be displayed using the ``ip`` command:

::

     $ ip --details link show can0
     5: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 qdisc pfifo_fast state UP mode DEFAULT group default qlen 10
       link/can  promiscuity 0 minmtu 0 maxmtu 0
       can state ERROR-PASSIVE (berr-counter tx 128 rx 0) restart-ms 100
         bitrate 100000 sample-point 0.875
         tq 50 prop-seg 87 phase-seg1 87 phase-seg2 25 sjw 1
         peak_canfd: tseg1 1..256 tseg2 1..128 sjw 1..128 brp 1..1024 brp-inc 1
         peak_canfd: dtseg1 1..32 dtseg2 1..16 dsjw 1..16 dbrp 1..1024 dbrp-inc 1
         clock 80000000 numtxqueues 1 numrxqueues 1 gso_max_size 65536 gso_max_segs 65535

Shown in line 6 are the timing-parameters ``tq``, ``prop-seg``, ``phase-seg1``, ``phase-seg2``
and ``sjw``. One bit-time consists of ``1 + prop-seg + phase-seg1 + phase-seg2`` time quanta.
The ``sjw`` should thus be adjusted to a value of ``sjw = ⌊0.05 * (1 + prop-seg + phase-seg1 + phase-seg2)⌋ = 10``.

The interface can be re-configured accordingly using the command:

::

    $ ip link set can0 type can tq 50 prop-seg 87 phase-seg1 87 phase-seg2 25 sjw 10

.. note::

   All other values but ``sjw`` are copied from the status output above.
