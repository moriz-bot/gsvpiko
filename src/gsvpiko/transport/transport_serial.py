"""Serial byte-stream transport for local COM ports.

SerialTransport opens a configured COM port, writes bytes, reads bytes, and
manages local input/output buffers. It does not parse GSV frames and does not
send GSV protocol commands.

Moxa RealCOM ports can be opened directly by name even when they are not shown
by serial.tools.list_ports. A configured COM name is therefore tested by opening
it directly.

Some Windows RealCOM driver states block inside the pyserial read call before
pyserial can apply its normal timeout. SerialTransport wraps the driver read in
a bounded daemon thread. If the driver call does not return, the COM handle is
cancelled/closed and a SerialTransportError is raised.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Optional

import serial

from .transport_base import BaseTransport


READ_POLL_INTERVAL_S = 0.002
DRIVER_READ_CALL_TIMEOUT_S = 0.25


class SerialTransportError(RuntimeError):
    """Base error raised by the serial transport layer."""


class SerialPortOpenError(SerialTransportError):
    """Raised when a serial/COM port cannot be opened."""


@dataclass(frozen=True)
class SerialOpenDiagnostics:
    """Diagnostic information for a failed serial open attempt."""

    port: str
    baudrate: int
    timeout_s: float
    original_error: str

    def to_message(self) -> str:
        """Return a user-facing diagnostic message."""
        return (
            f"Could not open serial port {self.port!r} at {self.baudrate} baud. "
            f"Original error: {self.original_error}. "
            "For RealCOM connections, check the COM mapping, device-server "
            "reachability, and whether another program has the port open."
        )


class SerialTransport(BaseTransport):
    """Serial transport implementation based on pyserial."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout: float,
        *,
        write_timeout: Optional[float] = None,
    ) -> None:
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.write_timeout = self.timeout if write_timeout is None else write_timeout
        self.serial_connection: Optional[serial.Serial] = None

    def open(self) -> None:
        """Open the configured serial port."""
        if self.serial_connection is not None and self.serial_connection.is_open:
            return

        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0,
                write_timeout=self.write_timeout,
            )
        except (OSError, serial.SerialException) as error:
            diagnostics = SerialOpenDiagnostics(
                port=self.port,
                baudrate=self.baudrate,
                timeout_s=self.timeout,
                original_error=str(error),
            )
            raise SerialPortOpenError(diagnostics.to_message()) from error

    def close(self) -> None:
        """Close the serial port if it is open."""
        if self.serial_connection is None:
            return

        try:
            self.serial_connection.close()
        finally:
            self.serial_connection = None

    def is_open(self) -> bool:
        """Return whether the underlying serial connection is open."""
        return (
            self.serial_connection is not None
            and self.serial_connection.is_open
        )

    def clear_input_buffer(self) -> None:
        """Discard pending bytes from the input buffer."""
        connection = self._require_open_connection()
        connection.reset_input_buffer()

    def clear_output_buffer(self) -> None:
        """Discard pending bytes from the output buffer."""
        connection = self._require_open_connection()
        connection.reset_output_buffer()

    def prepare_for_runtime(self) -> None:
        """Prepare the serial transport for runtime acquisition.

        The serial path does not need socket-level preparation. Keeping this
        method explicit documents that SerialTransport fulfils the same runtime
        transport contract as TcpTransport.
        """
        return None

    def write(
        self,
        data: bytes,
    ) -> None:
        """Write all bytes to the serial connection."""
        connection = self._require_open_connection()
        bytes_written = connection.write(data)

        if bytes_written != len(data):
            raise SerialTransportError(
                f"Incomplete serial write: expected {len(data)} bytes, "
                f"wrote {bytes_written} bytes."
            )

    def read(
        self,
        size: int = 1,
    ) -> bytes:
        """Read up to size bytes while enforcing the configured timeout."""
        connection = self._require_open_connection()
        requested_size = int(size)

        if requested_size <= 0:
            return b""

        deadline = time.monotonic() + self.timeout
        buffer = bytearray()

        while len(buffer) < requested_size:
            remaining_total_s = deadline - time.monotonic()
            if remaining_total_s <= 0:
                return bytes(buffer)

            read_call_timeout_s = min(
                DRIVER_READ_CALL_TIMEOUT_S,
                remaining_total_s,
            )
            chunk = self._read_from_driver_with_timeout(
                connection,
                requested_size - len(buffer),
                read_call_timeout_s,
            )

            if chunk:
                buffer.extend(chunk)
                return bytes(buffer)

            time.sleep(min(READ_POLL_INTERVAL_S, max(remaining_total_s, 0.0)))

        return bytes(buffer)


    def read_available(
        self,
        max_size: int,
    ) -> bytes:
        """Return currently buffered serial bytes without waiting."""
        connection = self._require_open_connection()
        requested_size = int(max_size)
        if requested_size <= 0:
            return b""

        waiting = int(getattr(connection, "in_waiting", 0) or 0)
        if waiting <= 0:
            return b""

        return bytes(connection.read(min(waiting, requested_size)))

    def read_exactly(
        self,
        size: int,
    ) -> bytes:
        """Read exactly size bytes or raise an error."""
        requested_size = int(size)
        buffer = bytearray()
        deadline = time.monotonic() + self.timeout

        while len(buffer) < requested_size:
            remaining = requested_size - len(buffer)
            chunk = self.read(remaining)

            if chunk:
                buffer.extend(chunk)
                continue

            if time.monotonic() >= deadline:
                raise SerialTransportError(
                    "Serial read timeout: "
                    f"expected {requested_size} bytes, got {len(buffer)} bytes."
                )

        return bytes(buffer)

    def _read_from_driver_with_timeout(
        self,
        connection: serial.Serial,
        size: int,
        timeout_s: float,
    ) -> bytes:
        """Call pyserial read and abort the COM handle if the driver blocks."""
        result: dict[str, bytes | BaseException] = {}

        def read_target() -> None:
            try:
                result["data"] = connection.read(size)
            except BaseException as error:
                result["error"] = error

        thread = threading.Thread(
            target=read_target,
            name=f"gsvpiko-read-{self.port}",
            daemon=True,
        )
        thread.start()
        thread.join(timeout=max(timeout_s, 0.001))

        if thread.is_alive():
            self._abort_blocked_driver_read(connection)
            raise SerialTransportError(
                "Serial driver read did not return within "
                f"{timeout_s:.3f} s on {self.port!r} at {self.baudrate} baud."
            )

        if "error" in result:
            error = result["error"]
            raise SerialTransportError(
                f"Serial read failed on {self.port!r} at {self.baudrate} baud: "
                f"{error}"
            ) from error

        return bytes(result.get("data", b""))

    def _abort_blocked_driver_read(
        self,
        connection: serial.Serial,
    ) -> None:
        """Cancel and close a COM handle after a blocked driver read."""
        try:
            connection.cancel_read()
        except (AttributeError, OSError, serial.SerialException):
            pass

        try:
            connection.close()
        except (OSError, serial.SerialException):
            pass

        if self.serial_connection is connection:
            self.serial_connection = None

    def _require_open_connection(self) -> serial.Serial:
        """Return the open serial connection or raise a clear error."""
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise SerialTransportError(
                f"Serial port {self.port!r} is not open."
            )

        return self.serial_connection
