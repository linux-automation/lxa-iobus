import logging
import struct
import types

from lxa_iobus.canopen import SdoAbort

logger = logging.getLogger("lxa_iobus.object_directory")

"""
IOBus node object directory

This module provides classes that allow you to interact with individual
features of IOBus nodes, like inputs, outputs and ADCs.
These features work the same on all IOBus nodes and nodes provide the
ability to automatically enumerate features.

To be able to enumerate features in an async fashion many of the classes
would need an `async def __init__(self)`, which does not exist yet.
Instead the provide an `async def new()` classmethod that should be used
instead of `__init__()`.

To use just the ADC feature on an LxaRemoteNode:

    node = await LxaRemoteNode.new("http://localhost:8080", "<node name>")
    adc = await Adc.new(node)

    print("number of ADC channels:", await adc.channel_count())

    for name, value in await adc.read_all():
        print(f"Channel {name}: {value}")

To automatically enumerate all features of an LxaRemoteNode:

    node = await LxaRemoteNode.new("http://localhost:8080", "<node name>")
    od = await ObjectDirectory.scan(node)
    adc = od.adc

    print("number of ADC channels:", await adc.channel_count())

    for name, value in await adc.read_all():
        print(f"Channel {name}: {value}")

The LxaRemoteNode and LxaBusNode classes also provide a pre-initialized
ObjectDirectory instance via `node.od`.
"""


class ProtocolVersionError(Exception):
    """Exception that is thrown when a node reports an unsupported protocol version"""

    pass


class SubIndex(object):
    """Information about a sub index

    This class describes a sub indexes id and how to encode/decode it from/into
    python representations.

    A sub index is the unit of information that is set/read in a single CANopen
    transaction (e.g. SDO reads and SDO writes).
    A sub index behaves like register does on a microcontroller peripheral.
    An ADC peripheral on a microcontroller will provide one or more registers
    to configure the ADC and one or more registers containing the digitized value.
    Likewise an ADC CANopen object can provide one or more sub indices to configure
    the ADC and one or multiple sub indices to read out the values.
    """

    @classmethod
    def u8(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single unsigned 8 bit number"""

        return cls(sub_index, "B")

    @classmethod
    def u16(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single unsigned 16 bit number"""

        return cls(sub_index, "H")

    @classmethod
    def u32(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single unsigned 32 bit number"""

        return cls(sub_index, "L")

    @classmethod
    def u64(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single unsigned 64 bit number"""

        return cls(sub_index, "Q")

    @classmethod
    def i32(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single signed 32 bit number"""

        return cls(sub_index, "l")

    @classmethod
    def f32(cls, sub_index: int):
        """Describes a sub index with id `sub_index` consisting of a single 32 bit floating point number"""

        return cls(sub_index, "f")

    def __init__(self, sub_index: int, encoding: str, fields=None):
        """Describes a sub index

        Arguments:

            - `sub_index` sub index id (0-255)
            - `encoding` a python `struct` format string that describes how to split the raw bytes into
              python datatypes and vice versa (without the trailing endianness specifier).
            - `fields` a name to use for each entry in `encoding`.
              Can be omitted if `encoding` only contains a single entry.

        """

        self.sub_index = sub_index
        self._encoding = encoding
        self._fields = fields

    def encode(self, values):
        """Encode value(s) for transfer to the node

        Arguments:

            - `values` takes either a single integer/float/value
              (if the sub index contains a single value)
              or a dictionary of field names and values to encode for transfer.

        Returns: The values encoded as bytestring
        """

        values = [values] if self._fields is None else tuple(values[field] for field in self._fields)

        return struct.pack("<" + self._encoding, *values)

    def decode(self, payload):
        """Decode value(s) received from a node

        Arguments:

            - `payload` the raw sdo message content received from the node
              as bytesting.

        Returns: Either a single integer/float/value (if the sub index contains a single value)
        or a dictionary of field names and values.
        """

        values = struct.unpack("<" + self._encoding, payload)

        if self._fields is None:
            return values[0]
        else:
            return dict(zip(self._fields, values))


class BitFieldSubIndex(object):
    """A sub index that contains multiple binary values in the form of a bit mask

    Each bit is given a a name that can be used to set/retrieve said bit:

        >>> sub = BitFieldSubIndex.u8(sub_index=0, fields=("Peter", "Paul", "Mary"))
        >>> enc = sub.encode({"Paul": True})
        >>> enc
        b'\x02'
        >>> sub.decode(enc)
        {'Peter': False, 'Paul': True, 'Mary': False}
    """

    @classmethod
    def u8(cls, sub_index: int, fields: [str]):
        """Describes a sub index with id `sub_index` containing eight individual bits"""

        return cls(sub_index, "B", fields)

    @classmethod
    def u16(cls, sub_index: int, fields: [str]):
        """Describes a sub index with id `sub_index` containing sixteen individual bits"""

        return cls(sub_index, "H", fields)

    @classmethod
    def u32(cls, sub_index: int, fields: [str]):
        """Describes a sub index with id `sub_index` containing thirty two individual bits"""

        return cls(sub_index, "L", fields)

    @classmethod
    def u64(cls, sub_index: int, fields: [str]):
        """Describes a sub index with id `sub_index` containing sixty four individual bits"""

        return cls(sub_index, "Q", fields)

    def __init__(self, sub_index: int, encoding: str, fields):
        """Describes a sub index containing a bit field

        Arguments:

            - `sub_index` - The sub index id.
            - `encoding` - A python `struct` format string used to encode/decode the raw bytes
              into a single integer or vice versa.
            - `fields` - A list of names for the bits in the bit fields.
              The first element in the list is the least significant bit.
              Unused bits can be denoted using `None`.
        """

        self.sub_index = sub_index
        self._encoding = encoding
        self._fields = fields

    def encode(self, values):
        """Encode a dictionary of bit_name: bit_value pairs into a bytesting

        Bits that are not listed in `values` are implicitly set to zero.

        An integer can be provided instead of a dictionary to set a raw value.
        """

        if isinstance(values, int):
            # Allow writing a raw number to the bit field to e.g.
            # clear all flags at once without listing all the field names.
            val = values
        else:
            val = 0

            for index, field in enumerate(self._fields):
                if field is not None:
                    # Fields that are not listed are implicitly zero
                    field_value = values.get(field, 0)

                    val |= (field_value != 0) << index

        return struct.pack("<" + self._encoding, val)

    def decode(self, payload):
        """Decode a raw bytestring received from a node into a dictionary of bit_name:bit_value pairs"""

        (val,) = struct.unpack("<" + self._encoding, payload)

        return dict(
            (field, (val & (1 << index)) != 0) for index, field in enumerate(self._fields) if field is not None
        )


class StringSubIndex(object):
    """A sub index that contains a text string"""

    def __init__(self, sub_index: int):
        self.sub_index = sub_index

    def encode(self, values: str):
        return values.encode("utf-8")

    def decode(self, payload):
        return payload.decode("utf-8")


class ProcessDataObject(object):
    """A CANopen process data object, e.g. a collection of sub indices with the same primary index

    This class is intended as a base class for classes that describe IOBus node features.
    It provides the `add_sub` and `add_sub_array` methods that register sub indices to the class.
    For each registered sub index methods are added to the class to read / set the sub index.

    For example:

        >>> class ExampleFeature(ProcessDataObject):
        >>>    INDEX = 1234
        >>>
        >>>    def __init__(self, node):
        >>>        super().__init__(self, node)
        >>>
        >>>        self.add_sub("example_value", SubIndex.u32(0))
        >>>        self.add_sub_array("example_array", [SubIndex.u32(1), SubIndex.u32(2)])
        >>>
        >>> node = await LxaRemoteNode.new("http://localhost:8080", "<node name>")
        >>> ex = ExampleFeature(node)
        >>> await ex.set_example_value(1)
        >>> await ex.example_value()
        1
        >>> await ex.set_example_array(1, 2)
        >>> await ex.example_array(1)
        2

    Sub indices can also be marked as read only / write only and cacheable
    (which means they do not have to be re-fetched from the node every time they are read).
    """

    INDEX = None

    def __init__(self, node):
        self._cache = dict()
        self._node = node

    def add_sub(self, name: str, sub: SubIndex, readable=True, writable=True, cacheable=False):
        if readable:

            async def get_sub(self):
                if cacheable and name in self._cache:
                    return self._cache[name]

                payload = await self._node.sdo_read(self.INDEX, sub.sub_index)
                payload = sub.decode(payload)

                if cacheable:
                    self._cache[name] = payload

                return payload

            # Add a self.{name}() method to the class that can be used to read values
            setattr(self, name, types.MethodType(get_sub, self))

        if writable:

            async def set_sub(self, values):
                if cacheable:
                    self._cache[name] = values

                payload = sub.encode(values)

                await self._node.sdo_write(self.INDEX, sub.sub_index, payload)

            # "public_value" becomes self.set_public_value() but
            # "_private_value" becomes self._set_private_value()
            set_name = "set_" + name if name[0] != "_" else "_set" + name
            setattr(self, set_name, types.MethodType(set_sub, self))

    def add_sub_array(self, name: str, subs: [SubIndex], readable=True, writable=True, cacheable=False):
        if readable:

            async def get_sub(self, instance: int):
                if cacheable and (name, instance) in self._cache:
                    return self._cache[name, instance]

                sub = subs[instance]
                payload = await self._node.sdo_read(self.INDEX, sub.sub_index)
                payload = sub.decode(payload)

                if cacheable:
                    self._cache[name, instance] = payload

                return payload

            setattr(self, name, types.MethodType(get_sub, self))

        if writable:

            async def set_sub(self, instance: int, values):
                if cacheable:
                    self._cache[name, instance] = values

                sub = subs[instance]
                payload = sub.encode(values)

                await self._node.sdo_write(self.INDEX, sub.sub_index, payload)

            # "public_value" becomes self.set_public_value() but
            # "_private_value" becomes self._set_private_value()
            set_name = "set_" + name if name[0] != "_" else "_set" + name
            setattr(self, set_name, types.MethodType(set_sub, self))


class ManufacturerDeviceName(ProcessDataObject):
    INDEX = 0x1008

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("name", StringSubIndex(0), writable=False, cacheable=True)


class ManufacturerHardwareVersion(ProcessDataObject):
    INDEX = 0x1009

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("version", StringSubIndex(0), writable=False, cacheable=True)


class ManufacturerSoftwareVersion(ProcessDataObject):
    INDEX = 0x100A

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("version", StringSubIndex(0), writable=False, cacheable=True)


class SupportedProtocols(ProcessDataObject):
    """Gets the protocol indices supported by a node

    This is the main entrypoint to the automatic IOBus device enumeration.
    First the list of available protocol / object indices is requested from
    the node and then all reported protocols with an index we know are set up.
    """

    INDEX = 0x2000

    @classmethod
    async def new(cls, node):
        this = cls(node)

        protocol_count = await this.protocol_count()

        protocols = list(SubIndex.u32(i + 1) for i in range(protocol_count))

        this.add_sub_array("protocol", protocols, writable=False, cacheable=True)

        return this

    def __init__(self, node):
        """Do not use directly.

        Use await SupportedProtocols.new() instead."""

        super().__init__(node)

        self.add_sub("protocol_count", SubIndex.u32(0), writable=False, cacheable=True)

    async def fetch(self):
        protocols = list()

        count = await self.protocol_count()

        for i in range(count):
            protocol = await self.protocol(i)
            protocols.append(protocol)

        return tuple(protocols)


class VersionInfo(ProcessDataObject):
    """IOBus specific information about a node"""

    INDEX = 0x2001

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("protocol", SubIndex.u32(0), writable=False, cacheable=True)
        self.add_sub("board", SubIndex.u32(1), writable=False, cacheable=True)
        self.add_sub("serial", StringSubIndex(2), writable=False, cacheable=True)
        self.add_sub("vendor_name", StringSubIndex(3), writable=False, cacheable=True)
        self.add_sub("notes", StringSubIndex(5), writable=False, cacheable=True)


class InputOutputBase(ProcessDataObject):
    """Common base class for inputs and outputs

    Should not be used directly.
    Use the derived Input and Output classes instead.
    """

    async def _setup_pin_count(self, channel_count):
        # The number of pins per channel
        pin_count_sub_indices = list(SubIndex.u32(2 * instance + 1) for instance in range(channel_count))

        self.add_sub_array("pin_count", pin_count_sub_indices, writable=False, cacheable=True)

    def __init__(self, node):
        """Do not use directly.

        Use await Outputs.new() or await Inputs.new() instead."""

        super().__init__(node)

        self.pins = list()
        self._name_to_channel_map = dict()

        # Only the channel count has a static sub index
        self.add_sub("_channel_count", SubIndex.u32(0), writable=False, cacheable=True)

    async def channel_count(self):
        # The channel count is given in terms of sub indices,
        # of which there are two per channel.
        # This is a bit confusing, so we calculate the actual channel count here.

        # This is not the number of individual inputs or outputs,
        # but rather the number of input/output "registers",
        # where each channel consists of a bit mask that controls multiple ios.

        return await self._channel_count() // 2

    async def get(self, name):
        """Read the state of a particular input/output"""

        # Which channel/"register"/"bank" does this i/o belong to?
        channel = self._name_to_channel_map[name]

        bits = await self.data(channel)

        # Return just the relevant bit for this input / output
        return bits[name]

    async def get_all(self):
        """Get the state of all inputs/outputs

        This is more efficitent than individual get()s because whole channels
        are read at once.
        """
        channel_count = await self.channel_count()

        res = dict()

        for channel in range(channel_count):
            bits = await self.data(channel)

            res.update((name, value) for name, value in bits.items() if not name.endswith("_mask"))

        return res


class Outputs(InputOutputBase):
    """Output pins whose state can be set and read"""

    INDEX = 0x2100

    @classmethod
    async def new(cls, node, pin_names: [[str]] = None):
        this = cls(node)

        if pin_names is None:
            pin_names = [[]]

        # Add fields for which we need to know the number of channels
        channel_count = await this.channel_count()

        await this._setup_pin_count(channel_count)

        data_sub_indices = list()

        for instance in range(channel_count):
            pin_count = await this.pin_count(instance)

            field_names = [None] * 32

            for i in range(pin_count):
                try:
                    pin_name = pin_names[instance][i]
                except IndexError:
                    # Provide a default name for pins that do not have an
                    # explicitly provided name.
                    pin_name = f"OUT{i}" if channel_count == 1 else f"OUT{instance}_{i}"

                # The state of a pin is set using two bits in the output
                # bit mask.
                # One that selects the pin for writing (the _mask bit) and
                # one that sets the actual new state.
                # This way unselected pins in a channel can stay at their old state.
                field_names[i] = pin_name
                field_names[i + 16] = f"{pin_name}_mask"

                this.pins.append(pin_name)
                this._name_to_channel_map[pin_name] = instance

            sub = BitFieldSubIndex.u32(instance * 2 + 2, field_names)

            data_sub_indices.append(sub)

        this.add_sub_array("data", data_sub_indices)

        return this

    async def set_pin(self, name, state):
        channel = self._name_to_channel_map[name]

        # We need to select the pin to set via its mask bit and
        # also set the new state.
        cmd = {name: state, f"{name}_mask": True}

        await self.set_data(channel, cmd)

    async def set_high(self, name):
        await self.set_pin(name, True)

    async def set_low(self, name):
        await self.set_pin(name, False)

    async def toggle(self, name):
        state = await self.get(name)
        await self.set_pin(name, not state)

        return not state


class Inputs(InputOutputBase):
    """Input pins whose state can be read out"""

    INDEX = 0x2101

    @classmethod
    async def new(cls, node, pin_names: [[str]] = None):
        this = cls(node)

        if pin_names is None:
            pin_names = [[]]

        # Add fields for which we need to know the number of channels
        channel_count = await this.channel_count()

        await this._setup_pin_count(channel_count)

        data_sub_indices = list()

        for instance in range(channel_count):
            pin_count = await this.pin_count(instance)

            field_names = list()

            for i in range(pin_count):
                try:
                    pin_name = pin_names[instance][i]
                except IndexError:
                    # Provide a default name for pins that do not have an
                    # explicitly provided name.
                    pin_name = f"IN{i}" if channel_count == 1 else f"IN{instance}_{i}"

                field_names.append(pin_name)

                this.pins.append(pin_name)
                this._name_to_channel_map[pin_name] = instance

            sub = BitFieldSubIndex.u32(2 * instance + 2, field_names)

            data_sub_indices.append(sub)

        this.add_sub_array("data", data_sub_indices, writable=False)

        return this


class Timers(ProcessDataObject):
    """Timers that can generate and capture timestamped events"""

    INDEX = 0x2102

    @classmethod
    async def new(cls, node):
        this = cls(node)

        # Check that we speek the same protocol version as the node
        version = await this.version()

        if version != 1:
            raise ProtocolVersionError(f"Timers expected protocol version 1 but got {version}")

        # Add fields for which we need to know the number of channels
        channel_count_out = await this.channel_count_out()
        channel_count_in = await this.channel_count_in()

        # The queue fill level sub index
        queue_levels_encoding = "B" * (channel_count_out + channel_count_in)
        queue_levels_fields_out = list(f"out{i}" for i in range(channel_count_out))
        queue_levels_fields_in = list(f"in{i}" for i in range(channel_count_in))
        queue_levels_fields = queue_levels_fields_out + queue_levels_fields_in

        this.add_sub("queue_capacities", SubIndex(6, queue_levels_encoding, queue_levels_fields))
        this.add_sub("queue_levels", SubIndex(7, queue_levels_encoding, queue_levels_fields))

        # The error flags sub index
        flag_fields = list()

        for instance in range(channel_count_out):
            flag_fields.append(f"output_overflow_{instance}")
            flag_fields.append(f"output_missed_{instance}")

        for instance in range(channel_count_in):
            flag_fields.append(f"input_overflow_{instance}")

        this.add_sub("flags", BitFieldSubIndex.u32(3, flag_fields))

        # Output fifos
        out_channels = list(
            SubIndex(8 + instance, "QB", ("timestamp", "state")) for instance in range(channel_count_out)
        )

        this.add_sub_array("output", out_channels)

        # Input fifos
        in_channels = list(
            SubIndex(8 + channel_count_out + instance, "QB", ("timestamp", "state"))
            for instance in range(channel_count_in)
        )

        this.add_sub_array("input", in_channels, writable=False)

        return this

    def __init__(self, node):
        """Do not use directly.

        Use await Timers.new() instead."""

        super().__init__(node)

        # Set up subindices with static position and encoding
        self.add_sub("channel_count_out", SubIndex.u32(0), writable=False, cacheable=True)
        self.add_sub("channel_count_in", SubIndex.u32(1), writable=False, cacheable=True)
        self.add_sub("version", SubIndex.u32(2), writable=False, cacheable=True)
        self.add_sub("frequency", SubIndex.u32(4), writable=False, cacheable=True)
        self.add_sub("time", SubIndex.u64(5), writable=False)

    async def clear_flags(self):
        await self.set_flags(0xFFFFFFFF)

    async def set_output_now(self, instance, state):
        """Clear the output queue of a channel and set its state immediately"""

        await self.set_output(instance, {"timestamp": 0, "state": state})


class Triggers(ProcessDataObject):
    """Control the reference level of a comparator

    This is used to provide a binary "higher than threshold"/
    "lower than threshold" value for use in the Timers input capture.
    """

    INDEX = 0x2103

    @classmethod
    async def new(cls, node):
        this = cls(node)

        # Check that we speek the same protocol version as the node
        version = await this.version()

        if version != 1:
            raise ProtocolVersionError(f"Triggers expected protocol version 1 but got {version}")

        # Add fields for which we need to know the number of channels
        channel_count = await this.channel_count()

        channels = list(SubIndex.u16(2 + instance) for instance in range(channel_count))

        this.add_sub_array("_threshold", channels)

        return this

    def __init__(self, node):
        """Do not use directly.

        Use await Triggers.new() instead."""

        super().__init__(node)

        self.add_sub("channel_count", SubIndex.u32(0), writable=False, cacheable=True)
        self.add_sub("version", SubIndex.u32(1), writable=False, cacheable=True)

    async def threshold(self, instance):
        """Get the threshold level

        Returns: the level as floating point number between 0 and 1
        """

        return await self._threshold(instance) / 0xFFFF

    async def set_threshold(self, instance, level):
        """Set the threshold level on a scale between 0 and 1."""

        level = int(level * 0xFFFF)
        level = min(level, 0xFFFF)
        level = max(level, 0)

        await self._set_threshold(instance, level)


class Locator(ProcessDataObject):
    """A flashing LED to find the correct node in a network

    The locator LED can be activated from both the node and the server
    to find the correct node on a potentially large bus.
    """

    INDEX = 0x210C

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("state", SubIndex.u32(1))

    async def active(self):
        state = await self.state()
        return state != 0

    async def disable(self):
        await self.set_state(0)

    async def enable(self):
        await self.set_state(1)


class Adc(ProcessDataObject):
    """Read analog voltages on the node

    The node contains the required calibration data to convert thease measurements
    to e.g. volts.
    """

    INDEX = 0x2ADC

    @classmethod
    async def new(cls, node, channel_names=None):
        this = cls(node)

        # Check that we speek the same protocol version as the node
        version = await this.protocol_version()

        if version != 1:
            raise ProtocolVersionError(f"Adc expected protocol version 1 but got {version}")

        channel_count = await this.channel_count()

        if channel_names is None:
            channel_names = list(f"ADC{i}" for i in range(channel_count))

        this.channel_names = channel_names
        this._name_to_index_map = dict((name, index) for index, name in enumerate(channel_names))

        channel_offsets = list((i + 1) * 4 for i in range(channel_count))

        data_indices = list(SubIndex.u16(c + 0) for c in channel_offsets)
        offset_indices = list(SubIndex.i32(c + 1) for c in channel_offsets)
        scale_indices = list(SubIndex.f32(c + 2) for c in channel_offsets)

        this.add_sub_array("data", data_indices, writable=False)
        this.add_sub_array("offset", offset_indices, writable=False, cacheable=True)
        this.add_sub_array("scale", scale_indices, writable=False, cacheable=True)

        return this

    def __init__(self, node):
        """Do not use directly.

        Use await Adc.new() instead."""

        super().__init__(node)

        self.add_sub("channel_count", SubIndex.u32(0), writable=False, cacheable=True)
        self.add_sub("protocol_version", SubIndex.u32(1), writable=False, cacheable=True)

    async def read_by_index(self, index):
        data = await self.data(index)
        offset = await self.offset(index)
        scale = await self.scale(index)

        return (data + offset) * scale

    async def read(self, channel_name):
        index = self._name_to_index_map[channel_name]

        return await self.read_by_index(index)

    async def read_all(self):
        res = dict()

        for name in self.channel_names:
            res[name] = await self.read(name)

        return res


class Bootloader(ProcessDataObject):
    """Ask the node to reset into bootloader mode

    This can be used to reset a node so that it can be flashed with a new
    firmware image.
    """

    INDEX = 0x2B07

    def __init__(self, node):
        super().__init__(node)

        self.add_sub("key", SubIndex.u32(0), readable=False)

    async def enter(self):
        # The node only resets when the correct key is presented,
        # to prevent erroneous resets.
        await self.set_key(0x12345678)


class ChipUid(ProcessDataObject):
    """Read the microcontrollers unique ID"""

    INDEX = 0x2C1D

    def __init__(self, node):
        super().__init__(node)

        sub_indices = list(SubIndex.u32(i) for i in range(4))

        self.add_sub_array("uid_field", sub_indices, writable=False, cacheable=True)

    async def uid(self):
        uid = list()

        for i in range(4):
            field = await self.uid_field(i)
            uid.append(field)

        return tuple(uid)


class ServerTimeout(ProcessDataObject):
    """Enable and disable node reset on server timeout

    To ensure that nodes reset their node id when the IOBus server goes away
    they will time out if not polled by the server periodically.
    This can become annoying when using a node without a full IOBus server.
    This object allows to disable the timeout.
    """

    INDEX = 0x2D06

    @classmethod
    async def new(cls, node):
        this = cls(node)

        # Check that we speek the same protocol version as the node
        version = await this.version()

        if version != 1:
            raise ProtocolVersionError(f"ServerTimeout expected protocol version 1 but got {version}")

        return this

    def __init__(self, node):
        """Do not use directly.

        Use await ServerTimeout.new() instead."""

        super().__init__(node)

        self.add_sub("version", SubIndex.u32(0), writable=False, cacheable=True)
        self.add_sub("status", SubIndex.u32(0))

    async def enable(self):
        self.set_status(1)

    async def disable(self):
        self.set_status(0)


class ObjectDirectory(dict):
    """Auto-Enumerated directory of LXA IOBus node CANopen objects"""

    _CONFIGURATIONLESS_OBJECTS = {
        "version_info": VersionInfo,
        "timers": Timers,
        "triggers": Triggers,
        "locator": Locator,
        "bootloader": Bootloader,
        "chip_uid": ChipUid,
        "server_timeout": ServerTimeout,
    }

    @classmethod
    async def scan(cls, node, adc_names=None, input_names=None, output_names=None):
        """Set up an ObjectDirectory by enumerating available objects on a node"""

        this = cls(node)

        try:
            this["supported_protocols"] = await SupportedProtocols.new(node)
        except SdoAbort:
            logger.info(f"Node {node.node} does not support IOBus protocol enumeration")
            return this

        protocols = await this.supported_protocols.fetch()

        # Setup all objects that do not need pin or channel names
        for name, obj_cls in this._CONFIGURATIONLESS_OBJECTS.items():
            if obj_cls.INDEX in protocols:
                await this._try_protocol_setup(node, name, obj_cls)

        if Adc.INDEX in protocols:
            await this._try_protocol_setup(node, "adc", Adc, adc_names)

        if Inputs.INDEX in protocols:
            await this._try_protocol_setup(node, "inputs", Inputs, input_names)

        if Outputs.INDEX in protocols:
            await this._try_protocol_setup(node, "outputs", Outputs, output_names)

        return this

    async def _try_protocol_setup(self, node, name, cls, *args):
        try:
            if hasattr(cls, "new"):
                # Protocols that need an async "__init__",
                # because they communicate with the node during setup.
                self[name] = await cls.new(node, *args)
            else:
                # Protocols that do not need to communicate with the node
                self[name] = cls(node, *args)
        except ProtocolVersionError as e:
            logger.warn(f"Node {node.name} has an incompatible protocol version: {e}")
        except Exception as e:
            proto_name = cls.__name__
            logger.error(f"Failed to enumerate protocol {proto_name} on node {node.name}: {e}")

    def __init__(self, node):
        """Do not use directly.

        This only sets up a fraction of available objects.
        Use await ObjectDirectory.scan() instead.
        """

        # These objects are defined by the CANopen standard and can be assumed to
        # always be there
        self["manufacturer_device_name"] = ManufacturerDeviceName(node)
        self["manufacturer_hardware_version"] = ManufacturerHardwareVersion(node)
        self["manufacturer_software_version"] = ManufacturerSoftwareVersion(node)

    def __getattr__(self, name):
        # This allows accessing e.g. od["adc"] via od.adc as well,
        # which is a bit prettier.
        return self[name]
