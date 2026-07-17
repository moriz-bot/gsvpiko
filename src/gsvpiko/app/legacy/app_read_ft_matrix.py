"""Read the active GSV F/T sensor calibration matrix from setup devices.

The app only reads calibration data. It does not write calibration data, does not
store sensor calibration data, and does not activate a sensor-calculation mode.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Any, Iterable

from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..protocol.protocol_payload_codec import (
    pack_uint8,
    pack_uint8_uint8,
    unpack_float32_payload,
    unpack_uint32_payload,
)
from ..utils.utils_hex import to_hex
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

COMMAND_GET_FT_SENSOR_CAL_ARR_NO = 0x54
COMMAND_READ_FT_SENSOR_CAL = 0x47
COMMAND_PREP_READ_FT_SENSOR = 0x7D

FT_TYPE_SERIAL_NUMBER = 0
FT_TYPE_MATRIX_SCALING_FACTOR = 1
FT_TYPE_MATRIX_A = 2
FT_TYPE_GEOMETRICAL_OFFSETS = 3
FT_TYPE_MAXIMUM_VALUES = 4
FT_TYPE_INPUT_SENSITIVITY = 5
FT_TYPE_ZERO_VALUES = 6
FT_TYPE_SENSOR_TYPE = 7
FT_TYPE_MATRIX_B = 8
FT_TYPE_INPUT_FACTOR_1_INDICES = 9
FT_TYPE_INPUT_FACTOR_2_INDICES = 10
FT_TYPE_UNIT_ENUM = 11
FT_TYPE_CALIBRATION_DATE = 12

MATRIX_LENGTH = 36
MATRIX_SIDE = 6

SETUP_KEY = DEFAULT_SETUP_KEY


@dataclass(frozen=True)
class FtCalEntry:
    """One decoded ReadFTSensorCal result or read error."""

    type_id: int
    index: int
    ok: bool
    raw_hex: str | None = None
    value_float32: float | None = None
    value_uint32: int | None = None
    error: str | None = None


def main() -> None:
    """Read F/T calibration data from all devices of one setup."""
    args = _parse_args()
    setup_config = get_setup_config(args.setup)
    resolved_setup = resolve_setup(setup_config)

    title = "F/T sensor calibration matrix readout"
    print(title)
    print("-" * len(title))
    print(f"setup_name: {resolved_setup.name}")
    print(f"connection_type: {resolved_setup.connection_type}")
    print(f"baudrate: {resolved_setup.baudrate}")
    print(f"requested_array_index: {_format_optional_int(args.array_index)}")
    print(f"read_full: {args.full}")
    print()

    for device_entry, resolved_device in zip(
        setup_config["attached_devices"],
        resolved_setup.devices,
    ):
        heading = f"{resolved_device.alias} = {device_entry['device']['name']}"
        print(heading)
        print("-" * len(heading))
        device = None

        try:
            device_config = _build_device_config_for_setup(
                device_entry["device"],
                resolved_setup=resolved_setup,
            )
            device = open_gsv_device_from_config(
                device_config,
                timeout_s=args.timeout_s,
                auto_probe_baudrate=not args.no_auto_probe,
                on_probe_result=None,
            )
            device.clear_input_buffer()

            array_info = _read_array_info(device)
            _print_array_info(array_info)

            selected_index = _select_array_index(
                device,
                requested_index=args.array_index,
                array_info=array_info,
            )
            print(f"selected_array_index_for_reading: {selected_index}")
            print()

            report = _read_ft_report(device, full=args.full)
            _print_ft_report(report, full=args.full)

        except DeviceConnectionError as error:
            print("opening_failed: True")
            print(f"error: {error}")
        except Exception as error:
            print("read_failed: True")
            print(f"error: {type(error).__name__}: {error}")
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
        print()


def _parse_args() -> argparse.Namespace:
    """Return command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read the current F/T sensor calibration data from setup devices. "
            "This app performs read commands only."
        )
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    parser.add_argument(
        "--array-index",
        type=int,
        default=None,
        help=(
            "F/T calibration structure index to select with PrepReadFTsensor. "
            "By default the device's active index is used when available."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also read offsets, maximums, zero values, units, date, and Matrix B.",
    )
    parser.add_argument(
        "--no-auto-probe",
        action="store_true",
        help="Use only the configured baudrate instead of probing alternative GSV baudrates.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=None,
        help="Optional transport timeout in seconds.",
    )
    args = parser.parse_args()

    if args.array_index is not None and args.array_index < 0:
        parser.error("--array-index must not be negative.")
    if args.timeout_s is not None and args.timeout_s <= 0:
        parser.error("--timeout-s must be positive.")
    return args


def _build_device_config_for_setup(
    device_config: dict[str, Any],
    *,
    resolved_setup,
) -> dict[str, Any]:
    """Return a device config copy with setup-level connection overrides."""
    result = dict(device_config)
    result["default_connection_type"] = resolved_setup.connection_type
    result["default_serial_interface"] = resolved_setup.serial_interface
    result["default_use_nport"] = resolved_setup.use_nport
    result["default_configure_nport"] = resolved_setup.configure_nport
    result["default_baudrate"] = resolved_setup.baudrate
    return result


def _read_array_info(device) -> dict[str, Any]:
    """Read GetFTSensorCalArrNo (0x54)."""
    try:
        response = device.request_ok(COMMAND_GET_FT_SENSOR_CAL_ARR_NO)
    except Exception as error:
        return {"ok": False, "error": str(error)}

    payload = response["payload"]
    result = {
        "ok": True,
        "payload_hex": to_hex(payload),
        "payload_length": len(payload),
    }
    if len(payload) >= 3:
        result.update(
            {
                "maximum_struct_count": payload[0],
                "stored_struct_count": payload[1],
                "active_struct_index": payload[2],
            }
        )
    else:
        result["error"] = f"Expected at least 3 payload bytes, received {len(payload)}."
    return result


def _print_array_info(array_info: dict[str, Any]) -> None:
    """Print GetFTSensorCalArrNo information."""
    print("ft_sensor_cal_structs:")
    if not array_info.get("ok"):
        print(f"  ok: False")
        print(f"  error: {array_info.get('error')}")
        return

    print("  ok: True")
    print(f"  payload_hex: {array_info.get('payload_hex')}")
    print(
        "  maximum_struct_count: "
        f"{_format_optional_int(array_info.get('maximum_struct_count'))}"
    )
    print(
        "  stored_struct_count: "
        f"{_format_optional_int(array_info.get('stored_struct_count'))}"
    )
    print(
        "  active_struct_index: "
        f"{_format_optional_int(array_info.get('active_struct_index'))}"
    )
    if array_info.get("error"):
        print(f"  warning: {array_info['error']}")


def _select_array_index(
    device,
    *,
    requested_index: int | None,
    array_info: dict[str, Any],
) -> int | None:
    """Select a calibration struct for subsequent ReadFTSensorCal calls."""
    selected_index = requested_index
    if selected_index is None and array_info.get("ok"):
        active_index = array_info.get("active_struct_index")
        if active_index is not None:
            selected_index = int(active_index)

    if selected_index is None:
        return None

    device.request_ok(COMMAND_PREP_READ_FT_SENSOR, pack_uint8(selected_index))
    return selected_index


def _read_ft_report(device, *, full: bool) -> dict[str, Any]:
    """Read the requested FT calibration values."""
    report: dict[str, Any] = {}
    report["serial_number"] = _read_entry(device, FT_TYPE_SERIAL_NUMBER, 0)
    report["matrix_scaling_factor"] = _read_entry(
        device,
        FT_TYPE_MATRIX_SCALING_FACTOR,
        0,
    )
    report["sensor_type"] = _read_entry(device, FT_TYPE_SENSOR_TYPE, 0)
    report["input_sensitivity"] = _read_entry(device, FT_TYPE_INPUT_SENSITIVITY, 0)
    report["matrix_a"] = [
        _read_entry(device, FT_TYPE_MATRIX_A, index)
        for index in range(MATRIX_LENGTH)
    ]

    if full:
        report["geometrical_offsets"] = [
            _read_entry(device, FT_TYPE_GEOMETRICAL_OFFSETS, index)
            for index in range(3)
        ]
        report["maximum_values"] = [
            _read_entry(device, FT_TYPE_MAXIMUM_VALUES, index)
            for index in range(6)
        ]
        report["zero_values"] = [
            _read_entry(device, FT_TYPE_ZERO_VALUES, index)
            for index in range(6)
        ]
        report["matrix_b"] = [
            _read_entry(device, FT_TYPE_MATRIX_B, index)
            for index in range(MATRIX_LENGTH)
        ]
        report["input_factor_1_indices"] = [
            _read_entry(device, FT_TYPE_INPUT_FACTOR_1_INDICES, index)
            for index in range(MATRIX_LENGTH)
        ]
        report["input_factor_2_indices"] = [
            _read_entry(device, FT_TYPE_INPUT_FACTOR_2_INDICES, index)
            for index in range(MATRIX_LENGTH)
        ]
        report["unit_enum"] = [
            _read_entry(device, FT_TYPE_UNIT_ENUM, index)
            for index in range(6)
        ]
        report["calibration_date"] = [
            _read_entry(device, FT_TYPE_CALIBRATION_DATE, index)
            for index in range(3)
        ]

    return report


def _read_entry(device, type_id: int, index: int) -> FtCalEntry:
    """Read one ReadFTSensorCal entry and decode conservative numeric views."""
    try:
        response = device.request_ok(
            COMMAND_READ_FT_SENSOR_CAL,
            pack_uint8_uint8(type_id, index),
        )
    except Exception as error:
        return FtCalEntry(
            type_id=type_id,
            index=index,
            ok=False,
            error=str(error),
        )

    payload = response["payload"]
    raw_hex = to_hex(payload)
    value_float32 = None
    value_uint32 = None
    if len(payload) == 4:
        value_uint32 = unpack_uint32_payload(payload)
        value_float32 = unpack_float32_payload(payload)

    return FtCalEntry(
        type_id=type_id,
        index=index,
        ok=True,
        raw_hex=raw_hex,
        value_float32=value_float32,
        value_uint32=value_uint32,
    )


def _print_ft_report(report: dict[str, Any], *, full: bool) -> None:
    """Print the FT calibration report."""
    print("metadata:")
    _print_scalar_entry("  serial_number", report["serial_number"], prefer_uint32=True)
    _print_scalar_entry("  matrix_scaling_factor", report["matrix_scaling_factor"])
    _print_scalar_entry("  sensor_type", report["sensor_type"], show_both=True)
    _print_scalar_entry("  input_sensitivity", report["input_sensitivity"])
    print()

    print("matrix_a_6x6_float32:")
    _print_matrix(report["matrix_a"])
    print()

    print("matrix_a_upper_left_3x3_float32:")
    _print_matrix(report["matrix_a"], rows=3, columns=3)

    if not full:
        return

    print()
    print("geometrical_offsets_float32:")
    _print_vector(report["geometrical_offsets"])
    print("maximum_values_float32:")
    _print_vector(report["maximum_values"])
    print("zero_values_float32:")
    _print_vector(report["zero_values"])
    print("unit_enum:")
    _print_vector(report["unit_enum"], show_both=True)
    print("calibration_date:")
    _print_vector(report["calibration_date"], show_both=True)
    print("matrix_b_6x6_float32:")
    _print_matrix(report["matrix_b"])
    print("input_factor_1_indices:")
    _print_vector(report["input_factor_1_indices"], show_both=True)
    print("input_factor_2_indices:")
    _print_vector(report["input_factor_2_indices"], show_both=True)


def _print_scalar_entry(
    label: str,
    entry: FtCalEntry,
    *,
    prefer_uint32: bool = False,
    show_both: bool = False,
) -> None:
    """Print one scalar FT calibration entry."""
    print(f"{label}: {_format_entry(entry, prefer_uint32=prefer_uint32, show_both=show_both)}")


def _print_matrix(
    entries: list[FtCalEntry],
    *,
    rows: int = MATRIX_SIDE,
    columns: int = MATRIX_SIDE,
) -> None:
    """Print a matrix from row-wise FT calibration entries."""
    for row in range(rows):
        cells = []
        for column in range(columns):
            entry = entries[row * MATRIX_SIDE + column]
            cells.append(_format_entry(entry, width=14))
        print("  " + " ".join(cells))


def _print_vector(
    entries: Iterable[FtCalEntry],
    *,
    show_both: bool = False,
) -> None:
    """Print one vector of FT calibration entries."""
    values = [
        _format_entry(entry, show_both=show_both)
        for entry in entries
    ]
    print("  [" + ", ".join(values) + "]")


def _format_entry(
    entry: FtCalEntry,
    *,
    prefer_uint32: bool = False,
    show_both: bool = False,
    width: int | None = None,
) -> str:
    """Format one decoded entry."""
    if not entry.ok:
        text = f"ERR({entry.error})"
    elif show_both:
        text = (
            f"float={_format_float(entry.value_float32)}, "
            f"uint32={_format_optional_int(entry.value_uint32)}, "
            f"raw={entry.raw_hex}"
        )
    elif prefer_uint32:
        text = str(entry.value_uint32) if entry.value_uint32 is not None else "<none>"
    else:
        text = _format_float(entry.value_float32)

    if width is None:
        return text
    return f"{text:>{width}}"


def _format_float(value: float | None) -> str:
    """Format one float while keeping diagnostic special values visible."""
    if value is None:
        return "<none>"
    if math.isnan(value) or math.isinf(value):
        return str(value)
    return f"{value:.9g}"


def _format_optional_int(value: int | None) -> str:
    """Format an optional integer."""
    return str(value) if value is not None else "<none>"


if __name__ == "__main__":
    main()
