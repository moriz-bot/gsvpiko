"""Runtime session orchestration for setup-applied GSV devices."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from threading import Event
from time import time
from typing import Any, Callable

from ..coordination.coordination_setup_application import AppliedSetup, AppliedSetupDevice
from ..transport.transport_base import BaseTransport
from .runtime_measurement_buffer import RuntimeRecordingResult
from .runtime_reader import (
    RuntimeCaptureReaderGroup,
    read_frames_concurrently,
    read_until_stopped_concurrently,
    start_capture_readers_concurrently,
)


class RuntimeSessionError(RuntimeError):
    """Raised when a runtime session cannot be executed safely."""


DEFAULT_RUNTIME_COMMAND_RESTART_DISCARD_FRAMES = 5


@dataclass
class ContinuousRuntimeSession:
    """Running transmission session with gated recording/capture windows."""

    applied_setup: AppliedSetup
    reader_group: RuntimeCaptureReaderGroup
    discard_initial_frames: int = 0
    started_at_unix_s: float = field(default_factory=time)
    events: dict[str, Any] = field(default_factory=dict)
    tare_reports: list[dict[str, Any]] = field(default_factory=list)
    start_reports: list[dict[str, Any]] = field(default_factory=list)
    stop_reports: list[dict[str, Any]] = field(default_factory=list)
    _capture_started_at_unix_s: float | None = None

    @property
    def is_capturing(self) -> bool:
        """Return whether incoming measurement frames are currently stored."""
        return self.reader_group.is_capturing

    def start_capture(self) -> dict[str, Any]:
        """Start one capture window without changing the GSV transmission state."""
        if self.is_capturing:
            raise RuntimeSessionError("Recording is already active.")
        timestamp = time()
        self._capture_started_at_unix_s = timestamp
        self.reader_group.start_capture()
        report = _command_event_report("start", timestamp)
        self.command_reports.append(report)
        return report

    def stop_capture(self, *, automatic: bool = False) -> dict[str, Any]:
        """Stop the active capture window while transmission continues."""
        if not self.is_capturing:
            raise RuntimeSessionError("No active recording window.")
        timestamp = time()
        self.reader_group.stop_capture()
        report = _command_event_report("stop", timestamp)
        if automatic:
            report["automatic"] = True
        if self._capture_started_at_unix_s is not None:
            report["capture_duration_s"] = timestamp - self._capture_started_at_unix_s
        self._capture_started_at_unix_s = None
        self.command_reports.append(report)
        return report

    @property
    def command_reports(self) -> list[dict[str, Any]]:
        """Return session-level command/event reports used by CSV output."""
        reports = self.events.setdefault("command_reports", [])
        return reports

    def add_command_event(self, command_name: str) -> dict[str, Any]:
        """Append one user-facing session command event."""
        report = _command_event_report(command_name, time())
        self.command_reports.append(report)
        return report

    def stop_transmission_and_collect(self) -> RuntimeRecordingResult:
        """Stop readers/transmission and return the collected runtime result."""
        if self.is_capturing:
            self.stop_capture(automatic=True)
        self.events["capture_readers_stop_requested_at"] = time()
        device_results = self.reader_group.stop_and_join()
        self.events["capture_readers_stopped_at"] = time()
        self.events["stop_transmission_requested_at"] = time()
        self.stop_reports = stop_transmission_concurrently(self.applied_setup)
        self.events["stop_transmission_sent_at"] = time()
        ended_at_unix_s = time()
        return RuntimeRecordingResult(
            setup_name=self.applied_setup.resolved_setup.name,
            requested_frame_count_per_device=0,
            discard_initial_frames=self.discard_initial_frames,
            started_at_unix_s=self.started_at_unix_s,
            ended_at_unix_s=ended_at_unix_s,
            device_results=device_results,
            tare_reports=self.tare_reports,
            start_reports=self.start_reports,
            stop_reports=self.stop_reports,
            events=dict(self.events),
        )


def start_continuous_runtime_session(
    applied_setup: AppliedSetup,
    *,
    discard_initial_frames: int = 0,
    zero_before_recording: bool = True,
    use_batched_transport_reader: bool = True,
    use_batched_serial_reader: bool | None = None,
) -> ContinuousRuntimeSession:
    """Start GSV transmission and continuous readers without storing frames yet."""
    if not applied_setup.can_start_transmission:
        raise RuntimeSessionError(
            "Setup application collected blocking warnings; transmission not started."
        )

    started_at_unix_s = time()
    events: dict[str, Any] = {
        "runtime_session_started_at": started_at_unix_s,
        "recording_mode": "continuous_capture_windows",
        "preparation_started_at": time(),
    }
    stop_transmission_concurrently(applied_setup)
    _prepare_transports_for_runtime(applied_setup.devices)
    _clear_input_buffers(applied_setup.devices)

    tare_reports: list[dict[str, Any]] = []
    if zero_before_recording:
        tare_reports = set_zero_all_channels_concurrently(applied_setup)
        events["zero_completed_at"] = time()
    else:
        events["zero_completed_at"] = None
    _clear_input_buffers(applied_setup.devices)
    events["preparation_completed_at"] = time()

    start_reports: list[dict[str, Any]] = []

    def start_after_readers_are_ready() -> None:
        nonlocal start_reports
        events["readers_ready_at"] = time()
        start_reports = start_transmission_concurrently(applied_setup)
        events["start_transmission_sent_at"] = time()

    reader_group = start_capture_readers_concurrently(
        applied_setup.devices,
        discard_initial_frames=discard_initial_frames,
        expected_sample_rate_hz=applied_setup.resolved_setup.sample_rate_hz,
        use_batched_transport_reader=use_batched_transport_reader,
        use_batched_serial_reader=use_batched_serial_reader,
        on_readers_ready=start_after_readers_are_ready,
    )
    session = ContinuousRuntimeSession(
        applied_setup=applied_setup,
        reader_group=reader_group,
        discard_initial_frames=discard_initial_frames,
        started_at_unix_s=started_at_unix_s,
        events=events,
        tare_reports=tare_reports,
        start_reports=start_reports,
    )
    if zero_before_recording:
        session.add_command_event("tare")
    return session


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
    """Clear input buffers on all applied devices where possible."""
    for applied_device in applied_devices:
        applied_device.device.clear_input_buffer()


def _run_device_command_concurrently(
    applied_devices: list[AppliedSetupDevice],
    *,
    command_name: str,
    command: Callable[[AppliedSetupDevice], Any],
    raise_on_error: bool = True,
) -> list[dict[str, Any]]:
    """Run one device command concurrently on all applied devices."""
    reports: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(applied_devices))) as executor:
        future_to_device = {
            executor.submit(_run_single_device_command, applied_device, command_name, command): applied_device
            for applied_device in applied_devices
        }
        for future in as_completed(future_to_device):
            report = future.result()
            reports.append(report)
            if raise_on_error and not report.get("ok"):
                raise RuntimeSessionError(
                    f"{command_name} failed on {report.get('device_alias')}: {report.get('error')}"
                )
    reports.sort(key=lambda report: str(report.get("device_alias")))
    return reports


def _run_single_device_command(
    applied_device: AppliedSetupDevice,
    command_name: str,
    command: Callable[[AppliedSetupDevice], Any],
) -> dict[str, Any]:
    """Run one command on one device and return a structured report."""
    started = time()
    try:
        response = command(applied_device)
        ended = time()
        return {
            "device_alias": applied_device.resolved_device.alias,
            "device_name": applied_device.device.name,
            "command_name": command_name,
            "started_at_unix_s": started,
            "ended_at_unix_s": ended,
            "duration_ms": (ended - started) * 1000.0,
            "response": response,
            "ok": True,
        }
    except Exception as error:
        ended = time()
        return {
            "device_alias": applied_device.resolved_device.alias,
            "device_name": applied_device.device.name,
            "command_name": command_name,
            "started_at_unix_s": started,
            "ended_at_unix_s": ended,
            "duration_ms": (ended - started) * 1000.0,
            "error": str(error),
            "ok": False,
        }


def _command_event_report(command_name: str, timestamp: float) -> dict[str, Any]:
    """Return a compact report for a session-level event marker."""
    return {
        "command_name": command_name,
        "command_group_id": f"{command_name}_{timestamp:.6f}",
        "started_at_unix_s": timestamp,
        "ended_at_unix_s": timestamp,
        "duration_ms": 0.0,
        "ok": True,
    }
