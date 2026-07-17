"""Reusable connection and admin diagnostics for GSV setups.

The functions in this module are intentionally non-mutating: they do not change
NPort settings, do not write GSV baudrate settings, and do not clear error
memory. Apps and external interfaces can reuse the same diagnostics instead of
keeping diagnostic logic in app modules.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..constants import constants_baudrates as BAUDRATE
from ..constants import constants_errors as ERROR
from ..constants import constants_errors_value as VALUE_ERROR
from ..device.device_gsv import GsvDevice
from ..transport.transport_serial import SerialTransport
from ..transport.transport_tcp import TcpTransport
from ..utils.utils_hex import to_hex
from .coordination_setup_resolution import ResolvedDevice, resolve_setup

DEFAULT_ERROR_INDICES = (0, 1)
PROTOCOL_ERROR_INDICES = (0, 1)
VALUE_ERROR_HISTORY_INDICES = tuple(range(84))
DEFAULT_HISTORY_WINDOW_H = 4.0
AGE_TOLERANCE_MIN = 1.0
TCP_FIRST = True
ADMIN_TCP_VERIFY_TIMEOUT_S = 1.0
ADMIN_SERIAL_VERIFY_TIMEOUT_S = 1.0



@dataclass
class DiagnosticConnectionAttempt:
    """One non-mutating connection attempt for admin diagnostics."""

    connection_type: str
    endpoint: str
    baudrate: int | None = None
    device_hours_h: float | None = None
    opened: bool = False
    responded: bool = False
    response_raw_hex: str | None = None
    error: str | None = None

    def to_token(self) -> str:
        """Return one compact token for external one-line diagnostics."""
        baudrate = self.baudrate if self.baudrate is not None else "na"
        return (
            f"{self.connection_type}@{self.endpoint}"
            f"/baudrate={baudrate}"
            f"/opened={self.opened}"
            f"/responded={self.responded}"
        )


@dataclass
class DiagnosticOpenResult:
    """Result of opening one device for non-mutating admin diagnostics."""

    device: GsvDevice
    connection_type: str
    endpoint: str
    baudrate: int | None
    attempts: list[DiagnosticConnectionAttempt]


@dataclass
class DeviceDiagnostics:
    """Diagnostics collected for one resolved setup device."""

    device_alias: str
    device_name: str
    attempts: list[DiagnosticConnectionAttempt] = field(default_factory=list)
    connection_type: str | None = None
    endpoint: str | None = None
    baudrate: int | None = None
    device_hours_h: float | None = None
    opened: bool = False
    responded: bool = False
    mode_flags: int | None = None
    software_configuration_flags: int | None = None
    protocol_errors: list[dict[str, Any]] = field(default_factory=list)
    value_errors: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether the diagnostic connection answered."""
        return self.opened and self.responded and not self.error


def diagnose_setup_connection(
    setup_config: dict[str, Any],
) -> list[DeviceDiagnostics]:
    """Try non-mutating diagnostic connections for all setup devices."""
    return _diagnose_setup(setup_config, read_error_memory=False)


def diagnose_setup_errors(
    setup_config: dict[str, Any],
    *,
    error_indices: tuple[int, ...] = DEFAULT_ERROR_INDICES,
) -> list[DeviceDiagnostics]:
    """Read non-destructive admin/status/error diagnostics for all setup devices."""
    return _diagnose_setup(
        setup_config,
        read_error_memory=True,
        error_indices=error_indices,
    )


def format_connection_diagnostics_token(results: list[DeviceDiagnostics]) -> str:
    """Return a compact single-line connection-diagnostic summary."""
    tokens = []
    for result in results:
        if result.ok:
            baudrate = result.baudrate if result.baudrate is not None else "na"
            tokens.append(
                f"{result.device_alias}:ok:{result.connection_type}@{result.endpoint}:baudrate={baudrate}"
            )
        else:
            tokens.append(f"{result.device_alias}:err:{_compact_error(result.error)}")
    return ",".join(tokens)


def format_error_diagnostics_token(
    results: list[DeviceDiagnostics],
    *,
    history_window_h: float = DEFAULT_HISTORY_WINDOW_H,
) -> str:
    """Return a compact single-line admin/error diagnostic summary."""
    tokens = []
    for result in results:
        if not result.ok:
            tokens.append(f"{result.device_alias}:err:{_compact_error(result.error)}")
            continue

        protocol_summary = _format_protocol_error_summary(result.protocol_errors)
        value_summary = _format_value_error_summary(
            result.value_errors,
            device_hours_h=result.device_hours_h,
            history_window_h=history_window_h,
        )
        tokens.append(
            f"{result.device_alias}:ok:protocol_error:{protocol_summary};"
            f"value_error:{value_summary}"
        )
    return ",".join(tokens)


def format_device_status_error_report_lines(
    result: DeviceDiagnostics,
) -> list[str]:
    """Return readable multi-line diagnostics for one setup device."""
    title = f"{result.device_alias} = {result.device_name}"
    lines = [
        title,
        "-" * len(title),
        "Diagnostic connection",
        "---------------------",
    ]
    if result.ok:
        lines.extend(
            [
                f"connection_type: {result.connection_type}",
                f"endpoint: {result.endpoint}",
                f"baudrate: {result.baudrate if result.baudrate is not None else '<not-applicable>'}",
                "nport_management: not attempted",
                "gsv_baudrate_write: not attempted",
            ]
        )
    else:
        lines.append(f"connection_error: {result.error or 'unknown'}")

    if result.attempts:
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

    lines.append("")
    lines.extend(_format_admin_status_lines(result))
    if result.protocol_errors:
        lines.append("")
        lines.extend(_format_protocol_error_lines(result.protocol_errors))
    if result.value_errors:
        lines.append("")
        lines.extend(_format_value_error_lines(result.value_errors))
    return lines


def _format_admin_status_lines(result: DeviceDiagnostics) -> list[str]:
    """Return mode/software-configuration lines."""
    lines = [
        "GetMode (0x26)",
        "--------------",
        f"mode_flags: {_format_hex_or_none(result.mode_flags)}",
        "",
        "GetSoftwareConfiguration (0x2A)",
        "-------------------------------",
        f"software_configuration_flags: {_format_hex_or_none(result.software_configuration_flags)}",
    ]
    return lines


def _format_protocol_error_lines(entries: list[dict[str, Any]]) -> list[str]:
    """Return readable protocol-error memory lines."""
    lines = []
    for entry in entries:
        index = entry.get("index", "?")
        lines.extend(
            [
                f"GetLastProtocolError (0x42), index={index}",
                "------------------------------------",
            ]
        )
        if "diagnostic_error" in entry:
            lines.append(f"diagnostic_error: {entry['diagnostic_error']}")
        else:
            lines.extend(
                [
                    f"raw_hex: {entry.get('raw_hex', '<none>')}",
                    f"request_raw_hex: {entry.get('request_raw_hex', '<none>')}",
                    f"status: 0x{int(entry.get('status', 0)):02X}",
                    f"payload_hex: {entry.get('payload_hex', '<none>')}",
                    f"value_uint32: {_format_uint32(entry.get('value_uint32'))}",
                    (
                        "decoded_protocol_error: "
                        f"{entry.get('decoded_error_name', 'unknown')} - "
                        f"{entry.get('decoded_error_description', 'Unknown GSV protocol error.')}"
                    ),
                ]
            )
        lines.append("")
    return lines[:-1] if lines and lines[-1] == "" else lines


def _format_value_error_lines(entries: list[dict[str, Any]]) -> list[str]:
    """Return readable value-error memory lines."""
    lines = []
    for entry in entries:
        index = entry.get("index", "?")
        lines.extend(
            [
                f"GetLastValueError (0x43), index={index}",
                "---------------------------------",
            ]
        )
        if "diagnostic_error" in entry:
            lines.append(f"diagnostic_error: {entry['diagnostic_error']}")
        else:
            lines.extend(
                [
                    f"raw_hex: {entry.get('raw_hex', '<none>')}",
                    f"request_raw_hex: {entry.get('request_raw_hex', '<none>')}",
                    f"status: 0x{int(entry.get('status', 0)):02X}",
                    f"payload_hex: {entry.get('payload_hex', '<none>')}",
                    f"decoded_summary: {entry.get('decoded_summary', '<none>')}",
                ]
            )
            if entry.get("decoded_power_on_error_count") is not None:
                lines.append(
                    "decoded_counters: "
                    f"power_on={entry.get('decoded_power_on_error_count')}, "
                    f"nonvolatile={entry.get('decoded_nonvolatile_error_count')}"
                )
            if entry.get("decoded_error_type") is not None:
                lines.extend(
                    [
                        (
                            "decoded_error_type: "
                            f"{entry.get('decoded_error_type_name')} - "
                            f"{entry.get('decoded_error_type_description')}"
                        ),
                        f"decoded_error_time_min: {entry.get('decoded_error_time_min', '<none>')}",
                        f"decoded_error_time_h: {_format_float_or_none(entry.get('decoded_error_time_h'))}",
                        f"decoded_error_flags: {_format_flags(entry.get('decoded_error_flags'))}",
                    ]
                )
                flag_details = VALUE_ERROR.compact_value_error_details(entry)
                if flag_details:
                    lines.append(f"decoded_error_flag_details: {flag_details}")
        lines.append("")
    return lines[:-1] if lines and lines[-1] == "" else lines


def _format_protocol_error_summary(entries: list[dict[str, Any]]) -> str:
    """Return compact protocol-error summary for one-line output."""
    parts = []
    for entry in entries:
        if "diagnostic_error" in entry:
            parts.append(f"i{entry.get('index', '?')}: {entry['diagnostic_error']}")
            continue
        parts.append(
            f"i{entry.get('index', '?')}: "
            f"{entry.get('decoded_error_name', 'unknown')}"
        )
    return "; ".join(parts) if parts else "unknown"


def _format_value_error_summary(
    entries: list[dict[str, Any]],
    *,
    device_hours_h: float | None = None,
    history_window_h: float = DEFAULT_HISTORY_WINDOW_H,
) -> str:
    """Return compact value-error summary for one-line output."""
    if not entries:
        return "unknown"

    parts = []
    power_on_count = 0
    history_count: int | None = None
    index1_seen = False

    for entry in entries:
        if entry.get("index") != 0 or "diagnostic_error" in entry:
            continue
        power_on_count = int(entry.get("decoded_power_on_error_count") or 0)
        history_count = int(entry.get("decoded_nonvolatile_error_count") or 0)
        parts.append(f"counters(power_on={power_on_count},history={history_count})")
        break

    for entry in entries:
        if entry.get("index") != 1:
            continue
        index1_seen = True
        if "diagnostic_error" in entry:
            parts.append(f"current_and_not_saved={_compact_error(entry['diagnostic_error'])}")
        else:
            name = entry.get("decoded_error_type_name", "unknown")
            if name == "NO_CURRENT_VALUE_ERROR":
                parts.append("current_and_not_saved=none")
            else:
                parts.append(f"current_and_not_saved={name}")
        break

    if not index1_seen:
        parts.append("current_and_not_saved=unknown")

    history_entries = _selected_value_history_entries(
        entries,
        power_on_count=power_on_count,
        device_hours_h=device_hours_h,
        history_window_h=history_window_h,
    )
    if history_entries:
        formatted_history = []
        for entry in history_entries:
            name = entry.get("decoded_error_type_name", "unknown")
            age_min = _value_error_age_min(entry, device_hours_h)
            age_text = "age_min=unknown" if age_min is None else f"age_min={age_min:.1f}"
            formatted_history.append(f"i{entry.get('index','?')}:{name}({age_text})")
        parts.append("history_entries=" + "|".join(formatted_history))
    else:
        parts.append("history_entries=none")

    return ";".join(parts)


def _selected_value_history_entries(
    entries: list[dict[str, Any]],
    *,
    power_on_count: int,
    device_hours_h: float | None,
    history_window_h: float,
) -> list[dict[str, Any]]:
    """Select history entries analogous to the default diagnostic app view."""
    history = [entry for entry in entries if _is_real_value_history_entry(entry)]
    if not history:
        return []

    if power_on_count > 0:
        newest_indices = {
            int(entry["index"])
            for entry in sorted(history, key=lambda item: int(item.get("index") or -1))[-power_on_count:]
        }
    else:
        newest_indices = set()
    selected: list[dict[str, Any]] = []
    for entry in history:
        index = int(entry.get("index") or -1)
        age_min = _value_error_age_min(entry, device_hours_h)
        if index in newest_indices or (
            age_min is not None and age_min <= history_window_h * 60.0
        ):
            selected.append(entry)
    return selected


def _is_real_value_history_entry(entry: dict[str, Any]) -> bool:
    """Return whether an entry is a real nonvolatile value-error history entry."""
    index = entry.get("index")
    if not isinstance(index, int) or index < 2:
        return False
    if "diagnostic_error" in entry:
        return False
    name = entry.get("decoded_error_type_name")
    return name not in {None, "NO_CURRENT_VALUE_ERROR"}


def _value_error_age_min(entry: dict[str, Any], device_hours_h: float | None) -> float | None:
    """Return age in minutes with a small tolerance for minute/hour rounding."""
    error_time_min = entry.get("decoded_error_time_min")
    if not isinstance(error_time_min, (int, float)) or device_hours_h is None:
        return None
    device_hours_min = float(device_hours_h) * 60.0
    if float(error_time_min) > device_hours_min + AGE_TOLERANCE_MIN:
        return None
    return max(0.0, device_hours_min - float(error_time_min))

def _format_hex_or_none(value: int | None) -> str:
    """Return one integer as hex/decimal text."""
    if value is None:
        return "<none>"
    return f"0x{int(value):08X} ({int(value)})"


def _format_uint32(value: object) -> str:
    """Return one optional uint32 value."""
    if not isinstance(value, int):
        return "<none>"
    return f"0x{value:08X} ({value})"


def _format_flags(value: object) -> str:
    """Return one optional 16-bit flag field."""
    if not isinstance(value, int):
        return "<none>"
    return f"0x{value:04X}"


def _format_float_or_none(value: object) -> str:
    """Return one optional float value."""
    if value is None:
        return "<none>"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _diagnose_setup(
    setup_config: dict[str, Any],
    *,
    read_error_memory: bool,
    error_indices: tuple[int, ...] = DEFAULT_ERROR_INDICES,
) -> list[DeviceDiagnostics]:
    resolved_setup = resolve_setup(setup_config)
    results: list[DeviceDiagnostics] = []

    for resolved_device in resolved_setup.devices:
        device_config = _diagnostic_device_config(resolved_device, resolved_setup.baudrate)
        diagnostic = DeviceDiagnostics(
            device_alias=resolved_device.alias,
            device_name=device_config["name"],
        )
        open_result: DiagnosticOpenResult | None = None
        try:
            open_result = _open_best_available_connection(device_config)
            diagnostic.attempts = list(open_result.attempts)
            diagnostic.connection_type = open_result.connection_type
            diagnostic.endpoint = open_result.endpoint
            diagnostic.baudrate = open_result.baudrate
            diagnostic.opened = True
            diagnostic.responded = True
            _read_admin_status(open_result.device, diagnostic)
            _read_device_hours(open_result.device, diagnostic)
            if read_error_memory:
                _read_error_memory(open_result.device, diagnostic, error_indices)
        except Exception as error:
            diagnostic.attempts = [] if open_result is None else list(open_result.attempts)
            diagnostic.error = str(error)
        finally:
            if open_result is not None:
                open_result.device.close()
        results.append(diagnostic)

    return results


def _diagnostic_device_config(
    resolved_device: ResolvedDevice,
    baudrate: int,
) -> dict[str, Any]:
    """Return a device config copy with setup-level baudrate for diagnostics."""
    device_config = deepcopy(resolved_device.device_config)
    device_config["default_baudrate"] = int(baudrate)
    return device_config


def _open_best_available_connection(device_config: dict[str, Any]) -> DiagnosticOpenResult:
    """Open a GSV over the currently reachable path without changing settings."""
    attempts: list[DiagnosticConnectionAttempt] = []
    openers = (
        (_try_tcp_connection, _try_serial_connections)
        if TCP_FIRST else
        (_try_serial_connections, _try_tcp_connection)
    )

    for opener in openers:
        result = opener(device_config, attempts)
        if result is not None:
            return result

    raise RuntimeError(_format_attempt_failure(device_config, attempts))


def _try_tcp_connection(
    device_config: dict[str, Any],
    attempts: list[DiagnosticConnectionAttempt],
) -> DiagnosticOpenResult | None:
    """Try the configured NPort TCP data socket once."""
    ip_address = device_config.get("ip_address")
    tcp_port = device_config.get("tcp_port")
    if not ip_address or tcp_port is None:
        return None

    attempt = DiagnosticConnectionAttempt(
        connection_type="tcp",
        endpoint=f"{ip_address}:{tcp_port}",
        baudrate=None,
    )
    attempts.append(attempt)
    device = GsvDevice(
        TcpTransport(str(ip_address), int(tcp_port), ADMIN_TCP_VERIFY_TIMEOUT_S),
        name=device_config["name"],
    )
    try:
        device.open()
        attempt.opened = True
        response = device.admin.read_mode_flags()
        attempt.responded = True
        attempt.response_raw_hex = response.get("raw_hex")
        return DiagnosticOpenResult(
            device=device,
            connection_type="tcp",
            endpoint=attempt.endpoint,
            baudrate=None,
            attempts=attempts,
        )
    except Exception as error:
        attempt.error = str(error)
        device.close()
        return None


def _try_serial_connections(
    device_config: dict[str, Any],
    attempts: list[DiagnosticConnectionAttempt],
) -> DiagnosticOpenResult | None:
    """Try the configured Real COM port using non-mutating baudrate probes."""
    com_port = device_config.get("com_port")
    if not com_port:
        return None

    if device_config.get("default_baudrate") is None:
        raise RuntimeError(
            f"Diagnostic device config {device_config.get('name', '<unnamed>')!r} "
            "does not define default_baudrate."
        )

    preferred_baudrate = int(device_config["default_baudrate"])
    for baudrate in BAUDRATE.build_probe_order(preferred_baudrate):
        attempt = DiagnosticConnectionAttempt(
            connection_type="serial",
            endpoint=str(com_port),
            baudrate=int(baudrate),
        )
        attempts.append(attempt)
        device = GsvDevice(
            SerialTransport(str(com_port), int(baudrate), ADMIN_SERIAL_VERIFY_TIMEOUT_S),
            name=device_config["name"],
        )
        try:
            device.open()
            attempt.opened = True
            response = device.admin.read_mode_flags()
            attempt.responded = True
            attempt.response_raw_hex = response.get("raw_hex")
            return DiagnosticOpenResult(
                device=device,
                connection_type="serial",
                endpoint=attempt.endpoint,
                baudrate=int(baudrate),
                attempts=attempts,
            )
        except Exception as error:
            attempt.error = str(error)
            device.close()
            continue

    return None


def _read_admin_status(device: GsvDevice, diagnostic: DeviceDiagnostics) -> None:
    """Read status/configuration admin values."""
    mode_response = _safe_call(device.admin.read_mode_flags)
    if "diagnostic_error" not in mode_response:
        value = mode_response.get("mode_flags")
        if isinstance(value, int):
            diagnostic.mode_flags = value

    software_response = _safe_call(device.admin.read_software_configuration)
    if "diagnostic_error" not in software_response:
        value = software_response.get("software_configuration_flags")
        if isinstance(value, int):
            diagnostic.software_configuration_flags = value


def _read_device_hours(device: GsvDevice, diagnostic: DeviceDiagnostics) -> None:
    """Read the absolute device-hour counter if available."""
    response = _safe_call(device.admin.read_device_hours, 0)
    value = response.get("device_hours_h")
    if isinstance(value, (int, float)):
        diagnostic.device_hours_h = float(value)


def _read_error_memory(
    device: GsvDevice,
    diagnostic: DeviceDiagnostics,
    error_indices: tuple[int, ...],
) -> None:
    """Read non-destructive protocol and value-error entries."""
    for index in PROTOCOL_ERROR_INDICES:
        response = _safe_call(device.admin.read_last_protocol_error, index)
        response["index"] = index
        _decode_protocol_error(response)
        diagnostic.protocol_errors.append(response)

    for index in error_indices:
        response = _safe_call(device.admin.read_last_value_error, index)
        response["index"] = index
        _decode_value_error(response)
        diagnostic.value_errors.append(response)


def _safe_call(func, *args) -> dict[str, Any]:
    """Call one diagnostic method and return either a response or an error dict."""
    try:
        return func(*args)
    except Exception as error:
        return {"diagnostic_error": str(error)}


def _decode_protocol_error(response: dict[str, Any]) -> None:
    """Add decoded protocol-error fields if possible."""
    value = response.get("value_uint32")
    if not isinstance(value, int):
        return
    error_byte = value & 0xFF
    error = ERROR.protocol_error_from_code(error_byte)
    response["decoded_error_byte"] = error_byte
    response["decoded_error_name"] = (
        error.name if error is not None else f"UNKNOWN_PROTOCOL_ERROR_0x{error_byte:02X}"
    )
    response["decoded_error_description"] = (
        error.description if error is not None else "Unknown GSV protocol error."
    )


def _decode_value_error(response: dict[str, Any]) -> None:
    """Add decoded GSV-8 value-error fields if possible."""
    payload = response.get("payload")
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != 6:
        return

    response.update(
        VALUE_ERROR.decode_value_error_payload(
            payload,
            index=response.get("index"),
        )
    )


def _summarize_error_entries(
    entries: list[dict[str, Any]],
    *,
    value_key: str,
    ok_value: int,
) -> str:
    """Return ok/error/mixed for decoded diagnostic entries."""
    values = [entry.get(value_key) for entry in entries if "diagnostic_error" not in entry]
    if not values:
        return "unknown"
    if all(value == ok_value for value in values):
        return "ok"
    return "present"


def _format_attempt_failure(
    device_config: dict[str, Any],
    attempts: list[DiagnosticConnectionAttempt],
) -> str:
    """Return a readable summary when no non-mutating connection worked."""
    lines = [
        f"Could not open a non-mutating diagnostic connection for {device_config['name']}.",
        "attempts:",
    ]
    for attempt in attempts:
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
    return "\n".join(lines)


def _compact_error(error: object) -> str:
    """Return compact error text for single-line protocol responses."""
    text = str(error or "unknown")
    return text.replace("\r", " ").replace("\n", " ").replace(",", ";")[:180]
