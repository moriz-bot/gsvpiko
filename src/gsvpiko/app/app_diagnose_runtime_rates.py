"""Scan runtime receive performance for several datatypes and sample rates."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options
from copy import deepcopy

from ..config import config_setups as SETUP
from ..coordination.coordination_recording import record_setup_frames
from ..coordination.coordination_report_print import (
    format_runtime_device_result_lines,
    format_sample_rate_limit_lines,
    format_setup_application_warning_lines,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError
from ..coordination.coordination_setup_application import (
    setup_application_warning_action_text,
)

BASE_SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH
DEFAULT_DIAGNOSTIC_BAUDRATE = 460800
DEFAULT_DATATYPES = ("float32", "int24", "int16")
DEFAULT_SAMPLE_RATES_HZ = (150.0, 300.0, 600.0, 1200.0, 2400.0, 3200.0, 4000.0)
DEFAULT_FRAME_COUNT_PER_DEVICE = 1000
DEFAULT_DISCARD_INITIAL_FRAMES = 20


def main() -> None:
    """Run datatype and receive-rate diagnostics for the two-GSV setup."""
    args = _parse_args()

    title = "Two-GSV runtime datatype-rate diagnostics"
    print(title)
    print("-" * len(title))
    print(f"diagnostic_baudrate: {args.baudrate}")
    print(f"datatypes: {', '.join(args.datatypes)}")
    print(f"sample_rates_hz: {', '.join(f'{rate:g}' for rate in args.sample_rates_hz)}")
    print(f"frame_count_per_device: {args.frame_count_per_device}")
    print(f"discard_initial_frames: {args.discard_initial_frames}")
    print()

    for datatype in args.datatypes:
        for sample_rate_hz in args.sample_rates_hz:
            setup_config = deepcopy(BASE_SETUP_CONFIG)
            setup_config["baudrate"] = args.baudrate
            setup_config["datatype"] = datatype
            setup_config["sample_rate_hz"] = float(sample_rate_hz)

            heading = f"datatype={datatype}, sample_rate_hz={sample_rate_hz:g}"
            print(heading)
            print("-" * len(heading))

            try:
                resolved_setup = resolve_setup(setup_config)
                for line in format_sample_rate_limit_lines(
                    resolved_setup,
                    include_frame_bytes=True,
                    include_warnings=False,
                ):
                    print(line)
                recording_result = record_setup_frames(
                    setup_config=setup_config,
                    resolved_setup=resolved_setup,
                    frame_count_per_device=args.frame_count_per_device,
                    discard_initial_frames=args.discard_initial_frames,
                    on_probe_result=None,
                )
            except DeviceConnectionError as error:
                print("opening_failed: True")
                print(error)
                print()
                continue
            except Exception as error:
                print("diagnostic_failed: True")
                print(f"{type(error).__name__}: {error}")
                print()
                continue

            if recording_result.application_warnings:
                _print_application_warnings(recording_result)

            if not recording_result.can_start_transmission:
                print(
                    setup_application_warning_action_text("measurement_not_started")
                )
                print()
                continue

            runtime_result = recording_result.runtime_result
            if runtime_result is None:
                print("runtime_result: <none>")
                print()
                continue

            print(f"duration_s: {runtime_result.duration_s:.6f}")
            print(f"expected_interval_ms: {1000.0 / sample_rate_hz:.3f}")
            print("devices:")
            for device_result in runtime_result.device_results:
                for line in format_runtime_device_result_lines(
                    device_result,
                    requested_sample_rate_hz=sample_rate_hz,
                ):
                    print(line)
            print()


def _parse_args() -> argparse.Namespace:
    """Return command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Test two-GSV runtime throughput for several datatype/sample-rate "
            "combinations."
        )
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_DIAGNOSTIC_BAUDRATE)
    parser.add_argument(
        "--datatypes",
        nargs="+",
        default=list(DEFAULT_DATATYPES),
        help="Datatype names to test, e.g. float32 int24 int16.",
    )
    parser.add_argument(
        "--sample-rates-hz",
        nargs="+",
        type=float,
        default=list(DEFAULT_SAMPLE_RATES_HZ),
        help="Sample rates to test in Hz.",
    )
    parser.add_argument(
        "--frame-count-per-device",
        type=int,
        default=DEFAULT_FRAME_COUNT_PER_DEVICE,
    )
    parser.add_argument(
        "--discard-initial-frames",
        type=int,
        default=DEFAULT_DISCARD_INITIAL_FRAMES,
    )
    args = parser.parse_args()

    if args.frame_count_per_device <= 0:
        parser.error("--frame-count-per-device must be positive.")
    if args.discard_initial_frames < 0:
        parser.error("--discard-initial-frames must not be negative.")
    if any(rate <= 0 for rate in args.sample_rates_hz):
        parser.error("--sample-rates-hz values must be positive.")
    print_cli_options(parser, args)
    return args


def _print_application_warnings(recording_result) -> None:
    """Print setup-application warnings."""
    lines = format_setup_application_warning_lines(recording_result.application_warnings)
    if lines:
        print("\n".join(lines).rstrip())
        print()


if __name__ == "__main__":
    main()
