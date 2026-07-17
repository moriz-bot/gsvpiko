"""Value-error types and flag decoders for GetLastValueError (0x43).

The GSV-8 value-error entry uses a 48-bit payload:
- bits 47..45: error type
- bits 44..16: error time in minutes of device operation
- bits 15..0: type-specific error flags
"""

from __future__ import annotations

from typing import Any


class ValueErrorType(int):
    """Integer GSV value-error type with name and protocol description."""

    def __new__(cls, code: int, name: str, description: str):
        obj = int.__new__(cls, code)
        obj.name = name
        obj.description = description
        return obj

    def __str__(self) -> str:
        return self.name


NO_CURRENT_VALUE_ERROR = ValueErrorType(
    0, "NO_CURRENT_VALUE_ERROR",
    "No current or nonvolatile value error is stored in this entry.",
)
VALUE_ERROR_SATURATED = ValueErrorType(
    1, "VALUE_ERROR_SATURATED",
    "Analog sensor input saturation occurred because the input range was exceeded.",
)
VALUE_ERROR_MAX_EXCEEDED = ValueErrorType(
    2, "VALUE_ERROR_MAX_EXCEEDED",
    "The maximum allowed physical value was exceeded.",
)
VALUE_ERROR_SENSOR_BROKEN = ValueErrorType(
    3, "VALUE_ERROR_SENSOR_BROKEN",
    "Bridge sensor line break or sensor wiring fault was detected.",
)
HARDWARE_ERROR_ANALOG_OUTPUT = ValueErrorType(
    4, "HARDWARE_ERROR_ANALOG_OUTPUT",
    "An analog output fault occurred.",
)
HARDWARE_ERROR_DIGITAL_IO = ValueErrorType(
    5, "HARDWARE_ERROR_DIGITAL_IO",
    "A digital input/output short circuit or conflicting external voltage was detected.",
)

_VALUE_ERROR_TYPES_BY_CODE = {
    int(value): value
    for value in globals().values()
    if isinstance(value, ValueErrorType)
}


def value_error_type_from_code(code: int) -> ValueErrorType | None:
    """Return the value-error type object for one numeric error type."""
    return _VALUE_ERROR_TYPES_BY_CODE.get(int(code))


def value_error_type_text_from_code(code: int) -> str:
    """Return a readable fallback text for one numeric value-error type."""
    error_type = value_error_type_from_code(code)
    if error_type is None:
        return f"UNKNOWN_VALUE_ERROR_TYPE_{int(code)}"
    return f"{error_type.name}: {error_type.description}"


def decode_value_error_payload(
    payload: bytes | bytearray,
    *,
    index: int | None = None,
) -> dict[str, Any]:
    """Decode one GetLastValueError payload conservatively."""
    if len(payload) != 6:
        return {
            "decoded_error": "invalid_payload_length",
            "decoded_payload_length": len(payload),
        }

    if index == 0:
        power_on_count = int(payload[0])
        nonvolatile_count = int(payload[1])
        result: dict[str, Any] = {
            "decoded_index0_kind": "GSV-8 value-error counters",
            "decoded_power_on_error_count": power_on_count,
            "decoded_nonvolatile_error_count": nonvolatile_count,
            "decoded_summary": (
                "no value errors since power-on"
                if power_on_count == 0 else
                "value errors since power-on"
            ),
        }
        if power_on_count == 0 and nonvolatile_count == 0:
            result["decoded_error_type"] = int(NO_CURRENT_VALUE_ERROR)
            result["decoded_error_type_name"] = NO_CURRENT_VALUE_ERROR.name
            result["decoded_error_type_description"] = NO_CURRENT_VALUE_ERROR.description
        else:
            result["decoded_error_type"] = None
        return result

    raw_value = int.from_bytes(payload, byteorder="big", signed=False)
    error_type_code = (raw_value >> 45) & 0b111
    error_time_min = (raw_value >> 16) & ((1 << 29) - 1)
    error_flags = raw_value & 0xFFFF
    error_type = value_error_type_from_code(error_type_code)
    result = {
        "decoded_raw_uint48": raw_value,
        "decoded_error_type": error_type_code,
        "decoded_error_type_name": (
            error_type.name if error_type is not None else f"UNKNOWN_VALUE_ERROR_TYPE_{error_type_code}"
        ),
        "decoded_error_type_description": (
            error_type.description if error_type is not None else "Unknown value-error type."
        ),
        "decoded_error_time_min": error_time_min,
        "decoded_error_time_h": error_time_min / 60.0,
        "decoded_error_flags": error_flags,
        "decoded_error_flag_details": decode_value_error_flags(error_type_code, error_flags),
    }
    if error_type_code == int(NO_CURRENT_VALUE_ERROR) and error_time_min == 0 and error_flags == 0:
        result["decoded_summary"] = "no current error in this entry"
    else:
        result["decoded_summary"] = _summary_from_decoded_value_error(
            error_type_code=error_type_code,
            error_flags=error_flags,
        )
    return result


def decode_value_error_flags(
    error_type_code: int,
    flags: int,
) -> dict[str, Any]:
    """Decode the type-specific 16-bit value-error flags."""
    error_type_code = int(error_type_code)
    flags = int(flags) & 0xFFFF
    if error_type_code == int(NO_CURRENT_VALUE_ERROR):
        return {
            "flag_summary": "no current error flags" if flags == 0 else "unexpected flags for no-current-error entry",
        }
    if error_type_code == int(VALUE_ERROR_SATURATED):
        positive_channels = [channel for channel in range(1, 9) if flags & (1 << (channel - 1))]
        negative_channels = [channel for channel in range(1, 9) if flags & (1 << (channel + 7))]
        return {
            "positive_saturation_channels": positive_channels,
            "negative_saturation_channels": negative_channels,
            "led_hint": "FUNCTION LED continuously red; measurement-frame status byte bit 0 is set while the error is current.",
        }
    if error_type_code == int(VALUE_ERROR_MAX_EXCEEDED):
        six_axis_names = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
        six_axis_exceeded = [name for bit, name in enumerate(six_axis_names) if flags & (1 << bit)]
        pt1000_channels = [channel for channel in range(1, 9) if flags & (1 << (channel - 1)) and flags & (1 << (channel + 7))]
        return {
            "six_axis_exceeded_axes": six_axis_exceeded,
            "pt1000_out_of_range_channels": pt1000_channels,
            "pt1000_output_hint": "PT1000 output is clamped to 9999 on overrange and -9999 on underrange.",
            "led_hint": "FUNCTION LED continuously red; measurement-frame status byte bit 1 is set while the error is current.",
        }
    if error_type_code == int(VALUE_ERROR_SENSOR_BROKEN):
        broken_lines = []
        for channel in range(1, 9):
            if flags & (1 << (2 * (channel - 1))):
                broken_lines.append(f"channel_{channel}:Ud+")
            if flags & (1 << (2 * (channel - 1) + 1)):
                broken_lines.append(f"channel_{channel}:Ud-")
        return {
            "sensor_broken_lines": broken_lines,
            "led_hint": "FUNCTION LED continuously red while the error is current.",
        }
    if error_type_code == int(HARDWARE_ERROR_ANALOG_OUTPUT):
        if flags == 0xFFFF:
            return {
                "analog_output_fault": "some analog output channel had a fault",
                "led_hint": "FUNCTION LED slowly blinks red while the error is current.",
            }
        open_current_channels = [channel for channel in range(1, 9) if flags & (1 << (channel - 1))]
        overheated_driver_channels = [channel for channel in range(1, 9) if flags & (1 << (channel + 7))]
        return {
            "open_current_output_channels": open_current_channels,
            "overheated_output_driver_channels": overheated_driver_channels,
            "hardware_hint": "Driver overtemperature may be caused by a short circuit of the corresponding voltage output.",
            "led_hint": "FUNCTION LED slowly blinks red while the error is current.",
        }
    if error_type_code == int(HARDWARE_ERROR_DIGITAL_IO):
        dio_numbers = [number for number in range(1, 17) if flags & (1 << (number - 1))]
        return {
            "short_circuit_dio_numbers": dio_numbers,
            "led_hint": "FUNCTION LED quickly blinks red while the error is current.",
        }
    return {
        "flag_summary": f"unknown value-error type {error_type_code} with flags 0x{flags:04X}",
    }


def compact_value_error_details(decoded: dict[str, Any]) -> str:
    """Return compact flag details for one decoded value-error entry."""
    details = decoded.get("decoded_error_flag_details")
    if not isinstance(details, dict):
        return ""

    parts = []
    for key, value in details.items():
        if value in (None, [], ""):
            continue
        parts.append(f"{key}={value}")
    return "; ".join(parts)


def _summary_from_decoded_value_error(
    *,
    error_type_code: int,
    error_flags: int,
) -> str:
    """Return a compact summary for one decoded value-error entry."""
    error_type = value_error_type_from_code(error_type_code)
    if error_type is None:
        return f"unknown value error type {error_type_code} with flags 0x{error_flags:04X}"
    if error_flags == 0:
        return f"{error_type.name} without type-specific flags"
    return f"{error_type.name} with flags 0x{error_flags:04X}"
