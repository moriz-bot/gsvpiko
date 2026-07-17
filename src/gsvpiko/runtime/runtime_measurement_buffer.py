"""Runtime measurement data containers.

The runtime layer stores normalized records that are independent of the final
file format. CSV writing can later consume these records without knowing how the
frames were read from the devices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class RuntimeMeasurementRecord:
    """One timestamped measurement frame received from one GSV device."""

    device_alias: str
    device_name: str
    frame_index: int
    read_index: int
    timestamp_unix_s: float
    timestamp_monotonic_s: float
    values: list[float]
    channels: dict[str, float]
    object_count: int
    datatype: int
    input_saturation: bool
    six_axis_error: bool
    raw_hex: str | None = None
    receive_timestamp_unix_s: float | None = None
    receive_timestamp_monotonic_s: float | None = None
    timestamp_mode: str = "receive_time"


@dataclass
class RuntimeDeviceResult:
    """Runtime result collected for one device reader."""

    device_alias: str
    device_name: str
    records: list[RuntimeMeasurementRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    discarded_frame_count: int = 0
    started_at_unix_s: float | None = None
    ended_at_unix_s: float | None = None
    started_at_monotonic_s: float | None = None
    ended_at_monotonic_s: float | None = None
    bytes_read: int = 0
    parser_resync_count: int = 0
    routed_non_measurement_frame_count: int = 0
    runtime_command_discarded_frame_count: int = 0
    runtime_command_reports: list[dict[str, Any]] = field(default_factory=list)
    reader_type: str = "frame_by_frame"

    @property
    def frame_count(self) -> int:
        """Return the number of stored measurement records."""
        return len(self.records)

    @property
    def total_measurement_frames_read(self) -> int:
        """Return stored and deliberately discarded measurement frames."""
        return self.frame_count + self.discarded_frame_count

    @property
    def has_errors(self) -> bool:
        """Return whether this reader collected errors."""
        return bool(self.errors)

    @property
    def read_duration_s(self) -> float | None:
        """Return the monotonic reader duration if start and end are known."""
        if self.started_at_monotonic_s is None or self.ended_at_monotonic_s is None:
            return None

        return self.ended_at_monotonic_s - self.started_at_monotonic_s

    @property
    def stored_frame_rate_hz(self) -> float | None:
        """Return stored frames per reader duration."""
        duration_s = self.read_duration_s
        if duration_s is None or duration_s <= 0:
            return None

        return self.frame_count / duration_s

    @property
    def total_frame_rate_hz(self) -> float | None:
        """Return all read measurement frames per reader duration."""
        duration_s = self.read_duration_s
        if duration_s is None or duration_s <= 0:
            return None

        return self.total_measurement_frames_read / duration_s

    @property
    def byte_rate_Bps(self) -> float | None:
        """Return read bytes per reader duration."""
        duration_s = self.read_duration_s
        if duration_s is None or duration_s <= 0:
            return None

        return self.bytes_read / duration_s

    def timestamp_unix_values(self) -> list[float]:
        """Return primary Unix timestamps for all stored records."""
        return [record.timestamp_unix_s for record in self.records]

    def receive_timestamp_unix_values(self) -> list[float]:
        """Return receive Unix timestamps for records where they are known."""
        return [
            record.receive_timestamp_unix_s
            for record in self.records
            if record.receive_timestamp_unix_s is not None
        ]

    def receive_intervals_s(self) -> list[float]:
        """Return intervals between consecutive primary timestamps."""
        timestamps = self.timestamp_unix_values()
        return [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]

    def receive_delivery_intervals_s(self) -> list[float]:
        """Return intervals between consecutive raw receive timestamps."""
        timestamps = self.receive_timestamp_unix_values()
        return [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]


@dataclass
class RuntimeRecordingResult:
    """Result of one multi-device runtime recording session."""

    setup_name: str
    requested_frame_count_per_device: int
    discard_initial_frames: int
    started_at_unix_s: float
    ended_at_unix_s: float
    device_results: list[RuntimeDeviceResult]
    tare_reports: list[dict[str, Any]] = field(default_factory=list)
    start_reports: list[dict[str, Any]] = field(default_factory=list)
    stop_reports: list[dict[str, Any]] = field(default_factory=list)
    events: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        """Return wall-clock duration of the runtime session."""
        return self.ended_at_unix_s - self.started_at_unix_s

    @property
    def has_errors(self) -> bool:
        """Return whether any device reader collected errors."""
        return any(device_result.has_errors for device_result in self.device_results)

    def get_device_result(
        self,
        device_alias: str,
    ) -> RuntimeDeviceResult:
        """Return the runtime result for one device alias."""
        for device_result in self.device_results:
            if device_result.device_alias == device_alias:
                return device_result

        raise KeyError(device_alias)

    def frame_count_by_device(self) -> dict[str, int]:
        """Return stored frame counts keyed by device alias."""
        return {
            device_result.device_alias: device_result.frame_count
            for device_result in self.device_results
        }


def average_or_none(
    values: list[float],
) -> float | None:
    """Return the arithmetic mean or None for an empty list."""
    if not values:
        return None

    return mean(values)
