"""Helpers for encoding command payloads and decoding protocol payloads."""

from __future__ import annotations

import struct

from ..constants import constants_datatypes as DATATYPE
from ..utils.utils_hex import to_hex


def _get_payload(response: dict) -> bytes:
    """Return the response payload and validate the frame kind."""
    if response["kind"] != "response":
        raise TypeError("Expected a response frame.")

    return response["payload"]


def _require_payload_length(payload: bytes, expected_length: int) -> bytes:
    """Validate one exact payload length."""
    if len(payload) != expected_length:
        raise ValueError(
            f"Expected {expected_length} payload bytes, received {len(payload)}."
        )

    return payload


def pack_float32(value: float) -> bytes:
    """Pack one float32 value in protocol byte order."""
    return struct.pack(">f", float(value))


def pack_uint8(value: int) -> bytes:
    """Pack one unsigned byte."""
    return struct.pack(">B", int(value))


def pack_uint16(value: int) -> bytes:
    """Pack one unsigned 16-bit integer in protocol byte order."""
    return struct.pack(">H", int(value))


def pack_uint32(value: int) -> bytes:
    """Pack one unsigned 32-bit integer in protocol byte order."""
    return struct.pack(">I", int(value))


def pack_uint8_float32(value_1: int, value_2: float) -> bytes:
    """Pack one uint8 followed by one float32."""
    return pack_uint8(value_1) + pack_float32(value_2)


def pack_uint8_uint8(value_1: int, value_2: int) -> bytes:
    """Pack two uint8 values."""
    return pack_uint8(value_1) + pack_uint8(value_2)


def pack_uint8_uint16(value_1: int, value_2: int) -> bytes:
    """Pack one uint8 followed by one uint16."""
    return pack_uint8(value_1) + pack_uint16(value_2)


def pack_uint8_uint32(value_1: int, value_2: int) -> bytes:
    """Pack one uint8 followed by one uint32."""
    return pack_uint8(value_1) + pack_uint32(value_2)


def unpack_float32_payload(payload: bytes) -> float:
    """Decode one float32 payload."""
    return struct.unpack(">f", _require_payload_length(payload, 4))[0]


def unpack_uint16_payload(payload: bytes) -> int:
    """Decode one uint16 payload."""
    return struct.unpack(">H", _require_payload_length(payload, 2))[0]


def unpack_uint32_payload(payload: bytes) -> int:
    """Decode one uint32 payload."""
    return struct.unpack(">I", _require_payload_length(payload, 4))[0]


def unpack_uint8_uint32_payload(payload: bytes) -> tuple[int, int]:
    """Decode one uint8 + one uint32 payload."""
    _require_payload_length(payload, 5)
    return payload[0], struct.unpack(">I", payload[1:])[0]


def unpack_float32_response(response: dict) -> float:
    """Decode one float32 payload from a response frame."""
    return unpack_float32_payload(_get_payload(response))


def unpack_uint16_response(response: dict) -> int:
    """Decode one uint16 payload from a response frame."""
    return unpack_uint16_payload(_get_payload(response))


def unpack_uint32_response(response: dict) -> int:
    """Decode one uint32 payload from a response frame."""
    return unpack_uint32_payload(_get_payload(response))


def unpack_uint8_uint32_response(response: dict) -> tuple[int, int]:
    """Decode one uint8 + one uint32 payload from a response frame."""
    return unpack_uint8_uint32_payload(_get_payload(response))


def decode_int24_values(payload: bytes) -> list[int]:
    """Decode signed big-endian int24 measurement values."""
    if len(payload) % 3:
        raise ValueError("int24 measurement payload length must be a multiple of 3.")

    values = []
    for index in range(0, len(payload), 3):
        raw_value = payload[index:index + 3]
        sign_byte = b"\xff" if raw_value[0] & 0x80 else b"\x00"
        values.append(int.from_bytes(sign_byte + raw_value, byteorder="big", signed=True))
    return values


def decode_measurement_values(
    payload: bytes,
    *,
    datatype: int,
    object_count: int,
) -> list[int | float]:
    """Decode a measurement payload for the documented GSV datatypes."""
    value_count = int(object_count)
    if value_count < 0:
        raise ValueError("object_count must not be negative.")

    if datatype == DATATYPE.FLOAT32:
        expected_len = value_count * 4
        _require_payload_length(payload, expected_len)
        return list(struct.unpack(f">{value_count}f", payload))

    if datatype == DATATYPE.INT16:
        expected_len = value_count * 2
        _require_payload_length(payload, expected_len)
        return list(struct.unpack(f">{value_count}h", payload))

    if datatype == DATATYPE.INT24:
        expected_len = value_count * 3
        _require_payload_length(payload, expected_len)
        return decode_int24_values(payload)

    raise ValueError(f"Unsupported measurement datatype bits: {datatype:03b}")


def decode_generic_payload_views(payload: bytes) -> dict[str, object]:
    """Return conservative numeric views for common short response payloads."""
    decoded: dict[str, object] = {
        "payload_length": len(payload),
        "payload_hex": to_hex(payload),
    }
    if len(payload) == 1:
        decoded["value_uint8"] = payload[0]
    elif len(payload) == 2:
        decoded["value_uint16"] = unpack_uint16_payload(payload)
    elif len(payload) == 4:
        decoded["value_uint32"] = unpack_uint32_payload(payload)
    return decoded
