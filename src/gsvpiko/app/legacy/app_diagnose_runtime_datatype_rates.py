"""Scan runtime receive performance for several datatypes and sample rates."""

from __future__ import annotations

import argparse
from copy import deepcopy

from ..config import config_setups as SETUP
from ..coordination.coordination_recording import record_setup_frames
from ..coordination.coordination_setup_resolution import ResolvedSetup, resolve_setup
from ..device.device_connection import DeviceConnectionError
from ..messages.messages_warning_text import format_warning, get_warning_action_text

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
                _print_sample_rate_limit_reports(resolved_setup)
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
                    get_warning_action_text(
                        "measurement_not_started",
                        language=recording_result.resolved_setup.language,
                    )
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
                delivery_intervals = device_result.receive_delivery_intervals_s()
                print(f"  {device_result.device_alias} = {device_result.device_name}")
                print(f"    reader_type: {device_result.reader_type}")
                print(f"    timestamp_mode: {_timestamp_mode(device_result)}")
                print(f"    frames: {device_result.frame_count}")
                print(f"    discarded_frames: {device_result.discarded_frame_count}")
                print(
                    "    total_measurement_frames_read: "
                    f"{device_result.total_measurement_frames_read}"
                )
                print(f"    errors: {len(device_result.errors)}")
                print(f"    reader_duration_s: {_format_float(device_result.read_duration_s)}")
                print(
                    "    stored_frame_rate_hz: "
                    f"{_format_float(device_result.stored_frame_rate_hz)}"
                )
                print(
                    "    total_frame_rate_hz: "
                    f"{_format_float(device_result.total_frame_rate_hz)}"
                )
                print(
                    "    total_frame_rate/requested: "
                    f"{_format_ratio(device_result.total_frame_rate_hz, sample_rate_hz)}"
                )
                print(f"    bytes_read: {device_result.bytes_read}")
                print(f"    byte_rate_Bps: {_format_float(device_result.byte_rate_Bps)}")
                print(f"    parser_resync_count: {device_result.parser_resync_count}")
                print(
                    "    max_receive_delivery_interval_ms: "
                    f"{_format_ms(max(delivery_intervals) if delivery_intervals else None)}"
                )
                for error in device_result.errors:
                    print(f"    error: {error}")
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
    return args


def _print_sample_rate_limit_reports(resolved_setup: ResolvedSetup) -> None:
    """Print setup-derived sample-rate limit estimates.

    The report dictionaries intentionally contain only the technical estimate.
    Device aliases are attached here from the resolved setup order.
    """
    devices = list(resolved_setup.devices)
    for index, report in enumerate(resolved_setup.sample_rate_limit_reports):
        device_alias = devices[index].alias if index < len(devices) else f"device_{index + 1}"
        plausible = report.get("request_plausible")
        estimated_limit = report.get("estimated_serial_limit_hz")
        print(
            "sample_rate_limit: "
            f"{device_alias}: "
            f"streamed_values={report.get('streamed_value_count')}, "
            f"datatype={report.get('datatype_name')}, "
            f"requested={report.get('requested_sample_rate_hz'):g} Hz, "
            f"estimated_limit={_format_float(estimated_limit)} Hz, "
            f"frame_bytes={report.get('frame_bytes')}, "
            f"plausible={plausible}"
        )


def _print_application_warnings(recording_result) -> None:
    """Print setup-application warnings in the selected setup language."""
    for warning in recording_result.application_warnings:
        print(
            format_warning(
                warning["warning_key"],
                language=recording_result.resolved_setup.language,
                context=warning["context"],
            )
        )
        action_key = "blocking" if warning.get("blocking") else "non_blocking"
        print(
            get_warning_action_text(
                action_key,
                language=recording_result.resolved_setup.language,
            )
        )
        print()


def _timestamp_mode(device_result) -> str:
    """Return the timestamp mode of the first record."""
    if not device_result.records:
        return "-"
    return device_result.records[0].timestamp_mode


def _format_ms(value_s: float | None) -> str:
    """Format a seconds value as milliseconds."""
    if value_s is None:
        return "-"
    return f"{1000.0 * value_s:.3f}"


def _format_float(value: float | None) -> str:
    """Format a float value or a placeholder."""
    if value is None:
        return "-"
    return f"{value:.3f}"


def _format_ratio(value: float | None, requested: float) -> str:
    """Format a rate divided by the requested rate."""
    if value is None or requested <= 0:
        return "-"
    return f"{value / requested:.3f}"


if __name__ == "__main__":
    main()
