"""Record a two-GSV runtime session from the configured setup."""

from __future__ import annotations

import argparse
from threading import Event, Thread
from typing import Any

from ..config import config_setups as SETUP
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
from ..coordination.coordination_sample_rate_limit import check_sample_rate_limit
from ..coordination.coordination_setup_resolution import (
    build_setup_metadata_lines,
    resolve_setup,
)
from ..device.device_connection import BaudrateProbeResult, DeviceConnectionError
from ..messages.messages_warning_text import (
    format_warning,
    get_warning_action_text,
)

SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH


def main() -> None:
    """Run an interactive start/stop recording session."""
    args = _parse_args()
    resolved_setup = resolve_setup(SETUP_CONFIG)
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
            setup_config=SETUP_CONFIG,
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
        description="Record a manually started/stopped two-GSV session.",
    )
    parser.add_argument("--session-name", default=None)
    parser.add_argument("--discard-initial-frames", type=int, default=None)
    parser.add_argument("--no-zero", action="store_true")
    parser.add_argument("--no-files", action="store_true")
    return parser.parse_args()


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
    title = "Two-GSV synchronized runtime recording"
    print(title)
    print("-" * len(title))
    print(f"session_name: {session_name}")
    print(f"setup_name: {resolved_setup.name}")
    print(f"language: {resolved_setup.language}")
    print(f"baudrate: {resolved_setup.baudrate} (source={resolved_setup.baudrate_source})")
    print(
        f"sample_rate_hz: {resolved_setup.sample_rate_hz} "
        f"(source={resolved_setup.sample_rate_source})"
    )
    print(f"datatype: {resolved_setup.datatype_name} (source={resolved_setup.datatype_source})")
    print(
        f"analog_filter_hz: {resolved_setup.analog_filter_hz} "
        f"(source={resolved_setup.analog_filter_source})"
    )
    print(f"crc_enabled: {resolved_setup.crc_enabled}")
    print(f"discard_initial_frames: {discard_initial_frames}")
    print(f"zero_before_recording: {zero_before_recording}")
    print(f"write_files: {files_enabled}")
    print()
    print("\n".join(build_setup_metadata_lines(resolved_setup)))
    print()
    _print_sample_rate_limit_reports(resolved_setup)


def _print_sample_rate_limit_reports(resolved_setup) -> None:
    """Print early sample-rate plausibility reports."""
    print("sample_rate_limit:")
    for index, device in enumerate(resolved_setup.devices):
        report = check_sample_rate_limit(
            requested_sample_rate_hz=resolved_setup.sample_rate_hz,
            baudrate=resolved_setup.baudrate,
            streamed_value_count=len(device.streamed_channels),
            datatype=resolved_setup.datatype,
            crc_enabled=resolved_setup.crc_enabled,
        )
        print(
            f"  {device.alias}: "
            f"streamed_values={report['streamed_value_count']}, "
            f"datatype={report['datatype_name']}, "
            f"requested={report['requested_sample_rate_hz']:g} Hz, "
            f"estimated_limit={report['estimated_serial_limit_hz']:.1f} Hz, "
            f"plausible={report['request_plausible']}"
        )
        if report["warning_key"] is not None:
            print()
            print(
                format_warning(
                    report["warning_key"],
                    language=resolved_setup.language,
                    context=report,
                )
            )
            print()
    print()


def _print_blocking_warnings(recording_result) -> None:
    """Print warnings that prevented autonomous transmission."""
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
