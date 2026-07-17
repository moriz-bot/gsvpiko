"""Estimate long-run clock drift and receive jitter between two GSV devices.

This diagnostic intentionally stores only counters and streaming statistics, not
all measurement frames. It is therefore suitable for long runs such as 30 to
60 minutes. The drift result estimates relative output-frame-rate drift from
received transport frames. The jitter result describes PC/driver/NPort receive
delivery jitter, not hard ADC sampling jitter.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Barrier, Event, Thread
from time import perf_counter, sleep, time
from typing import Any, TextIO

from ..config import config_setups as SETUP
from ..coordination.coordination_setup_application import (
    AppliedSetup,
    AppliedSetupDevice,
    close_applied_devices,
    open_and_apply_setup,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_report import print_baudrate_probe_result, print_connection_report_data
from ..protocol.protocol_frame_parser import extract_measurement_frames_from_buffer
from ..runtime.runtime_reader import (
    BATCH_READ_SIZE,
    EMPTY_READ_SLEEP_S,
    NO_PROGRESS_TIMEOUT_S,
)
from ..runtime.runtime_session import (
    start_transmission_concurrently,
    stop_transmission_concurrently,
)
from ..transport.transport_base import BaseTransport

BASE_SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH
DEFAULT_BAUDRATE = 460800
DEFAULT_SAMPLE_RATE_HZ = 2400.0
DEFAULT_DATATYPE = "float32"
DEFAULT_DURATION_S = 3600.0
DEFAULT_WINDOW_S = 60.0
DEFAULT_DISCARD_INITIAL_FRAMES = 100
AUTO_LOG_MIN_DURATION_S = 600.0
DEFAULT_PROGRESS_INTERVAL_S = 60.0
JITTER_THRESHOLD_MS = (1.0, 2.0, 5.0, 10.0, 50.0, 100.0)


@dataclass
class RunningStats:
    """Streaming mean, standard deviation, minimum and maximum."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: float) -> None:
        """Add one value to the streaming statistics."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2
        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value

    @property
    def stddev(self) -> float | None:
        """Return sample standard deviation."""
        if self.count < 2:
            return None
        return math.sqrt(self.m2 / (self.count - 1))


@dataclass
class JitterCounter:
    """Streaming receive-delivery jitter statistics."""

    gap_stats_ms: RunningStats = field(default_factory=RunningStats)
    over_threshold_counts: dict[float, int] = field(
        default_factory=lambda: {threshold: 0 for threshold in JITTER_THRESHOLD_MS}
    )

    def add_gap_s(self, gap_s: float) -> None:
        """Add one non-empty-read delivery gap in seconds."""
        gap_ms = gap_s * 1000.0
        self.gap_stats_ms.add(gap_ms)
        for threshold_ms in self.over_threshold_counts:
            if gap_ms > threshold_ms:
                self.over_threshold_counts[threshold_ms] += 1

    def copy_window(self) -> WindowJitterSummary:
        """Return a compact snapshot for a completed window."""
        return WindowJitterSummary(
            read_gap_count=self.gap_stats_ms.count,
            mean_read_gap_ms=self.gap_stats_ms.mean
            if self.gap_stats_ms.count
            else None,
            std_read_gap_ms=self.gap_stats_ms.stddev,
            max_read_gap_ms=self.gap_stats_ms.maximum,
            over_5ms=self.over_threshold_counts.get(5.0, 0),
            over_10ms=self.over_threshold_counts.get(10.0, 0),
            over_50ms=self.over_threshold_counts.get(50.0, 0),
        )


@dataclass
class WindowJitterSummary:
    """Receive jitter summary for one completed window."""

    read_gap_count: int = 0
    mean_read_gap_ms: float | None = None
    std_read_gap_ms: float | None = None
    max_read_gap_ms: float | None = None
    over_5ms: int = 0
    over_10ms: int = 0
    over_50ms: int = 0


@dataclass
class DriftWindow:
    """One counter window for a drift monitor."""

    window_index: int
    started_at_monotonic_s: float
    ended_at_monotonic_s: float
    frame_count: int
    bytes_read: int
    jitter: WindowJitterSummary = field(default_factory=WindowJitterSummary)

    @property
    def duration_s(self) -> float:
        """Return the monotonic duration of this window."""
        return self.ended_at_monotonic_s - self.started_at_monotonic_s

    @property
    def frame_rate_hz(self) -> float | None:
        """Return frames per second inside this window."""
        if self.duration_s <= 0:
            return None
        return self.frame_count / self.duration_s


@dataclass
class DriftMonitorResult:
    """Long-run receive-rate and jitter summary for one GSV."""

    device_alias: str
    device_name: str
    started_at_unix_s: float | None = None
    ended_at_unix_s: float | None = None
    started_at_monotonic_s: float | None = None
    ended_at_monotonic_s: float | None = None
    first_frame_unix_s: float | None = None
    last_frame_unix_s: float | None = None
    first_frame_monotonic_s: float | None = None
    last_frame_monotonic_s: float | None = None
    frame_count: int = 0
    discarded_frame_count: int = 0
    bytes_read: int = 0
    nonempty_read_count: int = 0
    parser_resync_count: int = 0
    receive_jitter: JitterCounter = field(default_factory=JitterCounter)
    errors: list[str] = field(default_factory=list)
    windows: list[DriftWindow] = field(default_factory=list)

    @property
    def read_duration_s(self) -> float | None:
        """Return monitor wall duration if known."""
        if self.started_at_monotonic_s is None or self.ended_at_monotonic_s is None:
            return None
        return self.ended_at_monotonic_s - self.started_at_monotonic_s

    @property
    def frame_span_s(self) -> float | None:
        """Return time between first and last counted receive events."""
        if self.first_frame_monotonic_s is None or self.last_frame_monotonic_s is None:
            return None
        return self.last_frame_monotonic_s - self.first_frame_monotonic_s

    @property
    def frame_rate_hz(self) -> float | None:
        """Return counted frames per receive-time span."""
        span_s = self.frame_span_s
        if span_s is None or span_s <= 0 or self.frame_count < 2:
            return None
        return (self.frame_count - 1) / span_s

    @property
    def total_input_frame_count(self) -> int:
        """Return counted plus deliberately discarded frames."""
        return self.frame_count + self.discarded_frame_count


class DriftMonitor:
    """Count measurement frames and receive gaps for one open GSV device."""

    def __init__(
        self,
        applied_device: AppliedSetupDevice,
        *,
        stop_event: Event,
        ready_barrier: Barrier,
        start_event: Event,
        window_s: float,
        discard_initial_frames: int,
    ) -> None:
        self.applied_device = applied_device
        self.stop_event = stop_event
        self.ready_barrier = ready_barrier
        self.start_event = start_event
        self.window_s = float(window_s)
        self.discard_initial_frames = int(discard_initial_frames)
        self.result = DriftMonitorResult(
            device_alias=applied_device.resolved_device.alias,
            device_name=applied_device.device.name,
        )
        self._thread = Thread(
            target=self._run,
            name=f"gsvpiko-drift-{applied_device.resolved_device.alias}",
            daemon=True,
        )

    def start(self) -> None:
        """Start the monitor thread."""
        self._thread.start()

    def join(self) -> None:
        """Wait until the monitor thread stops."""
        self._thread.join()

    def _run(self) -> None:
        """Monitor thread body."""
        self.result.started_at_unix_s = time()
        self.result.started_at_monotonic_s = perf_counter()
        try:
            self.ready_barrier.wait()
            self.start_event.wait()
            self._run_batched_counter()
        except Exception as error:
            self.result.errors.append(str(error))
        finally:
            self.result.ended_at_unix_s = time()
            self.result.ended_at_monotonic_s = perf_counter()

    def _run_batched_counter(self) -> None:
        """Read raw bytes and count measurement frames without storing values."""
        transport = _require_base_transport(self.applied_device.device.transport)
        raw_buffer = bytearray()
        last_progress_monotonic_s = perf_counter()
        last_nonempty_read_monotonic_s: float | None = None
        raw_frame_index = 0
        window_index = 1
        window_started = perf_counter()
        window_frames = 0
        window_bytes = 0
        window_jitter = JitterCounter()

        while not self.stop_event.is_set():
            chunk = transport.read_available(BATCH_READ_SIZE)
            receive_unix_s = time()
            receive_monotonic_s = perf_counter()

            if chunk:
                chunk_len = len(chunk)
                self.result.nonempty_read_count += 1
                if last_nonempty_read_monotonic_s is not None:
                    gap_s = receive_monotonic_s - last_nonempty_read_monotonic_s
                    self.result.receive_jitter.add_gap_s(gap_s)
                    window_jitter.add_gap_s(gap_s)
                last_nonempty_read_monotonic_s = receive_monotonic_s

                self.result.bytes_read += chunk_len
                window_bytes += chunk_len
                raw_buffer.extend(chunk)
                last_progress_monotonic_s = receive_monotonic_s
            elif receive_monotonic_s - last_progress_monotonic_s > NO_PROGRESS_TIMEOUT_S:
                self.result.errors.append(
                    "No measurement bytes were received before the batched-reader "
                    f"timeout of {NO_PROGRESS_TIMEOUT_S:.3f} s."
                )
                last_progress_monotonic_s = receive_monotonic_s
                sleep(EMPTY_READ_SLEEP_S)
                continue
            else:
                sleep(EMPTY_READ_SLEEP_S)
                continue

            extracted = extract_measurement_frames_from_buffer(raw_buffer)
            self.result.parser_resync_count += extracted.resync_count
            frames = extracted.frames
            for _frame in frames:
                raw_frame_index += 1
                if raw_frame_index <= self.discard_initial_frames:
                    self.result.discarded_frame_count += 1
                    continue

                if self.result.first_frame_unix_s is None:
                    self.result.first_frame_unix_s = receive_unix_s
                    self.result.first_frame_monotonic_s = receive_monotonic_s

                self.result.last_frame_unix_s = receive_unix_s
                self.result.last_frame_monotonic_s = receive_monotonic_s
                self.result.frame_count += 1
                window_frames += 1

            if receive_monotonic_s - window_started >= self.window_s:
                self.result.windows.append(
                    DriftWindow(
                        window_index=window_index,
                        started_at_monotonic_s=window_started,
                        ended_at_monotonic_s=receive_monotonic_s,
                        frame_count=window_frames,
                        bytes_read=window_bytes,
                        jitter=window_jitter.copy_window(),
                    )
                )
                window_index += 1
                window_started = receive_monotonic_s
                window_frames = 0
                window_bytes = 0
                window_jitter = JitterCounter()

        ended = perf_counter()
        if window_frames or window_bytes:
            self.result.windows.append(
                DriftWindow(
                    window_index=window_index,
                    started_at_monotonic_s=window_started,
                    ended_at_monotonic_s=ended,
                    frame_count=window_frames,
                    bytes_read=window_bytes,
                    jitter=window_jitter.copy_window(),
                )
            )


def _require_base_transport(transport: object) -> BaseTransport:
    """Return a transport that implements the shared runtime byte-stream API."""
    if not isinstance(transport, BaseTransport):
        raise TypeError(
            "Clock-drift diagnostic requires a BaseTransport-compatible byte stream."
        )
    return transport


class TeeStdout:
    """Write stdout to the terminal and to a log file."""

    def __init__(self, *streams: TextIO) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        """Write text to all configured streams."""
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        """Flush all configured streams."""
        for stream in self.streams:
            stream.flush()


def main() -> None:
    """Run the long-run drift diagnostic."""
    args = _parse_args()
    log_file = _resolve_log_file(args)

    if log_file is None:
        _run_main(args, log_file=None)
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8", newline="") as file:
        tee = TeeStdout(sys.stdout, file)
        with contextlib.redirect_stdout(tee):
            _run_main(args, log_file=log_file)


def _run_main(args: argparse.Namespace, *, log_file: Path | None) -> None:
    """Run the diagnostic after optional stdout logging has been installed."""
    setup_config = deepcopy(BASE_SETUP_CONFIG)
    setup_config["baudrate"] = args.baudrate
    setup_config["sample_rate_hz"] = args.sample_rate_hz
    setup_config["datatype"] = args.datatype

    resolved_setup = resolve_setup(setup_config)

    title = "Two-GSV clock-drift and receive-jitter diagnostics"
    print(title)
    print("-" * len(title))
    print(f"duration_s: {args.duration_s:g}")
    print(f"window_s: {args.window_s:g}")
    print(f"progress_interval_s: {args.progress_interval_s:g}")
    print(f"connection_type: {resolved_setup.connection_type}")
    print(f"reader_type: batched_{resolved_setup.connection_type}")
    print(f"baudrate: {args.baudrate}")
    print(f"sample_rate_hz: {args.sample_rate_hz:g}")
    print(f"datatype: {args.datatype}")
    print(f"discard_initial_frames: {args.discard_initial_frames}")
    print(f"batch_read_size: {BATCH_READ_SIZE}")
    print(f"log_file: {log_file if log_file is not None else '<none>'}")
    print()

    applied_setup: AppliedSetup | None = None
    stop_event = Event()
    monitors: list[DriftMonitor] = []

    try:
        applied_setup = open_and_apply_setup(
            setup_config=setup_config,
            resolved_setup=resolved_setup,
            on_probe_result=print_baudrate_probe_result,
        )
        for applied_device in applied_setup.devices:
            print_connection_report_data(
                getattr(applied_device.device, "connection_report", None)
            )

        if not applied_setup.can_start_transmission:
            print("Setup application collected blocking warnings; transmission not started.")
            return

        stop_transmission_concurrently(applied_setup)
        for applied_device in applied_setup.devices:
            applied_device.device.transport.prepare_for_runtime()
            applied_device.device.clear_input_buffer()

        ready_barrier = Barrier(len(applied_setup.devices) + 1)
        start_event = Event()
        monitors = [
            DriftMonitor(
                applied_device,
                stop_event=stop_event,
                ready_barrier=ready_barrier,
                start_event=start_event,
                window_s=args.window_s,
                discard_initial_frames=args.discard_initial_frames,
            )
            for applied_device in applied_setup.devices
        ]
        for monitor in monitors:
            monitor.start()

        ready_barrier.wait()
        print("Starting transmission...")
        try:
            for report in start_transmission_concurrently(applied_setup):
                print(
                    f"  {report['device_alias']}: ok={report['ok']} "
                    f"response={_response_text(report['response'])}"
                )
        finally:
            start_event.set()

        _sleep_with_progress(args.duration_s, monitors, args.progress_interval_s)

    finally:
        stop_event.set()
        for monitor in monitors:
            monitor.join()

        if applied_setup is not None:
            print("Stopping transmission...")
            for report in stop_transmission_concurrently(applied_setup):
                print(
                    f"  {report['device_alias']}: ok={report['ok']} "
                    f"response={_response_text(report['response'])}"
                )
            close_applied_devices(applied_setup.devices)

    if monitors:
        _print_results(
            [monitor.result for monitor in monitors],
            expected_sample_rate_hz=args.sample_rate_hz,
            duration_s=args.duration_s,
        )


def _parse_args() -> argparse.Namespace:
    """Return command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Estimate relative clock drift and receive jitter between two GSV devices."
    )
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--window-s", type=float, default=DEFAULT_WINDOW_S)
    parser.add_argument(
        "--progress-interval-s",
        type=float,
        default=DEFAULT_PROGRESS_INTERVAL_S,
        help="Terminal/log progress interval during the run.",
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--sample-rate-hz", type=float, default=DEFAULT_SAMPLE_RATE_HZ)
    parser.add_argument("--datatype", default=DEFAULT_DATATYPE)
    parser.add_argument(
        "--discard-initial-frames",
        type=int,
        default=DEFAULT_DISCARD_INITIAL_FRAMES,
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help=(
            "Path for a full text log. If omitted, long runs automatically create "
            "logs/clock_drift_<timestamp>.txt."
        ),
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable automatic log-file creation for long runs.",
    )
    args = parser.parse_args()

    if args.duration_s <= 0:
        parser.error("--duration-s must be positive.")
    if args.window_s <= 0:
        parser.error("--window-s must be positive.")
    if args.progress_interval_s <= 0:
        parser.error("--progress-interval-s must be positive.")
    if args.sample_rate_hz <= 0:
        parser.error("--sample-rate-hz must be positive.")
    if args.discard_initial_frames < 0:
        parser.error("--discard-initial-frames must not be negative.")
    return args


def _resolve_log_file(args: argparse.Namespace) -> Path | None:
    """Return explicit or automatic log file path."""
    if args.no_log_file:
        return None
    if args.log_file:
        return Path(args.log_file)
    if args.duration_s >= AUTO_LOG_MIN_DURATION_S:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path("logs") / f"clock_drift_{timestamp}.txt"
    return None


def _sleep_with_progress(
    duration_s: float,
    monitors: list[DriftMonitor],
    progress_interval_s: float,
) -> None:
    """Wait for the requested duration and print compact progress lines."""
    started = perf_counter()
    next_update = started + progress_interval_s
    while True:
        now = perf_counter()
        elapsed = now - started
        if elapsed >= duration_s:
            return
        if now >= next_update:
            counts = ", ".join(
                f"{monitor.result.device_alias}={monitor.result.frame_count}"
                for monitor in monitors
            )
            print(f"progress_s: {elapsed:.1f} | frames: {counts}")
            next_update = now + progress_interval_s
        sleep(min(0.5, duration_s - elapsed))


def _print_results(
    results: list[DriftMonitorResult],
    *,
    expected_sample_rate_hz: float,
    duration_s: float,
) -> None:
    """Print drift and receive-jitter summaries for all devices."""
    print()
    print("Clock-drift and receive-jitter summary")
    print("--------------------------------------")
    print(
        "Interpretation: drift rates are based on received measurement frames. "
        "They estimate relative output-frame-rate drift, not hard ADC phase. "
        "Receive jitter describes PC/driver/NPort delivery gaps between non-empty "
        "transport reads, not ADC sampling jitter."
    )
    print()
    print("devices:")
    for result in results:
        print(f"  {result.device_alias} = {result.device_name}")
        print(f"    frames: {result.frame_count}")
        print(f"    discarded_frames: {result.discarded_frame_count}")
        print(f"    bytes_read: {result.bytes_read}")
        print(f"    nonempty_reads: {result.nonempty_read_count}")
        print(f"    parser_resync_count: {result.parser_resync_count}")
        print(f"    errors: {len(result.errors)}")
        print(f"    read_duration_s: {_format_float(result.read_duration_s)}")
        print(f"    frame_span_s: {_format_float(result.frame_span_s)}")
        print(f"    observed_frame_rate_hz: {_format_float(result.frame_rate_hz)}")
        print(
            "    observed/requested: "
            f"{_format_ratio(result.frame_rate_hz, expected_sample_rate_hz)}"
        )
        _print_jitter_block("    receive_delivery_jitter", result.receive_jitter)
        for error in result.errors:
            print(f"    error: {error}")

    if len(results) >= 2:
        reference = results[0]
        print()
        print("relative drift:")
        for result in results[1:]:
            ppm = _relative_ppm(reference.frame_rate_hz, result.frame_rate_hz)
            drift_ms = None if ppm is None else ppm * 1e-6 * duration_s * 1000.0
            seconds_per_ms = None if ppm is None or ppm == 0 else 1000.0 / abs(ppm)
            count_delta = result.frame_count - reference.frame_count
            print(f"  {result.device_alias} - {reference.device_alias}")
            print(f"    frame_count_delta: {count_delta}")
            print(f"    relative_rate_ppm: {_format_float(ppm)}")
            print(f"    estimated_drift_over_run_ms: {_format_float(drift_ms)}")
            print(f"    seconds_per_1ms_relative_drift: {_format_float(seconds_per_ms)}")

    print()
    print("window_rates_and_jitter:")
    for result in results:
        print(f"  {result.device_alias}")
        for window in result.windows:
            print(
                f"    window={window.window_index}, "
                f"duration_s={window.duration_s:.3f}, "
                f"frames={window.frame_count}, "
                f"frame_rate_hz={_format_float(window.frame_rate_hz)}, "
                f"bytes={window.bytes_read}, "
                f"read_gaps={window.jitter.read_gap_count}, "
                f"mean_read_gap_ms={_format_float(window.jitter.mean_read_gap_ms)}, "
                f"std_read_gap_ms={_format_float(window.jitter.std_read_gap_ms)}, "
                f"max_read_gap_ms={_format_float(window.jitter.max_read_gap_ms)}, "
                f"gaps_gt_5ms={window.jitter.over_5ms}, "
                f"gaps_gt_10ms={window.jitter.over_10ms}, "
                f"gaps_gt_50ms={window.jitter.over_50ms}"
            )


def _print_jitter_block(label: str, jitter: JitterCounter) -> None:
    """Print compact jitter statistics."""
    stats = jitter.gap_stats_ms
    print(f"{label}:")
    print(f"      read_gap_count: {stats.count}")
    print(f"      mean_read_gap_ms: {_format_float(stats.mean if stats.count else None)}")
    print(f"      std_read_gap_ms: {_format_float(stats.stddev)}")
    print(f"      min_read_gap_ms: {_format_float(stats.minimum)}")
    print(f"      max_read_gap_ms: {_format_float(stats.maximum)}")
    for threshold_ms in JITTER_THRESHOLD_MS:
        count = jitter.over_threshold_counts.get(threshold_ms, 0)
        print(f"      gaps_gt_{threshold_ms:g}ms: {count}")


def _relative_ppm(
    reference_rate: float | None,
    other_rate: float | None,
) -> float | None:
    """Return relative rate difference in parts per million."""
    if reference_rate is None or other_rate is None or reference_rate <= 0:
        return None
    return (other_rate / reference_rate - 1.0) * 1_000_000.0


def _response_text(response: Any) -> str:
    """Return a compact response text."""
    if isinstance(response, dict):
        return str(response.get("raw_hex") or response)
    return str(response)


def _format_float(value: float | None) -> str:
    """Format a float value or placeholder."""
    if value is None:
        return "-"
    return f"{value:.6f}"


def _format_ratio(value: float | None, requested: float) -> str:
    """Format a value divided by requested."""
    if value is None or requested <= 0:
        return "-"
    return f"{value / requested:.6f}"


if __name__ == "__main__":
    main()
