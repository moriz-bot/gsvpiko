"""CRC helpers.

CRC support is intentionally not used in the current parsing step.
This module exists so the protocol package already has a stable place
for future CRC implementation.
"""


def crc8(_: bytes) -> int:
    """Placeholder for future command CRC support."""
    raise NotImplementedError("CRC-8 is not implemented yet.")


def crc16(_: bytes) -> int:
    """Placeholder for future measurement CRC support."""
    raise NotImplementedError("CRC-16 is not implemented yet.")
