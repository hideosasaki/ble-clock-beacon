"""Wire format for the time advertisement.

The ble-clock firmware identifies a frame as a time advertisement when it sees
AD type 0x21 (Service Data - 128-bit UUID) carrying SERVICE_UUID followed by a
5-byte payload: little-endian uint32 UNIX seconds (UTC) and a one-byte command
flag reserved for future use.
"""

from __future__ import annotations

SERVICE_UUID = "74f6fb5b-ef7a-4a08-8f3e-a6c2bdff2010"

PAYLOAD_LEN = 5
CMD_FLAG_NONE = 0x00


def build_payload(unix_sec: int, cmd_flag: int = CMD_FLAG_NONE) -> bytes:
    if not 0 <= unix_sec <= 0xFFFFFFFF:
        raise ValueError(f"unix_sec out of uint32 range: {unix_sec}")
    if not 0 <= cmd_flag <= 0xFF:
        raise ValueError(f"cmd_flag out of uint8 range: {cmd_flag}")
    return unix_sec.to_bytes(4, "little") + bytes([cmd_flag])
