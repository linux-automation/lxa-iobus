CAN Basics
==========

CAN and CANopen are, when compared to modern Ethernet and IP,
quite simple protocols.
Most software developers are however more familiar with Ethernet
and IP and less with CAN and CANopen.

This chapter tries to give a short introduction into CAN and CANopen and
tries to focus on topics that are relevant for the operation of the
LXA IOBus system.

CAN-Bus Introduction
--------------------

The CAN bus was developed to connect multiple small computers
in a reliable way.
A very common scenario is to connect multiple control units inside
a road vehicle:
There is a lot of noise and possible bad connectors on the bus
but CAN must still be able to carry information from one control
unit to the others.

CAN is a low-speed and low-bandwith bus:
A single message can only carry up to 8 bytes of payload.
The maximum symbol-rate on the bus is 1 M/s.

Messages not Addresses
......................

In common computer networks (e.g. Ethernet) every node has a static address
(e.g. MAC-address).
Information in such network is usually sent from one address to another
address on the same network segment, e.g. each message contains one source
address and one destination address.
(There are exception but let's leave those aside here.)

On a CAN bus messages are published to a message-id,
where a single message-id can be consumed by one or many nodes on the bus.
It is even possible that multiple nodes on the bus publish information
to the same message-id!
In modern terms: A CAN bus follows the publish / subscribe paradigm where
the message-ids are the topics.
(Beware that there is no central *broker* here. Subscription is done using
ingress filters on the receiving nodes.)
This means CAN messages only contain a destination address and no
source address and the destination address may be shared between multiple nodes.

CAN itself only defines the length of a message-id
(11 or 29 bit depending on the addressing scheme used)
but not how these message-id should be used.
In a vehicle all message-ids are pre-allocated by the manufacturer:
For every message-id a structure defining the contents of the payload
is defined and shared between all control units.

In the case of the LXA IOBus the meaning of the message-ids
and the payload is defined by a CANopen-inspired protocol.

Reliable transmission
.....................

CAN makes a good amount of effort to make sure all nodes on the
bus share a common understanding of the information transmitted:
Every message contains a checksum to make sure no bit-errors
occur on the bus.

Additionally all nodes on the bus do a handshake for every message
that ensures that either all or no node received the message.

To archive this every receiving node on the bus sends an
acknowledge-flag to the bus once the complete frame has been
received and the checksum is correct.

If the received checksum is not correct or another receive-error
occurs an error-message is send to the bus.
If an error message is received the current message is discarded
in the MAC - before forwarding it to the higher level.

Let's take a look at the following scenarios:

* **No other node on the bus:**
  The node sends a message on the bus.
  Since there is no other node on the bus the sender will
  not receive an ACK.
  The sending node will assume that the message has not
  been received by any node.
  This can happen if there are only two nodes on a bus
  and one is not powered or disconnected due to a faulty
  connection.
* **Two other nodes on the bus and the checksum is OK**:
  Both receiving nodes send an acknowledge after the end
  of the message.
  All three nodes assume that every other node has
  received the message correctly.
  This message is delivered to the next higher level.
* **Two other nodes on the bus and one receives an invalid**
  **checksum:**
  In this case the node receiving the invalid checksum
  will generate en error-frame instead of the acknowledge.
  Both other nodes will discard the message.
  The sending node will probably re-transmit the message.

