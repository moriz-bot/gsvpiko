from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import time
from typing import Any, Iterable

try:
    from .._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config
except ImportError:  # allows direct execution from a copied legacy file during ad-hoc tests
    from gsvpiko.app._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

FRAME_PREFIX = 0xAA
FRAME_SUFFIX = 0x85

COMMAND_GET_AOUT_TYPE = 0x0D
COMMAND_SET_AOUT_TYPE = 0x0E

AOUT_TYPE_SAFE_INACTIVE = 0  # GSVmulti-compatible: voltage range plus inactive mode.
AOUT_MODE_INACTIVE = 0x02

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


@dataclass
class GsvFrameResponse:
    """One parsed GSV response frame."""

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
    """One device target resolved from a setup."""

    alias: str
    name: str
    config: dict[str, Any]
    setup_connection_type: str
    setup_baudrate: int


class GsvTransport:
    """Small TCP/serial transport for short diagnostic/configuration commands."""

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
    require_ok: bool = True,
) -> GsvFrameResponse:
    request = make_request(command, params)
    transport.drain(max_time_s=0.2)
    transport.write(request)
    response = read_response_frame(transport, request_frame=request, timeout_s=timeout_s)
    if require_ok and not response.ok:
        raise RuntimeError(
            f"request_status=0x{response.request_status:02X} ({response.request_status_name})"
        )
    return response


def bytes_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def aout_type_name(value: int) -> str:
    return AOUT_TYPE_NAMES.get(value, f"reserved_{value}")


def describe_aout_payload(payload: bytes) -> str:
    if len(payload) < 2:
        return f"unexpected_payload={bytes_hex(payload)}"
    type_enum = payload[0]
    mode = payload[1]
    unknown_bits = mode & ~0x07
    extra = ""
    if mode in {0x03, 0x05, 0x06, 0x07} or unknown_bits:
        extra = "; mode_note=unusual_combination"
        if unknown_bits:
            extra += f"; unknown_mode_bits=0x{unknown_bits:02X}"
    return (
        f"type={type_enum} ({aout_type_name(type_enum)}), "
        f"inactive={bool(mode & 0x02)}, direct_mode={bool(mode & 0x01)}, "
        f"alternate_input={bool(mode & 0x04)}, mode=0x{mode:02X}"
        f"{extra}"
    )


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


def print_cli_option_header(options: list[tuple[str, object]]) -> None:
    print("Command-line options")
    print("--------------------")
    for name, value in options:
        print(f"{name}: current={value}")
    print("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set all GSV-8 analog-output channels to a safe inactive state. "
            "Read and optionally set unused GSV-8 Analog OUT channels to voltage 0..10 V with inactive mode."
        )
    )
    add_setup_argument(parser, default_setup_key=DEFAULT_SETUP_KEY)
    parser.add_argument(
        "--connection",
        choices=("auto", "tcp", "serial"),
        default="auto",
        help="Connection path used for this configuration helper.",
    )
    parser.add_argument(
        "--max-aout-channel",
        type=int,
        default=8,
        help="Highest analog-output channel to verify before/after. Default: 8.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and print current analog-output settings without writing SetAoutType.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print_cli_option_header([
        ("--setup <setup>", args.setup),
        ("--connection auto|tcp|serial", args.connection),
        ("--max-aout-channel <n>", args.max_aout_channel),
        ("--dry-run", args.dry_run),
    ])

    setup_config = get_setup_config(args.setup)
    print("Turn analog-output OFF")
    print("----------------------")
    print(f"diagnostic_time_utc: {datetime.now(timezone.utc).isoformat()}")
    print(f"setup_name: {setup_config.get('name', '<unnamed>')}")
    target_type_name = aout_type_name(AOUT_TYPE_SAFE_INACTIVE)
    print(
        "target: "
        f"SetAoutType(channel=0, type={AOUT_TYPE_SAFE_INACTIVE} {target_type_name}, "
        f"mode=0x{AOUT_MODE_INACTIVE:02X} inactive)"
    )
    print("note: channel 0 writes the same analog-output type/mode to all GSV-8 analog-output channels.")
    print("")

    for target in iter_device_targets(setup_config):
        print(f"{target.alias} = {target.name}")
        print("-" * (len(target.alias) + len(target.name) + 3))
        transport: GsvTransport | None = None
        try:
            transport, endpoint = open_target(target, connection=args.connection)
            print(f"connection: {endpoint}")

            print("before:")
            for channel in range(1, max(1, args.max_aout_channel) + 1):
                response = transact(transport, COMMAND_GET_AOUT_TYPE, [channel], require_ok=False)
                print(
                    f"  aout_{channel}: request_status=0x{response.request_status:02X} "
                    f"({response.request_status_name}); {describe_aout_payload(response.payload)}; "
                    f"response={bytes_hex(response.response_frame)}"
                )

            if args.dry_run:
                print("write: skipped because --dry-run is set")
            else:
                response = transact(
                    transport,
                    COMMAND_SET_AOUT_TYPE,
                    [0, AOUT_TYPE_SAFE_INACTIVE, AOUT_MODE_INACTIVE],
                    require_ok=False,
                )
                print(
                    "write: "
                    f"request={bytes_hex(response.request_frame)}; "
                    f"response={bytes_hex(response.response_frame)}; "
                    f"request_status=0x{response.request_status:02X} ({response.request_status_name})"
                )

                print("after:")
                for channel in range(1, max(1, args.max_aout_channel) + 1):
                    response = transact(transport, COMMAND_GET_AOUT_TYPE, [channel], require_ok=False)
                    print(
                        f"  aout_{channel}: request_status=0x{response.request_status:02X} "
                        f"({response.request_status_name}); {describe_aout_payload(response.payload)}; "
                        f"response={bytes_hex(response.response_frame)}"
                    )
        except Exception as error:
            print(f"configuration_error: {error}")
        finally:
            if transport is not None:
                transport.__exit__(None, None, None)
        print("")


if __name__ == "__main__":
    main()
