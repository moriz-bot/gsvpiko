"""Factory for concrete byte transports created from device presets.

The GSV device layer should talk to transports through the BaseTransport
interface. This module is the single place that translates the configured
connection type into the concrete transport implementation.
"""

from __future__ import annotations

from typing import Any

from .transport_base import BaseTransport
from .transport_serial import SerialTransport
from .transport_tcp import TcpTransport

CONNECTION_TYPE_SERIAL = "serial"
CONNECTION_TYPE_TCP = "tcp"
SUPPORTED_CONNECTION_TYPES = (CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_TCP)


class TransportFactoryError(ValueError):
    """Raised when a device preset cannot be translated into a transport."""


def normalize_connection_type(connection_type: object) -> str:
    """Return a supported connection type string from a config value."""
    normalized = str(connection_type or CONNECTION_TYPE_SERIAL).strip().lower()
    if normalized not in SUPPORTED_CONNECTION_TYPES:
        expected = ", ".join(repr(item) for item in SUPPORTED_CONNECTION_TYPES)
        raise TransportFactoryError(
            f"Unsupported default_connection_type {connection_type!r}. "
            f"Expected one of: {expected}."
        )
    return normalized


def create_transport_from_device_config(
    device_config: dict[str, Any],
    *,
    baudrate: int,
    timeout_s: float,
) -> BaseTransport:
    """Create an unopened BaseTransport implementation for one device preset.

    NPort mode and NPort serial-side baudrate are configured separately in
    transport_nport. This factory only creates the byte transport that GsvDevice
    can use through the BaseTransport interface.
    """
    connection_type = normalize_connection_type(
        device_config.get("default_connection_type", CONNECTION_TYPE_SERIAL)
    )

    if connection_type == CONNECTION_TYPE_SERIAL:
        return SerialTransport(
            port=device_config["com_port"],
            baudrate=baudrate,
            timeout=timeout_s,
        )

    if connection_type == CONNECTION_TYPE_TCP:
        return TcpTransport(
            host=device_config["ip_address"],
            port=device_config["tcp_port"],
            timeout=timeout_s,
        )

    raise TransportFactoryError(f"Unsupported connection type {connection_type!r}.")
