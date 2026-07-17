"""Zero- and user-offset-related feature methods for one GSV device."""

from __future__ import annotations

from math import isclose
from typing import TYPE_CHECKING

from ..constants import constants_commands as COMMAND
from ..protocol.protocol_payload_codec import (
    pack_uint8,
    pack_uint8_float32,
    unpack_float32_response,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


class ZeroFeature:
    """Toolbox for zeroing and user offset commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def read_user_offset(
        self,
        channel: int,
    ) -> dict:
        """Read the configured user offset for one channel."""
        payload = pack_uint8(channel)
        response = self.device.request_ok(COMMAND.READ_USER_OFFSET, payload)
        response["channel"] = channel
        response["user_offset"] = unpack_float32_response(response)
        return response

    def write_user_offset(
        self,
        channel: int,
        user_offset: float,
    ) -> dict:
        """Write the configured user offset for one channel."""
        payload = pack_uint8_float32(channel, user_offset)
        response = self.device.request_ok(COMMAND.WRITE_USER_OFFSET, payload)
        response["channel"] = channel
        response["user_offset"] = float(user_offset)
        return response

    def configure_user_offset(
        self,
        channel: int,
        user_offset: float,
    ) -> dict:
        """Write and read back one user offset."""
        self.write_user_offset(
            channel=channel,
            user_offset=user_offset,
        )
        response = self.read_user_offset(channel)

        if not isclose(
            float(response["user_offset"]),
            float(user_offset),
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "Configured user offset does not match the requested value."
            )

        return response

    def set_zero(
        self,
        channel: int,
    ) -> dict:
        """Tare one channel by setting the current input value to zero.

        The GSV protocol calls this action ``SetZero``. Channel 0 applies the
        action to all analogue input channels supported by the device.
        """
        response = self.device.request_ok(
            COMMAND.SET_ZERO,
            pack_uint8(channel),
        )
        response["channel"] = int(channel)
        response["tare_scope"] = "all_channels" if int(channel) == 0 else "single_channel"
        return response

    def set_zero_all_channels(self) -> dict:
        """Tare all analogue input channels with the current input values."""
        return self.set_zero(0)
