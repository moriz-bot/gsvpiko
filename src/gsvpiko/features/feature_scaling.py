"""Scaling-related feature methods for one GSV device."""

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


class ScalingFeature:
    """Toolbox for user scaling commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def read_scaling_factor(
        self,
        channel: int,
    ) -> dict:
        """Read the configured scaling factor for one channel."""
        payload = pack_uint8(channel)
        response = self.device.request_ok(COMMAND.READ_USER_SCALE, payload)
        response["channel"] = channel
        response["scaling_factor"] = unpack_float32_response(response)
        return response

    def write_scaling_factor(
        self,
        channel: int,
        scaling_factor: float,
    ) -> dict:
        """Write the scaling factor for one channel."""
        payload = pack_uint8_float32(channel, scaling_factor)
        response = self.device.request_ok(COMMAND.WRITE_USER_SCALE, payload)
        response["channel"] = channel
        response["scaling_factor"] = float(scaling_factor)
        return response

    def configure_scaling_factor(
        self,
        channel: int,
        scaling_factor: float,
    ) -> dict:
        """Write and read back one scaling factor."""
        self.write_scaling_factor(
            channel=channel,
            scaling_factor=scaling_factor,
        )
        response = self.read_scaling_factor(channel)

        if not isclose(
            float(response["scaling_factor"]),
            float(scaling_factor),
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "Configured scaling factor does not match the requested value."
            )

        return response
