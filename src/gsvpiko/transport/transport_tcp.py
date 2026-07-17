"""TCP byte-stream transport.

This transport is prepared for direct communication with a serial device server.
The GSV protocol still sees a byte stream; only the transport below changes from
a Windows COM port to a TCP socket.
"""

from __future__ import annotations

import socket
from typing import Optional

from .transport_base import BaseTransport


class TcpTransportError(RuntimeError):
    """Base error raised by the TCP transport layer."""


class TcpTransport(BaseTransport):
    """TCP transport implementation based on Python sockets."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.socket_connection: Optional[socket.socket] = None

    def open(self) -> None:
        """Open the configured TCP connection."""
        if self.socket_connection is not None:
            return

        try:
            self.socket_connection = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            )
            self.socket_connection.settimeout(self.timeout)
        except OSError as error:
            self.socket_connection = None
            raise TcpTransportError(
                f"Could not open TCP connection to {self.host}:{self.port}. "
                f"Original error: {error}."
            ) from error

    def close(self) -> None:
        """Close the TCP connection if it is open."""
        if self.socket_connection is None:
            return

        self.socket_connection.close()
        self.socket_connection = None

    def write(
        self,
        data: bytes,
    ) -> None:
        """Write all bytes to the TCP connection."""
        connection = self._require_open_connection()
        connection.sendall(data)

    def read(
        self,
        size: int = 1,
    ) -> bytes:
        """Read up to size bytes from the TCP connection."""
        connection = self._require_open_connection()

        try:
            return connection.recv(size)
        except socket.timeout:
            return b""

    def prepare_for_runtime(self) -> None:
        """Prepare the TCP socket for runtime acquisition."""
        self.clear_input_buffer()


    def read_available(
        self,
        max_size: int,
    ) -> bytes:
        """Return currently buffered TCP bytes without waiting."""
        connection = self._require_open_connection()
        requested_size = int(max_size)
        if requested_size <= 0:
            return b""

        previous_timeout = connection.gettimeout()
        connection.setblocking(False)
        buffer = bytearray()

        try:
            while len(buffer) < requested_size:
                try:
                    chunk = connection.recv(requested_size - len(buffer))
                except BlockingIOError:
                    break
                except socket.timeout:
                    break

                if not chunk:
                    break
                buffer.extend(chunk)
        finally:
            connection.settimeout(previous_timeout)

        return bytes(buffer)

    def clear_input_buffer(self) -> None:
        """Drain currently available input bytes without blocking."""
        connection = self._require_open_connection()
        previous_timeout = connection.gettimeout()
        connection.setblocking(False)

        try:
            while True:
                try:
                    chunk = connection.recv(4096)
                except BlockingIOError:
                    break

                if not chunk:
                    break
        finally:
            connection.settimeout(previous_timeout)

    def _require_open_connection(self) -> socket.socket:
        """Return the open TCP connection or raise a clear error."""
        if self.socket_connection is None:
            raise TcpTransportError(
                f"TCP connection to {self.host}:{self.port} is not open."
            )

        return self.socket_connection
