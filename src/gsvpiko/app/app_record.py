"""Run the local interactive GSVpiko recording shell."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from time import sleep
from typing import Any

from ._cli_options import print_cli_options
from ._setup_selection import (
    DEFAULT_SETUP_KEY,
    add_setup_argument,
    format_setup_keys,
    get_setup_config,
    parse_setup_key,
)
from ..coordination.coordination_diagnostics import (
    DEFAULT_HISTORY_WINDOW_H,
    VALUE_ERROR_HISTORY_INDICES,
    diagnose_setup_connection,
    diagnose_setup_errors,
    format_device_status_error_report_lines,
)
from ..coordination.coordination_recording import (
    PreparedRecordingSession,
    close_prepared_recording_session,
    prepare_recording_session,
    start_prepared_continuous_session,
)
from ..coordination.coordination_setup_application import setup_application_warning_action_text
from ..coordination.coordination_setup_resolution import ResolvedSetup, resolve_setup
from ..device.device_connection import BaudrateProbeResult, DeviceConnectionError
from ..device.device_report import (
    print_baudrate_probe_result,
    print_channel_layout,
    print_configuration_report,
    print_connection_report,
)
from ..output.output_csv import RecordingFileContext, build_recording_file_context, write_recording_csv
from ..output.output_paths import (
    apply_output_directories_to_setup_config,
    ensure_output_directories,
    format_output_directories_lines,
    reset_persistent_output_paths,
    resolve_output_directories,
    set_persistent_output_path,
)
from ..output.output_plot import plot_gsvpiko_csv
from ..output.output_report import format_recording_report, write_recording_report
from ..output.output_report_print import (
    format_connection_diagnostic_lines,
    format_sample_rate_limit_lines,
    format_setup_application_warning_lines,
    format_title_lines,
)
from ..runtime.runtime_session import ContinuousRuntimeSession, run_runtime_set_zero_cycle_concurrently
from ..utils.utils_duration import ParsedDuration, parse_optional_duration

SETUP_KEY = DEFAULT_SETUP_KEY


class RecordingShell:
    """Local interactive recording shell."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.setup_key = parse_setup_key(args.setup)
        self.data_dir_override = args.data_dir
        self.log_dir_override = args.log_dir
        self.prepared_session: PreparedRecordingSession | None = None
        self.continuous_session: ContinuousRuntimeSession | None = None
        self.session_name: str | None = None
        self.file_context: RecordingFileContext | None = None
        self.report_text: str | None = None
        self.graph_path: Path | None = None
        self.probe_results: list[BaudrateProbeResult] = []
        self.saved_current_session = False

    @property
    def state_name(self) -> str:
        """Return the current shell state."""
        if self.continuous_session is not None and self.continuous_session.is_capturing:
            return "RECORDING"
        if self.continuous_session is not None:
            return "SESSION"
        return "IDLE"

    def setup_config(self) -> dict[str, Any]:
        """Return the selected setup with active output folders applied."""
        return apply_output_directories_to_setup_config(
            get_setup_config(self.setup_key),
            data_dir=self.data_dir_override,
            log_dir=self.log_dir_override,
        )

    def resolved_setup(self) -> ResolvedSetup:
        """Return the currently resolved setup."""
        return resolve_setup(self.setup_config())

    def run(self) -> None:
        """Run the interactive shell."""
        self.print_overview()
        if self.args.session_name:
            if self.session(self.args.session_name):
                self.start([])
        while True:
            try:
                command_line = input(_prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self.quit()
                return
            if not command_line:
                continue
            if self.handle_command(command_line):
                return

    def handle_command(self, command_line: str) -> bool:
        """Handle one shell command. Return True when the shell should exit."""
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]
        try:
            if command == "help":
                self.print_commands()
            elif command == "status":
                self.print_status()
            elif command == "path":
                self.handle_path(args)
            elif command == "setup":
                self.handle_setup(args)
            elif command == "session":
                self.session(args[0] if args else None)
            elif command == "start":
                self.start(args)
            elif command in {"tare", "set_zero"}:
                self.tare()
            elif command == "stop":
                self.stop()
            elif command == "save":
                self.save()
            elif command == "diag":
                self.handle_diag(args)
            elif command in {"quit", "exit"}:
                self.quit()
                return True
            else:
                print(f"Unknown command: {command_line}")
                print("Type help for available commands.")
        except Exception as error:
            print(f"Command failed: {error}")
        return False

    def print_overview(self) -> None:
        """Print setup, output and command overview before entering the prompt."""
        resolved_setup = self.resolved_setup()
        lines: list[str] = []
        lines.extend(format_title_lines("GSVpiko recording shell"))
        lines.append(f"Active setup: {self.setup_key}")
        lines.append(f"setup_name: {resolved_setup.name}")
        lines.append(
            f"sample_rate_hz: {resolved_setup.sample_rate_hz:g}, "
            f"datatype: {resolved_setup.datatype_name}, "
            f"channels: {sum(len(device.channels) for device in resolved_setup.devices)}"
        )
        lines.append(f"zero_before_recording: {resolved_setup.zero_before_recording}")
        lines.append("")
        lines.extend(_format_compact_setup_table(resolved_setup))
        lines.append("")
        lines.extend(format_title_lines("Output paths"))
        lines.extend(
            format_output_directories_lines(
                resolve_output_directories(
                    data_dir=self.data_dir_override,
                    log_dir=self.log_dir_override,
                )
            )
        )
        lines.append("")
        lines.extend(self.command_lines())
        print("\n".join(lines).rstrip())
        print()

    def command_lines(self) -> list[str]:
        """Return command help lines for the local recording shell."""
        rows = [
            ("help", "show this command overview"),
            ("status", "show current shell state"),
            ("path", "show active output folders"),
            ("path set data <dir>", "set persistent CSV/plot output folder"),
            ("path set logs <dir>", "set persistent report output folder"),
            ("path reset", "reset persistent output folders to defaults"),
            ("setup", "show the active setup"),
            ("setup list", "list available setup presets"),
            ("setup use <setup_key>", "select another setup preset"),
            ("session <session_name>", "tare if configured and start transmission"),
            ("start", "start recording samples into the active session"),
            ("start 20 s", "record for a duration, then stop automatically"),
            ("tare", "run SetZero and mark the event"),
            ("stop", "pause recording while transmission continues"),
            ("save", "stop transmission and write CSV/report/plot"),
            ("diag connection", "check current connection paths"),
            ("diag errors", "read GSV diagnostics"),
            ("quit", "save if needed and close the program"),
        ]
        width = max(len(command) for command, _description in rows)
        lines = ["Commands:"]
        lines.extend(f"  {command:<{width}}  {description}" for command, description in rows)
        return lines

    def print_commands(self) -> None:
        """Print available shell commands."""
        print("\n".join(self.command_lines()))

    def print_status(self) -> None:
        """Print shell state, selected setup and output paths."""
        lines: list[str] = []
        lines.extend(format_title_lines("Recording shell status"))
        lines.append(f"state: {self.state_name}")
        lines.append(f"setup: {self.setup_key}")
        lines.append(f"session_name: {self.session_name or '<none>'}")
        if self.continuous_session is not None:
            lines.append(f"capturing: {self.continuous_session.is_capturing}")
        lines.extend(
            format_output_directories_lines(
                resolve_output_directories(
                    data_dir=self.data_dir_override,
                    log_dir=self.log_dir_override,
                )
            )
        )
        if self.file_context is not None:
            lines.append(f"csv_path: {self.file_context.csv_path}")
            lines.append(f"report_path: {self.file_context.report_path}")
            lines.append(f"graph_path: {self.file_context.graph_path}")
        print("\n".join(lines))

    def handle_path(self, args: list[str]) -> None:
        """Handle path commands."""
        if not args:
            lines = []
            lines.extend(format_title_lines("Output paths"))
            lines.extend(
                format_output_directories_lines(
                    resolve_output_directories(
                        data_dir=self.data_dir_override,
                        log_dir=self.log_dir_override,
                    )
                )
            )
            print("\n".join(lines))
            return
        action = args[0].lower()
        if action == "reset":
            if self.state_name != "IDLE":
                print("Output paths can only be reset in IDLE state.")
                return
            directories = reset_persistent_output_paths()
            self.data_dir_override = None
            self.log_dir_override = None
            print("Persistent output paths reset.")
            print("\n".join(format_output_directories_lines(directories)))
            return
        if action != "set" or len(args) < 3:
            print("Usage: path, path set data <dir>, path set logs <dir>, path reset")
            return
        if self.state_name != "IDLE":
            print("Output paths can only be changed in IDLE state.")
            return
        kind = args[1]
        directory = " ".join(args[2:])
        directories = set_persistent_output_path(kind, directory)
        self.data_dir_override = None
        self.log_dir_override = None
        print("Persistent output path saved.")
        print("\n".join(format_output_directories_lines(directories)))

    def handle_setup(self, args: list[str]) -> None:
        """Handle setup commands."""
        if not args:
            print(f"setup: {self.setup_key} (valid)")
            return
        subcommand = args[0].lower()
        if subcommand == "list":
            print("Available setups")
            print("----------------")
            for key in format_setup_keys().split(", "):
                print(f"  {key.lower()}")
            return
        if subcommand == "use" and len(args) >= 2:
            if self.state_name != "IDLE":
                print("Setup can only be changed in IDLE state.")
                return
            self.setup_key = parse_setup_key(args[1])
            print(f"Selected setup: {self.setup_key}")
            self.print_overview()
            return
        print("Usage: setup, setup list, setup use <setup_key>")

    def handle_diag(self, args: list[str]) -> None:
        """Handle diagnostic commands."""
        if self.state_name != "IDLE":
            print("Diagnostics can only run in IDLE state.")
            return
        if not args:
            print("Usage: diag connection, diag errors")
            return
        subcommand = args[0].lower()
        if subcommand == "connection":
            results = diagnose_setup_connection(self.setup_config())
            lines = []
            lines.extend(format_title_lines("Setup connection diagnostics"))
            lines.append(f"setup_name: {self.resolved_setup().name}")
            lines.append("connection_policy: non_mutating_adaptive")
            lines.append("")
            for result in results:
                lines.extend(format_connection_diagnostic_lines(result))
                lines.append("")
            print("\n".join(lines).rstrip())
            return
        if subcommand in {"errors", "error"}:
            results = diagnose_setup_errors(
                self.setup_config(),
                error_indices=VALUE_ERROR_HISTORY_INDICES,
            )
            lines = []
            lines.extend(format_title_lines("Setup status and error diagnostics"))
            lines.append(f"setup_name: {self.resolved_setup().name}")
            lines.append(f"history_window_h: {DEFAULT_HISTORY_WINDOW_H:g}")
            lines.append("")
            for result in results:
                lines.extend(format_device_status_error_report_lines(result))
                lines.append("")
            print("\n".join(lines).rstrip())
            return
        print("Usage: diag connection, diag errors")

    def session(self, session_name: str | None) -> bool:
        """Prepare a session and start transmission without capturing samples."""
        if self.state_name != "IDLE":
            print("A session is already active. Use save before starting another session.")
            return False
        if not session_name:
            print("Usage: session <session_name>")
            return False
        self.session_name = session_name.strip()
        self.probe_results = []
        self.saved_current_session = False
        self.file_context = None
        self.report_text = None
        self.graph_path = None
        try:
            print("Preparing session...")
            resolved_setup = self.resolved_setup()
            self.prepared_session = prepare_recording_session(
                setup_config=self.setup_config(),
                resolved_setup=resolved_setup,
                session_name=self.session_name,
                zero_before_recording=None,
                on_probe_result=self.probe_results.append,
            )
            self._print_session_preparation_details()
            if not self.prepared_session.can_start_transmission:
                self._print_blocking_warnings()
                self.close_without_saving()
                print("Devices closed.")
                return False
            self.continuous_session = start_prepared_continuous_session(
                self.prepared_session,
                discard_initial_frames=self._discard_initial_frames(resolved_setup),
            )
            print("Session ready.")
            print(
                "Tare: "
                + ("done" if self.prepared_session.zero_before_recording else "skipped")
            )
            print("Transmission started.")
            print("Enter 'start' to begin the measurement.")
            return True
        except DeviceConnectionError as error:
            print()
            print("Opening device failed.")
            print(error)
            self.close_without_saving()
            return False

    def start(self, args: list[str]) -> bool:
        """Start one capture window, optionally with an automatic duration."""
        if self.continuous_session is None:
            print("No active session. Use session <session_name> first.")
            return False
        if self.continuous_session.is_capturing:
            print("Recording is already running.")
            return False
        duration = parse_optional_duration(args)
        self.continuous_session.start_capture()
        if duration is None:
            print("Recording started.")
            return True
        print(f"Recording started for {duration.text}.")
        sleep(duration.seconds)
        if self.continuous_session is not None and self.continuous_session.is_capturing:
            self.continuous_session.stop_capture(automatic=True)
            print("Recording stopped automatically.")
        return True

    def tare(self) -> None:
        """Run SetZero on devices and record the event."""
        if self.prepared_session is None or self.continuous_session is None:
            print("No active session. Use session <session_name> first.")
            return
        reports = run_runtime_set_zero_cycle_concurrently(self.prepared_session.applied_setup)
        ok_count = sum(1 for report in reports if report.get("ok"))
        print(f"SetZero done: devices={ok_count}")

    def stop(self) -> bool:
        """Stop the active capture window while transmission continues."""
        if self.continuous_session is None:
            print("No active session.")
            return False
        if not self.continuous_session.is_capturing:
            print("No active recording window.")
            return False
        self.continuous_session.stop_capture()
        print("Recording paused. Transmission is still running.")
        return True

    def save(self) -> bool:
        """Stop transmission, write output files and close devices."""
        if self.prepared_session is None or self.continuous_session is None:
            print("No active session to save.")
            return False
        runtime_result = self.continuous_session.stop_transmission_and_collect()
        run_result = self.prepared_session.to_run_result(runtime_result)
        self.file_context = None
        if not self.args.no_files:
            self.file_context = build_recording_file_context(
                resolved_setup=self.prepared_session.resolved_setup,
                session_name=self.session_name or "session",
            )
            write_recording_csv(
                recording_result=run_result,
                file_context=self.file_context,
                zero_before_recording=self.prepared_session.zero_before_recording,
            )
        self.report_text = format_recording_report(
            recording_result=run_result,
            session_name=self.session_name or "session",
            file_context=self.file_context,
            zero_before_recording=self.prepared_session.zero_before_recording,
            probe_results=self.probe_results,
        )
        self.graph_path = None
        if self.file_context is not None:
            write_recording_report(report_text=self.report_text, file_context=self.file_context)
            if not self.args.no_plot and _has_records(runtime_result):
                self.graph_path = plot_gsvpiko_csv(
                    self.file_context.csv_path,
                    output_path=self.file_context.graph_path,
                )
        print("Session saved.")
        if self.file_context is not None:
            print(f"CSV saved at: {self.file_context.csv_path}")
            print(f"Report saved at: {self.file_context.report_path}")
            if self.graph_path is not None:
                print(f"Graph saved at: {self.graph_path}")
            elif not _has_records(runtime_result):
                print("Graph not created because the session contains no recorded samples.")
        else:
            print(self.report_text, end="")
        close_prepared_recording_session(self.prepared_session)
        self.prepared_session = None
        self.continuous_session = None
        self.saved_current_session = True
        print("Devices closed.")
        return True

    def quit(self) -> None:
        """Save active session if needed and close devices."""
        if self.continuous_session is not None:
            self.save()
        else:
            self.close_without_saving()

    def close_without_saving(self) -> None:
        """Close active devices without writing output files."""
        if self.continuous_session is not None:
            try:
                self.continuous_session.stop_transmission_and_collect()
            except Exception:
                pass
        if self.prepared_session is not None:
            close_prepared_recording_session(self.prepared_session)
        self.prepared_session = None
        self.continuous_session = None

    def _discard_initial_frames(self, resolved_setup: ResolvedSetup) -> int:
        """Return active discard-initial-frames value."""
        if self.args.discard_initial_frames is None:
            return resolved_setup.discard_initial_frames
        return int(self.args.discard_initial_frames)

    def _print_session_preparation_details(self) -> None:
        """Print compact or debug setup-application information."""
        if self.prepared_session is None:
            return
        if not self.args.debug:
            print("Setup applied.")
            if self.probe_results:
                print(f"Baudrate probe results: {len(self.probe_results)}")
            warnings = self.prepared_session.to_run_result().application_warnings
            if warnings:
                lines = format_setup_application_warning_lines(warnings)
                print("\n".join(lines).rstrip())
            return

        print()
        print("Setup applied.")
        print()
        for probe_result in self.probe_results:
            print_baudrate_probe_result(probe_result)
        if self.probe_results:
            print()
        for applied_device in self.prepared_session.applied_setup.devices:
            print_connection_report(applied_device.device)
            print_channel_layout(applied_device.device)
            print_configuration_report(applied_device.configuration_report)

    def _print_blocking_warnings(self) -> None:
        """Print warnings that prevented autonomous transmission."""
        if self.prepared_session is None:
            return
        lines = format_setup_application_warning_lines(
            self.prepared_session.to_run_result().application_warnings
        )
        if lines:
            print("\n".join(lines).rstrip())
            print()
        print(setup_application_warning_action_text("measurement_not_started"))


def main() -> None:
    """Run the local interactive recording shell."""
    args = _parse_args()
    ensure_output_directories(resolve_output_directories(data_dir=args.data_dir, log_dir=args.log_dir))
    shell = RecordingShell(args)
    shell.run()


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the recording app."""
    parser = argparse.ArgumentParser(
        description="Record measurement values from one selected setup preset.",
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    parser.add_argument("--session-name", default=None)
    parser.add_argument("--discard-initial-frames", type=int, default=None)
    parser.add_argument("--no-files", action="store_true")
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print_cli_options(parser, args)
    return args


def _format_compact_setup_table(resolved_setup: ResolvedSetup) -> list[str]:
    """Return a compact human-oriented setup table."""
    lines = ["Setup layout:"]
    rows: list[tuple[str, str, str, str]] = []
    for device in resolved_setup.devices:
        channels = ", ".join(channel.column_name for channel in device.channels)
        sensors = []
        for channel in device.channels:
            if channel.sensor_alias not in sensors:
                sensors.append(channel.sensor_alias)
        rows.append((device.alias, device.device_name, ", ".join(sensors), channels))
    widths = [max(len(row[index]) for row in rows + [("alias", "device", "sensors", "channels")]) for index in range(4)]
    header = ("alias", "device", "sensors", "channels")
    lines.append(
        "  "
        + "  ".join(f"{header[index]:<{widths[index]}}" for index in range(4))
    )
    lines.append("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  " + "  ".join(f"{row[index]:<{widths[index]}}" for index in range(4)))
    return lines


def _has_records(runtime_result: Any) -> bool:
    """Return whether a runtime result contains at least one stored sample."""
    return any(device_result.records for device_result in runtime_result.device_results)


def _prompt() -> str:
    """Return the local prompt with an empty line and optional ANSI color."""
    marker = ":>"
    if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
        marker = "\033[36m:>\033[0m"
    return f"\n{marker} "


if __name__ == "__main__":
    main()
