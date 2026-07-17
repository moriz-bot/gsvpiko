"""Frame reading, scanning, and parsing utilities for the GSV serial protocol.

The protocol layer owns byte-level frame knowledge. Runtime code may use the fast
buffer scanner here, but it must not duplicate frame-type, length, or measurement
payload rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

from ..constants import constants_datatypes as DATATYPE
from ..constants import constants_errors as ERROR
from ..constants import constants_frames as FRAME
from ..transport.transport_base import BaseTransport
from .protocol_payload_codec import decode_measurement_values


DEFAULT_FRAME_READ_TIMEOUT_S = 1.0
READ_RETRY_SLEEP_S = 0.001


@dataclass(frozen=True)
class ExtractedSerialFrames:
    """Complete frames extracted from a mutable byte buffer."""

    frames: list[bytes]
    resync_count: int = 0


def _get_transport_read_timeout(transport: BaseTransport) -> float:
    """Return the transport timeout used as the default frame-read timeout."""
    timeout = getattr(transport, "timeout", DEFAULT_FRAME_READ_TIMEOUT_S)

    try:
        timeout_s = float(timeout)
    except (TypeError, ValueError):
        return DEFAULT_FRAME_READ_TIMEOUT_S

    if timeout_s <= 0:
        return DEFAULT_FRAME_READ_TIMEOUT_S

    return timeout_s


def _raise_frame_timeout(
    *,
    expected_size: int,
    received_size: int,
) -> None:
    """Raise a timeout error for an incomplete frame read."""
    raise TimeoutError(
        f"Expected {expected_size} bytes, received {received_size} bytes "
        "before the frame-read timeout."
    )


def read_exactly(
    transport: BaseTransport,
    size: int,
    *,
    deadline: float | None = None,
) -> bytes:
    """Read exactly `size` bytes before the optional absolute deadline."""
    expected_size = int(size)
    buffer = bytearray()

    while len(buffer) < expected_size:
        if deadline is not None and time.monotonic() >= deadline:
            _raise_frame_timeout(
                expected_size=expected_size,
                received_size=len(buffer),
            )

        chunk = transport.read(expected_size - len(buffer))
        if chunk:
            buffer.extend(chunk)
            continue

        if deadline is None:
            _raise_frame_timeout(
                expected_size=expected_size,
                received_size=len(buffer),
            )

        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            _raise_frame_timeout(
                expected_size=expected_size,
                received_size=len(buffer),
            )

        time.sleep(min(READ_RETRY_SLEEP_S, remaining_s))

    return bytes(buffer)


def get_frame_type(header: int) -> int:
    """Extract frame type bits <7:6> from the header byte."""
    return (header & FRAME.FRAME_TYPE_MASK) >> FRAME.FRAME_TYPE_SHIFT


def get_interface(header: int) -> int:
    """Extract interface bits <5:4> from the header byte."""
    return (header & FRAME.INTERFACE_MASK) >> FRAME.INTERFACE_SHIFT


def get_length_field(header: int) -> int:
    """Extract length/object-count bits <3:0> from the header byte."""
    return header & FRAME.LENGTH_MASK


def is_serial_measurement_status(status_byte: int) -> bool:
    """Return True if the status byte matches a serial measurement frame."""
    return (
        status_byte & FRAME.STATUS_INDICATOR_MASK
    ) == FRAME.SERIAL_MEASUREMENT_INDICATOR_MASKED


def get_measurement_datatype(status_byte: int) -> int:
    """Extract datatype bits <6:4> from the measurement status byte."""
    return (status_byte & FRAME.STATUS_DATATYPE_MASK) >> FRAME.STATUS_DATATYPE_SHIFT


def get_measurement_value_size(status_byte: int) -> int:
    """Return the byte width of one measurement value."""
    datatype = get_measurement_datatype(status_byte)

    try:
        return DATATYPE.BYTES_PER_VALUE[datatype]
    except KeyError as error:
        raise ValueError(f"Unsupported measurement datatype bits: {datatype:03b}") from error


def measurement_frame_length(
    header: int,
    status_byte: int,
) -> int:
    """Return the complete byte length of one serial measurement frame."""
    object_count = get_length_field(header) + FRAME.MEASUREMENT_OBJECT_COUNT_OFFSET
    value_size = get_measurement_value_size(status_byte)
    crc_len = 2 if get_interface(header) == FRAME.SERIAL_WITH_CRC else 0
    return 3 + object_count * value_size + crc_len + 1


def serial_frame_length(
    header: int,
    third_byte: int,
) -> int:
    """Return the complete byte length of one serial frame.

    `third_byte` is the response status / extended response length byte, the
    measurement status byte, or the request command byte depending on frame type.
    """
    frame_type = get_frame_type(header)
    interface = get_interface(header)
    length_field = get_length_field(header)

    if frame_type == FRAME.RESPONSE:
        data_len = length_field if length_field < 15 else 15 + third_byte
        crc_len = 1 if interface == FRAME.SERIAL_WITH_CRC else 0
        return 3 + data_len + crc_len + 1

    if frame_type == FRAME.MEASUREMENT:
        if not is_serial_measurement_status(third_byte):
            raise ValueError("Frame does not contain a serial measurement status byte.")
        return measurement_frame_length(header, third_byte)

    if frame_type == FRAME.REQUEST:
        crc_len = 1 if interface == FRAME.SERIAL_WITH_CRC else 0
        return 3 + length_field + crc_len + 1

    raise ValueError(f"Unsupported frame type: {frame_type}")


def extract_serial_frames_from_buffer(
    raw_buffer: bytearray,
    *,
    accepted_frame_types: Iterable[int] | None = None,
) -> ExtractedSerialFrames:
    """Extract complete serial frames from a mutable byte buffer.

    Invalid leading bytes are removed and counted as resynchronizations. Complete
    but unaccepted frames are removed from the buffer and skipped. Incomplete
    trailing bytes stay in the buffer for the next read pass.
    """
    accepted = None if accepted_frame_types is None else set(accepted_frame_types)
    frames: list[bytes] = []
    resync_count = 0

    while True:
        prefix_index = raw_buffer.find(bytes([FRAME.PREFIX]))
        if prefix_index < 0:
            if raw_buffer:
                resync_count += len(raw_buffer)
                raw_buffer.clear()
            return ExtractedSerialFrames(frames=frames, resync_count=resync_count)

        if prefix_index > 0:
            resync_count += prefix_index
            del raw_buffer[:prefix_index]

        if len(raw_buffer) < 3:
            return ExtractedSerialFrames(frames=frames, resync_count=resync_count)

        header = raw_buffer[1]
        third_byte = raw_buffer[2]
        try:
            frame_length = serial_frame_length(header, third_byte)
        except ValueError:
            del raw_buffer[0]
            resync_count += 1
            continue

        if len(raw_buffer) < frame_length:
            return ExtractedSerialFrames(frames=frames, resync_count=resync_count)

        if raw_buffer[frame_length - 1] != FRAME.SUFFIX:
            del raw_buffer[0]
            resync_count += 1
            continue

        raw_frame = bytes(raw_buffer[:frame_length])
        del raw_buffer[:frame_length]
        if accepted is None or get_frame_type(header) in accepted:
            frames.append(raw_frame)


def extract_measurement_frames_from_buffer(
    raw_buffer: bytearray,
) -> ExtractedSerialFrames:
    """Extract complete measurement frames from a mutable byte buffer."""
    return extract_serial_frames_from_buffer(
        raw_buffer,
        accepted_frame_types={FRAME.MEASUREMENT},
    )


def contains_serial_frame(data: bytes) -> bool:
    """Return whether data contains at least one valid complete serial GSV frame."""
    buffer = bytearray(data)
    return bool(extract_serial_frames_from_buffer(buffer).frames)


def contains_response_status(
    data: bytes,
    *,
    status: int = ERROR.OK,
) -> bool:
    """Return whether data contains a response frame with the requested status."""
    buffer = bytearray(data)
    extracted = extract_serial_frames_from_buffer(
        buffer,
        accepted_frame_types={FRAME.RESPONSE},
    )
    for frame in extracted.frames:
        try:
            parsed = parse_frame(frame)
        except ValueError:
            continue
        if parsed.get("status") == status:
            return True
    return False


def read_next_serial_frame(
    transport: BaseTransport,
    *,
    timeout_s: float | None = None,
) -> bytes:
    """Read the next complete serial frame from the byte stream."""
    frame_timeout_s = (
        _get_transport_read_timeout(transport)
        if timeout_s is None
        else float(timeout_s)
    )
    deadline = time.monotonic() + frame_timeout_s

    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "No valid serial GSV frame was received before the "
                f"{frame_timeout_s:.3f} s frame-read timeout."
            )

        first_byte = read_exactly(
            transport,
            1,
            deadline=deadline,
        )[0]
        if first_byte != FRAME.PREFIX:
            continue

        header = read_exactly(
            transport,
            1,
            deadline=deadline,
        )[0]
        third_byte = read_exactly(
            transport,
            1,
            deadline=deadline,
        )[0]

        try:
            frame_length = serial_frame_length(header, third_byte)
        except ValueError:
            continue

        rest = read_exactly(
            transport,
            frame_length - 3,
            deadline=deadline,
        )
        frame = bytes([FRAME.PREFIX, header, third_byte]) + rest

        if frame[-1] != FRAME.SUFFIX:
            continue

        return frame


def parse_frame(frame: bytes) -> dict:
    """Parse a complete frame and return a structured dictionary."""
    if len(frame) < 4:
        raise ValueError("Frame is too short.")

    if frame[0] != FRAME.PREFIX:
        raise ValueError("Invalid frame prefix.")

    if frame[-1] != FRAME.SUFFIX:
        raise ValueError("Invalid frame suffix.")

    header = frame[1]
    frame_type = get_frame_type(header)

    if frame_type == FRAME.RESPONSE:
        return _parse_response_frame(frame)

    if frame_type == FRAME.MEASUREMENT:
        return parse_measurement_frame(frame)

    if frame_type == FRAME.REQUEST:
        return _parse_request_frame(frame)

    raise ValueError(f"Unsupported frame type: {frame_type}")


def _parse_request_frame(frame: bytes) -> dict:
    """Parse a serial request frame."""
    header = frame[1]
    interface = get_interface(header)
    length_field = get_length_field(header)
    command = frame[2]

    crc_len = 1 if interface == FRAME.SERIAL_WITH_CRC else 0
    payload_end = len(frame) - 1 - crc_len
    payload = frame[3:payload_end]
    crc = frame[payload_end:-1] if crc_len else b""

    return {
        "kind": "request",
        "frame_type": get_frame_type(header),
        "interface": interface,
        "length": length_field,
        "command": command,
        "payload": payload,
        "crc": crc,
        "raw": frame,
    }


def _parse_response_frame(frame: bytes) -> dict:
    """Parse a serial response frame."""
    header = frame[1]
    interface = get_interface(header)
    length_field = get_length_field(header)

    crc_len = 1 if interface == FRAME.SERIAL_WITH_CRC else 0
    payload_end = len(frame) - 1 - crc_len
    crc = frame[payload_end:-1] if crc_len else b""

    if length_field < 15:
        status_or_length = frame[2]
        payload = frame[3:payload_end]

        return {
            "kind": "response",
            "frame_type": get_frame_type(header),
            "interface": interface,
            "length": length_field,
            "status": status_or_length,
            "payload": payload,
            "crc": crc,
            "raw": frame,
        }

    extended_length = 15 + frame[2]
    payload = frame[3:payload_end]

    return {
        "kind": "response",
        "frame_type": get_frame_type(header),
        "interface": interface,
        "length": extended_length,
        "status": None,
        "payload": payload,
        "crc": crc,
        "raw": frame,
    }


def parse_measurement_frame(frame: bytes) -> dict:
    """Parse a serial measurement frame."""
    header = frame[1]
    interface = get_interface(header)
    object_count = get_length_field(header) + FRAME.MEASUREMENT_OBJECT_COUNT_OFFSET
    status = frame[2]

    if not is_serial_measurement_status(status):
        raise ValueError("Frame does not contain a serial measurement status byte.")

    datatype = get_measurement_datatype(status)
    value_size = get_measurement_value_size(status)
    crc_len = 2 if interface == FRAME.SERIAL_WITH_CRC else 0

    payload_end = len(frame) - 1 - crc_len
    payload = frame[3:payload_end]
    crc = frame[payload_end:-1] if crc_len else b""

    expected_payload_len = object_count * value_size
    if len(payload) != expected_payload_len:
        raise ValueError(
            f"Measurement payload length mismatch: expected {expected_payload_len}, got {len(payload)}."
        )

    values = decode_measurement_values(
        payload,
        datatype=datatype,
        object_count=object_count,
    )

    return {
        "kind": "measurement",
        "frame_type": get_frame_type(header),
        "interface": interface,
        "object_count": object_count,
        "status": status,
        "datatype": datatype,
        "error_bits": status & FRAME.STATUS_ERROR_MASK,
        "input_saturation": bool(status & FRAME.STATUS_INPUT_SATURATION_MASK),
        "six_axis_error": bool(status & FRAME.STATUS_SIX_AXIS_ERROR_MASK),
        "payload": payload,
        "values": values,
        "crc": crc,
        "raw": frame,
    }
