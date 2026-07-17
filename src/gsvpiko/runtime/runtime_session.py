"""Runtime session helpers for multi-device recording."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from time import time
from typing import Any, Callable

from ..coordination.coordination_setup_application import AppliedSetup, AppliedSetupDevice
from ..transport.transport_base import BaseTransport
from .runtime_measurement_buffer import RuntimeRecordingResult
from .runtime_reader import read_frames_concurrently, read_until_stopped_concurrently


class RuntimeSessionError(RuntimeError):
    """Raised when a runtime session cannot be executed safely."""


DEFAULT_RUNTIME_COMMAND_RESTART_DISCARD_FRAMES = 5


def run_fixed_frame_runtime_session(
    applied_setup: AppliedSetup,
    *,
    frame_count_per_device: int,
    discard_initial_frames: int = 0,
    zero_before_recording: bool = True,
    use_batched_transport_reader: bool = True,
    use_batched_serial_reader: bool | None = None,
) -> RuntimeRecordingResult:
    """Prepare transports, start transmission, read frames, stop transmission."""
    started_at_unix_s = time()
    events: dict[str, Any] = {
        "runtime_session_started_at": started_at_unix_s,
        "recording_mode": "fixed_frames",
    }
    tare_reports: list[dict[str, Any]] = []
    start_reports: list[dict[str, Any]] = []
    result: RuntimeRecordingResult | None = None
    transmission_started = False

    def start_after_readers_are_ready() -> None:
        nonlocal start_reports, transmission_started
        events["readers_ready_at"] = time()
        start_reports = start_transmission_concurrently(applied_setup)
        events["start_transmission_sent_at"] = time()
        transmission_started = True

    try:
        events["preparation_started_at"] = time()
        stop_transmission_concurrently(applied_setup)
        _prepare_transports_for_runtime(applied_setup.devices)
        _clear_input_buffers(applied_setup.devices)
        if zero_before_recording:
            tare_reports = set_zero_all_channels_concurrently(applied_setup)
            events["zero_completed_at"] = time()
            _clear_input_buffers(applied_setup.devices)
        else:
            events["zero_completed_at"] = None
        events["preparation_completed_at"] = time()
        device_results = read_frames_concurrently(
            applied_setup.devices,
            frame_count=frame_count_per_device,
            discard_initial_frames=discard_initial_frames,
            expected_sample_rate_hz=applied_setup.resolved_setup.sample_rate_hz,
            use_batched_transport_reader=(
                use_batched_transport_reader
                if use_batched_serial_reader is None
                else use_batched_serial_reader
            ),
            on_readers_ready=start_after_readers_are_ready,
        )
        result = RuntimeRecordingResult(
            setup_name=applied_setup.resolved_setup.name,
            requested_frame_count_per_device=frame_count_per_device,
            discard_initial_frames=discard_initial_frames,
            started_at_unix_s=started_at_unix_s,
            ended_at_unix_s=time(),
            device_results=device_results,
            tare_reports=tare_reports,
            start_reports=start_reports,
            stop_reports=[],
            events=events,
        )
        return result
    finally:
        if transmission_started:
            events["stop_transmission_requested_at"] = time()
            stop_reports = stop_transmission_concurrently(applied_setup)
            events["stop_transmission_sent_at"] = time()
            if result is not None:
                result.stop_reports = stop_reports
                result.events.update(events)


def run_manual_runtime_session(
    applied_setup: AppliedSetup,
    *,
    stop_event: Event,
    discard_initial_frames: int = 0,
    zero_before_recording: bool = True,
    use_batched_transport_reader: bool = True,
    use_batched_serial_reader: bool | None = None,
    on_recording_started: Callable[[], None] | None = None,
) -> RuntimeRecordingResult:
    """Record frames until stop_event is set by the caller."""
    started_at_unix_s = time()
    events: dict[str, Any] = {
        "runtime_session_started_at": started_at_unix_s,
        "recording_mode": "manual_start_stop",
    }
    tare_reports: list[dict[str, Any]] = []
    start_reports: list[dict[str, Any]] = []
    result: RuntimeRecordingResult | None = None
    transmission_started = False

    def start_after_readers_are_ready() -> None:
        nonlocal start_reports, transmission_started
        events["readers_ready_at"] = time()
        start_reports = start_transmission_concurrently(applied_setup)
        events["start_transmission_sent_at"] = time()
        transmission_started = True

    def mark_recording_started() -> None:
        events["recording_started_at"] = time()
        if on_recording_started is not None:
            on_recording_started()

    try:
        events["preparation_started_at"] = time()
        stop_transmission_concurrently(applied_setup)
        _prepare_transports_for_runtime(applied_setup.devices)
        _clear_input_buffers(applied_setup.devices)
        if zero_before_recording:
            tare_reports = set_zero_all_channels_concurrently(applied_setup)
            events["zero_completed_at"] = time()
            _clear_input_buffers(applied_setup.devices)
        else:
            events["zero_completed_at"] = None
        events["preparation_completed_at"] = time()
        device_results = read_until_stopped_concurrently(
            applied_setup.devices,
            stop_event=stop_event,
            discard_initial_frames=discard_initial_frames,
            expected_sample_rate_hz=applied_setup.resolved_setup.sample_rate_hz,
            use_batched_transport_reader=(
                use_batched_transport_reader
                if use_batched_serial_reader is None
                else use_batched_serial_reader
            ),
            on_readers_ready=start_after_readers_are_ready,
            on_recording_started=mark_recording_started,
        )
        result = RuntimeRecordingResult(
            setup_name=applied_setup.resolved_setup.name,
            requested_frame_count_per_device=0,
            discard_initial_frames=discard_initial_frames,
            started_at_unix_s=started_at_unix_s,
            ended_at_unix_s=time(),
            device_results=device_results,
            tare_reports=tare_reports,
            start_reports=start_reports,
            stop_reports=[],
            events=events,
        )
        return result
    finally:
        if transmission_started:
            events["stop_transmission_requested_at"] = time()
            stop_reports = stop_transmission_concurrently(applied_setup)
            events["stop_transmission_sent_at"] = time()
            if result is not None:
                result.stop_reports = stop_reports
                result.events.update(events)


def set_zero_all_channels_concurrently(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Tare all channels on all devices using one worker per GSV."""
    return _run_device_command_concurrently(
        applied_setup.devices,
        command_name="SetZero",
        command=lambda applied_device: applied_device.device.zero.set_zero_all_channels(),
    )



def run_runtime_set_zero_cycle_concurrently(
    applied_setup: AppliedSetup,
    *,
    restart_discard_frames: int = DEFAULT_RUNTIME_COMMAND_RESTART_DISCARD_FRAMES,
) -> list[dict[str, Any]]:
    """Run SetZero during active runtime recording as a controlled restart cycle."""
    command_group_id = f"set_zero_{time():.6f}"

    return _run_device_command_concurrently(
        applied_setup.devices,
        command_name="RuntimeSetZeroCycle",
        command=lambda applied_device: _run_runtime_set_zero_cycle_for_device(
            applied_device,
            command_group_id=command_group_id,
            restart_discard_frames=restart_discard_frames,
        ),
    )


def _run_runtime_set_zero_cycle_for_device(
    applied_device: AppliedSetupDevice,
    *,
    command_group_id: str,
    restart_discard_frames: int,
) -> dict[str, Any]:
    """Run one device's controlled runtime SetZero restart cycle."""
    exchange = applied_device.device.command_exchange
    if exchange is None or not hasattr(exchange, "run_set_zero_restart_cycle"):
        raise RuntimeSessionError(
            "Runtime SetZero requires an active runtime command exchange."
        )
    return exchange.run_set_zero_restart_cycle(
        command_group_id=command_group_id,
        restart_discard_frames=restart_discard_frames,
    )

def start_transmission_concurrently(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Start autonomous transmission on all devices using one worker per GSV."""
    return _run_device_command_concurrently(
        applied_setup.devices,
        command_name="StartTransmission",
        command=lambda applied_device: applied_device.device.acquisition.start_transmission(),
    )


def stop_transmission_concurrently(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Stop autonomous transmission on all devices using one worker per GSV."""
    return _run_device_command_concurrently(
        applied_setup.devices,
        command_name="StopTransmission",
        command=lambda applied_device: applied_device.device.acquisition.stop_transmission(),
        raise_on_error=False,
    )


def _prepare_transports_for_runtime(
    applied_devices: list[AppliedSetupDevice],
) -> None:
    """Run transport-level runtime preparation without exposing transport type."""
    for applied_device in applied_devices:
        transport = applied_device.device.transport
        if not isinstance(transport, BaseTransport):
            raise RuntimeSessionError(
                "Runtime session requires BaseTransport-compatible devices."
            )
        transport.prepare_for_runtime()


def _clear_input_buffers(
    applied_devices: list[AppliedSetupDevice],
) -> None:
    """Clear all device input buffers before autonomous transmission starts."""
    for applied_device in applied_devices:
        applied_device.device.clear_input_buffer()


def _run_device_command_concurrently(
    applied_devices: list[AppliedSetupDevice],
    *,
    command_name: str,
    command: Callable[[AppliedSetupDevice], dict[str, Any]],
    raise_on_error: bool = True,
) -> list[dict[str, Any]]:
    """Run one command concurrently for all applied devices."""
    reports: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=len(applied_devices) or 1) as executor:
        futures = {
            executor.submit(command, applied_device): (index, applied_device)
            for index, applied_device in enumerate(applied_devices)
        }
        for future in as_completed(futures):
            index, applied_device = futures[future]
            report: dict[str, Any] = {
                "_order": index,
                "device_alias": applied_device.resolved_device.alias,
                "device_name": applied_device.device.name,
                "command": command_name,
                "timestamp_unix_s": time(),
                "ok": False,
                "response": None,
                "error": None,
            }
            try:
                response = future.result()
                report["ok"] = True
                report["response"] = response
            except Exception as error:
                report["error"] = str(error)
                if raise_on_error:
                    reports.append(report)
                    raise RuntimeSessionError(
                        f"{command_name} failed for "
                        f"{applied_device.resolved_device.alias}: {error}"
                    ) from error

            reports.append(report)

    reports.sort(key=lambda entry: entry["_order"])
    for report in reports:
        report.pop("_order", None)
    return reports
