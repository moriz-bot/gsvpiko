
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import struct
import time
from typing import Any, Iterable

from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

FRAME_PREFIX = 0xAA
FRAME_SUFFIX = 0x85

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

PROTOCOL_ERROR_NAMES = {
    0x00000000: "OK",
    0x00000051: "PARAMETER_ADDRESS_ERROR",
    0x00000059: "PARAMETER_MODE_ERROR",
    0x00000091: "RETURN_TX_BUFFER_FULL",
    0x00000092: "RETURN_BUSY",
    0x00000099: "RETURN_RX_BUFFER_FULL",
}

AOUT_TYPE_NAMES = {
    0: "0V_to_10V",
    1: "minus10V_to_10V",
    2: "0V_to_5V",
    3: "minus5V_to_5V",
    4: "4mA_to_20mA",
    5: "OFF",
    6: "0mA_to_20mA",
    7: "0V_to_2_5V",
}

DIO_DIRECTION_NAMES = {0: "output", 1: "input"}

@dataclass
class GsvFrameResponse:
    """One parsed GSV response frame."""

    request_raw: bytes
    response_raw: bytes
    frame_type: int
    status: int
    payload: bytes

    @property
    def ok(self) -> bool:
        """Return whether the response status is OK-like."""
        return self.status in {0x00, 0x01}

    @property
    def status_name(self) -> str:
        """Return a compact status name."""
        return STATUS_NAMES.get(self.status, f"UNKNOWN_STATUS_0x{self.status:02X}")

@dataclass
class DeviceTarget:
    """One device target resolved from a setup."""

    alias: str
    name: str
    config: dict[str, Any]
    setup_connection_type: str
    setup_baudrate: int

class GsvTransport:
    """Tiny TCP/serial transport for one GSV protocol connection."""

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
                raise RuntimeError("pyserial is required for serial diagnostics.") from error
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

def configure_setup_argument(parser: Any) -> None:
    add_setup_argument(parser, default_setup_key=DEFAULT_SETUP_KEY)

def selected_setup(args: Any) -> dict[str, Any]:
    return get_setup_config(args.setup)

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
    setup_mode = target.setup_connection_type
    if connection in {"tcp", "auto"} and setup_mode == "tcp":
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

def close_transport(transport: GsvTransport) -> None:
    transport.__exit__(None, None, None)

def make_request(command: int, params: Iterable[int] = ()) -> bytes:
    payload = bytes(int(value) & 0xFF for value in params)
    if len(payload) > 15:
        raise ValueError("this helper only supports payload lengths up to 15 bytes")
    return bytes([FRAME_PREFIX, 0x90 | len(payload), int(command) & 0xFF]) + payload + bytes([FRAME_SUFFIX])

def transact(
    transport: GsvTransport,
    command: int,
    params: Iterable[int] = (),
    *,
    timeout_s: float = 2.0,
    require_ok: bool = True,
) -> GsvFrameResponse:
    request = make_request(command, params)
    transport.drain(max_time_s=0.2)
    transport.write(request)
    response = read_response_frame(transport, request_raw=request, timeout_s=timeout_s)
    if require_ok and not response.ok:
        raise RuntimeError(f"Response status 0x{response.status:02X}: {response.status_name}")
    return response

def read_response_frame(
    transport: GsvTransport,
    *,
    request_raw: bytes,
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
                    request_raw=request_raw,
                    response_raw=frame,
                    frame_type=frame_type,
                    status=frame[2],
                    payload=frame[3:-1],
                )
    raise TimeoutError("No GSV response frame was received before timeout.")

def read_u32(transport: GsvTransport, command: int, index: int) -> tuple[int, GsvFrameResponse]:
    response = transact(transport, command, [index])
    if len(response.payload) != 4:
        raise RuntimeError(f"expected 4 payload bytes, got {len(response.payload)}")
    return int.from_bytes(response.payload, byteorder="big", signed=False), response

def read_u16(transport: GsvTransport, command: int, index: int) -> tuple[int, GsvFrameResponse]:
    response = transact(transport, command, [index])
    if len(response.payload) != 2:
        raise RuntimeError(f"expected 2 payload bytes, got {len(response.payload)}")
    return int.from_bytes(response.payload, byteorder="big", signed=False), response

def read_float32(transport: GsvTransport, command: int, index: int) -> tuple[float, GsvFrameResponse]:
    response = transact(transport, command, [index])
    if len(response.payload) != 4:
        raise RuntimeError(f"expected 4 payload bytes, got {len(response.payload)}")
    return float(struct.unpack(">f", response.payload)[0]), response

def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)

def protocol_error_name(value: int) -> str:
    return PROTOCOL_ERROR_NAMES.get(value, f"UNKNOWN_PROTOCOL_ERROR_0x{value:08X}")

def describe_txmode(value: int) -> str:
    known = []
    known_mask = 0
    flags = (
        (0x0001, "temporary_off"),
        (0x0002, "permanent_off"),
        (0x0004, "max_values_in_frame"),
        (0x0008, "min_values_in_frame"),
        (0x0020, "crc16_in_measurement_frame"),
        (0x0040, "uart_write_blocked"),
        (0x0080, "usb_write_blocked"),
        (0x0100, "tx_sync_slave"),
        (0x0200, "tx_sync_master"),
    )
    for bit, label in flags:
        known_mask |= bit
        if value & bit:
            known.append(label)
    unknown = value & ~known_mask
    if unknown:
        known.append(f"unknown_flags=0x{unknown:04X}")
    return ",".join(known) if known else "no_known_flags"

def aout_type_name(value: int) -> str:
    return AOUT_TYPE_NAMES.get(value, f"reserved_{value}")

def dio_direction_name(value: int) -> str:
    return DIO_DIRECTION_NAMES.get(value, f"unknown_{value}")

def print_cli_option_header(options: list[tuple[str, object]]) -> None:
    print("Command-line options")
    print("--------------------")
    for name, value in options:
        print(f"{name}: current={value}")
    print("")

COMMAND_GET_TX_MODE = 0x80
COMMAND_SET_TX_MODE = 0x81
TX_MODE_INDEX = 0
WRITABLE_TXMODE_MASK = 0x002E
PERMANENT_OFF_BIT = 0x0002


def main() -> None:
    """Set permanent autonomous TX off while preserving writable TX-mode bits."""
    parser = argparse.ArgumentParser(
        description=(
            "Read GetTXMode(0), write SetTXMode(0) with permanent TX off, "
            "then read GetTXMode(0) again."
        )
    )
    configure_setup_argument(parser)
    parser.add_argument(
        "--connection",
        choices=("auto", "tcp", "serial"),
        default="auto",
        help="Connection path used for this temporary diagnostic app.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show the target TX mode value; do not write SetTXMode.",
    )
    args = parser.parse_args()
    print_cli_option_header([
        ("--setup <setup>", args.setup),
        ("--connection auto|tcp|serial", args.connection),
        ("--dry-run", args.dry_run),
    ])

    setup_config = selected_setup(args)
    print("L SetTXMode non-permanent-start app")
    print("-----------------------------------")
    print(f"diagnostic_time_utc: {datetime.now(timezone.utc).isoformat()}")
    print(f"setup_name: {setup_config.get('name', '<unnamed>')}")
    print("target: permanent measurement transmission off after power-on")
    print("")

    for target in iter_device_targets(setup_config):
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        transport = None
        try:
            transport, endpoint = open_target(target, connection=args.connection)
            print(f"connection: {endpoint}")
            before, before_response = read_u16(transport, COMMAND_GET_TX_MODE, TX_MODE_INDEX)
            target_value = (before & WRITABLE_TXMODE_MASK) | PERMANENT_OFF_BIT
            print(f"before_txmode: 0x{before:04X} ({describe_txmode(before)})")
            print(f"before_response_raw_hex: {hex_bytes(before_response.response_raw)}")
            print(f"target_txmode: 0x{target_value:04X} ({describe_txmode(target_value)})")
            if args.dry_run:
                print("write: skipped because --dry-run is set")
                continue
            write_response = transact(
                transport,
                COMMAND_SET_TX_MODE,
                [TX_MODE_INDEX, (target_value >> 8) & 0xFF, target_value & 0xFF],
            )
            print(f"set_response_raw_hex: {hex_bytes(write_response.response_raw)}")
            print(f"set_status: 0x{write_response.status:02X} ({write_response.status_name})")
            after, after_response = read_u16(transport, COMMAND_GET_TX_MODE, TX_MODE_INDEX)
            print(f"after_txmode: 0x{after:04X} ({describe_txmode(after)})")
            print(f"after_response_raw_hex: {hex_bytes(after_response.response_raw)}")
        except Exception as error:
            print(f"diagnostic_error: {error}")
        finally:
            if transport is not None:
                close_transport(transport)
        print("")


if __name__ == "__main__":
    main()
