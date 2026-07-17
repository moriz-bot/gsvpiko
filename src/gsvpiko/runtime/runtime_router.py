"""Runtime frame router for concurrent measurement acquisition and commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import RLock
from time import monotonic, time
from typing import Any, TYPE_CHECKING

from ..constants import constants_commands as COMMAND
from ..constants import constants_errors as ERROR
from ..constants import constants_frames as FRAME
from ..protocol.protocol_frame_parser import (
    extract_serial_frames_from_buffer,
    get_frame_type,
    parse_frame,
)
from ..protocol.protocol_payload_codec import pack_uint8
from ..utils.utils_hex import to_hex

if TYPE_CHECKING:
    from ..coordination.coordination_setup_application import AppliedSetupDevice
    from .runtime_measurement_buffer import RuntimeDeviceResult


@dataclass(frozen=True)
class RoutedMeasurementFrame:
    """One measurement frame routed from the runtime byte stream."""

    raw_frame: bytes
    receive_timestamp_unix_s: float
    receive_timestamp_monotonic_s: float


@dataclass
class RuntimeCommandReport:
    """Diagnostic report for one controlled command cycle during runtime."""

    command_name: str
    command_group_id: str
    started_at_unix_s: float
    started_at_monotonic_s: float
    finished_at_unix_s: float | None = None
    finished_at_monotonic_s: float | None = None
    ok: bool = False
    error: str | None = None
    stop_response_raw_hex: str | None = None
    set_zero_response_raw_hex: str | None = None
    start_response_raw_hex: str | None = None
    discarded_measurement_frames_before_stop_response: int = 0
    discarded_measurement_frames_after_restart: int = 0
    restart_discard_frames_requested: int = 0
    input_buffer_cleared_after_stop: bool = False
    timebase_restarted: bool = False

    @property
    def duration_ms(self) -> float | None:
        """Return total command-cycle duration in milliseconds."""
        if self.finished_at_monotonic_s is None:
            return None
        return (self.finished_at_monotonic_s - self.started_at_monotonic_s) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable report dictionary."""
        return {
            "command_name": self.command_name,
            "command_group_id": self.command_group_id,
            "started_at_unix_s": self.started_at_unix_s,
            "finished_at_unix_s": self.finished_at_unix_s,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "error": self.error,
            "stop_response_raw_hex": self.stop_response_raw_hex,
            "set_zero_response_raw_hex": self.set_zero_response_raw_hex,
            "start_response_raw_hex": self.start_response_raw_hex,
            "discarded_measurement_frames_before_stop_response": (
                self.discarded_measurement_frames_before_stop_response
            ),
            "discarded_measurement_frames_after_restart": (
                self.discarded_measurement_frames_after_restart
            ),
            "restart_discard_frames_requested": self.restart_discard_frames_requested,
            "input_buffer_cleared_after_stop": self.input_buffer_cleared_after_stop,
            "timebase_restarted": self.timebase_restarted,
        }


@dataclass
class _PendingResponse:
    """Internal state for one command response awaited by the router."""

    command_name: str
    response_queue: Queue[dict[str, Any]] = field(default_factory=Queue)


class RuntimeFrameRouter:
    """Route all frames while runtime acquisition owns the byte stream.

    The reader owns all incoming bytes during autonomous transmission. Measurement
    frames normally go to the runtime reader. Response frames go to the command
    that is currently waiting for them.

    Runtime SetZero is intentionally handled as a controlled Stop/SetZero/Start
    cycle. This creates a documented measurement interruption instead of risking
    a silent timestamp/index shift.
    """

    NORMAL = "normal"
    BEFORE_STOP_RESPONSE = "before_stop_response"
    AFTER_RESTART = "after_restart"

    def __init__(
        self,
        applied_device: "AppliedSetupDevice",
        result: "RuntimeDeviceResult",
    ) -> None:
        self.applied_device = applied_device
        self.device = applied_device.device
        self.result = result
        self.raw_buffer = bytearray()
        self._lock = RLock()
        self._pending_response: _PendingResponse | None = None
        self._phase = self.NORMAL
        self._active_report: RuntimeCommandReport | None = None
        self._restart_discard_remaining = 0
        self._timebase_restart_requests = 0
        self._report_finalized = False

    def __enter__(self) -> "RuntimeFrameRouter":
        """Attach this router as the active command exchange."""
        self.device.attach_command_exchange(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Detach this router and finalize any active command report."""
        with self._lock:
            self._finalize_active_report_if_needed()
        self.device.detach_command_exchange(self)

    def route_available_bytes(
        self,
        chunk: bytes,
        *,
        receive_timestamp_unix_s: float,
        receive_timestamp_monotonic_s: float,
    ) -> list[RoutedMeasurementFrame]:
        """Route all complete frames from one newly received byte chunk."""
        if not chunk:
            return []

        with self._lock:
            self.raw_buffer.extend(chunk)
            extracted = extract_serial_frames_from_buffer(self.raw_buffer)
            self.result.parser_resync_count += extracted.resync_count
            measurements: list[RoutedMeasurementFrame] = []

            for raw_frame in extracted.frames:
                frame_type = get_frame_type(raw_frame[1])
                if frame_type == FRAME.MEASUREMENT:
                    routed = RoutedMeasurementFrame(
                        raw_frame=raw_frame,
                        receive_timestamp_unix_s=receive_timestamp_unix_s,
                        receive_timestamp_monotonic_s=receive_timestamp_monotonic_s,
                    )
                    if self._should_discard_measurement_during_runtime_command():
                        self._count_runtime_command_discard()
                        continue
                    measurements.append(routed)
                    continue

                try:
                    parsed = parse_frame(raw_frame)
                except ValueError as error:
                    self.result.errors.append(f"runtime router parse error: {error}")
                    continue

                parsed["raw_hex"] = to_hex(raw_frame)
                if parsed["kind"] == "response" and self._pending_response is not None:
                    self._mark_pending_response_seen(parsed)
                    self._pending_response.response_queue.put(parsed)
                    continue

                self.result.routed_non_measurement_frame_count += 1

            return measurements

    def _mark_pending_response_seen(self, parsed_response: dict[str, Any]) -> None:
        """Mirror routed command-response metadata into the active report early."""
        if self._active_report is None or self._pending_response is None:
            return
        raw_hex = parsed_response.get("raw_hex")
        if self._pending_response.command_name == "StopTransmission":
            self._active_report.stop_response_raw_hex = raw_hex
        elif self._pending_response.command_name == "SetZero":
            self._active_report.set_zero_response_raw_hex = raw_hex
        elif self._pending_response.command_name == "StartTransmission":
            self._active_report.start_response_raw_hex = raw_hex

    def request(
        self,
        command: int,
        payload: bytes = b"",
        *,
        on_measurement=None,
    ) -> dict[str, Any]:
        """Send one command and wait for its response through the router."""
        if on_measurement is not None:
            raise ValueError(
                "Runtime command exchange does not support on_measurement callbacks; "
                "measurement frames are owned by the active runtime reader."
            )
        return self._request_response(
            command,
            payload,
            command_name=_command_name(command),
        )

    def run_set_zero_restart_cycle(
        self,
        *,
        command_group_id: str,
        restart_discard_frames: int,
        timeout_s: float = 2.0,
    ) -> dict[str, Any]:
        """Run StopTransmission, SetZero, and StartTransmission as one cycle."""
        restart_discard_count = int(restart_discard_frames)
        if restart_discard_count < 0:
            raise ValueError("restart_discard_frames must not be negative.")

        with self._lock:
            if self._active_report is not None:
                raise RuntimeError("A runtime command cycle is already active.")
            self._active_report = RuntimeCommandReport(
                command_name="SET_ZERO",
                command_group_id=command_group_id,
                started_at_unix_s=time(),
                started_at_monotonic_s=monotonic(),
                restart_discard_frames_requested=restart_discard_count,
            )
            self._report_finalized = False
            self._phase = self.BEFORE_STOP_RESPONSE

        try:
            stop_response = self._request_response(
                COMMAND.STOP_TRANSMISSION,
                command_name="StopTransmission",
                timeout_s=timeout_s,
            )
            if self._active_report is not None:
                self._active_report.stop_response_raw_hex = stop_response.get("raw_hex")

            self.clear_pending_input()
            if self._active_report is not None:
                self._active_report.input_buffer_cleared_after_stop = True

            set_zero_response = self._request_response(
                COMMAND.SET_ZERO,
                pack_uint8(0),
                command_name="SetZero",
                timeout_s=timeout_s,
            )
            if self._active_report is not None:
                self._active_report.set_zero_response_raw_hex = set_zero_response.get("raw_hex")

            with self._lock:
                self._phase = self.AFTER_RESTART
                self._restart_discard_remaining = restart_discard_count

            start_response = self._request_response(
                COMMAND.START_TRANSMISSION,
                command_name="StartTransmission",
                timeout_s=timeout_s,
            )
            if self._active_report is not None:
                self._active_report.start_response_raw_hex = start_response.get("raw_hex")

            with self._lock:
                if self._restart_discard_remaining == 0:
                    self._request_timebase_restart_locked()
                    self._phase = self.NORMAL
                    self._finalize_active_report_if_needed(ok=True)

            return {
                "kind": "response",
                "status": ERROR.OK,
                "runtime_controlled": True,
                "command_name": "SET_ZERO",
                "command_group_id": command_group_id,
                "restart_discard_frames": restart_discard_count,
            }
        except BaseException as error:
            with self._lock:
                if self._active_report is not None:
                    self._active_report.error = str(error)
                    self._active_report.finished_at_unix_s = time()
                    self._active_report.finished_at_monotonic_s = monotonic()
                    self._phase = self.NORMAL
                    self._restart_discard_remaining = 0
                    self._finalize_active_report_if_needed(ok=False)
            raise

    def consume_timebase_restart_request(self) -> bool:
        """Consume one pending request to start a new estimated timebase segment."""
        with self._lock:
            if self._timebase_restart_requests <= 0:
                return False
            self._timebase_restart_requests -= 1
            return True

    def clear_pending_input(self) -> None:
        """Clear transport and router buffers after controlled StopTransmission."""
        with self._lock:
            self.raw_buffer.clear()
            self.device.clear_input_buffer()

    def _request_response(
        self,
        command: int,
        payload: bytes = b"",
        *,
        command_name: str,
        timeout_s: float = 2.0,
    ) -> dict[str, Any]:
        """Send a command and wait for the next routed response frame."""
        with self._lock:
            if self._pending_response is not None:
                raise RuntimeError("Another runtime command is already waiting for a response.")
            pending = _PendingResponse(command_name=command_name)
            self._pending_response = pending
            request_frame = self.device.build_command_frame(command, payload)
            request_raw_hex = to_hex(request_frame)
            self.device.transport.write(request_frame)

        try:
            deadline = monotonic() + float(timeout_s)
            while True:
                remaining_s = deadline - monotonic()
                if remaining_s <= 0:
                    raise TimeoutError(
                        f"No runtime response for {command_name} before "
                        f"{timeout_s:.3f} s timeout."
                    )
                try:
                    response = pending.response_queue.get(timeout=min(0.05, remaining_s))
                    break
                except Empty:
                    continue

            response["request_raw_hex"] = request_raw_hex
            response["runtime_routed"] = True
            return self.device.ensure_ok(response)
        finally:
            with self._lock:
                if self._pending_response is pending:
                    self._pending_response = None

    def _should_discard_measurement_during_runtime_command(self) -> bool:
        """Return whether the current measurement must be hidden from records."""
        if self._phase == self.BEFORE_STOP_RESPONSE:
            return True
        if self._phase == self.AFTER_RESTART:
            if self._active_report is not None and self._active_report.start_response_raw_hex is None:
                return True
            if self._restart_discard_remaining > 0:
                return True
            return False
        return False

    def _count_runtime_command_discard(self) -> None:
        """Count one deliberately discarded runtime-command measurement frame."""
        self.result.runtime_command_discarded_frame_count += 1
        if self._active_report is None:
            return

        if self._phase == self.BEFORE_STOP_RESPONSE:
            self._active_report.discarded_measurement_frames_before_stop_response += 1
            return

        if self._phase == self.AFTER_RESTART:
            self._active_report.discarded_measurement_frames_after_restart += 1
            if self._restart_discard_remaining > 0:
                self._restart_discard_remaining -= 1
            if (
                self._restart_discard_remaining == 0
                and self._active_report.start_response_raw_hex is not None
            ):
                self._request_timebase_restart_locked()
                self._phase = self.NORMAL
                self._finalize_active_report_if_needed(ok=True)

    def _request_timebase_restart_locked(self) -> None:
        """Mark that the next stored frame starts a new estimated timebase segment."""
        self._timebase_restart_requests += 1
        if self._active_report is not None:
            self._active_report.timebase_restarted = True

    def _finalize_active_report_if_needed(self, *, ok: bool | None = None) -> None:
        """Append the active command report once."""
        if self._active_report is None or self._report_finalized:
            return
        if ok is not None:
            self._active_report.ok = ok
        elif self._active_report.error is None:
            self._active_report.ok = True
        if self._active_report.finished_at_unix_s is None:
            self._active_report.finished_at_unix_s = time()
            self._active_report.finished_at_monotonic_s = monotonic()
        self.result.runtime_command_reports.append(self._active_report.to_dict())
        self._report_finalized = True
        self._active_report = None


def _command_name(command: int) -> str:
    """Return a compact command name for diagnostics."""
    for name, value in vars(COMMAND).items():
        if name.isupper() and value == int(command):
            return name
    return f"0x{int(command):02X}"
