"""Scan requested sample rates and record active GSV readback values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import time

from ..config import config_devices as DEVICE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report

DEVICE_CONFIG = DEVICE.GSV_24456060
OUTPUT_DIR = Path("docs")
OUTPUT_BASENAME = "sample_rate_scan"

REQUESTED_SAMPLE_RATES_HZ = (
    0.1,
    0.2,
    0.5,
    1,
    2,
    5,
    10,
    20,
    25,
    50,
    100,
    125,
    150,
    200,
    240,
    250,
    300,
    320,
    375,
    400,
    480,
    500,
    600,
    640,
    750,
    800,
    960,
    1000,
    1200,
    1500,
    1600,
    1920,
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


@dataclass(frozen=True)
class SampleRateScanResult:
    """One requested sample-rate write/readback result."""

    requested_sample_rate_hz: float
    write_accepted: bool
    active_sample_rate_hz: float | None
    sample_rate_matches_request: bool
    error: str = ""


def scan_one_sample_rate(
    *,
    device,
    requested_sample_rate_hz: float,
) -> SampleRateScanResult:
    """Write one requested sample rate and read the active value back."""
    try:
        response = device.acquisition.configure_sample_rate(
            requested_sample_rate_hz,
            strict=False,
        )
    except Exception as error:
        return SampleRateScanResult(
            requested_sample_rate_hz=float(requested_sample_rate_hz),
            write_accepted=False,
            active_sample_rate_hz=None,
            sample_rate_matches_request=False,
            error=str(error),
        )

    return SampleRateScanResult(
        requested_sample_rate_hz=float(requested_sample_rate_hz),
        write_accepted=True,
        active_sample_rate_hz=float(response["sample_rate_hz"]),
        sample_rate_matches_request=bool(response["sample_rate_matches_request"]),
    )


def write_csv(
    *,
    results: list[SampleRateScanResult],
) -> Path:
    """Write scan results to a CSV file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"{OUTPUT_BASENAME}_{timestamp}.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "requested_sample_rate_hz",
                "write_accepted",
                "active_sample_rate_hz",
                "sample_rate_matches_request",
                "error",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for result in results:
            writer.writerow(result.__dict__)

    return csv_path


def main() -> None:
    """Run the sample-rate scan."""
    device = None
    results = []

    print("Sample-rate scan")
    print("----------------")
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

    original_sample_rate_hz = float(device.acquisition.read_sample_rate()["sample_rate_hz"])

    try:
        for requested_sample_rate_hz in REQUESTED_SAMPLE_RATES_HZ:
            result = scan_one_sample_rate(
                device=device,
                requested_sample_rate_hz=requested_sample_rate_hz,
            )
            results.append(result)

            active = result.active_sample_rate_hz
            active_text = "<none>" if active is None else f"{active:g}"
            print(
                f"requested={result.requested_sample_rate_hz:g} Hz -> "
                f"active={active_text} Hz, "
                f"matches={result.sample_rate_matches_request}"
            )
            if result.error:
                print(f"    {result.error}")

    finally:
        if device is not None:
            print()
            print("Restoring original sample rate...")
            try:
                response = device.acquisition.configure_sample_rate(
                    original_sample_rate_hz
                )
                print(f"restored_sample_rate_hz: {response['sample_rate_hz']}")
            except Exception as error:
                print(f"sample-rate restore failed: {error}")

            device.close()
            print("Device closed.")

    if results:
        csv_path = write_csv(results=results)
        print(f"CSV written: {csv_path}")


if __name__ == "__main__":
    main()
