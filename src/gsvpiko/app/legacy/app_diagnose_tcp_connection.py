"""Diagnose direct TCP access to NPort/GSV byte streams.

This app checks whether the configured NPort IP addresses expose a raw TCP
byte stream that can be used by GSVpiko without RealCOM. It deliberately keeps
this as a diagnostic tool: a TCP socket can be open while the serial side still
uses wrong line settings, is claimed by another mode/client, or does not forward
bytes to the GSV.
"""

from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from typing import Iterable

from ..config.config_devices import DEVICE_PRESETS
from ..constants import constants_commands as COMMAND
from ..protocol.protocol_frame_builder import build_command_frame
from ..protocol.protocol_frame_parser import contains_response_status, contains_serial_frame
from ..utils.utils_hex import to_hex

DEFAULT_CANDIDATE_PORTS = (
    4001,  # NPort TCP Server default listening port.
    950,   # NPort 5000 RealCOM data-port base for port 1.
    966,   # NPort 5000 RealCOM command-port base for port 1.
    23,    # Telnet console reachability check.
    80,    # Web UI reachability check.
    4900,  # Firmware/update service on many NPort variants.
)

RAW_GSV_TEST_PORTS = set(range(950, 966)) | {4001}
STOP_TRANSMISSION_FRAME = build_command_frame(COMMAND.STOP_TRANSMISSION)
START_TRANSMISSION_FRAME = build_command_frame(COMMAND.START_TRANSMISSION)


@dataclass(frozen=True)
class TcpPortProbeResult:
    """One TCP port probe result."""

    host: str
    port: int
    connect_ok: bool
    connect_ms: float | None = None
    raw_gsv_tested: bool = False
    passive_bytes: int = 0
    passive_hex_head: str = ""
    stop_response_bytes: int = 0
    stop_response_hex_head: str = ""
    gsv_frame_seen: bool = False
    stop_response_seen: bool = False
    error: str = ""


def parse_csv_ints(text: str) -> tuple[int, ...]:
    """Parse a comma-separated integer list."""
    values = []
    for item in text.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        values.append(int(stripped))
    return tuple(values)


def probe_tcp_port(
    host: str,
    port: int,
    *,
    connect_timeout_s: float,
    passive_read_s: float,
    post_send_read_s: float,
    send_gsv_probe: bool,
    send_start_after_stop: bool,
) -> TcpPortProbeResult:
    """Try to open a TCP port and optionally verify raw GSV protocol response."""
    started_s = time.perf_counter()

    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout_s)
    except OSError as error:
        return TcpPortProbeResult(
            host=host,
            port=port,
            connect_ok=False,
            error=str(error),
        )

    connect_ms = (time.perf_counter() - started_s) * 1000.0

    with sock:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        if not send_gsv_probe:
            return TcpPortProbeResult(
                host=host,
                port=port,
                connect_ok=True,
                connect_ms=connect_ms,
                raw_gsv_tested=False,
            )

        try:
            passive = _read_for_duration(sock, duration_s=passive_read_s)
            sock.sendall(STOP_TRANSMISSION_FRAME)
            stop_response = _read_for_duration(sock, duration_s=post_send_read_s)

            if send_start_after_stop:
                sock.sendall(START_TRANSMISSION_FRAME)
                _read_for_duration(sock, duration_s=min(0.2, post_send_read_s))
        except OSError as error:
            return TcpPortProbeResult(
                host=host,
                port=port,
                connect_ok=True,
                connect_ms=connect_ms,
                raw_gsv_tested=True,
                error=str(error),
            )

    combined = passive + stop_response
    return TcpPortProbeResult(
        host=host,
        port=port,
        connect_ok=True,
        connect_ms=connect_ms,
        raw_gsv_tested=True,
        passive_bytes=len(passive),
        passive_hex_head=_hex_head(passive),
        stop_response_bytes=len(stop_response),
        stop_response_hex_head=_hex_head(stop_response),
        gsv_frame_seen=contains_serial_frame(combined),
        stop_response_seen=contains_response_status(stop_response),
        error="" if combined else "no bytes received from raw TCP stream",
    )


def _read_for_duration(sock: socket.socket, *, duration_s: float) -> bytes:
    """Read all currently delivered bytes for a short diagnostic duration."""
    deadline_s = time.perf_counter() + max(0.0, duration_s)
    chunks: list[bytes] = []
    sock.settimeout(0.05)

    while time.perf_counter() < deadline_s:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue

        if not chunk:
            break

        chunks.append(chunk)

    return b"".join(chunks)


def _hex_head(data: bytes, *, max_bytes: int = 80) -> str:
    """Return a compact hex preview of received bytes."""
    if not data:
        return ""

    head = data[:max_bytes]
    suffix = " ..." if len(data) > max_bytes else ""
    return to_hex(head) + suffix


def iter_selected_devices(device_names: Iterable[str]) -> list[dict]:
    """Return selected device presets."""
    selected = []
    for device_name in device_names:
        name = device_name.strip()
        if not name:
            continue
        try:
            selected.append(DEVICE_PRESETS[name])
        except KeyError as error:
            raise SystemExit(f"Unknown device preset: {name!r}") from error
    return selected


def print_probe_result(result: TcpPortProbeResult) -> None:
    """Print one probe result."""
    status = "open" if result.connect_ok else "closed/timeout"
    connect = "" if result.connect_ms is None else f" connect_ms={result.connect_ms:.1f}"
    print(f"  port {result.port}: {status}{connect}")

    if result.raw_gsv_tested:
        print(
            "    raw_gsv_test: "
            f"gsv_frame_seen={result.gsv_frame_seen} "
            f"stop_response_seen={result.stop_response_seen}"
        )
        print(
            "    passive_read: "
            f"bytes={result.passive_bytes} "
            f"head={result.passive_hex_head or '<none>'}"
        )
        print(
            "    after_stop: "
            f"bytes={result.stop_response_bytes} "
            f"head={result.stop_response_hex_head or '<none>'}"
        )

    if result.error:
        print(f"    note: {result.error}")


def print_interpretation(results: list[TcpPortProbeResult]) -> None:
    """Print a compact interpretation for one device."""
    open_ports = [result.port for result in results if result.connect_ok]
    gsv_ports = [result.port for result in results if result.gsv_frame_seen]
    stop_ports = [result.port for result in results if result.stop_response_seen]

    print("Interpretation")
    print("--------------")
    if stop_ports:
        print(
            "A direct TCP byte stream responded to StopTransmission on: "
            + ", ".join(str(port) for port in stop_ports)
        )
        print("Use one of these ports as tcp_port for direct TCP tests.")
        return

    if gsv_ports:
        print(
            "GSV-looking frames were seen on: "
            + ", ".join(str(port) for port in gsv_ports)
        )
        print(
            "The byte stream reaches the GSV, but the explicit StopTransmission response "
            "was not seen. Check whether measurement frames dominate the stream or increase "
            "the read timeout for the next test."
        )
        return

    if 4001 not in open_ports:
        print(
            "Port 4001 is not reachable. The NPort is probably not listening in TCP "
            "Server/socket mode on port 4001, or the connection is blocked."
        )
    else:
        print(
            "Port 4001 is open, but no GSV bytes were received. The TCP service is "
            "reachable; the remaining problem is likely on the NPort serial side: serial "
            "parameters, serial interface wiring, exclusive client/session state, or mode "
            "not fully applied after restart."
        )

    if any(port in open_ports for port in (23, 80)):
        print(
            "The NPort itself appears reachable through a management port. That supports "
            "a configuration/serial-side issue rather than a wrong IP address."
        )

    if 966 in open_ports:
        print(
            "Port 966 is the NPort command/control port, not the raw GSV data stream. "
            "Do not use it as tcp_port for GSV protocol traffic."
        )


def main() -> None:
    """Run TCP reachability and raw-GSV-response diagnostics."""
    parser = argparse.ArgumentParser(
        description="Diagnose direct TCP access to configured NPort/GSV devices."
    )
    parser.add_argument(
        "--devices",
        default="GSV_24456060,GSV_24456057",
        help="Comma-separated device preset names.",
    )
    parser.add_argument(
        "--ports",
        default=",".join(str(port) for port in DEFAULT_CANDIDATE_PORTS),
        help="Comma-separated TCP ports to test.",
    )
    parser.add_argument("--connect-timeout-s", type=float, default=1.0)
    parser.add_argument(
        "--passive-read-s",
        type=float,
        default=0.5,
        help="Passive read duration before sending StopTransmission on raw data ports.",
    )
    parser.add_argument(
        "--post-send-read-s",
        type=float,
        default=1.5,
        help="Read duration after sending StopTransmission on raw data ports.",
    )
    parser.add_argument(
        "--raw-gsv-on-all-open-ports",
        action="store_true",
        help="Send the GSV StopTransmission probe on every open port, not only data-port candidates.",
    )
    parser.add_argument(
        "--send-start-after-stop",
        action="store_true",
        help="Restart transmission after the StopTransmission probe. Off by default to keep the diagnostic conservative.",
    )
    args = parser.parse_args()

    devices = iter_selected_devices(args.devices.split(","))
    ports = parse_csv_ints(args.ports)

    print("Two-GSV TCP connection diagnostics")
    print("----------------------------------")
    print(f"devices: {', '.join(device['name'] for device in devices)}")
    print(f"ports: {', '.join(str(port) for port in ports)}")
    print(f"connect_timeout_s: {args.connect_timeout_s:g}")
    print(f"passive_read_s: {args.passive_read_s:g}")
    print(f"post_send_read_s: {args.post_send_read_s:g}")
    print(f"stop_frame: {to_hex(STOP_TRANSMISSION_FRAME)}")
    print()

    for device_config in devices:
        host = device_config["ip_address"]
        print(f"{device_config['name']} at {host}")
        print("-" * (len(device_config["name"]) + len(host) + 4))
        results = []
        for port in ports:
            send_gsv_probe = args.raw_gsv_on_all_open_ports or port in RAW_GSV_TEST_PORTS
            result = probe_tcp_port(
                host,
                port,
                connect_timeout_s=args.connect_timeout_s,
                passive_read_s=args.passive_read_s,
                post_send_read_s=args.post_send_read_s,
                send_gsv_probe=send_gsv_probe,
                send_start_after_stop=args.send_start_after_stop,
            )
            results.append(result)
            print_probe_result(result)
        print()
        print_interpretation(results)
        print()


if __name__ == "__main__":
    main()
