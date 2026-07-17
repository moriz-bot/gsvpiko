"""Frame builder for serial request frames."""

from ..constants import constants_frames as FRAME


def build_command_frame(command_id: int, payload: bytes = b"") -> bytes:
    """Build a serial request frame without CRC.

    This function only supports the normal short-length request format
    that is sufficient for the current parsing step.
    """
    if len(payload) > 15:
        raise ValueError("Request payload is too large for the short serial frame format.")

    header = (
        (FRAME.REQUEST << FRAME.FRAME_TYPE_SHIFT)
        | (FRAME.SERIAL << FRAME.INTERFACE_SHIFT)
        | len(payload)
    )

    return bytes([FRAME.PREFIX, header, command_id]) + payload + bytes([FRAME.SUFFIX])


def build_stop_transmission_frame(command_id: int) -> bytes:
    """Convenience helper for readability at the call site."""
    return build_command_frame(command_id)
