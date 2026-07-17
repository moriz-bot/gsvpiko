"""Probe GSV analogue-filter write payload formats.

The app tests several plausible payload encodings for WRITE_ANALOG_FILTER (0x91),
reads the active analogue filter after each attempt, prints the result, and
stores a CSV plus a Markdown summary in the project docs directory.

The scan writes device settings. It tries to restore the initial analogue filter
at the end if a working payload format is found.
"""

from __future__ import annotations

import csv
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Callable

from ..config.config_devices import DEFAULT_DEVICE
from ..constants import constants_analog_filters as ANALOG_FILTER
from ..constants import constants_commands as COMMAND
from ..constants import constants_errors as ERROR
from ..device.device_gsv import GsvDevice
from ..protocol import protocol_error_text
from ..transport.transport_serial import SerialTransport
from ..utils.utils_hex import to_hex


READ_BACK_DELAY_S = 0.10

TEST_FILTERS = [
    ("low", 28),
    ("medium", 850),
    ("high", 11700),
]

FILTER_ENUM_ZERO_BASED = {
    28: 0,
    850: 1,
    11700: 2,
}

FILTER_ENUM_ONE_BASED = {
    28: 1,
    850: 2,
    11700: 3,
}


@dataclass
class AnalogFilterProbeResult:
    """One analogue-filter write attempt and the device response."""

    index: int
    filter_name: str
    requested_analog_filter_hz: int
    payload_format: str
    payload_hex: str
    request_raw_hex: str
    response_raw_hex: str
    response_status: int | None
    response_status_text: str
    write_accepted: bool
    active_analog_filter_hz: int | None
    matches_request: bool
    error: str


ANALOG_FILTER_PROBE_TRANSPORT_TIMEOUT_S = 1.0


def pack_no_payload(_: int) -> bytes:
    """Return an empty payload."""
    return b""


def pack_uint8_enum_zero_based(value_hz: int) -> bytes:
    """Encode low/medium/high as enum values 0/1/2."""
    return struct.pack(">B", FILTER_ENUM_ZERO_BASED[value_hz])


def pack_uint8_enum_one_based(value_hz: int) -> bytes:
    """Encode low/medium/high as enum values 1/2/3."""
    return struct.pack(">B", FILTER_ENUM_ONE_BASED[value_hz])


def pack_uint16_be(value_hz: int) -> bytes:
    """Encode the frequency as big-endian uint16."""
    return struct.pack(">H", value_hz)


def pack_uint16_le(value_hz: int) -> bytes:
    """Encode the frequency as little-endian uint16."""
    return struct.pack("<H", value_hz)


def pack_uint32_be(value_hz: int) -> bytes:
    """Encode the frequency as big-endian uint32."""
    return struct.pack(">I", value_hz)


def pack_uint32_le(value_hz: int) -> bytes:
    """Encode the frequency as little-endian uint32."""
    return struct.pack("<I", value_hz)


def pack_float32_be(value_hz: int) -> bytes:
    """Encode the frequency as big-endian float32."""
    return struct.pack(">f", float(value_hz))


def pack_float32_le(value_hz: int) -> bytes:
    """Encode the frequency as little-endian float32."""
    return struct.pack("<f", float(value_hz))


def pack_channel0_float32_be(value_hz: int) -> bytes:
    """Encode channel 0 followed by a big-endian float32 frequency."""
    return struct.pack(">Bf", 0, float(value_hz))


def pack_channel1_float32_be(value_hz: int) -> bytes:
    """Encode channel 1 followed by a big-endian float32 frequency."""
    return struct.pack(">Bf", 1, float(value_hz))


def pack_channel0_uint16_be(value_hz: int) -> bytes:
    """Encode channel 0 followed by a big-endian uint16 frequency."""
    return struct.pack(">BH", 0, value_hz)


def pack_channel1_uint16_be(value_hz: int) -> bytes:
    """Encode channel 1 followed by a big-endian uint16 frequency."""
    return struct.pack(">BH", 1, value_hz)


PAYLOAD_FORMATS: list[tuple[str, Callable[[int], bytes]]] = [
    ("no_payload", pack_no_payload),
    ("uint8_enum_zero_based", pack_uint8_enum_zero_based),
    ("uint8_enum_one_based", pack_uint8_enum_one_based),
    ("uint16_be_hz", pack_uint16_be),
    ("uint16_le_hz", pack_uint16_le),
    ("uint32_be_hz", pack_uint32_be),
    ("uint32_le_hz", pack_uint32_le),
    ("float32_be_hz", pack_float32_be),
    ("float32_le_hz", pack_float32_le),
    ("channel0_float32_be_hz", pack_channel0_float32_be),
    ("channel1_float32_be_hz", pack_channel1_float32_be),
    ("channel0_uint16_be_hz", pack_channel0_uint16_be),
    ("channel1_uint16_be_hz", pack_channel1_uint16_be),
]


def find_project_root() -> Path:
    """Return the project root for a src/gsvpiko/app module layout."""
    return Path(__file__).resolve().parents[3]


def build_output_paths(project_root: Path) -> tuple[Path, Path]:
    """Create timestamped CSV and Markdown output paths."""
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = docs_dir / f"analog_filter_probe_{timestamp}.csv"
    markdown_path = docs_dir / f"analog_filter_probe_{timestamp}.md"

    return csv_path, markdown_path


def read_active_analog_filter(device: GsvDevice) -> tuple[int | None, str]:
    """Read and normalize the active analogue filter."""
    try:
        response = device.filters.read_analog_filter()
        active_filter_hz = ANALOG_FILTER.normalize_analog_filter(
            response["analog_filter_hz"]
        )
        return active_filter_hz, ""
    except Exception as error:
        return None, str(error)


def status_text(status: int | None) -> str:
    """Return a readable status text for one response status byte."""
    if status is None:
        return "<no response status>"

    return protocol_error_text.get_error_text(status)


def is_success_status(status: int | None) -> bool:
    """Return whether one status byte represents a successful response."""
    return status in (ERROR.OK, ERROR.OK_CHANGED)


def request_write_analog_filter(
    device: GsvDevice,
    *,
    payload: bytes,
) -> tuple[dict | None, str]:
    """Send WRITE_ANALOG_FILTER without raising on non-OK status codes."""
    try:
        response = device.request(
            COMMAND.WRITE_ANALOG_FILTER,
            payload,
        )
        return response, ""
    except Exception as error:
        return None, str(error)


def probe_one_payload(
    device: GsvDevice,
    *,
    index: int,
    filter_name: str,
    requested_analog_filter_hz: int,
    payload_format: str,
    payload_builder: Callable[[int], bytes],
) -> AnalogFilterProbeResult:
    """Run one analogue-filter write attempt and read the active value after it."""
    error_parts = []

    payload = payload_builder(requested_analog_filter_hz)
    payload_hex = to_hex(payload)

    response, write_error = request_write_analog_filter(
        device,
        payload=payload,
    )

    if write_error:
        error_parts.append(f"write_error={write_error}")

    response_status = None
    request_raw_hex = ""
    response_raw_hex = ""

    if response is not None:
        response_status = response.get("status")
        request_raw_hex = response.get("request_raw_hex", "")
        response_raw_hex = response.get("raw_hex", "")

    if response_status is not None and not is_success_status(response_status):
        error_parts.append(
            f"response_status=0x{response_status:02X} {status_text(response_status)}"
        )

    sleep(READ_BACK_DELAY_S)

    active_analog_filter_hz, read_error = read_active_analog_filter(device)
    if read_error:
        error_parts.append(f"read_error={read_error}")

    matches_request = active_analog_filter_hz == requested_analog_filter_hz
    write_accepted = is_success_status(response_status)

    return AnalogFilterProbeResult(
        index=index,
        filter_name=filter_name,
        requested_analog_filter_hz=requested_analog_filter_hz,
        payload_format=payload_format,
        payload_hex=payload_hex,
        request_raw_hex=request_raw_hex,
        response_raw_hex=response_raw_hex,
        response_status=response_status,
        response_status_text=status_text(response_status),
        write_accepted=write_accepted,
        active_analog_filter_hz=active_analog_filter_hz,
        matches_request=matches_request,
        error="; ".join(error_parts),
    )


def print_result(result: AnalogFilterProbeResult) -> None:
    """Print one probe result line."""
    status_hex = (
        f"0x{result.response_status:02X}"
        if result.response_status is not None
        else "<none>"
    )

    print(
        f"{result.index:03d} "
        f"{result.filter_name:<6} "
        f"requested={result.requested_analog_filter_hz:<5} "
        f"format={result.payload_format:<24} "
        f"payload={result.payload_hex:<20} "
        f"status={status_hex:<6} "
        f"accepted={result.write_accepted!s:<5} "
        f"active={result.active_analog_filter_hz} "
        f"match={result.matches_request}"
    )

    if result.error:
        print(f"    {result.error}")


def write_csv(
    csv_path: Path,
    results: list[AnalogFilterProbeResult],
) -> None:
    """Write the full probe result table as CSV."""
    fieldnames = [
        "index",
        "filter_name",
        "requested_analog_filter_hz",
        "payload_format",
        "payload_hex",
        "request_raw_hex",
        "response_raw_hex",
        "response_status",
        "response_status_text",
        "write_accepted",
        "active_analog_filter_hz",
        "matches_request",
        "error",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow(
                {
                    "index": result.index,
                    "filter_name": result.filter_name,
                    "requested_analog_filter_hz": result.requested_analog_filter_hz,
                    "payload_format": result.payload_format,
                    "payload_hex": result.payload_hex,
                    "request_raw_hex": result.request_raw_hex,
                    "response_raw_hex": result.response_raw_hex,
                    "response_status": result.response_status,
                    "response_status_text": result.response_status_text,
                    "write_accepted": result.write_accepted,
                    "active_analog_filter_hz": result.active_analog_filter_hz,
                    "matches_request": result.matches_request,
                    "error": result.error,
                }
            )


def write_markdown_summary(
    markdown_path: Path,
    *,
    csv_path: Path,
    initial_analog_filter_hz: int | None,
    restored_analog_filter_hz: int | None,
    results: list[AnalogFilterProbeResult],
) -> None:
    """Write a compact Markdown summary of the probe."""
    successful_matches = [
        result for result in results
        if result.write_accepted and result.matches_request
    ]
    accepted_without_match = [
        result for result in results
        if result.write_accepted and not result.matches_request
    ]

    lines = []
    lines.append("# GSVpiko Analogue Filter Probe")
    lines.append("")
    lines.append(f"- CSV file: `{csv_path.name}`")
    lines.append(f"- Initial active analogue filter: `{initial_analog_filter_hz}` Hz")
    lines.append(f"- Restored active analogue filter: `{restored_analog_filter_hz}` Hz")
    lines.append(f"- Tested write attempts: `{len(results)}`")
    lines.append(f"- Successful matching writes: `{len(successful_matches)}`")
    lines.append(f"- Accepted writes without matching read-back: `{len(accepted_without_match)}`")
    lines.append("")
    lines.append("## Successful matching payload formats")
    lines.append("")

    if successful_matches:
        lines.append("| Filter | Requested Hz | Payload format | Payload hex | Request hex | Response hex |")
        lines.append("|---|---:|---|---|---|---|")
        for result in successful_matches:
            lines.append(
                "| "
                f"{result.filter_name} | "
                f"{result.requested_analog_filter_hz} | "
                f"{result.payload_format} | "
                f"`{result.payload_hex}` | "
                f"`{result.request_raw_hex}` | "
                f"`{result.response_raw_hex}` |"
            )
    else:
        lines.append("- No payload format both returned OK and read back the requested filter.")

    lines.append("")
    lines.append("## All write attempts")
    lines.append("")
    lines.append(
        "| # | Filter | Requested Hz | Format | Payload | Status | Accepted | Active Hz | Match | Error |"
    )
    lines.append("|---:|---|---:|---|---|---|:---:|---:|:---:|---|")

    for result in results:
        status_hex = (
            f"0x{result.response_status:02X}"
            if result.response_status is not None
            else ""
        )
        error_text = result.error.replace("|", "\\|")
        lines.append(
            "| "
            f"{result.index} | "
            f"{result.filter_name} | "
            f"{result.requested_analog_filter_hz} | "
            f"{result.payload_format} | "
            f"`{result.payload_hex}` | "
            f"{status_hex} {result.response_status_text} | "
            f"{result.write_accepted} | "
            f"{result.active_analog_filter_hz} | "
            f"{result.matches_request} | "
            f"{error_text} |"
        )

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def restore_initial_filter(
    device: GsvDevice,
    *,
    initial_analog_filter_hz: int | None,
    results: list[AnalogFilterProbeResult],
) -> int | None:
    """Try to restore the initial analogue filter using known successful formats."""
    if initial_analog_filter_hz is None:
        return None

    successful_formats = []
    seen_formats = set()

    for result in results:
        if not result.write_accepted:
            continue

        if result.payload_format in seen_formats:
            continue

        seen_formats.add(result.payload_format)
        successful_formats.append(result.payload_format)

    format_lookup = dict(PAYLOAD_FORMATS)

    for payload_format in successful_formats:
        payload = format_lookup[payload_format](initial_analog_filter_hz)
        response, _ = request_write_analog_filter(
            device,
            payload=payload,
        )

        if response is None or not is_success_status(response.get("status")):
            continue

        sleep(READ_BACK_DELAY_S)
        active_filter_hz, _ = read_active_analog_filter(device)
        if active_filter_hz == initial_analog_filter_hz:
            return active_filter_hz

    active_filter_hz, _ = read_active_analog_filter(device)
    return active_filter_hz


def main() -> None:
    project_root = find_project_root()
    csv_path, markdown_path = build_output_paths(project_root)

    transport = SerialTransport(
        port=str(DEFAULT_DEVICE["com_port"]),
        baudrate=int(DEFAULT_DEVICE["default_baudrate"]),
        timeout=ANALOG_FILTER_PROBE_TRANSPORT_TIMEOUT_S,
    )
    device = GsvDevice(
        transport,
        name="GSV1",
    )

    print("Opening device...")
    device.open()
    print("Device opened.")
    print()

    initial_analog_filter_hz = None
    restored_analog_filter_hz = None
    results = []

    try:
        device.clear_input_buffer()
        device.acquisition.stop_transmission()
        device.clear_input_buffer()

        initial_analog_filter_hz, initial_read_error = read_active_analog_filter(device)
        if initial_read_error:
            print(f"Initial analogue filter could not be read: {initial_read_error}")
        else:
            print(f"Initial active analogue filter: {initial_analog_filter_hz} Hz")

        print()

        index = 0
        for filter_name, requested_analog_filter_hz in TEST_FILTERS:
            for payload_format, payload_builder in PAYLOAD_FORMATS:
                index += 1
                result = probe_one_payload(
                    device,
                    index=index,
                    filter_name=filter_name,
                    requested_analog_filter_hz=requested_analog_filter_hz,
                    payload_format=payload_format,
                    payload_builder=payload_builder,
                )
                results.append(result)
                print_result(result)

    finally:
        print()
        print("Restoring initial analogue filter...")
        try:
            restored_analog_filter_hz = restore_initial_filter(
                device,
                initial_analog_filter_hz=initial_analog_filter_hz,
                results=results,
            )
            print(f"Active analogue filter after restore attempt: {restored_analog_filter_hz} Hz")
        except Exception as error:
            print(f"Restoring initial analogue filter failed: {error}")

        print()
        print("Stopping transmission...")
        try:
            stop_response = device.acquisition.stop_transmission()
            print(f"StopTransmission response: {stop_response['raw_hex']}")
        except Exception as error:
            print(f"StopTransmission failed: {error}")

        device.close()
        print("Device closed.")

    if results:
        write_csv(
            csv_path=csv_path,
            results=results,
        )
        write_markdown_summary(
            markdown_path=markdown_path,
            csv_path=csv_path,
            initial_analog_filter_hz=initial_analog_filter_hz,
            restored_analog_filter_hz=restored_analog_filter_hz,
            results=results,
        )

        print()
        print(f"CSV written to: {csv_path}")
        print(f"Markdown summary written to: {markdown_path}")


if __name__ == "__main__":
    main()
