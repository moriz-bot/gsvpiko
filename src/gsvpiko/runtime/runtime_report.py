"""Runtime recording reports for frame counts, timing, and offsets."""

from __future__ import annotations

from statistics import mean

from .runtime_measurement_buffer import RuntimeDeviceResult, RuntimeRecordingResult


def build_runtime_summary(
    result: RuntimeRecordingResult,
) -> dict:
    """Return a compact summary of frame counts, intervals, and time offsets."""
    return {
        "setup_name": result.setup_name,
        "duration_s": result.duration_s,
        "requested_frame_count_per_device": result.requested_frame_count_per_device,
        "discard_initial_frames": result.discard_initial_frames,
        "device_summaries": [
            _summarize_device_result(device_result)
            for device_result in result.device_results
        ],
        "pair_summaries": _summarize_pairs(result.device_results),
        "has_errors": result.has_errors,
    }


def format_runtime_summary(
    result: RuntimeRecordingResult,
    *,
    expected_sample_rate_hz: float | None = None,
) -> str:
    """Return a readable terminal summary for one runtime recording result."""
    summary = build_runtime_summary(result)
    lines = [
        "Runtime recording summary",
        "-------------------------",
        f"setup_name: {summary['setup_name']}",
        f"duration_s: {summary['duration_s']:.6f}",
        (
            "requested_frame_count_per_device: "
            f"{summary['requested_frame_count_per_device']}"
        ),
        f"discard_initial_frames: {summary['discard_initial_frames']}",
    ]

    if expected_sample_rate_hz is not None:
        lines.append(f"expected_sample_rate_hz: {float(expected_sample_rate_hz):g}")
        lines.append(
            "expected_interval_ms: "
            f"{1000.0 / float(expected_sample_rate_hz):.3f}"
        )

    lines.append("")
    lines.append("devices:")
    for device_summary in summary["device_summaries"]:
        lines.extend(_format_device_summary(device_summary))

    if summary["pair_summaries"]:
        lines.append("")
        lines.append("timestamp offsets:")
        for pair_summary in summary["pair_summaries"]:
            lines.extend(_format_pair_summary(pair_summary))

    return "\n".join(lines)


def _summarize_device_result(
    device_result: RuntimeDeviceResult,
) -> dict:
    """Return a compact summary for one device result."""
    intervals = device_result.receive_intervals_s()
    delivery_intervals = device_result.receive_delivery_intervals_s()
    return {
        "device_alias": device_result.device_alias,
        "device_name": device_result.device_name,
        "reader_type": device_result.reader_type,
        "frame_count": device_result.frame_count,
        "discarded_frame_count": device_result.discarded_frame_count,
        "total_measurement_frames_read": device_result.total_measurement_frames_read,
        "error_count": len(device_result.errors),
        "errors": list(device_result.errors),
        "bytes_read": device_result.bytes_read,
        "byte_rate_Bps": device_result.byte_rate_Bps,
        "parser_resync_count": device_result.parser_resync_count,
        "routed_non_measurement_frame_count": device_result.routed_non_measurement_frame_count,
        "runtime_command_discarded_frame_count": device_result.runtime_command_discarded_frame_count,
        "runtime_command_count": len(device_result.runtime_command_reports),
        "stored_frame_rate_hz": device_result.stored_frame_rate_hz,
        "total_frame_rate_hz": device_result.total_frame_rate_hz,
        "read_duration_s": device_result.read_duration_s,
        "timestamp_mode": _timestamp_mode(device_result),
        "first_timestamp_unix_s": _first_timestamp(device_result),
        "last_timestamp_unix_s": _last_timestamp(device_result),
        "mean_interval_s": _mean_or_none(intervals),
        "min_interval_s": min(intervals) if intervals else None,
        "max_interval_s": max(intervals) if intervals else None,
        "mean_delivery_interval_s": _mean_or_none(delivery_intervals),
        "min_delivery_interval_s": min(delivery_intervals) if delivery_intervals else None,
        "max_delivery_interval_s": max(delivery_intervals) if delivery_intervals else None,
    }


def _summarize_pairs(
    device_results: list[RuntimeDeviceResult],
) -> list[dict]:
    """Return timestamp offset summaries relative to the first device."""
    if len(device_results) < 2:
        return []

    reference = device_results[0]
    summaries = []
    for other in device_results[1:]:
        common_count = min(reference.frame_count, other.frame_count)
        deltas = [
            other.records[index].timestamp_unix_s
            - reference.records[index].timestamp_unix_s
            for index in range(common_count)
        ]
        receive_deltas = [
            other.records[index].receive_timestamp_unix_s
            - reference.records[index].receive_timestamp_unix_s
            for index in range(common_count)
            if other.records[index].receive_timestamp_unix_s is not None
            and reference.records[index].receive_timestamp_unix_s is not None
        ]
        summaries.append(
            {
                "reference_device_alias": reference.device_alias,
                "device_alias": other.device_alias,
                "common_frame_count": common_count,
                "mean_delta_s": _mean_or_none(deltas),
                "mean_abs_delta_s": _mean_or_none([abs(value) for value in deltas]),
                "min_delta_s": min(deltas) if deltas else None,
                "max_delta_s": max(deltas) if deltas else None,
                "mean_receive_delta_s": _mean_or_none(receive_deltas),
                "mean_abs_receive_delta_s": _mean_or_none(
                    [abs(value) for value in receive_deltas]
                ),
                "min_receive_delta_s": min(receive_deltas) if receive_deltas else None,
                "max_receive_delta_s": max(receive_deltas) if receive_deltas else None,
            }
        )

    return summaries


def _format_device_summary(
    device_summary: dict,
) -> list[str]:
    """Return terminal lines for one device summary."""
    lines = [
        f"  {device_summary['device_alias']} = {device_summary['device_name']}",
        f"    reader_type: {device_summary['reader_type']}",
        f"    timestamp_mode: {device_summary['timestamp_mode']}",
        f"    frames: {device_summary['frame_count']}",
        f"    discarded_frames: {device_summary['discarded_frame_count']}",
        f"    total_measurement_frames_read: {device_summary['total_measurement_frames_read']}",
        f"    errors: {device_summary['error_count']}",
    ]

    for field_name, label in (
        ("first_timestamp_unix_s", "first_timestamp_unix_s"),
        ("last_timestamp_unix_s", "last_timestamp_unix_s"),
    ):
        value = device_summary[field_name]
        if value is not None:
            lines.append(f"    {label}: {value:.6f}")

    for field_name, label in (
        ("read_duration_s", "reader_duration_s"),
        ("mean_interval_s", "mean_timestamp_interval_ms"),
        ("min_interval_s", "min_timestamp_interval_ms"),
        ("max_interval_s", "max_timestamp_interval_ms"),
        ("mean_delivery_interval_s", "mean_receive_delivery_interval_ms"),
        ("min_delivery_interval_s", "min_receive_delivery_interval_ms"),
        ("max_delivery_interval_s", "max_receive_delivery_interval_ms"),
    ):
        value = device_summary[field_name]
        if value is not None:
            if field_name == "read_duration_s":
                lines.append(f"    {label}: {value:.6f}")
            else:
                lines.append(f"    {label}: {1000.0 * value:.3f}")

    for field_name, label in (
        ("stored_frame_rate_hz", "stored_frame_rate_hz"),
        ("total_frame_rate_hz", "total_frame_rate_hz"),
        ("byte_rate_Bps", "byte_rate_Bps"),
    ):
        value = device_summary[field_name]
        if value is not None:
            lines.append(f"    {label}: {value:.1f}")

    lines.append(f"    bytes_read: {device_summary['bytes_read']}")
    lines.append(f"    parser_resync_count: {device_summary['parser_resync_count']}")
    lines.append(
        "    routed_non_measurement_frame_count: "
        f"{device_summary['routed_non_measurement_frame_count']}"
    )
    lines.append(
        "    runtime_command_discarded_frames: "
        f"{device_summary['runtime_command_discarded_frame_count']}"
    )
    lines.append(f"    runtime_command_count: {device_summary['runtime_command_count']}")

    for error in device_summary["errors"]:
        lines.append(f"    error: {error}")

    return lines


def _format_pair_summary(
    pair_summary: dict,
) -> list[str]:
    """Return terminal lines for one timestamp offset summary."""
    lines = [
        (
            f"  {pair_summary['device_alias']} - "
            f"{pair_summary['reference_device_alias']}"
        ),
        f"    common_frames: {pair_summary['common_frame_count']}",
    ]

    for field_name, label in (
        ("mean_delta_s", "mean_timestamp_delta_ms"),
        ("mean_abs_delta_s", "mean_abs_timestamp_delta_ms"),
        ("min_delta_s", "min_timestamp_delta_ms"),
        ("max_delta_s", "max_timestamp_delta_ms"),
        ("mean_receive_delta_s", "mean_receive_delta_ms"),
        ("mean_abs_receive_delta_s", "mean_abs_receive_delta_ms"),
        ("min_receive_delta_s", "min_receive_delta_ms"),
        ("max_receive_delta_s", "max_receive_delta_ms"),
    ):
        value = pair_summary[field_name]
        if value is not None:
            lines.append(f"    {label}: {1000.0 * value:.3f}")

    return lines


def _timestamp_mode(
    device_result: RuntimeDeviceResult,
) -> str:
    """Return the timestamp mode used by the first stored record."""
    if not device_result.records:
        return "-"

    return device_result.records[0].timestamp_mode


def _first_timestamp(
    device_result: RuntimeDeviceResult,
) -> float | None:
    """Return the first primary Unix timestamp for one device result."""
    if not device_result.records:
        return None

    return device_result.records[0].timestamp_unix_s


def _last_timestamp(
    device_result: RuntimeDeviceResult,
) -> float | None:
    """Return the last primary Unix timestamp for one device result."""
    if not device_result.records:
        return None

    return device_result.records[-1].timestamp_unix_s


def _mean_or_none(
    values: list[float],
) -> float | None:
    """Return the arithmetic mean, or None for an empty list."""
    if not values:
        return None

    return mean(values)
