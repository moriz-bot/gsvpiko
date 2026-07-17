"""Diagnose whether software-controlled measurement blocks are viable.

This app repeatedly starts autonomous transmission, reads a small fixed block of
frames, stops transmission, clears the transport input buffers, and immediately
starts the next block. It measures the receive-time gap between consecutive
stored blocks.

The result estimates the practical discontinuity introduced by a software block
mode. It does not prove ADC sample phase and it does not implement a production
synchronization mode.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from statistics import mean
from time import perf_counter
from typing import Any

from ..config import config_setups as SETUP
from ..coordination.coordination_setup_application import (
    AppliedSetup,
    close_applied_devices,
    open_and_apply_setup,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError
from ..messages.messages_warning_text import format_warning, get_warning_action_text
from ..runtime.runtime_measurement_buffer import RuntimeDeviceResult
from ..runtime.runtime_reader import BATCH_READ_SIZE, read_frames_concurrently
from ..runtime.runtime_session import (
    start_transmission_concurrently,
    stop_transmission_concurrently,
)

BASE_SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH
DEFAULT_BAUDRATE = 460800
DEFAULT_DATATYPE = "float32"
DEFAULT_SAMPLE_RATES_HZ = (150.0, 300.0, 600.0, 1200.0, 2400.0)
DEFAULT_BLOCK_FRAMES = 128
DEFAULT_CYCLES = 6
DEFAULT_DISCARD_INITIAL_FRAMES = 10
DEFAULT_CANDIDATE_BLOCK_DURATIONS_S = (1.0, 5.0, 10.0, 30.0, 60.0)
DEFAULT_MAX_GAP_FRACTION = 0.01
DEFAULT_RELATIVE_PPM = 61.744537


@dataclass(frozen=True)
class BlockDeviceSlice:
    """Receive-time boundaries for one device in one software block."""

    device_alias: str
    device_name: str
    frame_count: int
    total_measurement_frames_read: int
    bytes_read: int
    parser_resync_count: int
    errors: list[str]
    first_receive_monotonic_s: float | None
    last_receive_monotonic_s: float | None


@dataclass(frozen=True)
class BlockRun:
    """One start-read-stop cycle."""

    index: int
    start_command_duration_s: float
    stop_command_duration_s: float
    devices: dict[str, BlockDeviceSlice] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionGap:
    """Measured gap between two consecutive blocks for one device."""

    device_alias: str
    previous_block: int
    next_block: int
    gap_s: float
    extra_gap_s: float
    equivalent_missing_frames: float


@dataclass(frozen=True)
class RateResult:
    """Collected software-block result for one sample rate."""

    sample_rate_hz: float
    block_frames: int
    cycles: int
    block_runs: list[BlockRun]
    transitions: list[TransitionGap]


def main() -> None:
    """Run software block-mode transition diagnostics."""
    args = _parse_args()
    sample_rates_hz = _parse_float_list(args.sample_rates_hz)
    candidate_block_durations_s = _parse_float_list(args.candidate_block_durations_s)

    title = "Two-GSV software block-mode diagnostics"
    print(title)
    print("-" * len(title))
    print(f"baudrate: {args.baudrate}")
    print(f"datatype: {args.datatype}")
    print(f"sample_rates_hz: {_format_float_sequence(sample_rates_hz)}")
    print(f"block_frames: {args.block_frames}")
    print(f"cycles: {args.cycles}")
    print(f"discard_initial_frames: {args.discard_initial_frames}")
    print(f"batch_read_size: {BATCH_READ_SIZE}")
    print(f"max_gap_fraction: {args.max_gap_fraction:g}")
    print(f"relative_ppm_for_context: {args.relative_ppm:g}")
    print(
        "candidate_block_durations_s: "
        f"{_format_float_sequence(candidate_block_durations_s)}"
    )
    print()
    print(
        "Interpretation: this diagnostic deliberately creates gaps by stopping "
        "and restarting autonomous transmission. It measures receive-time gaps "
        "between stored blocks, not hard ADC sample gaps."
    )
    print()

    for sample_rate_hz in sample_rates_hz:
        _run_one_rate(
            sample_rate_hz=sample_rate_hz,
            datatype=args.datatype,
            baudrate=args.baudrate,
            block_frames=args.block_frames,
            cycles=args.cycles,
            discard_initial_frames=args.discard_initial_frames,
            max_gap_fraction=args.max_gap_fraction,
            relative_ppm=args.relative_ppm,
            candidate_block_durations_s=candidate_block_durations_s,
        )


def _run_one_rate(
    *,
    sample_rate_hz: float,
    datatype: str,
    baudrate: int,
    block_frames: int,
    cycles: int,
    discard_initial_frames: int,
    max_gap_fraction: float,
    relative_ppm: float,
    candidate_block_durations_s: list[float],
) -> None:
    """Run the software-block diagnostic for one sample rate."""
    heading = f"sample_rate_hz={sample_rate_hz:g}"
    print(heading)
    print("-" * len(heading))

    setup_config = deepcopy(BASE_SETUP_CONFIG)
    setup_config["baudrate"] = int(baudrate)
    setup_config["datatype"] = datatype
    setup_config["sample_rate_hz"] = float(sample_rate_hz)

    applied_setup: AppliedSetup | None = None
    try:
        resolved_setup = resolve_setup(setup_config)
        applied_setup = open_and_apply_setup(
            setup_config=setup_config,
            resolved_setup=resolved_setup,
            on_probe_result=None,
        )

        if applied_setup.warnings:
            for warning in applied_setup.warnings:
                print(
                    format_warning(
                        warning["warning_key"],
                        language=resolved_setup.language,
                        context=warning["context"],
                    )
                )
                action_key = "blocking" if warning.get("blocking") else "non_blocking"
                print(
                    get_warning_action_text(
                        action_key,
                        language=resolved_setup.language,
                    )
                )
                print()

        if not applied_setup.can_start_transmission:
            print(
                get_warning_action_text(
                    "measurement_not_started",
                    language=resolved_setup.language,
                )
            )
            print()
            return

        _clear_all_input_buffers(applied_setup)
        block_runs = _run_block_cycles(
            applied_setup=applied_setup,
            block_frames=block_frames,
            cycles=cycles,
            discard_initial_frames=discard_initial_frames,
            sample_rate_hz=sample_rate_hz,
        )
        transitions = _build_transition_gaps(
            block_runs=block_runs,
            sample_rate_hz=sample_rate_hz,
        )
        result = RateResult(
            sample_rate_hz=sample_rate_hz,
            block_frames=block_frames,
            cycles=cycles,
            block_runs=block_runs,
            transitions=transitions,
        )
        _print_rate_result(
            result=result,
            max_gap_fraction=max_gap_fraction,
            relative_ppm=relative_ppm,
            candidate_block_durations_s=candidate_block_durations_s,
        )
        print()
    except DeviceConnectionError as error:
        print("opening_failed: True")
        print(error)
        print()
    except Exception as error:
        print("diagnostic_failed: True")
        print(error)
        print()
    finally:
        if applied_setup is not None:
            close_applied_devices(applied_setup.devices)


def _run_block_cycles(
    *,
    applied_setup: AppliedSetup,
    block_frames: int,
    cycles: int,
    discard_initial_frames: int,
    sample_rate_hz: float,
) -> list[BlockRun]:
    """Run repeated start-read-stop blocks."""
    block_runs: list[BlockRun] = []

    for cycle_index in range(1, cycles + 1):
        _clear_all_input_buffers(applied_setup)

        start_t0 = perf_counter()
        start_transmission_concurrently(applied_setup)
        start_t1 = perf_counter()

        device_results = read_frames_concurrently(
            applied_setup.devices,
            frame_count=block_frames,
            discard_initial_frames=discard_initial_frames,
            expected_sample_rate_hz=sample_rate_hz,
            use_batched_transport_reader=True,
        )

        stop_t0 = perf_counter()
        stop_transmission_concurrently(applied_setup)
        stop_t1 = perf_counter()
        _clear_all_input_buffers(applied_setup)

        block_runs.append(
            BlockRun(
                index=cycle_index,
                start_command_duration_s=start_t1 - start_t0,
                stop_command_duration_s=stop_t1 - stop_t0,
                devices={
                    device_result.device_alias: _device_slice_from_result(device_result)
                    for device_result in device_results
                },
            )
        )

    return block_runs


def _device_slice_from_result(
    device_result: RuntimeDeviceResult,
) -> BlockDeviceSlice:
    """Return compact receive boundaries for one runtime device result."""
    receive_times = [
        record.receive_timestamp_monotonic_s
        for record in device_result.records
        if record.receive_timestamp_monotonic_s is not None
    ]
    return BlockDeviceSlice(
        device_alias=device_result.device_alias,
        device_name=device_result.device_name,
        frame_count=device_result.frame_count,
        total_measurement_frames_read=device_result.total_measurement_frames_read,
        bytes_read=device_result.bytes_read,
        parser_resync_count=device_result.parser_resync_count,
        errors=list(device_result.errors),
        first_receive_monotonic_s=receive_times[0] if receive_times else None,
        last_receive_monotonic_s=receive_times[-1] if receive_times else None,
    )


def _build_transition_gaps(
    *,
    block_runs: list[BlockRun],
    sample_rate_hz: float,
) -> list[TransitionGap]:
    """Compute receive gaps between consecutive blocks."""
    if sample_rate_hz <= 0:
        return []

    expected_interval_s = 1.0 / sample_rate_hz
    transitions: list[TransitionGap] = []

    for previous, following in zip(block_runs, block_runs[1:]):
        for device_alias, previous_slice in previous.devices.items():
            following_slice = following.devices.get(device_alias)
            if following_slice is None:
                continue
            if previous_slice.last_receive_monotonic_s is None:
                continue
            if following_slice.first_receive_monotonic_s is None:
                continue

            gap_s = (
                following_slice.first_receive_monotonic_s
                - previous_slice.last_receive_monotonic_s
            )
            extra_gap_s = max(0.0, gap_s - expected_interval_s)
            equivalent_missing_frames = max(0.0, gap_s * sample_rate_hz - 1.0)
            transitions.append(
                TransitionGap(
                    device_alias=device_alias,
                    previous_block=previous.index,
                    next_block=following.index,
                    gap_s=gap_s,
                    extra_gap_s=extra_gap_s,
                    equivalent_missing_frames=equivalent_missing_frames,
                )
            )

    return transitions


def _print_rate_result(
    *,
    result: RateResult,
    max_gap_fraction: float,
    relative_ppm: float,
    candidate_block_durations_s: list[float],
) -> None:
    """Print one sample-rate diagnostic result."""
    expected_interval_s = 1.0 / result.sample_rate_hz
    block_duration_s = result.block_frames / result.sample_rate_hz
    start_durations = [block.start_command_duration_s for block in result.block_runs]
    stop_durations = [block.stop_command_duration_s for block in result.block_runs]

    print(f"expected_interval_ms: {1000.0 * expected_interval_s:.3f}")
    print(f"measured_block_frames: {result.block_frames}")
    print(f"measured_block_duration_ms: {1000.0 * block_duration_s:.3f}")
    print(f"cycles_completed: {len(result.block_runs)}")
    print(f"start_command_duration_ms_mean: {_format_ms(_mean_or_none(start_durations))}")
    print(f"start_command_duration_ms_max: {_format_ms(max(start_durations) if start_durations else None)}")
    print(f"stop_command_duration_ms_mean: {_format_ms(_mean_or_none(stop_durations))}")
    print(f"stop_command_duration_ms_max: {_format_ms(max(stop_durations) if stop_durations else None)}")

    print("devices:")
    aliases = sorted({alias for block in result.block_runs for alias in block.devices})
    for alias in aliases:
        slices = [block.devices[alias] for block in result.block_runs if alias in block.devices]
        errors = sum(len(item.errors) for item in slices)
        resync = sum(item.parser_resync_count for item in slices)
        frames = sum(item.frame_count for item in slices)
        print(f"  {alias}")
        print(f"    stored_frames_total: {frames}")
        print(f"    errors: {errors}")
        print(f"    parser_resync_count: {resync}")

    print("transition_gaps:")
    for alias in aliases:
        gaps = [gap for gap in result.transitions if gap.device_alias == alias]
        gap_values_s = [gap.gap_s for gap in gaps]
        extra_values_s = [gap.extra_gap_s for gap in gaps]
        missing_values = [gap.equivalent_missing_frames for gap in gaps]
        p95_gap_s = _percentile(gap_values_s, 95.0)
        max_missing = max(missing_values) if missing_values else None
        p95_missing = _percentile(missing_values, 95.0)
        measured_gap_fraction = (
            (p95_missing or 0.0) / result.block_frames
            if result.block_frames > 0 and p95_missing is not None
            else None
        )
        seamless_ok = p95_gap_s is not None and p95_gap_s <= expected_interval_s
        gap_fraction_ok = (
            measured_gap_fraction is not None
            and measured_gap_fraction <= max_gap_fraction
        )
        print(f"  {alias}")
        print(f"    transitions: {len(gaps)}")
        print(f"    gap_ms_mean: {_format_ms(_mean_or_none(gap_values_s))}")
        print(f"    gap_ms_p95: {_format_ms(p95_gap_s)}")
        print(f"    gap_ms_max: {_format_ms(max(gap_values_s) if gap_values_s else None)}")
        print(f"    extra_gap_ms_mean: {_format_ms(_mean_or_none(extra_values_s))}")
        print(f"    equivalent_missing_frames_p95: {_format_float(p95_missing)}")
        print(f"    equivalent_missing_frames_max: {_format_float(max_missing)}")
        print(f"    measured_gap_fraction_p95: {_format_ratio(measured_gap_fraction)}")
        print(f"    seamless_ok: {seamless_ok}")
        print(f"    gap_fraction_ok: {gap_fraction_ok}")

    print("candidate_block_durations:")
    p95_missing_all = _percentile(
        [gap.equivalent_missing_frames for gap in result.transitions],
        95.0,
    )
    max_gap_s_all = max((gap.gap_s for gap in result.transitions), default=None)
    for duration_s in candidate_block_durations_s:
        candidate_frames = max(1, int(round(duration_s * result.sample_rate_hz)))
        gap_fraction = (
            (p95_missing_all or 0.0) / candidate_frames
            if p95_missing_all is not None
            else None
        )
        drift_ms = abs(relative_ppm) * 1e-3 * duration_s
        print(
            f"  duration_s={duration_s:g}, frames≈{candidate_frames}, "
            f"p95_missing_frames≈{_format_float(p95_missing_all)}, "
            f"gap_fraction≈{_format_ratio(gap_fraction)}, "
            f"free_run_relative_drift_ms≈{drift_ms:.3f}, "
            f"measured_max_gap_ms≈{_format_ms(max_gap_s_all)}"
        )

    if result.transitions:
        print(
            "decision_hint: seamless block switching requires gap_ms_p95 <= "
            "expected_interval_ms. If that is false, software blocks produce "
            "real gaps and are only useful if bounded drift is more important "
            "than the discontinuity at every block boundary."
        )


def _clear_all_input_buffers(
    applied_setup: AppliedSetup,
) -> None:
    """Clear all device input buffers where possible."""
    for applied_device in applied_setup.devices:
        try:
            applied_device.device.clear_input_buffer()
        except Exception:
            pass


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Diagnose software block-mode stop/start gaps for two GSVs.",
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--datatype", default=DEFAULT_DATATYPE)
    parser.add_argument(
        "--sample-rates-hz",
        default=",".join(f"{rate:g}" for rate in DEFAULT_SAMPLE_RATES_HZ),
        help="Comma-separated sample rates to test.",
    )
    parser.add_argument("--block-frames", type=int, default=DEFAULT_BLOCK_FRAMES)
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument(
        "--discard-initial-frames",
        type=int,
        default=DEFAULT_DISCARD_INITIAL_FRAMES,
    )
    parser.add_argument(
        "--max-gap-fraction",
        type=float,
        default=DEFAULT_MAX_GAP_FRACTION,
        help="Allowed transition-gap fraction relative to block frames.",
    )
    parser.add_argument(
        "--relative-ppm",
        type=float,
        default=DEFAULT_RELATIVE_PPM,
        help="Relative drift ppm used only for context calculations.",
    )
    parser.add_argument(
        "--candidate-block-durations-s",
        default=",".join(f"{value:g}" for value in DEFAULT_CANDIDATE_BLOCK_DURATIONS_S),
        help="Comma-separated block durations for post-run viability estimates.",
    )
    args = parser.parse_args()

    if args.block_frames <= 0:
        raise ValueError("--block-frames must be greater than zero.")
    if args.cycles < 2:
        raise ValueError("--cycles must be at least 2 to measure transitions.")
    if args.discard_initial_frames < 0:
        raise ValueError("--discard-initial-frames must not be negative.")
    if args.max_gap_fraction < 0:
        raise ValueError("--max-gap-fraction must not be negative.")

    return args


def _parse_float_list(
    text: str,
) -> list[float]:
    """Parse a comma-separated float list."""
    values = []
    for item in text.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        value = float(stripped)
        if value <= 0:
            raise ValueError(f"List values must be greater than zero: {value!r}")
        values.append(value)

    if not values:
        raise ValueError("At least one list value is required.")
    return values


def _mean_or_none(
    values: list[float],
) -> float | None:
    """Return arithmetic mean or None."""
    if not values:
        return None
    return mean(values)


def _percentile(
    values: list[float],
    percentile: float,
) -> float | None:
    """Return a simple linearly interpolated percentile."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * percentile / 100.0
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = rank - lower_index
    return (
        sorted_values[lower_index] * (1.0 - fraction)
        + sorted_values[upper_index] * fraction
    )


def _format_ms(
    value_s: float | None,
) -> str:
    """Format seconds as milliseconds."""
    if value_s is None:
        return "-"
    return f"{1000.0 * value_s:.3f}"


def _format_float(
    value: float | None,
) -> str:
    """Format a float or placeholder."""
    if value is None:
        return "-"
    return f"{value:.3f}"


def _format_ratio(
    value: float | None,
) -> str:
    """Format a ratio or placeholder."""
    if value is None:
        return "-"
    return f"{value:.6f}"


def _format_float_sequence(
    values: list[float] | tuple[float, ...],
) -> str:
    """Format float sequence compactly."""
    return ", ".join(f"{value:g}" for value in values)


if __name__ == "__main__":
    main()
