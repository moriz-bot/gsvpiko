"""GSV-8 front-panel socket definitions.

The keys use the visible GSV-8 socket labels. A socket describes the fixed
device-side connection point, while the channel list describes the analogue GSV
channels that can be reached through that socket.
"""

from __future__ import annotations

SOCKETS = {
    "1/3": {
        "type": "analog",
        "channels": [1, 2, 3],
        "exclusive_with": ["1/6"],
        "implemented": True,
    },
    "4/6": {
        "type": "analog",
        "channels": [4, 5, 6],
        "exclusive_with": ["1/6"],
        "implemented": True,
    },
    "1/6": {
        "type": "analog",
        "channels": [1, 2, 3, 4, 5, 6],
        "exclusive_with": ["1/3", "4/6"],
        "implemented": True,
    },
    "7/8": {
        "type": "analog",
        "channels": [7, 8],
        "exclusive_with": [],
        "implemented": True,
    },
    "digital_io": {
        "type": "digital",
        "channels": [],
        "exclusive_with": [],
        "implemented": False,
    },
}


def normalize_socket_name(
    socket_name: str,
) -> str:
    """Return one validated GSV-8 socket name."""
    normalized = str(socket_name).strip()

    if normalized not in SOCKETS:
        allowed = ", ".join(sorted(SOCKETS))
        raise ValueError(
            f"Unknown GSV-8 socket {socket_name!r}. "
            f"Allowed sockets are: {allowed}."
        )

    return normalized


def get_socket_definition(
    socket_name: str,
) -> dict:
    """Return the definition for one GSV-8 socket."""
    return SOCKETS[normalize_socket_name(socket_name)]


def get_socket_type(
    socket_name: str,
) -> str:
    """Return the socket type, such as analog or digital."""
    return get_socket_definition(socket_name)["type"]


def get_socket_channels(
    socket_name: str,
) -> list[int]:
    """Return the analogue channels available through one socket."""
    return list(get_socket_definition(socket_name)["channels"])


def is_socket_implemented(
    socket_name: str,
) -> bool:
    """Return whether the socket is implemented in the current software layer."""
    return bool(get_socket_definition(socket_name)["implemented"])


def get_exclusive_sockets(
    socket_name: str,
) -> list[str]:
    """Return socket names that cannot be used together with this socket."""
    return list(get_socket_definition(socket_name)["exclusive_with"])
