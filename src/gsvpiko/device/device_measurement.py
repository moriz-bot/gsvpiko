"""Helpers for normalized measurement records."""

from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device_gsv import GsvDevice


def create_measurement_record(
    frame: dict,
    device: "GsvDevice",
) -> dict:
    """Convert one parsed measurement frame into a normalized record."""
    if frame["kind"] != "measurement":
        raise TypeError("Expected a measurement frame.")

    values = list(frame["values"])
    channels = device.channels.build_channel_map(values)

    return {
        "timestamp_unix_s": time(),
        "device_name": device.name,
        "values": values,
        "channels": channels,
        "object_count": frame["object_count"],
        "datatype": frame["datatype"],
        "input_saturation": frame["input_saturation"],
        "six_axis_error": frame["six_axis_error"],
        "raw_hex": frame.get("raw_hex"),
    }


def format_measurement_record(record: dict) -> str:
    """Return a readable one-block text representation of a measurement record."""
    channel_parts = [
        f"{channel_name}={channel_value}"
        for channel_name, channel_value in record["channels"].items()
    ]

    lines = [
        f"device_name: {record['device_name']}",
        f"timestamp_unix_s: {record['timestamp_unix_s']:.6f}",
        f"values: {record['values']}",
        f"channels: {', '.join(channel_parts)}",
        f"input_saturation: {record['input_saturation']}",
        f"six_axis_error: {record['six_axis_error']}",
    ]

    if record.get("raw_hex"):
        lines.append(f"raw: {record['raw_hex']}")

    return "\n".join(lines)
