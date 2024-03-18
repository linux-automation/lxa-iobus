import struct
from time import time

from can import Message

LSS_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER = 2020
LSS_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE = 2021

LSS_COMMAND_SPECIFIER_SWITCH_MODE_GLOBAL = 0x04
LSS_COMMAND_SPECIFIER_CONFIGURE_NODE_ID = 0x11
LSS_COMMAND_SPECIFIER_FAST_SCAN = 0x51
LSS_COMMAND_SPECIFIER_IDENTIFY_SLAVE = 0x4F

SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX = 0x600
SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE = range(
    SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX + 1, SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX + 0b1111111 + 1
)
SDO_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER = range(0x581, 0x5FF + 1)

# The length of the data is stored in the data field
SDO_TRANSFER_TYPE_SIZE = 0b01

# The length is stored in n and data in the data field
SDO_TRANSFER_TYPE_DATA_WITH_SIZE = 0b11

# No size is given and must be inverted from packet size
SDO_TRANSFER_TYPE_DATA_NO_SIZE = 0b10

SDO_ABORT_CODES = {
    0x05030000: "Toggle bit not alternated",
    0x05040000: "SDO protocol timed out",
    0x05040001: "Client/server command specifier not valid or unknown",
    0x05040002: "Invalid block size",
    0x05040003: "Invalid sequence number",
    0x05040004: "CRC error",
    0x05040005: "Out of memory",
    0x06010000: "Unsupported access to an object",
    0x06010001: "Attempt to read a write only object",
    0x06010002: "Attempt to write a read only object",
    0x06020000: "Object does not exist in the object dictionary",
    0x06040041: "Object cannot be mapped to the PDO",
    0x06040042: "The number and length of the objects to be mapped would exceed PDO length",
    0x06040043: "General parameter incompatibility reason",
    0x06040047: "General internal incompatibility in the device",
    0x06060000: "Access failed due to an hardware error",
    0x06070010: "Data type does not match, length of service parameter does not match",
    0x06070012: "Data type does not match, length of service parameter too high",
    0x06070013: "Data type does not match, length of service parameter too low",
    0x06090011: "Sub-index does not exist",
    0x06090030: "Invalid value for parameter",
    0x06090031: "Value of parameter written too high",
    0x06090032: "Value of parameter written too low",
    0x06090036: "Maximum value is less than minimum value",
    0x060A0023: "Resource not available: SDO connection",
    0x08000000: "General error",
    0x08000020: "Data cannot be transferred or stored to the application",
    0x08000021: "Data cannot be transferred or stored to the application because of local control",
    0x08000022: "Data cannot be transferred or stored to the application because of the present device state",
    0x08000023: "Object dictionary dynamic generation fails or no object dictionary is present",
    0x08000024: "No data available",
}


class LssMode:
    OPERATION = 0
    CONFIGURATION = 1


class SdoAbort(Exception):
    def __init__(self, node_id, index, sub_index, error_code):
        self.node_id = node_id
        self.index = index
        self.sub_index = sub_index
        self.error_code = error_code

    def __str__(self):
        error_text = SDO_ABORT_CODES.get(self.error_code, "")

        return "SDO Abort: node: {} 0x{:02X}-0x{:02X} code: 0x{:08}: {}".format(
            self.node_id,
            self.index,
            self.sub_index,
            self.error_code,
            error_text,
        )

    def __repr__(self):
        return self.__str__()


class SdoMessage:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def gen_lss_switch_mode_global_message(lss_mode):
    if lss_mode not in (LssMode.OPERATION, LssMode.CONFIGURATION):
        raise ValueError

    return Message(
        timestamp=time(),
        arbitration_id=LSS_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE,
        data=struct.pack(
            "<BBxxxxxx",
            LSS_COMMAND_SPECIFIER_SWITCH_MODE_GLOBAL,
            lss_mode,
        ),
        is_extended_id=False,
    )


def gen_lss_configure_node_id_message(node_id):
    if (
        not isinstance(node_id, int)
        or node_id not in range(0, 128)  # only integer
        or node_id == 125  # canopen ids from 0-127 are valid
    ):  # reserved for the ISP (bootloader)
        raise ValueError

    return Message(
        timestamp=time(),
        arbitration_id=LSS_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE,
        data=struct.pack(
            "<BBxxxxxx",
            LSS_COMMAND_SPECIFIER_CONFIGURE_NODE_ID,
            node_id,
        ),
        is_extended_id=False,
    )


def gen_invalidate_node_ids_message():
    return Message(
        timestamp=time(),
        arbitration_id=LSS_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE,
        data=struct.pack(
            "<BBxxxxxx",
            LSS_COMMAND_SPECIFIER_CONFIGURE_NODE_ID,
            255,
        ),
        is_extended_id=False,
    )


def gen_lss_fast_scan_message(id_number, bit_checked, lss_sub, lss_next):
    if not isinstance(id_number, int) or id_number not in range(0, 2**32):
        raise ValueError

    if not isinstance(bit_checked, int) or bit_checked not in range(0, 256):
        raise ValueError

    if not isinstance(lss_sub, int) or lss_sub not in range(0, 256):
        raise ValueError

    if not isinstance(lss_next, int) or lss_next not in range(0, 256):
        raise ValueError

    return Message(
        timestamp=time(),
        arbitration_id=LSS_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE,
        data=struct.pack(
            "<BLBBB",
            LSS_COMMAND_SPECIFIER_FAST_SCAN,
            id_number,
            bit_checked,
            lss_sub,
            lss_next,
        ),
        is_extended_id=False,
    )


def parse_lss_result(message):
    if not message.arbitration_id == LSS_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER:
        raise ValueError

    command_specifier = message.data[0]
    error_code = message.data[1]
    spec_error = message.data[2]

    return command_specifier, error_code, spec_error


def parse_lss_fast_scan_result(message):
    if not message.arbitration_id == LSS_PROTOCOL_IDENTIFIER_SLAVE_TO_MASTER:
        raise ValueError

    command_specifier = message.data[0]

    if not command_specifier == LSS_COMMAND_SPECIFIER_IDENTIFY_SLAVE:
        raise ValueError


def gen_sdo_initiate_download(node_id, type, index, sub_index, data):
    # InitiateDownload (Server -> Node)

    command_specifier = 1

    if node_id not in range(0, 128):
        raise ValueError

    if type not in range(0, 4):
        raise ValueError

    if index not in range(0, 0xFFFF + 1):
        raise ValueError

    if sub_index not in range(0, 0xFF + 1):
        raise ValueError

    if len(data) not in range(0, 5):
        raise ValueError

    n = 4 - len(data)

    return Message(
        timestamp=time(),
        arbitration_id=SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX | node_id,
        data=struct.pack(
            "<BHB4s",
            (command_specifier << 5) | (n << 2) | type,
            index,
            sub_index,
            data,
        ),
        is_extended_id=False,
    )


def gen_sdo_segment_download(node_id, toggle, complete, seg_data):
    # DownloadSegment (Server -> Node)

    command_specifier = 0

    if node_id not in range(0, 128):
        raise ValueError

    if not isinstance(toggle, bool):
        raise ValueError

    if not isinstance(complete, bool):
        raise ValueError

    toggle = int(toggle)
    complete = int(complete)

    if len(seg_data) not in range(0, 8):
        raise ValueError

    n = 7 - len(seg_data)

    return Message(
        timestamp=time(),
        arbitration_id=SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX | node_id,
        data=struct.pack(
            "<B7s",
            (command_specifier << 5) | (toggle << 4) | (n << 1) | complete,
            seg_data,
        ),
        is_extended_id=False,
    )


def gen_sdo_initiate_upload(node_id, index, sub_index):
    # DownloadSegment (Node -> Server)

    command_specifier = 2

    if index not in range(0, 0xFFFF + 1):
        raise ValueError

    if sub_index not in range(0, 0xFF + 1):
        raise ValueError

    return Message(
        timestamp=time(),
        arbitration_id=SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX | node_id,
        data=struct.pack(
            "<BHB4s",
            (command_specifier << 5),
            index,
            sub_index,
            b"",
        ),
        is_extended_id=False,
    )


def gen_sdo_segment_upload(node_id, toggle):
    # UploadSegment (Node -> Server)

    command_specifier = 3

    if node_id not in range(0, 128):
        raise ValueError

    if not isinstance(toggle, bool):
        raise ValueError

    toggle = int(toggle)

    return Message(
        timestamp=time(),
        arbitration_id=SDO_PROTOCOL_IDENTIFIER_MASTER_TO_SLAVE_PREFIX | node_id,
        data=struct.pack(
            "<B7s",
            (command_specifier << 5) | (toggle << 4),
            b"",
        ),
        is_extended_id=False,
    )


def parse_sdo_message(message):
    sdo_message_kwargs = {}

    command_specifier = (message.data[0] >> 5) & 0b111
    node_id = message.arbitration_id & 0b1111111

    # upload segment (node -> server)
    if command_specifier == 0:
        toggle = ((message.data[0] >> 4) & 1) == 1
        number_of_bytes_not_used = (message.data[0] >> 1) & 0b111
        complete = (message.data[0] & 1) == 1
        seg_data = message.data[1:]

        sdo_message_kwargs = {
            "type": "upload_segment",
            "node_id": node_id,
            "toggle": toggle,
            "number_of_bytes_not_used": number_of_bytes_not_used,
            "complete": complete,
            "seg_data": seg_data,
        }

    # download segment (server -> node)
    elif command_specifier == 1:
        toggle = ((message.data[0] >> 4) & 1) == 1

        sdo_message_kwargs = {
            "type": "download_segment",
            "node_id": node_id,
            "toggle": toggle,
        }

    # initiate upload (node -> server)
    elif command_specifier == 2:
        sdo_message_kwargs["type"] = "initiate_upload"

        number_of_bytes_not_used = (message.data[0] >> 2) & 0b11
        transfer_type = ((message.data[0] >> 1) & 1) == 1
        indicates_size = ((message.data[0] >> 0) & 1) == 1

        index, subindex = struct.unpack("<xHBxxxx", message.data)
        data = message.data[4:]

        # e s
        readable_transfer_type = {
            (0, 0): "Reserved",
            # The length of the data is stored in the data field
            (0, 1): "Size",
            # The length is stored in n and data in the data field
            (1, 1): "DataWithSize",
            # No size is given and must be inverted from packet size
            (1, 0): "DataNoSize",
        }[transfer_type, indicates_size]

        sdo_message_kwargs = {
            "type": "initiate_upload",
            "node_id": node_id,
            "number_of_bytes_not_used": number_of_bytes_not_used,
            "transfer_type": transfer_type,
            "indicates_size": indicates_size,
            "index": index,
            "subindex": subindex,
            "data": data,
            "readable_transfer_type": readable_transfer_type,
        }

    # initiate download (server -> node)
    elif command_specifier == 3:
        index, subindex = struct.unpack("<xHBxxxx", message.data)

        sdo_message_kwargs = {
            "type": "initiate_download",
            "node_id": node_id,
            "index": index,
            "subindex": subindex,
        }

    # abort
    elif command_specifier == 4:
        index, subindex, error_code = struct.unpack("<xHBL", message.data)

        sdo_message_kwargs = {
            "type": "abort",
            "node_id": node_id,
            "index": index,
            "subindex": subindex,
            "error_code": error_code,
        }

    sdo_message_kwargs["message"] = message

    return SdoMessage(**sdo_message_kwargs)
