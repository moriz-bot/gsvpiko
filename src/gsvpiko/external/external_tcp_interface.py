"""External TCP control interface for GSVpiko."""

from __future__ import annotations

from dataclasses import dataclass, field
import socket
from threading import Event, RLock, Thread
from typing import Any

from ..config import config_setups as SETUP
from ..coordination.coordination_diagnostics import (
    DEFAULT_HISTORY_WINDOW_H,
    VALUE_ERROR_HISTORY_INDICES,
    diagnose_setup_connection,
    diagnose_setup_errors,
    format_connection_diagnostics_token,
    format_error_diagnostics_token,
)
from ..coordination.coordination_recording import (
    PreparedRecordingSession,
    close_prepared_recording_session,
    prepare_recording_session,
    start_prepared_continuous_session,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..coordination.coordination_setup_validation import (
    evaluate_setup_validation_status,
    format_setup_validation_token,
)
from ..output.output_csv import (
    RecordingFileContext,
    build_recording_file_context,
    read_csv_preview,
    write_recording_csv,
)
from ..output.output_paths import (
    reset_persistent_output_paths,
    resolve_output_directories,
    set_persistent_output_path,
)
from ..output.output_plot import plot_gsvpiko_csv
from ..output.output_report import format_recording_report, write_recording_report
from ..runtime.runtime_session import ContinuousRuntimeSession, run_runtime_set_zero_cycle_concurrently
from ..utils.utils_duration import parse_optional_duration
from .external_ascii_protocol import ExternalCommand, err, ok, parse_command

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5050
DEFAULT_SETUP_KEY = "TWO_GSVS_TWO_SENSORS_EACH"

HELP_TEXT = (
    "OK HELP "
    "PING: check connection and protocol info; "
    "ECHO <text>: return text for client/debug tests; "
    "HELP: list commands; "
    "STATUS: show interface state and selected setup; "
    "PATH: show active output folders; "
    "PATH SET DATA <dir>: set persistent CSV/plot output folder; "
    "PATH SET LOGS <dir>: set persistent report output folder; "
    "PATH RESET: reset persistent output folders; "
    "SETUP LIST: list available setup keys; "
    "SETUP: show selected setup; "
    "SETUP USE <setup_key>: select setup; "
    "SESSION <session_name> or SESSION session=<name>: tare if configured and start transmission; "
    "START: start recording samples; "
    "START 20 S or START 20S: record for a duration, then stop automatically; "
    "STOP: pause recording while transmission continues; "
    "TARE or SET_ZERO: run SetZero and mark the event during an active session; "
    "SAVE: stop transmission and write CSV/report/plot; "
    "CSV: show compact CSV preview; "
    "CSV PATH: show last CSV path; "
    "REPORT: show compact last report text; "
    "REPORT PATH: show last report path; "
    "DIAG CONNECTION: check non-mutating current connection paths in IDLE state; "
    "DIAG ERRORS or DIAG ERROR: read non-destructive GSV admin/error diagnostics in IDLE state; "
    "QUIT: save active session if needed and close connection"
)


@dataclass
class ExternalTcpInterfaceState:
    """Mutable state for one external TCP control session."""

    setup_key: str = DEFAULT_SETUP_KEY
    prepared_session: PreparedRecordingSession | None = None
    continuous_session: ContinuousRuntimeSession | None = None
    session_name: str | None = None
    file_context: RecordingFileContext | None = None
    report_text: str | None = None
    graph_path: object | None = None
    capture_timer_cancel: Event | None = None
    capture_timer_thread: Thread | None = None
    lock: RLock = field(default_factory=RLock)

    @property
    def setup_config(self) -> dict[str, Any]:
        """Return the active setup configuration."""
        return _get_setup_config(self.setup_key)

    @property
    def state_name(self) -> str:
        """Return a compact state name for STATUS."""
        if self.continuous_session is not None and self.continuous_session.is_capturing:
            return "RECORDING"
        if self.continuous_session is not None:
            return "SESSION"
        return "IDLE"


def run_server(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the external TCP control server until Ctrl+C stops it."""
    stop_event = Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, int(port)))
        server_socket.listen(1)
        server_socket.settimeout(0.5)
        print(f"GSVpiko external TCP interface listening on {host}:{port}")
        print("Stop the server app with Ctrl+C in this terminal.")
        try:
            while not stop_event.is_set():
                try:
                    connection, address = server_socket.accept()
                except socket.timeout:
                    continue
                with connection:
                    print(f"External control client connected: {address[0]}:{address[1]}")
                    try:
                        _serve_connection(connection, stop_event=stop_event)
                    except OSError as error:
                        print(
                            "External control client connection ended with socket error: "
                            f"{error}"
                        )
                    finally:
                        print("External control client disconnected.")
        except KeyboardInterrupt:
            stop_event.set()
            print("\nGSVpiko external TCP interface stopped by Ctrl+C.")
        if stop_event.is_set():
            print("GSVpiko external TCP interface stopped.")


def _serve_connection(connection: socket.socket, *, stop_event: Event) -> None:
    """Serve one TCP client until QUIT, Ctrl+C, or disconnect."""
    state = ExternalTcpInterfaceState()
    buffer = b""
    connection.settimeout(0.5)
    try:
        while not stop_event.is_set():
            try:
                chunk = connection.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break

            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                command_line = line.decode("utf-8", errors="replace").strip()
                response = handle_command(command_line, state)
                if not _write_response(connection, response):
                    return
                try:
                    should_quit = parse_command(command_line).name == "QUIT"
                except ValueError:
                    should_quit = False
                if should_quit or stop_event.is_set():
                    return

            if len(buffer) > 65536:
                if not _write_response(connection, err("COMMAND_TOO_LONG")):
                    return
                buffer = b""
    finally:
        _cleanup_state(state)


def handle_command(line: str, state: ExternalTcpInterfaceState) -> str:
    """Handle one external ASCII command and return a response string."""
    try:
        command = parse_command(line)
        if not command.name:
            return err("EMPTY_COMMAND")
        if command.name == "PING":
            return ok("PONG", protocol="ascii", encoding="utf-8")
        if command.name == "ECHO":
            return ok("ECHO", text=_echo_text(command.raw))
        if command.name == "HELP":
            return HELP_TEXT
        if command.name == "STATUS":
            return _handle_status(state)
        if command.name in {"PATH", "PATH SET", "PATH RESET"}:
            return _handle_path(command, state)
        if command.name == "SETUP LIST":
            return ok("SETUP_LIST", setups=_setup_list_text())
        if command.name == "SETUP":
            return ok("SETUP", current=state.setup_key, validation=_setup_validation(state.setup_key))
        if command.name == "SETUP USE":
            return _handle_setup_use(command, state)
        if command.name == "SESSION":
            return _handle_session(command, state)
        if command.name == "START":
            return _handle_start(command, state)
        if command.name == "STOP":
            return _handle_stop(state)
        if command.name in {"TARE", "SET_ZERO"}:
            return _handle_tare(state)
        if command.name == "SAVE":
            return _handle_save(state)
        if command.name == "CSV":
            return _handle_csv_preview(state)
        if command.name == "CSV PATH":
            return _path_response("CSV_PATH", state.file_context.csv_path if state.file_context else None)
        if command.name == "REPORT":
            if state.report_text is None:
                return err("NO_REPORT")
            return ok("REPORT", text=state.report_text)
        if command.name == "REPORT PATH":
            return _path_response("REPORT_PATH", state.file_context.report_path if state.file_context else None)
        if command.name == "DIAG CONNECTION":
            return _handle_diag_connection(state)
        if command.name in {"DIAG ERRORS", "DIAG ERROR"}:
            return _handle_diag_errors(state)
        if command.name == "QUIT":
            return _handle_quit(state)
        return err("UNKNOWN_COMMAND", command=command.raw)
    except Exception as error:
        return err("COMMAND_FAILED", error=error)


def _handle_status(state: ExternalTcpInterfaceState) -> str:
    """Return one-line interface status."""
    return ok(
        "STATUS",
        state=state.state_name,
        setup=state.setup_key,
        validation=_setup_validation(state.setup_key),
        session=state.session_name,
        capturing=state.continuous_session.is_capturing if state.continuous_session else None,
        csv_path=state.file_context.csv_path if state.file_context else None,
        report_path=state.file_context.report_path if state.file_context else None,
        graph_path=state.graph_path,
    )


def _echo_text(raw_command_line: str) -> str:
    """Return the exact text after the ECHO command name."""
    parts = raw_command_line.strip().split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1]


def _setup_keys() -> tuple[str, ...]:
    """Return selectable setup keys from the central setup registry."""
    return tuple(key for key in SETUP.__all__ if key != "SETUP_TEMPLATE")


def _normalize_setup_key(setup_key: str) -> str:
    """Normalize one external setup key token."""
    return setup_key.strip().upper().replace("-", "_")


def _get_setup_config(setup_key: str) -> dict[str, Any]:
    """Return one setup config from the central setup registry."""
    normalized = _normalize_setup_key(setup_key)
    if normalized not in _setup_keys():
        raise KeyError(normalized)
    return getattr(SETUP, normalized)


def _setup_list_text() -> str:
    """Return setup keys with static validation status."""
    return ",".join(
        format_setup_validation_token(setup_key, _get_setup_config(setup_key))
        for setup_key in sorted(_setup_keys())
    )


def _setup_validation(setup_key: str) -> str:
    """Return the static validation token for one setup key."""
    return evaluate_setup_validation_status(_get_setup_config(setup_key)).token


def _setup_response_fields(setup_key: str) -> dict[str, object]:
    """Return common setup fields for one-line external responses."""
    return {"setup": setup_key, "validation": _setup_validation(setup_key)}


def _handle_path(command: ExternalCommand, state: ExternalTcpInterfaceState) -> str:
    """Show, set, or reset persistent output paths."""
    if state.state_name != "IDLE" and command.name != "PATH":
        return err("BUSY", command=command.name, state=state.state_name, allowed_state="IDLE")
    if command.name == "PATH RESET":
        directories = reset_persistent_output_paths()
        return _output_paths_response("PATH_RESET", directories)
    if command.name == "PATH SET":
        if len(command.args) < 2:
            return err("INVALID_PATH_SYNTAX", usage="PATH SET DATA <dir> or PATH SET LOGS <dir>")
        kind = command.args[0]
        directory = " ".join(command.args[1:])
        directories = set_persistent_output_path(kind, directory)
        return _output_paths_response("PATH_SET", directories)
    if command.args or command.options:
        return err("INVALID_PATH_SYNTAX", usage="PATH, PATH SET DATA <dir>, PATH SET LOGS <dir>, PATH RESET")
    return _output_paths_response("PATH", resolve_output_directories())


def _output_paths_response(message: str, directories: object) -> str:
    """Return output path fields for external responses."""
    return ok(
        message,
        data_dir=getattr(directories, "data_dir", None),
        log_dir=getattr(directories, "log_dir", None),
        settings_path=getattr(directories, "settings_path", None),
    )


def _handle_setup_use(command: ExternalCommand, state: ExternalTcpInterfaceState) -> str:
    """Switch the selected setup key."""
    if state.state_name != "IDLE":
        return err("BUSY", command="SETUP USE", state=state.state_name, allowed_state="IDLE")
    if not command.args:
        return err("MISSING_SETUP_KEY")
    setup_key = _normalize_setup_key(command.args[0])
    if setup_key not in _setup_keys():
        return err("UNKNOWN_SETUP", setup=setup_key)
    _cleanup_state(state)
    state.setup_key = setup_key
    return ok("SETUP_SELECTED", **_setup_response_fields(setup_key))


def _handle_diag_connection(state: ExternalTcpInterfaceState) -> str:
    """Return current non-mutating connection diagnostics for the selected setup."""
    if state.state_name != "IDLE":
        return _diagnostics_busy_response("DIAG_CONNECTION", state)
    results = diagnose_setup_connection(state.setup_config)
    ok_count = sum(1 for result in results if result.ok)
    fields = {
        **_setup_response_fields(state.setup_key),
        "devices": len(results),
        "ok_devices": ok_count,
        "results": _format_connection_diagnostics_token_for_external(
            results,
            setup_config=state.setup_config,
        ),
    }
    if ok_count == 0:
        return err("DIAG_CONNECTION_FAILED", **fields)
    return ok("DIAG_CONNECTION", **fields)


def _handle_diag_errors(state: ExternalTcpInterfaceState) -> str:
    """Return current non-destructive GSV admin/error diagnostics."""
    if state.state_name != "IDLE":
        return _diagnostics_busy_response("DIAG_ERRORS", state)
    results = diagnose_setup_errors(
        state.setup_config,
        error_indices=VALUE_ERROR_HISTORY_INDICES,
    )
    ok_count = sum(1 for result in results if result.ok)
    fields = {
        **_setup_response_fields(state.setup_key),
        "devices": len(results),
        "ok_devices": ok_count,
        "history_window_h": DEFAULT_HISTORY_WINDOW_H,
        "results": format_error_diagnostics_token(
            results,
            history_window_h=DEFAULT_HISTORY_WINDOW_H,
        ),
    }
    if ok_count == 0:
        return err("DIAG_ERRORS_FAILED", **fields)
    return ok("DIAG_ERRORS", **fields)


def _diagnostics_busy_response(command_name: str, state: ExternalTcpInterfaceState) -> str:
    """Return a clear diagnostic-state conflict response."""
    return err(
        "BUSY",
        command=command_name,
        state=state.state_name,
        allowed_state="IDLE",
        reason="diagnostics_require_idle_state",
        **_setup_response_fields(state.setup_key),
    )


def _format_connection_diagnostics_token_for_external(results: object, *, setup_config: dict[str, Any]) -> str:
    """Return compact connection diagnostics with setup baudrate for TCP paths."""
    token = format_connection_diagnostics_token(results)
    baudrate = setup_config.get("baudrate")
    if baudrate is None:
        return token
    return token.replace("baudrate=na", f"baudrate={baudrate}")


def _handle_quit(state: ExternalTcpInterfaceState) -> str:
    """Save an active session if needed and close the client session."""
    if state.continuous_session is None:
        return ok("BYE")
    save_response = _handle_save(state)
    if not save_response.startswith("OK SESSION_SAVED"):
        return save_response
    return save_response.replace("OK SESSION_SAVED", "OK BYE session_saved=True", 1)


def _handle_tare(state: ExternalTcpInterfaceState) -> str:
    """Run SetZero on prepared devices during an active transmission session."""
    if state.prepared_session is None or state.continuous_session is None:
        return err("NO_ACTIVE_SESSION")
    reports = run_runtime_set_zero_cycle_concurrently(state.prepared_session.applied_setup)
    ok_count = sum(1 for report in reports if report.get("ok"))
    return ok("SET_ZERO_DONE", devices=ok_count)


def _handle_session(command: ExternalCommand, state: ExternalTcpInterfaceState) -> str:
    """Start a new transmission session without capturing samples yet."""
    if state.state_name != "IDLE":
        return err("BUSY", state=state.state_name, allowed_state="IDLE")
    invalid_options = sorted(key for key in command.options if key not in {"session", "session_name"})
    if invalid_options or len(command.args) > 1:
        return err("INVALID_SESSION_SYNTAX", usage="SESSION <session_name> or SESSION session=<name>")
    session_name = _session_name(command)
    if not session_name:
        return err("MISSING_SESSION_NAME")
    resolved_setup = resolve_setup(state.setup_config)
    prepared = prepare_recording_session(
        setup_config=state.setup_config,
        resolved_setup=resolved_setup,
        session_name=session_name,
        zero_before_recording=None,
    )
    state.prepared_session = prepared
    state.session_name = session_name
    state.file_context = None
    state.report_text = None
    state.graph_path = None
    if not prepared.can_start_transmission:
        warnings = _blocking_warnings_text(prepared)
        close_prepared_recording_session(prepared)
        state.prepared_session = None
        return err(
            "SETUP_NOT_READY",
            session=session_name,
            **_setup_response_fields(state.setup_key),
            warnings=warnings,
        )
    state.continuous_session = start_prepared_continuous_session(prepared)
    return ok(
        "SESSION_READY",
        session=session_name,
        **_setup_response_fields(state.setup_key),
        tare="done" if prepared.zero_before_recording else "skipped",
        transmission="started",
        next="START",
    )


def _blocking_warnings_text(prepared: PreparedRecordingSession) -> str:
    """Return compact blocking warning tokens from an applied setup."""
    tokens: list[str] = []
    for applied_device in prepared.applied_setup.devices:
        alias = applied_device.resolved_device.alias
        name = applied_device.device.name
        for warning in applied_device.warnings:
            if not warning.get("blocking"):
                continue
            key = str(warning.get("warning_key") or "blocking_warning")
            context = warning.get("context") or {}
            detail = context.get("sample_rate_readback_hz")
            if detail is None:
                detail = context.get("active_baudrate")
            if detail is None:
                detail = context.get("baudrate_source")
            if detail is None:
                tokens.append(f"{alias}:{name}:{key}")
            else:
                tokens.append(f"{alias}:{name}:{key}:{detail}")
    return ",".join(tokens) or "<none>"


def _session_name(command: ExternalCommand) -> str | None:
    """Return session name from key-value or shorthand SESSION syntax."""
    return (
        command.options.get("session")
        or command.options.get("session_name")
        or (command.args[0] if command.args else None)
    )


def _handle_start(command: ExternalCommand, state: ExternalTcpInterfaceState) -> str:
    """Start one capture window, optionally with a non-blocking auto-stop timer."""
    if state.continuous_session is None:
        return err("NO_ACTIVE_SESSION")
    if state.continuous_session.is_capturing:
        return err("ALREADY_RECORDING")
    duration = parse_optional_duration(command.args)
    state.continuous_session.start_capture()
    if duration is not None:
        _start_capture_timer(state, duration.seconds)
        return ok("RECORDING_STARTED", duration=duration.text, auto_stop=True)
    return ok("RECORDING_STARTED")


def _start_capture_timer(state: ExternalTcpInterfaceState, duration_s: float) -> None:
    """Start or replace the auto-stop timer for the active capture window."""
    _cancel_capture_timer(state)
    cancel_event = Event()
    state.capture_timer_cancel = cancel_event

    def worker() -> None:
        if cancel_event.wait(duration_s):
            return
        with state.lock:
            if state.continuous_session is not None and state.continuous_session.is_capturing:
                state.continuous_session.stop_capture(automatic=True)

    state.capture_timer_thread = Thread(
        target=worker,
        name="gsvpiko-external-auto-stop",
        daemon=True,
    )
    state.capture_timer_thread.start()


def _cancel_capture_timer(state: ExternalTcpInterfaceState) -> None:
    """Cancel a pending external auto-stop timer."""
    if state.capture_timer_cancel is not None:
        state.capture_timer_cancel.set()
    state.capture_timer_cancel = None
    state.capture_timer_thread = None


def _handle_stop(state: ExternalTcpInterfaceState) -> str:
    """Pause the active capture window while transmission continues."""
    if state.continuous_session is None:
        return err("NO_ACTIVE_SESSION")
    if not state.continuous_session.is_capturing:
        return err("NOT_RECORDING")
    _cancel_capture_timer(state)
    state.continuous_session.stop_capture()
    return ok("RECORDING_PAUSED", transmission="running")


def _handle_save(state: ExternalTcpInterfaceState) -> str:
    """Stop transmission, write CSV/report/plot output and close devices."""
    if state.prepared_session is None or state.continuous_session is None:
        return err("NO_ACTIVE_SESSION")
    _cancel_capture_timer(state)
    runtime_result = state.continuous_session.stop_transmission_and_collect()
    run_result = state.prepared_session.to_run_result(runtime_result)
    state.file_context = build_recording_file_context(
        resolved_setup=state.prepared_session.resolved_setup,
        session_name=state.session_name or "session",
    )
    write_recording_csv(
        recording_result=run_result,
        file_context=state.file_context,
        zero_before_recording=state.prepared_session.zero_before_recording,
    )
    state.report_text = format_recording_report(
        recording_result=run_result,
        session_name=state.session_name or "session",
        file_context=state.file_context,
        zero_before_recording=state.prepared_session.zero_before_recording,
    )
    write_recording_report(report_text=state.report_text, file_context=state.file_context)
    state.graph_path = None
    if _has_records(runtime_result):
        state.graph_path = plot_gsvpiko_csv(
            state.file_context.csv_path,
            output_path=state.file_context.graph_path,
        )
    close_prepared_recording_session(state.prepared_session)
    state.prepared_session = None
    state.continuous_session = None
    return ok(
        "SESSION_SAVED",
        csv_path=state.file_context.csv_path,
        report_path=state.file_context.report_path,
        graph_path=state.graph_path,
    )


def _has_records(runtime_result: Any) -> bool:
    """Return whether a runtime result contains at least one stored sample."""
    return any(device_result.records for device_result in runtime_result.device_results)


def _handle_csv_preview(state: ExternalTcpInterfaceState) -> str:
    """Return a compact preview of the last CSV file."""
    if state.file_context is None:
        return err("NO_CSV")
    return ok("CSV_PREVIEW", text=read_csv_preview(state.file_context.csv_path))


def _path_response(message: str, path: object | None) -> str:
    """Return an OK path response or a missing-file error."""
    if path is None:
        return err("NO_PATH")
    return ok(message, path=path)


def _write_response(connection: socket.socket, response: str) -> bool:
    """Write exactly one UTF-8 response line to the client socket."""
    response = str(response).replace("\r", " ").replace("\n", " ").strip() + "\n"
    try:
        connection.sendall(response.encode("utf-8"))
    except OSError:
        return False
    return True


def _cleanup_state(state: ExternalTcpInterfaceState) -> None:
    """Stop and close any prepared state owned by the external interface."""
    _cancel_capture_timer(state)
    if state.continuous_session is not None:
        try:
            state.continuous_session.stop_transmission_and_collect()
        except Exception:
            pass
    if state.prepared_session is not None:
        close_prepared_recording_session(state.prepared_session)
    state.prepared_session = None
    state.continuous_session = None
