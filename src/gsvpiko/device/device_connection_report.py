"""Report data structures and formatting for GSV device connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..transport import transport_nport as NPORT


@dataclass(frozen=True)
class BaudrateProbeResult:
    """Result of probing one GSV communication baudrate."""

    baudrate: int
    port_opened: bool
    gsv_responded: bool
    response_raw_hex: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        """Return a plain dictionary representation."""
        return {
            "baudrate": self.baudrate,
            "port_opened": self.port_opened,
            "gsv_responded": self.gsv_responded,
            "response_raw_hex": self.response_raw_hex,
            "error": self.error,
        }


@dataclass(frozen=True)
class DeviceConnectionReport:
    """Report describing how a GSV device was opened."""

    device_name: str
    connection_type: str
    configured_baudrate: int | None = None
    active_baudrate: int | None = None
    baudrate_matches_config: bool | None = None
    com_port: str | None = None
    ip_address: str | None = None
    tcp_port: int | None = None
    used_baudrate_probe: bool = False
    probe_results: list[BaudrateProbeResult] = field(default_factory=list)
    baudrate_setting_index: int | None = None
    stored_baudrate_before: int | None = None
    stored_baudrate_after: int | None = None
    baudrate_setting_matches_config: bool | None = None
    baudrate_setting_write_executed: bool | None = None
    baudrate_setting_error: str | None = None
    baudrate_change_requires_power_cycle: bool = False
    nport_report: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        """Return a plain dictionary representation."""
        return {
            "device_name": self.device_name,
            "connection_type": self.connection_type,
            "configured_baudrate": self.configured_baudrate,
            "active_baudrate": self.active_baudrate,
            "baudrate_matches_config": self.baudrate_matches_config,
            "com_port": self.com_port,
            "ip_address": self.ip_address,
            "tcp_port": self.tcp_port,
            "used_baudrate_probe": self.used_baudrate_probe,
            "probe_results": [result.to_dict() for result in self.probe_results],
            "baudrate_setting_index": self.baudrate_setting_index,
            "stored_baudrate_before": self.stored_baudrate_before,
            "stored_baudrate_after": self.stored_baudrate_after,
            "baudrate_setting_matches_config": self.baudrate_setting_matches_config,
            "baudrate_setting_write_executed": self.baudrate_setting_write_executed,
            "baudrate_setting_error": self.baudrate_setting_error,
            "baudrate_change_requires_power_cycle": self.baudrate_change_requires_power_cycle,
            "nport_report": self.nport_report,
        }


def build_connection_report(
    *,
    device_config: dict[str, Any],
    connection_type: str,
    configured_baudrate: int,
    active_baudrate: int,
    probe_results: list[BaudrateProbeResult],
    nport_report: dict[str, Any] | None = None,
) -> DeviceConnectionReport:
    """Build a connection report from the shared baudrate-probe state."""
    return DeviceConnectionReport(
        device_name=device_config["name"],
        connection_type=connection_type,
        configured_baudrate=configured_baudrate,
        active_baudrate=active_baudrate,
        baudrate_matches_config=active_baudrate == configured_baudrate,
        com_port=device_config.get("com_port"),
        ip_address=device_config.get("ip_address"),
        tcp_port=device_config.get("tcp_port"),
        used_baudrate_probe=active_baudrate != configured_baudrate,
        probe_results=probe_results,
        nport_report=nport_report,
    )


def mark_nport_data_path_verified(
    nport_report: dict[str, Any] | None,
    *,
    mode: str,
    message: str,
) -> dict[str, Any] | None:
    """Mark a requested NPort state as operational when the GSV link works.

    The NPort management path can be unavailable while the requested data path
    is already usable. In that case connection reports should reflect the
    operational data path and keep the management failure as a warning.
    """
    if nport_report is None:
        return None
    if not nport_report.get("requested"):
        return nport_report
    if nport_report.get("mode") != mode:
        return nport_report
    if nport_report.get("ok") is True:
        return nport_report

    updated = dict(nport_report)
    warnings = list(updated.get("warnings") or [])
    previous_error = updated.get("error")
    if previous_error:
        warnings.append(f"NPort management did not confirm the mode change: {previous_error}")
    updated["ok"] = True
    updated["message"] = message
    updated["error"] = None
    updated["warnings"] = warnings
    return updated


def format_nport_report_lines(
    nport_report: dict[str, Any] | None,
) -> list[str]:
    """Return readable NPort-management report lines."""
    if nport_report is None:
        return []

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

    warnings = nport_report.get("warnings") or []
    for warning in warnings:
        lines.append(f"  warning: {warning}")

    transcript_tail = nport_report.get("transcript_tail")
    if transcript_tail:
        lines.append("  transcript_tail:")
        for line in str(transcript_tail).splitlines()[-12:]:
            lines.append(f"    {line}")

    return lines


def format_connection_failure(
    *,
    device_config: dict[str, Any],
    configured_baudrate: int,
    probe_results: list[BaudrateProbeResult],
    nport_report: dict[str, Any] | None = None,
) -> str:
    """Return a readable GSV connection failure summary."""
    lines = [
        f"Could not verify GSV connection for {device_config['name']}.",
        f"com_port: {device_config['com_port']}",
        f"configured baudrate: {configured_baudrate}",
    ]

    if device_config.get("ip_address") is not None:
        lines.append(f"ip_address: {device_config['ip_address']}")

    lines.append("probe_results:")
    for result in probe_results:
        lines.append(
            "  "
            f"baudrate={result.baudrate}, "
            f"port_opened={result.port_opened}, "
            f"gsv_responded={result.gsv_responded}, "
            f"response={result.response_raw_hex or '<none>'}, "
            f"error={result.error or '<none>'}"
        )

    lines.extend(format_nport_report_lines(nport_report))

    return "\n".join(lines)
