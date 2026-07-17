"""Abstract byte-stream transport interface."""

from abc import ABC, abstractmethod


class BaseTransport(ABC):
    """Common interface for all byte-stream transports.

    Upper layers must not depend on whether the byte stream comes from a local
    COM port, a Moxa RealCOM mapping, or a direct TCP socket. Blocking reads are
    used by command/response code. Non-blocking available-byte reads are used by
    high-rate runtime acquisition.
    """

    @abstractmethod
    def open(self) -> None:
        """Open the transport connection."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the transport connection."""
        raise NotImplementedError

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Write raw bytes to the transport."""
        raise NotImplementedError

    @abstractmethod
    def read(self, size: int = 1) -> bytes:
        """Read raw bytes using the transport timeout semantics."""
        raise NotImplementedError

    @abstractmethod
    def read_available(self, max_size: int) -> bytes:
        """Return currently available bytes without waiting for new bytes.

        The method must return quickly. It may return fewer than max_size bytes
        and returns b"" when no bytes are currently available.
        """
        raise NotImplementedError

    @abstractmethod
    def clear_input_buffer(self) -> None:
        """Discard pending input bytes from the transport buffer."""
        raise NotImplementedError


    def prepare_for_runtime(self) -> None:
        """Prepare the open transport for high-rate runtime acquisition."""
        return None

    @property
    def connection_type(self) -> str:
        """Return a short user-facing name for this transport type."""
        return self.__class__.__name__.removesuffix("Transport").lower()
