"""Input-mode-related feature methods for one GSV device."""

from __future__ import annotations

from math import isclose
from typing import TYPE_CHECKING

from ..constants import constants_commands as COMMAND
from ..constants import constants_sensor_input_modes as SENSOR_INPUT_MODE
from ..protocol.protocol_payload_codec import (
    pack_uint8_uint8,
    unpack_uint8_uint32_response,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


class InputFeature:
    """Toolbox for analogue input mode / range commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def read_input_mode(
        self,
        channel: int,
    ) -> dict:
        """Read the currently configured input mode for one channel."""
        payload = pack_uint8_uint8(channel, 0xFF)
        response = self.device.request_ok(COMMAND.GET_INPUT_TYPE, payload)
        input_mode, raw_input_range = unpack_uint8_uint32_response(response)

        response["channel"] = channel
        response["sensor_input_mode"] = input_mode
        response["sensor_input_mode_name"] = SENSOR_INPUT_MODE.MODE_DEFINITIONS[
            input_mode
        ]["canonical_name"]
        response["sensor_input_sensitivity_mv_per_v"] = raw_input_range / 100.0
        return response

    def write_input_mode(
        self,
        channel: int,
        sensor_input_mode: str | int,
    ) -> dict:
        """Write the input mode for one channel.

        The GSV-8 reloads default channel scaling and user-offset values when
        the input mode is changed. The current values are therefore preserved
        and restored automatically so callers do not need to manage command
        order manually.
        """
        normalized_mode = SENSOR_INPUT_MODE.normalize_sensor_input_mode(
            sensor_input_mode
        )
        preserved_settings = self._read_dependent_channel_settings(channel)

        payload = pack_uint8_uint8(channel, normalized_mode)
        response = self.device.request_ok(COMMAND.SET_INPUT_TYPE, payload)

        self._restore_dependent_channel_settings(
            channel=channel,
            preserved_settings=preserved_settings,
        )

        response["channel"] = channel
        response["sensor_input_mode"] = normalized_mode
        response["sensor_input_mode_name"] = SENSOR_INPUT_MODE.MODE_DEFINITIONS[
            normalized_mode
        ]["canonical_name"]
        response["sensor_input_sensitivity_mv_per_v"] = (
            SENSOR_INPUT_MODE.get_input_sensitivity_mv_per_v(normalized_mode)
        )
        response["restored_scaling_factor"] = preserved_settings["scaling_factor"]
        response["restored_user_offset"] = preserved_settings["user_offset"]
        return response

    def configure_input_mode(
        self,
        channel: int,
        sensor_input_mode: str | int,
    ) -> dict:
        """Write and read back one input mode."""
        normalized_mode = SENSOR_INPUT_MODE.normalize_sensor_input_mode(
            sensor_input_mode
        )
        requested_sensitivity = SENSOR_INPUT_MODE.get_input_sensitivity_mv_per_v(
            normalized_mode
        )

        write_response = self.write_input_mode(
            channel=channel,
            sensor_input_mode=normalized_mode,
        )
        read_response = self.read_input_mode(channel)

        if read_response["sensor_input_mode"] != normalized_mode:
            raise ValueError(
                "Configured sensor input mode does not match the requested value."
            )

        read_back_sensitivity = read_response["sensor_input_sensitivity_mv_per_v"]
        if requested_sensitivity is not None:
            if not isclose(
                float(read_back_sensitivity),
                float(requested_sensitivity),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "Configured sensor input sensitivity does not match the requested mode."
                )

        read_response["requested_sensor_input_mode"] = normalized_mode
        read_response["restored_scaling_factor"] = write_response[
            "restored_scaling_factor"
        ]
        read_response["restored_user_offset"] = write_response["restored_user_offset"]
        return read_response

    def _read_dependent_channel_settings(
        self,
        channel: int,
    ) -> dict:
        """Read settings that are known to be reset by SetInputType."""
        scaling_response = self.device.scaling.read_scaling_factor(channel)
        offset_response = self.device.zero.read_user_offset(channel)

        return {
            "scaling_factor": scaling_response["scaling_factor"],
            "user_offset": offset_response["user_offset"],
        }

    def _restore_dependent_channel_settings(
        self,
        *,
        channel: int,
        preserved_settings: dict,
    ) -> None:
        """Restore settings that were reset by SetInputType."""
        self.device.scaling.write_scaling_factor(
            channel=channel,
            scaling_factor=preserved_settings["scaling_factor"],
        )
        self.device.zero.write_user_offset(
            channel=channel,
            user_offset=preserved_settings["user_offset"],
        )
