"""Coordinate setup-based runtime recording.

This module is the boundary between reusable setup application and the runtime
layer. It opens devices, applies a resolved setup, runs runtime recording
sessions, and closes the devices again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable

from ..device.device_connection import BaudrateProbeResult
from ..runtime.runtime_measurement_buffer import RuntimeRecordingResult
from ..runtime.runtime_session import (
    run_fixed_frame_runtime_session,
    run_manual_runtime_session,
)
from .coordination_setup_application import (
    AppliedSetup,
    close_applied_devices,
    open_and_apply_setup,
)
from .coordination_setup_resolution import ResolvedSetup, resolve_setup

BaudrateProbeCallback = Callable[[BaudrateProbeResult], None]


@dataclass
class RecordingRunResult:
    """Result of one setup-based recording coordination run."""

    resolved_setup: ResolvedSetup
    runtime_result: RuntimeRecordingResult | None = None
    application_warnings: list[dict[str, Any]] = field(default_factory=list)
    connection_reports: list[Any] = field(default_factory=list)
    can_start_transmission: bool = False

    @property
    def completed(self) -> bool:
        """Return whether a runtime recording result was produced."""
        return self.runtime_result is not None


@dataclass
class PreparedRecordingSession:
    """Open setup state kept between RECORD, START, and STOP."""

    setup_config: dict[str, Any]
    resolved_setup: ResolvedSetup
    applied_setup: AppliedSetup
    application_warnings: list[dict[str, Any]] = field(default_factory=list)
    connection_reports: list[Any] = field(default_factory=list)
    can_start_transmission: bool = False
    session_name: str | None = None
    zero_before_recording: bool = True

    def to_run_result(
        self,
        runtime_result: RuntimeRecordingResult | None = None,
    ) -> RecordingRunResult:
        """Return a recording-run result using the prepared setup reports."""
        return RecordingRunResult(
            resolved_setup=self.resolved_setup,
            runtime_result=runtime_result,
            application_warnings=list(self.application_warnings),
            connection_reports=list(self.connection_reports),
            can_start_transmission=self.can_start_transmission,
        )


class RecordingCoordinationError(RuntimeError):
    """Raised when setup recording cannot be coordinated."""


def prepare_recording_session(
    *,
    setup_config: dict[str, Any],
    resolved_setup: ResolvedSetup | None = None,
    session_name: str | None = None,
    zero_before_recording: bool | None = None,
    on_probe_result: BaudrateProbeCallback | None = None,
) -> PreparedRecordingSession:
    """Open and configure a setup without starting autonomous transmission."""
    resolved = resolved_setup or resolve_setup(setup_config)
    applied_setup = open_and_apply_setup(
        setup_config=setup_config,
        resolved_setup=resolved,
        on_probe_result=on_probe_result,
    )
    return PreparedRecordingSession(
        setup_config=setup_config,
        resolved_setup=resolved,
        applied_setup=applied_setup,
        application_warnings=applied_setup.warnings,
        connection_reports=[
            getattr(applied_device.device, "connection_report", None)
            for applied_device in applied_setup.devices
        ],
        can_start_transmission=applied_setup.can_start_transmission,
        session_name=session_name,
        zero_before_recording=(
            bool(resolved.zero_before_recording)
            if zero_before_recording is None
            else bool(zero_before_recording)
        ),
    )


def close_prepared_recording_session(
    prepared_session: PreparedRecordingSession,
) -> None:
    """Close all open devices from a prepared recording session."""
    close_applied_devices(prepared_session.applied_setup.devices)


def record_setup_frames(
    *,
    setup_config: dict[str, Any],
    frame_count_per_device: int,
    discard_initial_frames: int | None = None,
    zero_before_recording: bool | None = None,
    resolved_setup: ResolvedSetup | None = None,
    on_probe_result: BaudrateProbeCallback | None = None,
) -> RecordingRunResult:
    """Apply one setup and record a fixed number of frames per device."""
    resolved = resolved_setup or resolve_setup(setup_config)
    prepared_session: PreparedRecordingSession | None = None

    try:
        prepared_session = prepare_recording_session(
            setup_config=setup_config,
            resolved_setup=resolved,
            zero_before_recording=zero_before_recording,
            on_probe_result=on_probe_result,
        )
        if not prepared_session.can_start_transmission:
            return prepared_session.to_run_result()

        runtime_result = run_fixed_frame_runtime_session(
            prepared_session.applied_setup,
            frame_count_per_device=frame_count_per_device,
            discard_initial_frames=(
                resolved.discard_initial_frames
                if discard_initial_frames is None
                else int(discard_initial_frames)
            ),
            zero_before_recording=prepared_session.zero_before_recording,
        )
        return prepared_session.to_run_result(runtime_result)

    finally:
        if prepared_session is not None:
            close_prepared_recording_session(prepared_session)


def record_prepared_session_until_stopped(
    prepared_session: PreparedRecordingSession,
    *,
    stop_event: Event,
    discard_initial_frames: int | None = None,
    on_recording_started: Callable[[], None] | None = None,
) -> RuntimeRecordingResult:
    """Record a prepared setup until stop_event is set by the caller."""
    if not prepared_session.can_start_transmission:
        raise RecordingCoordinationError(
            "Prepared setup collected blocking warnings; transmission not started."
        )

    return run_manual_runtime_session(
        prepared_session.applied_setup,
        stop_event=stop_event,
        discard_initial_frames=(
            prepared_session.resolved_setup.discard_initial_frames
            if discard_initial_frames is None
            else int(discard_initial_frames)
        ),
        zero_before_recording=prepared_session.zero_before_recording,
        on_recording_started=on_recording_started,
    )
