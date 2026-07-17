"""Record measurement values using a reusable GSVpiko setup preset."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options
from threading import Event, Thread
from typing import Any

from ..coordination.coordination_csv import (
    build_recording_file_context,
    write_recording_csv,
)
from ..coordination.coordination_recording import (
    PreparedRecordingSession,
    close_prepared_recording_session,
    prepare_recording_session,
    record_prepared_session_until_stopped,
)
from ..coordination.coordination_report import (
    format_recording_report,
    write_recording_report,
)
from ..coordination.coordination_report_print import (
    format_sample_rate_limit_lines,
    format_setup_application_warning_lines,
    format_setup_metadata_block_lines,
    format_title_lines,
)
from ..coordination.coordination_setup_application import (
    setup_application_warning_action_text,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import BaudrateProbeResult, DeviceConnectionError
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY


def main() -> None:
    """Run an interactive start/stop recording session."""
    args = _parse_args()
    setup_config = get_setup_config(args.setup)
    resolved_setup = resolve_setup(setup_config)
    session_name = _resolve_session_name(
        provided_session_name=args.session_name,
        files_enabled=not args.no_files,
    )
    zero_before_recording = False if args.no_zero else resolved_setup.zero_before_recording
    discard_initial_frames = (
        resolved_setup.discard_initial_frames
        if args.discard_initial_frames is None
        else int(args.discard_initial_frames)
    )
    probe_results: list[BaudrateProbeResult] = []
    prepared_session: PreparedRecordingSession | None = None
    runtime_error: BaseException | None = None
    runtime_result_holder: dict[str, Any] = {}

    _print_start_header(
        resolved_setup=resolved_setup,
        session_name=session_name,
        zero_before_recording=zero_before_recording,
        discard_initial_frames=discard_initial_frames,
        files_enabled=not args.no_files,
    )

    try:
        print("Preparing...")
        prepared_session = prepare_recording_session(
            setup_config=setup_config,
            resolved_setup=resolved_setup,
            session_name=session_name,
            zero_before_recording=zero_before_recording,
            on_probe_result=probe_results.append,
        )
        preliminary_result = prepared_session.to_run_result()
        if not prepared_session.can_start_transmission:
            _print_blocking_warnings(preliminary_result)
            print("Devices closed.")
            return

        input("Press Enter to start the measurement.")
        stop_event = Event()
        recording_started = Event()

        def on_recording_started() -> None:
            recording_started.set()
            print("Recording started.", flush=True)

        def runtime_worker() -> None:
            nonlocal runtime_error
            try:
                runtime_result_holder["runtime_result"] = (
                    record_prepared_session_until_stopped(
                        prepared_session,
                        stop_event=stop_event,
                        discard_initial_frames=discard_initial_frames,
                        on_recording_started=on_recording_started,
                    )
                )
            except BaseException as error:
                runtime_error = error
                stop_event.set()

        worker = Thread(
            target=runtime_worker,
            name="gsvpiko-interactive-recording",
            daemon=True,
        )
        worker.start()
        while not recording_started.wait(timeout=0.1):
            if runtime_error is not None:
                break
        if runtime_error is not None:
            raise runtime_error

        _wait_for_stop_command(stop_event)
        worker.join()
        if runtime_error is not None:
            raise runtime_error

        runtime_result = runtime_result_holder.get("runtime_result")
        recording_result = prepared_session.to_run_result(runtime_result)
        file_context = None
        if not args.no_files:
            file_context = build_recording_file_context(
                resolved_setup=resolved_setup,
                session_name=session_name,
            )
            write_recording_csv(
                recording_result=recording_result,
                file_context=file_context,
                zero_before_recording=zero_before_recording,
            )

        report_text = format_recording_report(
            recording_result=recording_result,
            session_name=session_name,
            file_context=file_context,
            zero_before_recording=zero_before_recording,
            probe_results=probe_results,
        )
        if file_context is not None and resolved_setup.output.get("write_report_with_csv", True):
            write_recording_report(
                report_text=report_text,
                file_context=file_context,
            )

        print("Recording stopped.")
        if file_context is not None:
            print(f"CSV saved at: {file_context.csv_path}")
            print(f"Report saved at: {file_context.report_path}")
        else:
            print(report_text, end="")
        print("Devices closed.")

    except DeviceConnectionError as error:
        print()
        print("Opening device failed.")
        print(error)
    finally:
        if prepared_session is not None:
            close_prepared_recording_session(prepared_session)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the recording app."""
    parser = argparse.ArgumentParser(
        description="Record measurement values from one selected setup preset.",
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    parser.add_argument("--session-name", default=None)
    parser.add_argument("--discard-initial-frames", type=int, default=None)
    parser.add_argument("--no-zero", action="store_true")
    parser.add_argument("--no-files", action="store_true")
    args = parser.parse_args()
    print_cli_options(parser, args)
    return args


def _resolve_session_name(
    *,
    provided_session_name: str | None,
    files_enabled: bool,
) -> str:
    """Return a session name, prompting when files need a user-facing name."""
    if provided_session_name:
        return provided_session_name.strip()
    if not files_enabled:
        return "debug"

    while True:
        value = input("Enter a descriptive, general-to-specific session_name: ").strip()
        if value:
            return value
        print("session_name must not be empty.")


def _print_start_header(
    *,
    resolved_setup,
    session_name: str,
    zero_before_recording: bool,
    discard_initial_frames: int,
    files_enabled: bool,
) -> None:
    """Print the short pre-recording overview."""
    lines = []
    lines.extend(format_title_lines("Setup runtime recording"))
    lines.extend(
        [
            f"session_name: {session_name}",
            f"setup_name: {resolved_setup.name}",
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
            f"discard_initial_frames: {discard_initial_frames}",
            f"zero_before_recording: {zero_before_recording}",
            f"write_files: {files_enabled}",
            "",
        ]
    )
    lines.extend(format_setup_metadata_block_lines(resolved_setup))
    lines.append("")
    lines.extend(format_sample_rate_limit_lines(resolved_setup))
    print("\n".join(lines).rstrip())
    print()

def _print_blocking_warnings(recording_result) -> None:
    """Print warnings that prevented autonomous transmission."""
    lines = format_setup_application_warning_lines(recording_result.application_warnings)
    if lines:
        print("\n".join(lines).rstrip())
        print()

def _wait_for_stop_command(stop_event: Event) -> None:
    """Wait until the user types STOP and presses Enter."""
    while not stop_event.is_set():
        value = input("Type STOP and press Enter to stop the measurement: ").strip()
        if value.upper() == "STOP":
            stop_event.set()
            return
        print("Measurement is still running. Type STOP to stop it.")


if __name__ == "__main__":
    main()
