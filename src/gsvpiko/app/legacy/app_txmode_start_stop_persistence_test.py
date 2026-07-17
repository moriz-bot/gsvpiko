from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import time
from typing import Any, Iterable

try:
    from .._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config
    from ...coordination.coordination_setup_application import (
        close_applied_devices,
        open_and_apply_setup,
        start_transmission,
        stop_transmission,
    )
    from ...coordination.coordination_setup_resolution import resolve_setup
except ImportError:  # allows direct execution from a copied app file during ad-hoc tests
    from gsvpiko.app._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config
    from gsvpiko.coordination.coordination_setup_application import (
        close_applied_devices,
        open_and_apply_setup,
        start_transmission,
        stop_transmission,
    )
    from gsvpiko.coordination.coordination_setup_resolution import resolve_setup

FRAME_PREFIX = 0xAA
FRAME_SUFFIX = 0x85

COMMAND_GET_TX_MODE = 0x80
COMMAND_SET_TX_MODE = 0x81
TX_MODE_INDEX = 0
TX_MODE_PERMANENT_OFF = 0x0002
WRITABLE_TXMODE_MASK = 0x002E

STATUS_NAMES = {
    0x00: "OK",
    0x01: "OK_CHANGED",
    0x50: "GENERAL_ERROR",
    0x51: "PARAMETER_ADDRESS_ERROR",
    0x52: "PARAMETER_VALUE_ERROR",
    0x53: "COMMAND_NOT_ALLOWED",
    0x54: "COMMAND_NOT_IMPLEMENTED",
    0x55: "DATA_FORMAT_ERROR",
    0x56: "WRITE_PROTECTED",
    0x57: "CALIBRATION_ERROR",
    0x59: "PARAMETER_MODE_ERROR",
    0x86: "ERR_FILE",
    0x87: "ERR_WRONG_DIR",
    0x91: "RETURN_TX_BUFFER_FULL",
    0x92: "RETURN_BUSY",
    0x99: "RETURN_RX_BUFFER_FULL",
}

TXMODE_FLAG_NAMES = {
    0x0001: "temporary_off",
    0x0002: "permanent_off",
    0x0004: "tx_max_min_frames",
    0x0008: "crc_enabled",
    0x0020: "send_rate_100_hz_marker",
    0x0080: "usb_write_blocked",
}


@dataclass
class GsvFrameResponse:
    request_frame: bytes
    response_frame: bytes
    frame_type: int
    request_status: int
    payload: bytes

    @property
    def ok(self) -> bool:
        return self.request_status in {0x00, 0x01}

    @property
    def request_status_name(self) -> str:
        return STATUS_NAMES.get(self.request_status, f"UNKNOWN_STATUS_0x{self.request_status:02X}")


@dataclass
class DeviceTarget:
    alias: str
    name: str
    config: dict[str, Any]
    setup_connection_type: str
    setup_baudrate: int


@dataclass
class TxModeRead:
    value: int | None
    response: GsvFrameResponse | None
    error: str | None = None

    @property
    def has_permanent_off(self) -> bool:
        return self.value is not None and bool(self.value & TX_MODE_PERMANENT_OFF)


@dataclass
class DeviceReport:
    target: DeviceTarget
    connection_label: str | None = None
    before_set: TxModeRead | None = None
    set_response: GsvFrameResponse | None = None
    after_set: TxModeRead | None = None
    after_first_powercycle: TxModeRead | None = None
    start_responses: list[dict[str, Any]] | None = None
    stop_responses: list[dict[str, Any]] | None = None
    start_stop_error: str | None = None
    after_start_stop: TxModeRead | None = None
    after_second_powercycle: TxModeRead | None = None


class GsvTransport:
    def __init__(self, *, mode: str, endpoint: str, baudrate: int | None = None):
        self.mode = mode
        self.endpoint = endpoint
        self.baudrate = baudrate
        self._socket: socket.socket | None = None
        self._serial: Any | None = None

    def __enter__(self) -> "GsvTransport":
        if self.mode == "tcp":
            host, port_text = self.endpoint.rsplit(":", 1)
            sock = socket.create_connection((host, int(port_text)), timeout=2.0)
            sock.settimeout(0.2)
            self._socket = sock
            return self
        if self.mode == "serial":
            try:
                import serial  # type: ignore[import-not-found]
            except ImportError as error:  # pragma: no cover - local dependency
                raise RuntimeError("pyserial is required for serial access.") from error
            ser = serial.Serial(
                self.endpoint,
                baudrate=int(self.baudrate or 460800),
                timeout=0.2,
                write_timeout=1.0,
            )
            self._serial = ser
            return self
        raise ValueError(f"unsupported transport mode {self.mode!r}")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def write(self, data: bytes) -> None:
        if self._socket is not None:
            self._socket.sendall(data)
            return
        if self._serial is not None:
            self._serial.write(data)
            self._serial.flush()
            return
        raise RuntimeError("transport is not open")

    def read(self, size: int) -> bytes:
        if self._socket is not None:
            try:
                return self._socket.recv(size)
            except socket.timeout:
                return b""
        if self._serial is not None:
            return self._serial.read(size)
        raise RuntimeError("transport is not open")

    def drain(self, *, quiet_time_s: float = 0.08, max_time_s: float = 1.0) -> int:
        drained = 0
        start = time.monotonic()
        last_data = time.monotonic()
        while time.monotonic() - start < max_time_s:
            chunk = self.read(4096)
            if chunk:
                drained += len(chunk)
                last_data = time.monotonic()
                continue
            if time.monotonic() - last_data >= quiet_time_s:
                break
        return drained


def bytes_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def make_request(command: int, params: Iterable[int] = ()) -> bytes:
    payload = bytes(int(value) & 0xFF for value in params)
    if len(payload) > 15:
        raise ValueError("this helper only supports payload lengths up to 15 bytes")
    return bytes([FRAME_PREFIX, 0x90 | len(payload), int(command) & 0xFF]) + payload + bytes([FRAME_SUFFIX])


def read_response_frame(
    transport: GsvTransport,
    *,
    request_frame: bytes,
    timeout_s: float,
) -> GsvFrameResponse:
    deadline = time.monotonic() + timeout_s
    buffer = b""
    while time.monotonic() < deadline:
        chunk = transport.read(256)
        if chunk:
            buffer += chunk
        else:
            continue
        while True:
            start = buffer.find(bytes([FRAME_PREFIX]))
            if start < 0:
                buffer = b""
                break
            if start:
                buffer = buffer[start:]
            if len(buffer) < 3:
                break
            frame_type = buffer[1]
            payload_length = frame_type & 0x0F
            total_length = 1 + 1 + 1 + payload_length + 1
            if len(buffer) < total_length:
                break
            frame = buffer[:total_length]
            buffer = buffer[total_length:]
            if frame[-1] != FRAME_SUFFIX:
                buffer = buffer[1:]
                continue
            if 0x50 <= frame_type <= 0x5F:
                return GsvFrameResponse(
                    request_frame=request_frame,
                    response_frame=frame,
                    frame_type=frame_type,
                    request_status=frame[2],
                    payload=frame[3:-1],
                )
    raise TimeoutError("No GSV response frame was received before timeout.")


def transact(
    transport: GsvTransport,
    command: int,
    params: Iterable[int] = (),
    *,
    timeout_s: float = 2.0,
) -> GsvFrameResponse:
    request = make_request(command, params)
    transport.drain(max_time_s=0.2)
    transport.write(request)
    return read_response_frame(transport, request_frame=request, timeout_s=timeout_s)


def iter_device_targets(setup_config: dict[str, Any]) -> list[DeviceTarget]:
    connection_type = str(setup_config.get("connection_type") or "tcp")
    baudrate = int(setup_config.get("baudrate") or 460800)
    result: list[DeviceTarget] = []
    for entry in setup_config.get("attached_devices", []):
        config = dict(entry.get("device", {}))
        result.append(
            DeviceTarget(
                alias=str(entry.get("alias") or config.get("name") or "device"),
                name=str(config.get("name") or entry.get("alias") or "device"),
                config=config,
                setup_connection_type=connection_type,
                setup_baudrate=baudrate,
            )
        )
    return result


def open_target(target: DeviceTarget, *, connection: str = "auto") -> tuple[GsvTransport, str]:
    attempts: list[tuple[str, str, int | None]] = []
    if connection in {"tcp", "auto"} and target.setup_connection_type == "tcp":
        ip_address = target.config.get("ip_address")
        tcp_port = target.config.get("tcp_port") or 4001
        if ip_address:
            attempts.append(("tcp", f"{ip_address}:{tcp_port}", None))
    if connection in {"serial", "auto"}:
        com_port = target.config.get("com_port")
        if com_port:
            attempts.append(("serial", str(com_port), target.setup_baudrate))
    if connection == "tcp" and not attempts:
        ip_address = target.config.get("ip_address")
        tcp_port = target.config.get("tcp_port") or 4001
        if ip_address:
            attempts.append(("tcp", f"{ip_address}:{tcp_port}", None))

    errors: list[str] = []
    for mode, endpoint, baudrate in attempts:
        try:
            transport = GsvTransport(mode=mode, endpoint=endpoint, baudrate=baudrate)
            transport.__enter__()
            label = f"{mode}@{endpoint}"
            if baudrate is not None:
                label += f":baudrate={baudrate}"
            transport.drain(max_time_s=0.3)
            return transport, label
        except Exception as error:
            errors.append(f"{mode}@{endpoint}: {error}")
    raise RuntimeError("Could not open target. attempts=" + "; ".join(errors))


def read_txmode_for_target(target: DeviceTarget, *, connection: str) -> tuple[TxModeRead, str | None]:
    transport: GsvTransport | None = None
    try:
        transport, connection_label = open_target(target, connection=connection)
        response = transact(transport, COMMAND_GET_TX_MODE, [TX_MODE_INDEX])
        value = int.from_bytes(response.payload[-2:], byteorder="big", signed=False) if len(response.payload) >= 2 else None
        return TxModeRead(value=value, response=response), connection_label
    except Exception as error:
        return TxModeRead(value=None, response=None, error=str(error)), None
    finally:
        if transport is not None:
            transport.__exit__(None, None, None)


def set_permanent_off_for_target(target: DeviceTarget, *, connection: str) -> tuple[TxModeRead, GsvFrameResponse | None, TxModeRead, str | None]:
    transport: GsvTransport | None = None
    try:
        transport, connection_label = open_target(target, connection=connection)
        before_response = transact(transport, COMMAND_GET_TX_MODE, [TX_MODE_INDEX])
        before_value = int.from_bytes(before_response.payload[-2:], byteorder="big", signed=False) if len(before_response.payload) >= 2 else None
        if before_value is None:
            return (
                TxModeRead(value=None, response=before_response, error="GetTXMode returned too few payload bytes."),
                None,
                TxModeRead(value=None, response=None, error="SetTXMode skipped because GetTXMode failed."),
                connection_label,
            )
        target_value = (before_value & WRITABLE_TXMODE_MASK) | TX_MODE_PERMANENT_OFF
        set_response = transact(
            transport,
            COMMAND_SET_TX_MODE,
            [TX_MODE_INDEX, (target_value >> 8) & 0xFF, target_value & 0xFF],
        )
        after_response = transact(transport, COMMAND_GET_TX_MODE, [TX_MODE_INDEX])
        after_value = int.from_bytes(after_response.payload[-2:], byteorder="big", signed=False) if len(after_response.payload) >= 2 else None
        return (
            TxModeRead(value=before_value, response=before_response),
            set_response,
            TxModeRead(value=after_value, response=after_response),
            connection_label,
        )
    except Exception as error:
        error_read = TxModeRead(value=None, response=None, error=str(error))
        return error_read, None, error_read, None
    finally:
        if transport is not None:
            transport.__exit__(None, None, None)


def describe_txmode(value: int | None) -> str:
    if value is None:
        return "unavailable"
    flags = [name for bit, name in sorted(TXMODE_FLAG_NAMES.items()) if value & bit]
    known_mask = 0
    for bit in TXMODE_FLAG_NAMES:
        known_mask |= bit
    unknown = value & ~known_mask
    if unknown:
        flags.append(f"unknown_0x{unknown:04X}")
    if not flags:
        flags.append("no_known_flags")
    return ",".join(flags)


def format_response(response: GsvFrameResponse | None, *, indent: str = "  ") -> list[str]:
    if response is None:
        return [f"{indent}response: unavailable"]
    return [
        f"{indent}request: {bytes_hex(response.request_frame)}",
        f"{indent}request_status: 0x{response.request_status:02X} ({response.request_status_name})",
        f"{indent}response: {bytes_hex(response.response_frame)}",
        f"{indent}payload: {bytes_hex(response.payload)}",
    ]


def format_txmode_read(label: str, reading: TxModeRead | None) -> list[str]:
    lines = [f"{label}:"]
    if reading is None:
        lines.append("  value: not_read")
        return lines
    if reading.error:
        lines.append(f"  error: {reading.error}")
        return lines
    lines.append(f"  txmode: 0x{reading.value or 0:04X} ({describe_txmode(reading.value)})")
    lines.append(f"  permanent_off: {str(reading.has_permanent_off).lower()}")
    lines.extend(format_response(reading.response))
    return lines


def print_cli_options(options: list[tuple[str, object]]) -> None:
    print("Command-line options")
    print("--------------------")
    for name, value in options:
        print(f"{name}: current={value}")
    print("")


def print_powercycle_instruction(step: str) -> None:
    print(step)
    print("- Switch off all GSV devices used by the selected setup.")
    print("- Wait until the devices are off.")
    print("- Switch them on again.")
    print("- Wait until the TCP/serial connection is reachable again.")
    input("Press Enter here after the power cycle is complete.")
    print("")


def run_start_stop_cycle(setup_config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    applied_setup = None
    start_result: list[dict[str, Any]] = []
    stop_result: list[dict[str, Any]] = []
    try:
        resolved_setup = resolve_setup(setup_config)
        applied_setup = open_and_apply_setup(setup_config=setup_config, resolved_setup=resolved_setup)
        if not applied_setup.can_start_transmission:
            return [], [], "setup application reported can_start_transmission=False"
        start_result = start_transmission(applied_setup)
        time.sleep(0.5)
        stop_result = stop_transmission(applied_setup)
        return start_result, stop_result, None
    except Exception as error:
        return start_result, stop_result, str(error)
    finally:
        if applied_setup is not None:
            close_applied_devices(applied_setup.devices)


def response_status_summary(entry: dict[str, Any]) -> str:
    response = entry.get("response")
    if isinstance(response, dict):
        raw = response.get("raw_hex") or response.get("response") or response
        status = response.get("status") or response.get("request_status") or "unknown"
        return f"{entry.get('device_alias')}: status={status}; response={raw}"
    return f"{entry.get('device_alias')}: response={response}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test whether SetTXMode permanent-off remains active after power cycle, "
            "StartTransmission, StopTransmission and another power cycle."
        )
    )
    add_setup_argument(parser, default_setup_key=DEFAULT_SETUP_KEY)
    parser.add_argument(
        "--connection",
        choices=("auto", "tcp", "serial"),
        default="auto",
        help="Connection path used for TXMode reads/writes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print_cli_options([
        ("--setup <setup>", args.setup),
        ("--connection auto|tcp|serial", args.connection),
    ])

    setup_config = get_setup_config(args.setup)
    targets = iter_device_targets(setup_config)
    reports: dict[str, DeviceReport] = {
        target.alias: DeviceReport(target=target) for target in targets
    }

    print("TXMode start/stop persistence test")
    print("----------------------------------")
    print(f"diagnostic_time_utc: {datetime.now(timezone.utc).isoformat()}")
    print(f"setup_name: {setup_config.get('name', '<unnamed>')}")
    print("target: SetTXMode permanent_off; then verify after power cycle, start/stop and another power cycle.")
    print("")

    print("Step 1: set permanent_off")
    for target in targets:
        report = reports[target.alias]
        before, set_response, after, connection_label = set_permanent_off_for_target(
            target,
            connection=args.connection,
        )
        report.connection_label = connection_label
        report.before_set = before
        report.set_response = set_response
        report.after_set = after
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        if connection_label:
            print(f"connection: {connection_label}")
        for line in format_txmode_read("before_set", before):
            print(line)
        print("set_permanent_off:")
        for line in format_response(set_response):
            print(line)
        for line in format_txmode_read("after_set", after):
            print(line)
        print("")

    print_powercycle_instruction("Step 2: first power cycle")

    print("Step 3: read TXMode after first power cycle")
    for target in targets:
        report = reports[target.alias]
        reading, connection_label = read_txmode_for_target(target, connection=args.connection)
        report.after_first_powercycle = reading
        if connection_label:
            report.connection_label = connection_label
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        if report.connection_label:
            print(f"connection: {report.connection_label}")
        for line in format_txmode_read("after_first_powercycle", reading):
            print(line)
        print("")

    print("Step 4: run StartTransmission and StopTransmission through the normal setup path")
    start_responses, stop_responses, start_stop_error = run_start_stop_cycle(setup_config)
    for report in reports.values():
        report.start_responses = start_responses
        report.stop_responses = stop_responses
        report.start_stop_error = start_stop_error
    if start_stop_error:
        print(f"start_stop_error: {start_stop_error}")
    else:
        print("start_responses:")
        for entry in start_responses:
            print(f"  {response_status_summary(entry)}")
        print("stop_responses:")
        for entry in stop_responses:
            print(f"  {response_status_summary(entry)}")
    print("")

    print("Step 5: read TXMode after StartTransmission/StopTransmission")
    for target in targets:
        report = reports[target.alias]
        reading, connection_label = read_txmode_for_target(target, connection=args.connection)
        report.after_start_stop = reading
        if connection_label:
            report.connection_label = connection_label
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        for line in format_txmode_read("after_start_stop", reading):
            print(line)
        print("")

    print_powercycle_instruction("Step 6: second power cycle")

    print("Step 7: final TXMode read after second power cycle")
    for target in targets:
        report = reports[target.alias]
        reading, connection_label = read_txmode_for_target(target, connection=args.connection)
        report.after_second_powercycle = reading
        if connection_label:
            report.connection_label = connection_label
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        for line in format_txmode_read("after_second_powercycle", reading):
            print(line)
        print("")

    print("Evaluation")
    print("----------")
    for report in reports.values():
        checks = {
            "after_set_permanent_off": bool(report.after_set and report.after_set.has_permanent_off),
            "after_first_powercycle_permanent_off": bool(
                report.after_first_powercycle and report.after_first_powercycle.has_permanent_off
            ),
            "start_stop_completed": report.start_stop_error is None,
            "after_start_stop_permanent_off": bool(
                report.after_start_stop and report.after_start_stop.has_permanent_off
            ),
            "after_second_powercycle_permanent_off": bool(
                report.after_second_powercycle and report.after_second_powercycle.has_permanent_off
            ),
        }
        passed = all(checks.values())
        print(f"{report.target.alias} = {report.target.name}")
        for name, value in checks.items():
            print(f"  {name}: {str(value).lower()}")
        print(f"  result: {'PASS' if passed else 'CHECK_REQUIRED'}")
        if not checks["after_second_powercycle_permanent_off"]:
            print("  interpretation: permanent_off did not survive the complete test path.")
        elif not checks["after_start_stop_permanent_off"]:
            print("  interpretation: permanent_off was lost after the Start/Stop path before the second power cycle.")
        elif not checks["start_stop_completed"]:
            print("  interpretation: StartTransmission/StopTransmission did not complete cleanly.")
        else:
            print("  interpretation: permanent_off survived power cycle, StartTransmission, StopTransmission and another power cycle.")


if __name__ == "__main__":
    main()
