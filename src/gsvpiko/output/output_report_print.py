"""Reusable terminal-formatting helpers for coordination-layer reports.

The functions in this module return text lines. Command-line apps decide when and
where to print them.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..coordination.coordination_sample_rate_limit import format_sample_rate_limit_warning
from ..coordination.coordination_setup_resolution import (
    ResolvedSetup,
    build_setup_metadata_lines,
)


def format_title_lines(title: str) -> list[str]:
    """Return one standard title block."""
    return [title, "-" * len(title)]


def format_setup_overview_lines(
    resolved_setup: ResolvedSetup,
    *,
    include_connection: bool = True,
    include_runtime: bool = True,
) -> list[str]:
    """Return compact setup fields shared by setup-based apps."""
    lines = [f"setup_name: {resolved_setup.name}"]
    if include_connection:
        lines.extend(
            [
                (
                    f"connection_type: {resolved_setup.connection_type} "
                    f"(source={resolved_setup.connection_type_source})"
                ),
                (
                    f"serial_interface: {resolved_setup.serial_interface} "
                    f"(source={resolved_setup.serial_interface_source})"
                ),
                f"use_nport: {resolved_setup.use_nport} (source={resolved_setup.use_nport_source})",
            ]
        )
    if include_runtime:
        lines.extend(
            [
                f"start_mode: {resolved_setup.start_mode}",
                f"sync_mode: {resolved_setup.sync_mode}",
                f"timebase_mode: {resolved_setup.timebase_mode}",
            ]
        )
    lines.extend(
        [
            f"baudrate: {resolved_setup.baudrate} (source={resolved_setup.baudrate_source})",
            (
                f"sample_rate_hz: {resolved_setup.sample_rate_hz:g} "
                f"(source={resolved_setup.sample_rate_source})"
            ),
            f"datatype: {resolved_setup.datatype_name} (source={resolved_setup.datatype_source})",
            (
                f"analog_filter_hz: {resolved_setup.analog_filter_hz} "
                f"(source={resolved_setup.analog_filter_source})"
            ),
            f"crc_enabled: {resolved_setup.crc_enabled}",
        ]
    )
    return lines


def format_setup_metadata_block_lines(
    resolved_setup: ResolvedSetup,
) -> list[str]:
    """Return setup device order and channel mapping lines."""
    return build_setup_metadata_lines(resolved_setup)


def format_streamed_channels_lines(
    resolved_setup: ResolvedSetup,
) -> list[str]:
    """Return used/streamed channel overview lines."""
    lines = ["streamed_channels:"]
    for device in resolved_setup.devices:
        lines.append(
            f"  {device.alias}: "
            f"used={list(device.used_channels)}, "
            f"streamed={list(device.streamed_channels)}"
        )
    return lines


def format_sample_rate_limit_lines(
    resolved_setup: ResolvedSetup,
    *,
    include_frame_bytes: bool = False,
    include_warnings: bool = True,
) -> list[str]:
    """Return sample-rate limit report lines for one resolved setup."""
    lines = ["sample_rate_limit:"]
    for device_alias, report in iter_sample_rate_limit_reports(resolved_setup):
        frame_bytes_text = ""
        if include_frame_bytes:
            frame_bytes_text = f", frame_bytes={report.get('frame_bytes')}"
        lines.append(
            f"  {device_alias}: "
            f"streamed_values={report.get('streamed_value_count')}, "
            f"datatype={report.get('datatype_name')}, "
            f"requested={float(report.get('requested_sample_rate_hz')):g} Hz, "
            f"estimated_limit={float(report.get('estimated_serial_limit_hz')):.1f} Hz"
            f"{frame_bytes_text}, "
            f"plausible={report.get('request_plausible')}"
        )
        if include_warnings and report.get("warning_key") is not None:
            lines.append("")
            lines.extend(format_sample_rate_limit_warning(report).splitlines())
            lines.append("")
    return lines


def iter_sample_rate_limit_reports(
    resolved_setup: ResolvedSetup,
):
    """Yield sample-rate reports with matching device alias."""
    for index, report in enumerate(resolved_setup.sample_rate_limit_reports):
        if "device_alias" in report:
            yield report["device_alias"], report
            continue
        if index < len(resolved_setup.devices):
            yield resolved_setup.devices[index].alias, report
            continue
        yield f"device_{index + 1}", report


def format_setup_application_warning_lines(
    warnings: Iterable[dict[str, Any]],
) -> list[str]:
    """Return setup-application warnings and suggested action lines."""
    from ..coordination.coordination_setup_application import (
        format_setup_application_warning,
        setup_application_warning_action_text,
    )

    lines: list[str] = []
    for warning in warnings:
        lines.extend(format_setup_application_warning(warning).splitlines())
        action_key = "blocking" if warning.get("blocking") else "non_blocking"
        lines.append(setup_application_warning_action_text(action_key))
        lines.append("")
    return lines



def format_connection_diagnostic_lines(result: Any) -> list[str]:
    """Return readable lines for one non-mutating connection diagnostic result."""
    heading = f"{result.device_alias} = {result.device_name}"
    lines = [heading, "-" * len(heading)]
    if result.ok:
        lines.extend(
            [
                "status: ok",
                f"connection_type: {result.connection_type}",
                f"endpoint: {result.endpoint}",
                (
                    "baudrate: "
                    f"{result.baudrate if result.baudrate is not None else '<not-applicable>'}"
                ),
            ]
        )
    else:
        lines.extend(["status: failed", f"error: {result.error or '<none>'}"])

    lines.append("attempts:")
    for attempt in result.attempts:
        lines.append(
            "  "
            f"connection_type={attempt.connection_type}, "
            f"endpoint={attempt.endpoint}, "
            f"baudrate={attempt.baudrate if attempt.baudrate is not None else '<not-applicable>'}, "
            f"opened={attempt.opened}, "
            f"responded={attempt.responded}, "
            f"response={attempt.response_raw_hex or '<none>'}, "
            f"error={attempt.error or '<none>'}"
        )
    return lines

def format_runtime_device_result_lines(
    device_result: Any,
    *,
    requested_sample_rate_hz: float,
) -> list[str]:
    """Return compact runtime-throughput lines for one device result."""
    delivery_intervals = device_result.receive_delivery_intervals_s()
    lines = [
        f"  {device_result.device_alias} = {device_result.device_name}",
        f"    reader_type: {device_result.reader_type}",
        f"    timestamp_mode: {_timestamp_mode(device_result)}",
        f"    frames: {device_result.frame_count}",
        f"    discarded_frames: {device_result.discarded_frame_count}",
        f"    uncaptured_frames: {getattr(device_result, 'uncaptured_frame_count', 0)}",
        "    total_measurement_frames_read: "
        f"{device_result.total_measurement_frames_read}",
        f"    errors: {len(device_result.errors)}",
        f"    reader_duration_s: {_format_float(device_result.read_duration_s)}",
        f"    stored_frame_rate_hz: {_format_float(device_result.stored_frame_rate_hz)}",
        f"    total_frame_rate_hz: {_format_float(device_result.total_frame_rate_hz)}",
        "    total_frame_rate/requested: "
        f"{_format_ratio(device_result.total_frame_rate_hz, requested_sample_rate_hz)}",
        f"    bytes_read: {device_result.bytes_read}",
        f"    byte_rate_Bps: {_format_float(device_result.byte_rate_Bps)}",
        f"    parser_resync_count: {device_result.parser_resync_count}",
        "    max_receive_delivery_interval_ms: "
        f"{_format_ms(max(delivery_intervals) if delivery_intervals else None)}",
    ]
    for error in device_result.errors:
        lines.append(f"    error: {error}")
    return lines


def _timestamp_mode(device_result: Any) -> str:
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
