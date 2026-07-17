"""Sample-rate throughput checks for setup coordination.

The early check estimates whether a requested GSV output sample/frame rate is
plausible for the selected serial frame layout. It does not query a device. The
final decision is made later by writing the sample rate to the GSV and reading
the active value back.
"""

from __future__ import annotations

from math import isclose

from ..constants import constants_datatypes as DATATYPE

SERIAL_FRAME_OVERHEAD_BYTES_WITHOUT_CRC = 4
SERIAL_CRC_BYTES = 2
SERIAL_BITS_PER_BYTE_8N1 = 10


def calculate_serial_measurement_frame_bytes(
    *,
    streamed_value_count: int,
    datatype: int | str,
    crc_enabled: bool = False,
) -> int:
    """Return bytes per normal serial measurement frame."""
    normalized_datatype = DATATYPE.normalize_datatype(datatype)
    value_bytes = DATATYPE.get_value_byte_count(normalized_datatype)
    crc_bytes = SERIAL_CRC_BYTES if crc_enabled else 0

    return (
        SERIAL_FRAME_OVERHEAD_BYTES_WITHOUT_CRC
        + int(streamed_value_count) * value_bytes
        + crc_bytes
    )


def estimate_serial_sample_rate_limit_hz(
    *,
    baudrate: int,
    streamed_value_count: int,
    datatype: int | str,
    crc_enabled: bool = False,
    bits_per_byte: int = SERIAL_BITS_PER_BYTE_8N1,
) -> float:
    """Estimate the serial throughput limit in frames per second."""
    frame_bytes = calculate_serial_measurement_frame_bytes(
        streamed_value_count=streamed_value_count,
        datatype=datatype,
        crc_enabled=crc_enabled,
    )
    return float(baudrate) / (float(bits_per_byte) * float(frame_bytes))


def check_sample_rate_limit(
    *,
    requested_sample_rate_hz: float,
    baudrate: int,
    streamed_value_count: int,
    datatype: int | str,
    crc_enabled: bool = False,
) -> dict:
    """Return an early sample-rate plausibility report."""
    normalized_datatype = DATATYPE.normalize_datatype(datatype)
    estimated_limit = estimate_serial_sample_rate_limit_hz(
        baudrate=baudrate,
        streamed_value_count=streamed_value_count,
        datatype=normalized_datatype,
        crc_enabled=crc_enabled,
    )
    frame_bytes = calculate_serial_measurement_frame_bytes(
        streamed_value_count=streamed_value_count,
        datatype=normalized_datatype,
        crc_enabled=crc_enabled,
    )
    request_plausible = float(requested_sample_rate_hz) <= estimated_limit

    return {
        "request_plausible": request_plausible,
        "warning_key": None if request_plausible else "SAMPLE_RATE_LIMIT_EXCEEDED",
        "requested_sample_rate_hz": float(requested_sample_rate_hz),
        "estimated_serial_limit_hz": estimated_limit,
        "baudrate": int(baudrate),
        "streamed_value_count": int(streamed_value_count),
        "datatype": normalized_datatype,
        "datatype_name": DATATYPE.get_name(normalized_datatype),
        "crc_enabled": bool(crc_enabled),
        "frame_bytes": frame_bytes,
    }


def check_sample_rate_readback(
    *,
    requested_sample_rate_hz: float,
    active_sample_rate_hz: float,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-3,
) -> dict:
    """Return the final write/readback sample-rate check."""
    requested = float(requested_sample_rate_hz)
    active = float(active_sample_rate_hz)
    matches = isclose(
        active,
        requested,
        rel_tol=rel_tol,
        abs_tol=abs_tol,
    )

    return {
        "sample_rate_matches_request": matches,
        "warning_key": None if matches else "SAMPLE_RATE_ADJUSTED_BY_DEVICE",
        "requested_sample_rate_hz": requested,
        "active_sample_rate_hz": active,
        "sample_rate_difference_hz": active - requested,
    }


class _SafeFormatDict(dict):
    """Dictionary that keeps unknown placeholders visible in formatted text."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_warning_line(text: str, context: dict | None) -> str:
    """Format one warning line while preserving unknown placeholders."""
    if context is None:
        return text
    return text.format_map(_SafeFormatDict(context))


def format_sample_rate_limit_warning(report: dict) -> str:
    """Return the early sample-rate-limit warning for terminal output."""
    title = "Sample rate probably too high"
    lines = [
        title,
        "-" * len(title),
        (
            "The requested sample rate is above the calculated serial throughput "
            "limit. This early check is a plausibility check; the final decision is "
            "made by writing to the GSV and reading the active value back."
        ),
        "",
    ]
    details = [
        "Requested: {requested_sample_rate_hz:g} Hz",
        "Estimated limit: {estimated_serial_limit_hz:.1f} Hz",
        "Streamed values per frame: {streamed_value_count}",
        "Datatype: {datatype_name}",
        "Baudrate: {baudrate}",
        "CRC enabled: {crc_enabled}",
    ]
    lines.extend(f"- {_format_warning_line(entry, report)}" for entry in details)
    lines.extend(
        [
            "",
            "Limiting factors",
            "- baudrate / serial throughput",
            "- number of transmitted measurement values",
            "- datatype",
            "- CRC",
            "- communication interface, such as UART, Ethernet, RS422, or CANopen",
            "- digital FIR/IIR filters",
            "- analogue filter and automatic filter settings",
            "- trigger, threshold, and additional firmware functions",
            "",
            "Possible options",
            "- Store a higher baudrate and activate it after a power cycle.",
            "- Transmit fewer measurement values per frame.",
            "- Use a more compact datatype, such as int24 or int16.",
            "- Use a faster communication interface when available.",
            "- Keep CRC disabled if CRC transmission is not required.",
        ]
    )
    return "\n".join(lines)
