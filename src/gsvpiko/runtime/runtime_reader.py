"""Concurrent runtime readers for measurement frames."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Barrier, Event, Thread
from time import perf_counter, sleep, time
from typing import Any, Callable

from ..coordination.coordination_setup_application import AppliedSetupDevice
from ..protocol.protocol_frame_parser import parse_measurement_frame
from ..transport.transport_base import BaseTransport
from .runtime_measurement_buffer import (
    RuntimeDeviceResult,
    RuntimeMeasurementRecord,
)
from .runtime_router import RuntimeFrameRouter, RoutedMeasurementFrame

BATCH_READ_SIZE = 65536
EMPTY_READ_SLEEP_S = 0.0001
NO_PROGRESS_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class RuntimeReaderConfig:
    """Configuration for one fixed-length runtime reader pass."""

    frame_count: int
    discard_initial_frames: int = 0
    expected_sample_rate_hz: float | None = None
    use_batched_transport_reader: bool = True

    def __post_init__(self) -> None:
        """Validate reader configuration values."""
        if self.frame_count <= 0:
            raise ValueError("frame_count must be greater than zero.")
        if self.discard_initial_frames < 0:
            raise ValueError("discard_initial_frames must not be negative.")
        if self.expected_sample_rate_hz is not None and self.expected_sample_rate_hz <= 0:
            raise ValueError("expected_sample_rate_hz must be greater than zero.")


@dataclass(frozen=True)
class RuntimeManualReaderConfig:
    """Configuration for one manual start/stop runtime reader pass."""

    discard_initial_frames: int = 0
    expected_sample_rate_hz: float | None = None
    use_batched_transport_reader: bool = True

    def __post_init__(self) -> None:
        """Validate reader configuration values."""
        if self.discard_initial_frames < 0:
            raise ValueError("discard_initial_frames must not be negative.")
        if self.expected_sample_rate_hz is not None and self.expected_sample_rate_hz <= 0:
            raise ValueError("expected_sample_rate_hz must be greater than zero.")


class RuntimeMeasurementReader:
    """Read a fixed number of measurement frames from one applied GSV device."""

    def __init__(
        self,
        applied_device: AppliedSetupDevice,
        *,
        config: RuntimeReaderConfig,
        ready_barrier: Barrier,
        start_event: Event,
    ) -> None:
        self.applied_device = applied_device
        self.config = config
        self.ready_barrier = ready_barrier
        self.start_event = start_event
        self.result = RuntimeDeviceResult(
            device_alias=applied_device.resolved_device.alias,
            device_name=applied_device.device.name,
        )
        self._thread = Thread(
            target=self._run,
            name=f"gsvpiko-reader-{applied_device.resolved_device.alias}",
            daemon=True,
        )

    def start(self) -> None:
        """Start the reader thread."""
        self._thread.start()

    def join(
        self,
        timeout: float | None = None,
    ) -> None:
        """Wait until the reader thread stops."""
        self._thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        """Return whether the reader thread is still running."""
        return self._thread.is_alive()

    def _run(self) -> None:
        """Reader thread body."""
        self.result.started_at_unix_s = time()
        self.result.started_at_monotonic_s = perf_counter()
        try:
            self.ready_barrier.wait()
            self.start_event.wait()
            if self.config.use_batched_transport_reader:
                self._run_batched_transport_reader()
            else:
                self._run_frame_by_frame_reader()
        except Exception as error:
            self.result.errors.append(str(error))
        finally:
            self.result.ended_at_unix_s = time()
            self.result.ended_at_monotonic_s = perf_counter()

    def _run_frame_by_frame_reader(self) -> None:
        """Read frames through the normal device parser."""
        self.result.reader_type = "frame_by_frame"
        total_reads = self.config.frame_count + self.config.discard_initial_frames
        stored_index = 0

        for read_index in range(1, total_reads + 1):
            frame = self.applied_device.device.acquisition.read_next_measurement_frame()
            timestamp_unix_s = time()
            timestamp_monotonic_s = perf_counter()

            if read_index <= self.config.discard_initial_frames:
                self.result.discarded_frame_count += 1
                continue

            stored_index += 1
            self.result.records.append(
                _build_runtime_record_from_frame(
                    applied_device=self.applied_device,
                    frame=frame,
                    frame_index=stored_index,
                    read_index=read_index,
                    timestamp_unix_s=timestamp_unix_s,
                    timestamp_monotonic_s=timestamp_monotonic_s,
                    receive_timestamp_unix_s=timestamp_unix_s,
                    receive_timestamp_monotonic_s=timestamp_monotonic_s,
                    timestamp_mode="receive_time",
                )
            )

    def _run_batched_transport_reader(self) -> None:
        """Read raw transport bytes in batches and route complete frames."""
        transport = _require_base_transport(self.applied_device.device.transport)
        self.result.reader_type = f"batched_{transport.connection_type}"
        read_index = 0
        stored_index = 0
        first_stored_unix_s: float | None = None
        first_stored_monotonic_s: float | None = None
        segment_first_frame_index = 1
        last_progress_monotonic_s = perf_counter()

        with RuntimeFrameRouter(self.applied_device, self.result) as router:
            while stored_index < self.config.frame_count:
                chunk = transport.read_available(BATCH_READ_SIZE)
                receive_timestamp_unix_s = time()
                receive_timestamp_monotonic_s = perf_counter()

                if chunk:
                    self.result.bytes_read += len(chunk)
                    last_progress_monotonic_s = receive_timestamp_monotonic_s
                elif receive_timestamp_monotonic_s - last_progress_monotonic_s > NO_PROGRESS_TIMEOUT_S:
                    raise TimeoutError(
                        "No measurement bytes were received before the batched-reader "
                        f"timeout of {NO_PROGRESS_TIMEOUT_S:.3f} s."
                    )
                else:
                    sleep(EMPTY_READ_SLEEP_S)
                    continue

                for routed_frame in router.route_available_bytes(
                    chunk,
                    receive_timestamp_unix_s=receive_timestamp_unix_s,
                    receive_timestamp_monotonic_s=receive_timestamp_monotonic_s,
                ):
                    read_index += 1
                    if read_index <= self.config.discard_initial_frames:
                        self.result.discarded_frame_count += 1
                        continue

                    stored_index += 1
                    if router.consume_timebase_restart_request():
                        first_stored_unix_s = None
                        first_stored_monotonic_s = None
                        segment_first_frame_index = stored_index
                    if first_stored_unix_s is None:
                        first_stored_unix_s = routed_frame.receive_timestamp_unix_s
                        first_stored_monotonic_s = routed_frame.receive_timestamp_monotonic_s

                    timestamp_unix_s, timestamp_monotonic_s, timestamp_mode = (
                        _timestamp_for_stored_frame(
                            frame_index=stored_index,
                            segment_first_frame_index=segment_first_frame_index,
                            first_stored_unix_s=first_stored_unix_s,
                            first_stored_monotonic_s=first_stored_monotonic_s,
                            receive_timestamp_unix_s=routed_frame.receive_timestamp_unix_s,
                            receive_timestamp_monotonic_s=routed_frame.receive_timestamp_monotonic_s,
                            expected_sample_rate_hz=self.config.expected_sample_rate_hz,
                        )
                    )
                    self.result.records.append(
                        _build_runtime_record_from_routed_measurement_frame(
                            applied_device=self.applied_device,
                            routed_frame=routed_frame,
                            frame_index=stored_index,
                            read_index=read_index,
                            timestamp_unix_s=timestamp_unix_s,
                            timestamp_monotonic_s=timestamp_monotonic_s,
                            timestamp_mode=timestamp_mode,
                        )
                    )

                    if stored_index >= self.config.frame_count:
                        break


class RuntimeManualMeasurementReader:
    """Read measurement frames until a shared stop event is set."""

    def __init__(
        self,
        applied_device: AppliedSetupDevice,
        *,
        config: RuntimeManualReaderConfig,
        ready_barrier: Barrier,
        start_event: Event,
        stop_event: Event,
    ) -> None:
        self.applied_device = applied_device
        self.config = config
        self.ready_barrier = ready_barrier
        self.start_event = start_event
        self.stop_event = stop_event
        self.first_stored_event = Event()
        self.result = RuntimeDeviceResult(
            device_alias=applied_device.resolved_device.alias,
            device_name=applied_device.device.name,
        )
        self._thread = Thread(
            target=self._run,
            name=f"gsvpiko-manual-reader-{applied_device.resolved_device.alias}",
            daemon=True,
        )

    def start(self) -> None:
        """Start the reader thread."""
        self._thread.start()

    def join(
        self,
        timeout: float | None = None,
    ) -> None:
        """Wait until the reader thread stops."""
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        """Reader thread body."""
        self.result.started_at_unix_s = time()
        self.result.started_at_monotonic_s = perf_counter()
        try:
            self.ready_barrier.wait()
            self.start_event.wait()
            if self.config.use_batched_transport_reader:
                self._run_batched_transport_reader()
            else:
                self._run_frame_by_frame_reader()
        except Exception as error:
            self.result.errors.append(str(error))
        finally:
            self.result.ended_at_unix_s = time()
            self.result.ended_at_monotonic_s = perf_counter()

    def _run_frame_by_frame_reader(self) -> None:
        """Read frames through the normal device parser until stop is requested."""
        self.result.reader_type = "frame_by_frame"
        read_index = 0
        stored_index = 0

        while not self.stop_event.is_set():
            frame = self.applied_device.device.acquisition.read_next_measurement_frame()
            timestamp_unix_s = time()
            timestamp_monotonic_s = perf_counter()
            read_index += 1

            if read_index <= self.config.discard_initial_frames:
                self.result.discarded_frame_count += 1
                continue

            stored_index += 1
            if stored_index == 1:
                self.first_stored_event.set()
            self.result.records.append(
                _build_runtime_record_from_frame(
                    applied_device=self.applied_device,
                    frame=frame,
                    frame_index=stored_index,
                    read_index=read_index,
                    timestamp_unix_s=timestamp_unix_s,
                    timestamp_monotonic_s=timestamp_monotonic_s,
                    receive_timestamp_unix_s=timestamp_unix_s,
                    receive_timestamp_monotonic_s=timestamp_monotonic_s,
                    timestamp_mode="receive_time",
                )
            )

    def _run_batched_transport_reader(self) -> None:
        """Read raw transport bytes in batches until stop is requested."""
        transport = _require_base_transport(self.applied_device.device.transport)
        self.result.reader_type = f"batched_{transport.connection_type}"
        read_index = 0
        stored_index = 0
        first_stored_unix_s: float | None = None
        first_stored_monotonic_s: float | None = None
        segment_first_frame_index = 1
        last_progress_monotonic_s = perf_counter()

        with RuntimeFrameRouter(self.applied_device, self.result) as router:
            while not self.stop_event.is_set():
                chunk = transport.read_available(BATCH_READ_SIZE)
                receive_timestamp_unix_s = time()
                receive_timestamp_monotonic_s = perf_counter()

                if chunk:
                    self.result.bytes_read += len(chunk)
                    last_progress_monotonic_s = receive_timestamp_monotonic_s
                elif receive_timestamp_monotonic_s - last_progress_monotonic_s > NO_PROGRESS_TIMEOUT_S:
                    raise TimeoutError(
                        "No measurement bytes were received before the batched-reader "
                        f"timeout of {NO_PROGRESS_TIMEOUT_S:.3f} s."
                    )
                else:
                    sleep(EMPTY_READ_SLEEP_S)
                    continue

                for routed_frame in router.route_available_bytes(
                    chunk,
                    receive_timestamp_unix_s=receive_timestamp_unix_s,
                    receive_timestamp_monotonic_s=receive_timestamp_monotonic_s,
                ):
                    read_index += 1
                    if read_index <= self.config.discard_initial_frames:
                        self.result.discarded_frame_count += 1
                        continue

                    stored_index += 1
                    if router.consume_timebase_restart_request():
                        first_stored_unix_s = None
                        first_stored_monotonic_s = None
                        segment_first_frame_index = stored_index
                    if first_stored_unix_s is None:
                        first_stored_unix_s = routed_frame.receive_timestamp_unix_s
                        first_stored_monotonic_s = routed_frame.receive_timestamp_monotonic_s
                        self.first_stored_event.set()

                    timestamp_unix_s, timestamp_monotonic_s, timestamp_mode = (
                        _timestamp_for_stored_frame(
                            frame_index=stored_index,
                            segment_first_frame_index=segment_first_frame_index,
                            first_stored_unix_s=first_stored_unix_s,
                            first_stored_monotonic_s=first_stored_monotonic_s,
                            receive_timestamp_unix_s=routed_frame.receive_timestamp_unix_s,
                            receive_timestamp_monotonic_s=routed_frame.receive_timestamp_monotonic_s,
                            expected_sample_rate_hz=self.config.expected_sample_rate_hz,
                        )
                    )
                    self.result.records.append(
                        _build_runtime_record_from_routed_measurement_frame(
                            applied_device=self.applied_device,
                            routed_frame=routed_frame,
                            frame_index=stored_index,
                            read_index=read_index,
                            timestamp_unix_s=timestamp_unix_s,
                            timestamp_monotonic_s=timestamp_monotonic_s,
                            timestamp_mode=timestamp_mode,
                        )
                    )


def read_frames_concurrently(
    applied_devices: list[AppliedSetupDevice],
    *,
    frame_count: int,
    discard_initial_frames: int = 0,
    expected_sample_rate_hz: float | None = None,
    use_batched_transport_reader: bool = True,
    use_batched_serial_reader: bool | None = None,
    on_readers_ready: Callable[[], None] | None = None,
) -> list[RuntimeDeviceResult]:
    """Read a fixed number of frames from all devices using one thread per GSV."""
    if not applied_devices:
        return []

    config = RuntimeReaderConfig(
        frame_count=frame_count,
        discard_initial_frames=discard_initial_frames,
        expected_sample_rate_hz=expected_sample_rate_hz,
        use_batched_transport_reader=(
            use_batched_transport_reader
            if use_batched_serial_reader is None
            else use_batched_serial_reader
        ),
    )
    ready_barrier = Barrier(len(applied_devices) + 1)
    start_event = Event()
    readers = [
        RuntimeMeasurementReader(
            applied_device,
            config=config,
            ready_barrier=ready_barrier,
            start_event=start_event,
        )
        for applied_device in applied_devices
    ]

    for reader in readers:
        reader.start()

    callback_error: BaseException | None = None
    try:
        ready_barrier.wait()
        if on_readers_ready is not None:
            on_readers_ready()
    except BaseException as error:
        callback_error = error
    finally:
        start_event.set()

    for reader in readers:
        reader.join()

    if callback_error is not None:
        raise callback_error

    return [reader.result for reader in readers]


def read_until_stopped_concurrently(
    applied_devices: list[AppliedSetupDevice],
    *,
    stop_event: Event,
    discard_initial_frames: int = 0,
    expected_sample_rate_hz: float | None = None,
    use_batched_transport_reader: bool = True,
    use_batched_serial_reader: bool | None = None,
    on_readers_ready: Callable[[], None] | None = None,
    on_recording_started: Callable[[], None] | None = None,
) -> list[RuntimeDeviceResult]:
    """Read frames from all devices until stop_event is set."""
    if not applied_devices:
        return []

    config = RuntimeManualReaderConfig(
        discard_initial_frames=discard_initial_frames,
        expected_sample_rate_hz=expected_sample_rate_hz,
        use_batched_transport_reader=(
            use_batched_transport_reader
            if use_batched_serial_reader is None
            else use_batched_serial_reader
        ),
    )
    ready_barrier = Barrier(len(applied_devices) + 1)
    start_event = Event()
    readers = [
        RuntimeManualMeasurementReader(
            applied_device,
            config=config,
            ready_barrier=ready_barrier,
            start_event=start_event,
            stop_event=stop_event,
        )
        for applied_device in applied_devices
    ]

    for reader in readers:
        reader.start()

    callback_error: BaseException | None = None
    notifier: Thread | None = None
    try:
        ready_barrier.wait()
        if on_readers_ready is not None:
            on_readers_ready()
        if on_recording_started is not None:
            notifier = Thread(
                target=_notify_when_all_readers_stored_first_frame,
                args=(readers, on_recording_started),
                name="gsvpiko-recording-started-notifier",
                daemon=True,
            )
            notifier.start()
    except BaseException as error:
        callback_error = error
    finally:
        start_event.set()

    for reader in readers:
        reader.join()

    if notifier is not None:
        notifier.join(timeout=0.5)

    if callback_error is not None:
        raise callback_error

    return [reader.result for reader in readers]


def _notify_when_all_readers_stored_first_frame(
    readers: list[RuntimeManualMeasurementReader],
    callback: Callable[[], None],
) -> None:
    """Call callback after each reader has stored at least one frame."""
    for reader in readers:
        reader.first_stored_event.wait()
    callback()


def _require_base_transport(transport: object) -> BaseTransport:
    """Return a transport that implements the shared runtime byte-stream API."""
    if not isinstance(transport, BaseTransport):
        raise TypeError(
            "Runtime reader requires a BaseTransport-compatible byte stream."
        )
    return transport


def _timestamp_for_stored_frame(
    *,
    frame_index: int,
    segment_first_frame_index: int,
    first_stored_unix_s: float,
    first_stored_monotonic_s: float,
    receive_timestamp_unix_s: float,
    receive_timestamp_monotonic_s: float,
    expected_sample_rate_hz: float | None,
) -> tuple[float, float, str]:
    """Return the primary timestamp for one stored frame."""
    if expected_sample_rate_hz is None or expected_sample_rate_hz <= 0:
        return receive_timestamp_unix_s, receive_timestamp_monotonic_s, "receive_time"

    offset_s = (frame_index - segment_first_frame_index) / expected_sample_rate_hz
    return (
        first_stored_unix_s + offset_s,
        first_stored_monotonic_s + offset_s,
        "estimated_sample_time",
    )


def _build_runtime_record_from_frame(
    *,
    applied_device: AppliedSetupDevice,
    frame: dict[str, Any],
    frame_index: int,
    read_index: int,
    timestamp_unix_s: float,
    timestamp_monotonic_s: float,
    receive_timestamp_unix_s: float,
    receive_timestamp_monotonic_s: float,
    timestamp_mode: str,
) -> RuntimeMeasurementRecord:
    """Convert one parsed measurement frame into a runtime record."""
    if frame["kind"] != "measurement":
        raise TypeError("Expected a measurement frame.")

    values = list(frame["values"])
    channels = applied_device.device.channels.build_channel_map(values)

    return RuntimeMeasurementRecord(
        device_alias=applied_device.resolved_device.alias,
        device_name=applied_device.device.name,
        frame_index=frame_index,
        read_index=read_index,
        timestamp_unix_s=timestamp_unix_s,
        timestamp_monotonic_s=timestamp_monotonic_s,
        values=values,
        channels=channels,
        object_count=frame["object_count"],
        datatype=frame["datatype"],
        input_saturation=frame["input_saturation"],
        six_axis_error=frame["six_axis_error"],
        raw_hex=frame.get("raw_hex"),
        receive_timestamp_unix_s=receive_timestamp_unix_s,
        receive_timestamp_monotonic_s=receive_timestamp_monotonic_s,
        timestamp_mode=timestamp_mode,
    )


def _build_runtime_record_from_routed_measurement_frame(
    *,
    applied_device: AppliedSetupDevice,
    routed_frame: RoutedMeasurementFrame,
    frame_index: int,
    read_index: int,
    timestamp_unix_s: float,
    timestamp_monotonic_s: float,
    timestamp_mode: str,
) -> RuntimeMeasurementRecord:
    """Convert one routed measurement frame into a runtime record."""
    parsed = parse_measurement_frame(routed_frame.raw_frame)
    return _build_runtime_record_from_frame(
        applied_device=applied_device,
        frame=parsed,
        frame_index=frame_index,
        read_index=read_index,
        timestamp_unix_s=timestamp_unix_s,
        timestamp_monotonic_s=timestamp_monotonic_s,
        receive_timestamp_unix_s=routed_frame.receive_timestamp_unix_s,
        receive_timestamp_monotonic_s=routed_frame.receive_timestamp_monotonic_s,
        timestamp_mode=timestamp_mode,
    )
