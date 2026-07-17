"""Probe sample-rate write/readback behavior for selected frame layouts."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from ..config import config_devices as DEVICE
from ..constants import constants_datatypes as DATATYPE
from ..coordination import coordination_sample_rate_limit as SRL
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report

DEVICE_CONFIG = DEVICE.GSV_24456060
DOCS_OUTPUT_DIR = Path("docs")
OUTPUT_BASENAME = "sample_rate_limit_probe"

OBJECT_COUNTS_TO_TEST = (3, 6)
DATATYPES_TO_TEST = ("float32", "int24", "int16")
REQUESTED_SAMPLE_RATES_HZ = (
    100,
    150,
    200,
    250,
    300,
    400,
    500,
    640,
    800,
    1000,
    1200,
    1500,
    1600,
    2000,
    2400,
    2500,
    3000,
    3200,
    4000,
    4800,
    6000,
    8000,
    9600,
    12000,
)

SAFE_SAMPLE_RATE_HZ = 100.0
CRC_ENABLED = False


def configure_safe_sample_rate(
    *,
    device,
) -> None:
    """Set a low sample rate before changing TX layout settings."""
    device.acquisition.configure_sample_rate(
        SAFE_SAMPLE_RATE_HZ,
        strict=False,
    )


def restore_original_settings(
    *,
    device,
    original_datatype: int,
    original_mapping_count: int,
    original_sample_rate_hz: float,
) -> None:
    """Restore datatype, TX mapping count, and sample rate in a safe order."""
    print()
    print("Restoring original settings")
    print("---------------------------")

    try:
        configure_safe_sample_rate(device=device)
        print(f"safe_sample_rate_hz: {SAFE_SAMPLE_RATE_HZ:g}")
    except Exception as error:
        print(f"safe sample-rate restore step failed: {error}")

    try:
        response = device.acquisition.configure_datatype(original_datatype)
        print(f"datatype: {response['datatype_name']}")
    except Exception as error:
        print(f"datatype restore failed: {error}")

    try:
        response = device.acquisition.configure_tx_mapping_count(original_mapping_count)
        print(f"tx_mapping_count: {response['tx_mapping_count']}")
    except Exception as error:
        print(f"tx_mapping_count restore failed: {error}")

    try:
        response = device.acquisition.configure_sample_rate(original_sample_rate_hz)
        print(f"sample_rate_hz: {response['sample_rate_hz']}")
    except Exception as error:
        print(f"sample_rate restore failed: {error}")


def configure_probe_layout(
    *,
    device,
    object_count: int,
    datatype: int,
) -> bool:
    """Configure one TX layout at a safe sample rate."""
    try:
        configure_safe_sample_rate(device=device)
        device.acquisition.configure_datatype(datatype)
        device.acquisition.configure_tx_mapping_count(object_count)
        return True
    except Exception as error:
        print(
            f"layout setup failed for objects={object_count}, "
            f"datatype={DATATYPE.get_name(datatype)}: {error}"
        )
        return False


def run_one_probe(
    *,
    device,
    object_count: int,
    datatype: int,
    requested_sample_rate_hz: float,
) -> dict[str, Any]:
    """Run one sample-rate write/readback test."""
    calculated = SRL.check_sample_rate_limit(
        baudrate=device.connection_report.active_baudrate,
        streamed_value_count=object_count,
        datatype=datatype,
        requested_sample_rate_hz=requested_sample_rate_hz,
        crc_enabled=CRC_ENABLED,
    )

    row = dict(calculated)
    row.update(
        {
            "write_accepted": False,
            "active_sample_rate_hz": None,
            "sample_rate_matches_request": False,
            "error": "",
        }
    )

    try:
        response = device.acquisition.configure_sample_rate(
            requested_sample_rate_hz,
            strict=False,
        )
        row["write_accepted"] = True
        row["active_sample_rate_hz"] = float(response["sample_rate_hz"])
        row["sample_rate_matches_request"] = bool(
            response["sample_rate_matches_request"]
        )
        row["readback_warning_key"] = response["warning_key"]
    except Exception as error:
        row["error"] = str(error)

    return row


def print_row(row: dict[str, Any]) -> None:
    """Print one compact probe row."""
    active = row["active_sample_rate_hz"]
    active_text = "<none>" if active is None else f"{active:g}"
    print(
        f"objects={row['streamed_value_count']}, "
        f"datatype={row['datatype_name']:<7}, "
        f"requested={row['requested_sample_rate_hz']:>7g}, "
        f"active={active_text:>7}, "
        f"matches={row['sample_rate_matches_request']!s:<5}, "
        f"serial_estimate={row['estimated_serial_limit_hz']:>8.1f}"
    )
    if row["error"]:
        print(f"    {row['error']}")


def summarize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Print and return maximum matching sample rate per tested frame layout."""
    print()
    print("Summary")
    print("-------")
    groups = {}
    for row in rows:
        key = (row["streamed_value_count"], row["datatype_name"])
        groups.setdefault(key, []).append(row)

    summary_rows = []
    for key, group_rows in groups.items():
        matching = [row for row in group_rows if row["sample_rate_matches_request"]]
        max_matching = max(
            (row["requested_sample_rate_hz"] for row in matching),
            default=None,
        )
        object_count, datatype_name = key
        first_row = group_rows[0]
        summary_row = {
            "streamed_value_count": object_count,
            "datatype_name": datatype_name,
            "max_matching_requested_sample_rate_hz": max_matching,
            "estimated_serial_limit_hz": first_row["estimated_serial_limit_hz"],
        }
        summary_rows.append(summary_row)

        if max_matching is None:
            print(
                f"objects={object_count}, datatype={datatype_name}: "
                "no matching rate"
            )
        else:
            print(
                f"objects={object_count}, datatype={datatype_name}: "
                f"max matching requested sample rate = {max_matching:g} Hz "
                f"(serial estimate {first_row['estimated_serial_limit_hz']:.1f} Hz)"
            )

    return summary_rows


def write_outputs(
    *,
    rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
) -> None:
    """Write CSV and Markdown probe output files."""
    DOCS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = DOCS_OUTPUT_DIR / f"{OUTPUT_BASENAME}_{timestamp}.csv"
    md_path = DOCS_OUTPUT_DIR / f"{OUTPUT_BASENAME}_{timestamp}.md"

    columns = [
        "baudrate",
        "streamed_value_count",
        "datatype_name",
        "crc_enabled",
        "frame_bytes",
        "estimated_serial_limit_hz",
        "requested_sample_rate_hz",
        "request_plausible",
        "write_accepted",
        "active_sample_rate_hz",
        "sample_rate_matches_request",
        "error",
    ]

    with csv_path.open("w", encoding="utf-8") as file:
        file.write(";".join(columns) + "\n")
        for row in rows:
            file.write(";".join(str(row.get(column, "")) for column in columns) + "\n")

    with md_path.open("w", encoding="utf-8") as file:
        file.write("# Sample rate limit probe\n\n")
        file.write(f"Device: `{DEVICE_CONFIG['name']}`\n\n")
        file.write("## Summary\n\n")
        file.write(
            "| streamed_value_count | datatype | "
            "max_matching_requested_sample_rate_hz | estimated_serial_limit_hz |\n"
        )
        file.write("| --- | --- | --- | --- |\n")
        for row in summary_rows:
            file.write(
                f"| {row['streamed_value_count']} "
                f"| {row['datatype_name']} "
                f"| {row['max_matching_requested_sample_rate_hz']} "
                f"| {row['estimated_serial_limit_hz']} |\n"
            )

    print()
    print(f"CSV written: {csv_path}")
    print(f"Markdown written: {md_path}")


def main() -> None:
    """Run the sample-rate limit probe."""
    device = None
    rows: list[dict[str, Any]] = []

    print("Sample-rate limit probe")
    print("-----------------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print()

    print("Opening device...")
    print("Connection probe")
    print("----------------")
    try:
        device = open_gsv_device_from_config(
            DEVICE_CONFIG,
            on_probe_result=print_baudrate_probe_result,
        )
    except DeviceConnectionError as error:
        print("Opening device failed.")
        print(error)
        return

    print()
    print("Device opened.")
    print_connection_report(device)

    device.clear_input_buffer()
    device.acquisition.stop_transmission()
    device.clear_input_buffer()

    original_datatype = device.acquisition.read_datatype()["datatype"]
    original_mapping_count = device.acquisition.read_tx_mapping_count()[
        "tx_mapping_count"
    ]
    original_sample_rate_hz = float(device.acquisition.read_sample_rate()["sample_rate_hz"])

    try:
        for object_count in OBJECT_COUNTS_TO_TEST:
            for datatype in DATATYPES_TO_TEST:
                normalized_datatype = DATATYPE.normalize_datatype(datatype)

                if not configure_probe_layout(
                    device=device,
                    object_count=object_count,
                    datatype=normalized_datatype,
                ):
                    continue

                for requested_sample_rate_hz in REQUESTED_SAMPLE_RATES_HZ:
                    row = run_one_probe(
                        device=device,
                        object_count=object_count,
                        datatype=normalized_datatype,
                        requested_sample_rate_hz=requested_sample_rate_hz,
                    )
                    rows.append(row)
                    print_row(row)

    finally:
        restore_original_settings(
            device=device,
            original_datatype=original_datatype,
            original_mapping_count=original_mapping_count,
            original_sample_rate_hz=original_sample_rate_hz,
        )
        device.close()
        print("Device closed.")

    if not rows:
        print("No probe rows were recorded.")
        return

    summary_rows = summarize_results(rows)
    write_outputs(
        rows=rows,
        summary_rows=summary_rows,
    )


if __name__ == "__main__":
    main()
