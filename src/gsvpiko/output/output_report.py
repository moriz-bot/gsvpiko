"""Reusable text reports for recording sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..device.device_connection import BaudrateProbeResult
from ..runtime.runtime_report import format_runtime_summary
from ..transport import transport_nport as NPORT
from ..coordination.coordination_recording import RecordingRunResult
from ..coordination.coordination_setup_application import format_setup_application_warning
from .output_csv import RecordingFileContext


def format_probe_result(
    result: BaudrateProbeResult,
) -> str:
    """Return one baudrate-probe line."""
    line = (
        f"{result.baudrate:>6} baud | "
        f"port_opened={result.port_opened!s:<5} | "
        f"gsv_responded={result.gsv_responded!s:<5} | "
        f"response={result.response_raw_hex or '<none>'}"
    )
    if result.error:
        line += f"\n    {result.error}"
    return line


def format_recording_report(
    *,
    recording_result: RecordingRunResult,
    session_name: str,
    file_context: RecordingFileContext | None = None,
    zero_before_recording: bool | None = None,
    probe_results: list[BaudrateProbeResult] | None = None,
) -> str:
    """Return the complete text report for one recording session."""
    lines: list[str] = []
    _extend_section(lines, "Recording session", _format_session_lines(
        recording_result=recording_result,
        session_name=session_name,
        file_context=file_context,
        zero_before_recording=zero_before_recording,
    ))

    if probe_results:
        _extend_section(lines, "Connection probe", [
            format_probe_result(result)
            for result in probe_results
        ])

    if recording_result.connection_reports:
        for report in recording_result.connection_reports:
            lines.extend(_format_connection_report(report))
            lines.append("")

    if recording_result.application_warnings:
        _extend_section(lines, "Application warnings", [
            format_setup_application_warning(warning)
            for warning in recording_result.application_warnings
        ])

    runtime_result = recording_result.runtime_result
    if runtime_result is not None:
        _extend_section(lines, "Runtime events", _format_event_lines(runtime_result.events))
        lines.append(
            format_runtime_summary(
                runtime_result,
                expected_sample_rate_hz=recording_result.resolved_setup.sample_rate_hz,
            )
        )
        lines.append("")
        _extend_section(lines, "Runtime command reports", _format_command_reports(runtime_result))
        _extend_section(lines, "First and last stored records", _format_first_last_records(runtime_result))

    return "\n".join(lines).rstrip() + "\n"


def write_recording_report(
    *,
    report_text: str,
    file_context: RecordingFileContext,
) -> Path:
    """Write a report text to its report path."""
    file_context.report_path.parent.mkdir(parents=True, exist_ok=True)
    file_context.report_path.write_text(report_text, encoding="utf-8")
    return file_context.report_path


def _format_session_lines(
    *,
    recording_result: RecordingRunResult,
    session_name: str,
    file_context: RecordingFileContext | None,
    zero_before_recording: bool | None,
) -> list[str]:
    """Return high-level session lines."""
    resolved = recording_result.resolved_setup
    lines = [
        f"session_name: {session_name}",
        f"setup_name: {resolved.name}",
        f"sample_rate_hz: {resolved.sample_rate_hz:g}",
        f"analog_filter_hz: {resolved.analog_filter_hz}",
        f"digital_filter: {resolved.digital_filter if resolved.digital_filter is not None else 'off'}",
        f"discard_initial_frames: {resolved.discard_initial_frames}",
    ]
    if zero_before_recording is not None:
        lines.append(f"zero_before_recording: {str(bool(zero_before_recording)).lower()}")
    if file_context is not None:
        lines.extend(
            [
                f"session_id: {file_context.session_id}",
                f"csv_path: {file_context.csv_path}",
                f"report_path: {file_context.report_path}",
                f"graph_path: {file_context.graph_path}",
            ]
        )
    return lines


def _format_connection_report(report: Any) -> list[str]:
    """Return readable lines for one stored connection report object."""
    if report is None:
        return []

    lines = [
        "Connection",
        "----------",
        f"device_name: {report.device_name}",
        f"connection_type: {report.connection_type}",
    ]
    if report.com_port is not None:
        lines.append(f"com_port: {report.com_port}")
    if report.configured_baudrate is not None:
        lines.append(
            "baudrate: "
            f"configured={report.configured_baudrate}, "
            f"active={report.active_baudrate}, "
            f"matches={report.baudrate_matches_config}"
        )
    if report.ip_address is not None:
        lines.append(f"ip_address: {report.ip_address}")
    if report.tcp_port is not None:
        lines.append(f"tcp_port: {report.tcp_port}")

    if report.nport_report is not None:
        lines.extend(_format_nport_report(report.nport_report))

    if report.used_baudrate_probe:
        lines.append("baudrate_probe: used")

    if report.baudrate_setting_index is not None:
        lines.append(
            "stored_baudrate: "
            f"index={report.baudrate_setting_index}, "
            f"before={report.stored_baudrate_before}, "
            f"after={report.stored_baudrate_after}, "
            f"matches_config={report.baudrate_setting_matches_config}"
        )
        lines.append(
            "stored_baudrate_note: new value becomes active after the next power cycle"
        )

    if report.baudrate_setting_error is not None:
        lines.append(f"stored_baudrate_error: {report.baudrate_setting_error}")

    return lines


def _format_nport_report(nport_report: dict[str, Any]) -> list[str]:
    """Return readable NPort-management report lines."""
    lines = [
        "nport:",
        (
            "  "
            f"requested={nport_report.get('requested')}, "
            f"attempted={nport_report.get('attempted')}, "
            f"ok={nport_report.get('ok')}"
        ),
    ]
    for key in (
        "mode",
        "ip_address",
        "baudrate",
        "tcp_port",
        "command_port",
        "message",
        "error",
    ):
        value = nport_report.get(key)
        if key == "mode":
            value = NPORT.format_nport_mode(value)
        if value is not None and value != "":
            lines.append(f"  {key}: {value}")

    for warning in nport_report.get("warnings") or []:
        lines.append(f"  warning: {warning}")

    transcript_tail = nport_report.get("transcript_tail")
    if transcript_tail:
        lines.append("  transcript_tail:")
        for line in str(transcript_tail).splitlines()[-12:]:
            lines.append(f"    {line}")
    return lines


def _format_event_lines(events: dict[str, Any]) -> list[str]:
    """Return runtime event timestamps."""
    if not events:
        return ["<none>"]
    return [f"{key}: {value}" for key, value in sorted(events.items())]


def _format_command_reports(runtime_result: Any) -> list[str]:
    """Return compact Start/Stop/SetZero command report lines."""
    lines: list[str] = []
    for label, reports in (
        ("SetZero before recording", runtime_result.tare_reports),
        ("StartTransmission", runtime_result.start_reports),
        ("StopTransmission", runtime_result.stop_reports),
    ):
        if not reports:
            continue
        lines.append(f"{label} reports")
        for report in reports:
            if report["ok"]:
                raw_hex = report["response"].get("raw_hex")
                lines.append(f"  {report['device_alias']}: ok=True response={raw_hex}")
            else:
                lines.append(f"  {report['device_alias']}: ok=False error={report['error']}")

    runtime_command_lines = _format_runtime_routed_command_reports(runtime_result)
    if runtime_command_lines:
        lines.append("Runtime command reports")
        lines.extend(runtime_command_lines)

    return lines or ["<none>"]


def _format_runtime_routed_command_reports(runtime_result: Any) -> list[str]:
    """Return command reports generated by runtime frame routers."""
    lines: list[str] = []
    for device_result in runtime_result.device_results:
        for report in device_result.runtime_command_reports:
            duration = report.get("duration_ms")
            duration_text = "-" if duration is None else f"{float(duration):.3f} ms"
            lines.append(
                f"  {device_result.device_alias}: "
                f"command={report.get('command_name')} "
                f"group={report.get('command_group_id')} "
                f"ok={report.get('ok')} "
                f"duration={duration_text}"
            )
            lines.append(
                "    discarded_before_stop_response="
                f"{report.get('discarded_measurement_frames_before_stop_response')} "
                "discarded_after_restart="
                f"{report.get('discarded_measurement_frames_after_restart')} "
                "restart_discard_requested="
                f"{report.get('restart_discard_frames_requested')} "
                "timebase_restarted="
                f"{report.get('timebase_restarted')}"
            )
            for key in (
                "stop_response_raw_hex",
                "set_zero_response_raw_hex",
                "start_response_raw_hex",
            ):
                if report.get(key):
                    lines.append(f"    {key}: {report[key]}")
            if report.get("error"):
                lines.append(f"    error: {report['error']}")
    return lines


def _format_first_last_records(runtime_result: Any) -> list[str]:
    """Return compact first/last channel snapshots for each device."""
    lines: list[str] = []
    for device_result in runtime_result.device_results:
        lines.append(f"{device_result.device_alias} = {device_result.device_name}")
        if not device_result.records:
            lines.append("  no records")
            continue

        for label, record in (
            ("first", device_result.records[0]),
            ("last", device_result.records[-1]),
        ):
            channels = ", ".join(
                f"{channel_name}={value}"
                for channel_name, value in record.channels.items()
            )
            lines.append(
                f"  {label}: frame={record.frame_index}, "
                f"timestamp_unix_s={record.timestamp_unix_s:.6f}, "
                f"channels: {channels}"
            )
    return lines


def _extend_section(lines: list[str], title: str, body_lines: list[str]) -> None:
    """Append a titled report section."""
    lines.append(title)
    lines.append("-" * len(title))
    lines.extend(body_lines)
    lines.append("")
