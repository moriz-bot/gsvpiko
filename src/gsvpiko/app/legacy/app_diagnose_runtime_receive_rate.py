"""Scan receive performance for several sample rates on a two-GSV setup."""

from __future__ import annotations

from copy import deepcopy

from ..config import config_setups as SETUP
from ..coordination.coordination_recording import record_setup_frames
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError
from ..device.device_report import print_connection_report_data
from ..messages.messages_warning_text import format_warning, get_warning_action_text

BASE_SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH
DIAGNOSTIC_BAUDRATE = 460800
SAMPLE_RATES_HZ = (150.0, 300.0, 600.0, 1200.0, 2400.0)
FRAME_COUNT_PER_DEVICE = 1000
DISCARD_INITIAL_FRAMES = 20


def main() -> None:
    """Run a compact runtime receive-rate scan."""
    title = "Two-GSV runtime receive-rate diagnostics"
    print(title)
    print("-" * len(title))
    print(f"diagnostic_baudrate: {DIAGNOSTIC_BAUDRATE}")
    print(f"sample_rates_hz: {', '.join(f'{rate:g}' for rate in SAMPLE_RATES_HZ)}")
    print(f"frame_count_per_device: {FRAME_COUNT_PER_DEVICE}")
    print(f"discard_initial_frames: {DISCARD_INITIAL_FRAMES}")
    print()

    for sample_rate_hz in SAMPLE_RATES_HZ:
        setup_config = deepcopy(BASE_SETUP_CONFIG)
        setup_config["baudrate"] = DIAGNOSTIC_BAUDRATE
        setup_config["sample_rate_hz"] = float(sample_rate_hz)

        print(f"sample_rate_hz = {sample_rate_hz:g}")
        print("-" * (len("sample_rate_hz = ") + len(f"{sample_rate_hz:g}")))

        try:
            resolved_setup = resolve_setup(setup_config)
            recording_result = record_setup_frames(
                setup_config=setup_config,
                resolved_setup=resolved_setup,
                frame_count_per_device=FRAME_COUNT_PER_DEVICE,
                discard_initial_frames=DISCARD_INITIAL_FRAMES,
                on_probe_result=None,
            )
        except DeviceConnectionError as error:
            print("opening_failed: True")
            print(error)
            print()
            continue

        _print_connection_reports(recording_result.connection_reports)

        if recording_result.application_warnings:
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
            print(
                "    byte_rate_Bps: "
                f"{_format_float(device_result.byte_rate_Bps)}"
            )
            print(f"    parser_resync_count: {device_result.parser_resync_count}")
            print(
                "    mean_receive_delivery_interval_ms: "
                f"{_format_ms(_mean(delivery_intervals))}"
            )
            print(
                "    min_receive_delivery_interval_ms: "
                f"{_format_ms(min(delivery_intervals) if delivery_intervals else None)}"
            )
            print(
                "    max_receive_delivery_interval_ms: "
                f"{_format_ms(max(delivery_intervals) if delivery_intervals else None)}"
            )
            for error in device_result.errors:
                print(f"    error: {error}")

        print()


def _print_connection_reports(
    reports,
) -> None:
    """Print connection and optional NPort reports for one run."""
    for report in reports:
        print_connection_report_data(report)


def _timestamp_mode(device_result) -> str:
    """Return the timestamp mode of the first record."""
    if not device_result.records:
        return "-"
    return device_result.records[0].timestamp_mode


def _mean(
    values: list[float],
) -> float | None:
    """Return the arithmetic mean or None for an empty list."""
    if not values:
        return None

    return sum(values) / len(values)


def _format_ms(
    value_s: float | None,
) -> str:
    """Format a seconds value as milliseconds."""
    if value_s is None:
        return "-"

    return f"{1000.0 * value_s:.3f}"


def _format_float(
    value: float | None,
) -> str:
    """Format a float value or a placeholder."""
    if value is None:
        return "-"

    return f"{value:.3f}"


def _format_ratio(
    value: float | None,
    requested: float,
) -> str:
    """Format a rate divided by the requested rate."""
    if value is None or requested <= 0:
        return "-"

    return f"{value / requested:.3f}"


if __name__ == "__main__":
    main()
