"""Hex formatting helpers."""


def to_hex(data: bytes) -> str:
    """Return a byte sequence as an uppercase space-separated hex string."""
    return " ".join(f"{byte:02X}" for byte in data)
