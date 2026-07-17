"""Administrative and diagnostic feature methods for one GSV device.

This module follows the command-group logic of the ME GSV protocol
specification. It contains device-level administration, status, and error-memory
commands that do not belong to acquisition, scaling, input configuration,
interface configuration, filtering, or zero-point adjustment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import constants_commands as COMMAND
from ..protocol.protocol_payload_codec import (
    decode_generic_payload_views,
    pack_uint8,
    unpack_float32_payload,
    unpack_uint32_payload,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


class AdminFeature:
    """Device administration, status, and error-memory commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def read_mode_flags(self) -> dict:
        """Read the GSV mode flags via GetMode (0x26)."""
        response = self.device.request_ok(COMMAND.GET_MODE)
        response.update(_decode_generic_payload(response["payload"]))
        if len(response["payload"]) == 4:
            response["mode_flags"] = unpack_uint32_payload(response["payload"])
        return response

    def read_software_configuration(self) -> dict:
        """Read device software/configuration feature flags via 0x2A."""
        response = self.device.request_ok(COMMAND.GET_SOFTWARE_CONFIGURATION)
        response.update(_decode_generic_payload(response["payload"]))
        if len(response["payload"]) == 4:
            response["software_configuration_flags"] = unpack_uint32_payload(response["payload"])
        return response

    def read_last_protocol_error(
        self,
        index: int,
    ) -> dict:
        """Read one last-protocol-error entry via 0x42."""
        response = self.device.request_ok(
            COMMAND.GET_LAST_PROTOCOL_ERROR,
            pack_uint8(index),
        )
        response["index"] = int(index)
        response.update(_decode_generic_payload(response["payload"]))
        return response

    def read_last_value_error(
        self,
        index: int,
    ) -> dict:
        """Read one value-error/error-memory entry via 0x43."""
        response = self.device.request_ok(
            COMMAND.GET_LAST_VALUE_ERROR,
            pack_uint8(index),
        )
        response["index"] = int(index)
        response.update(_decode_generic_payload(response["payload"]))
        return response


    def read_device_hours(
        self,
        index: int = 0,
    ) -> dict:
        """Read one GSV-8 device-hour counter via ReadDeviceHours (0x56)."""
        response = self.device.request_ok(
            COMMAND.READ_DEVICE_HOURS,
            pack_uint8(index),
        )
        response["index"] = int(index)
        response.update(_decode_generic_payload(response["payload"]))
        if len(response["payload"]) == 4:
            response["device_hours_h"] = float(unpack_float32_payload(response["payload"]))
        return response

    def erase_error_memory(self) -> dict:
        """Erase the non-volatile error memory via 0x44.

        This is intentionally exposed as an explicit method only. Diagnostic apps
        should not call it implicitly because the command changes device state.
        """
        return self.device.request_ok(COMMAND.ERASE_ERROR_MEMORY)



def _decode_generic_payload(payload: bytes) -> dict:
    """Return conservative decoded views for one response payload."""
    return decode_generic_payload_views(payload)
