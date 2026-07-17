"""Filter-related feature methods for one GSV device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import constants_analog_filters as ANALOG_FILTER
from ..constants import constants_commands as COMMAND
from ..protocol.protocol_payload_codec import (
    pack_uint16,
    pack_uint32,
    unpack_uint16_response,
    unpack_uint32_payload,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


ANALOG_FILTER_AUTOMATIC_MODE_FLAG = 1 << 1


class FiltersFeature:
    """Toolbox for analogue filter commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def read_mode_flags(self) -> dict:
        """Read the GSV mode flags."""
        response = self.device.request_ok(COMMAND.GET_MODE)
        response["mode_flags"] = unpack_uint32_payload(response["payload"])
        response["analog_filter_automatic"] = bool(
            response["mode_flags"] & ANALOG_FILTER_AUTOMATIC_MODE_FLAG
        )
        return response

    def write_mode_flags(
        self,
        mode_flags: int,
    ) -> dict:
        """Write the GSV mode flags."""
        payload = pack_uint32(mode_flags)
        response = self.device.request_ok(COMMAND.SET_MODE, payload)
        response["mode_flags"] = int(mode_flags)
        response["analog_filter_automatic"] = bool(
            int(mode_flags) & ANALOG_FILTER_AUTOMATIC_MODE_FLAG
        )
        return response

    def disable_analog_filter_automatic(self) -> dict:
        """Disable automatic analogue-filter selection while preserving other flags."""
        before_response = self.read_mode_flags()
        mode_flags_before = before_response["mode_flags"]
        mode_flags_after_request = mode_flags_before & ~ANALOG_FILTER_AUTOMATIC_MODE_FLAG

        write_response = None
        if mode_flags_after_request != mode_flags_before:
            write_response = self.write_mode_flags(mode_flags_after_request)

        after_response = self.read_mode_flags()
        mode_flags_after = after_response["mode_flags"]
        analog_filter_automatic_after = after_response["analog_filter_automatic"]

        if analog_filter_automatic_after:
            raise ValueError(
                "Automatic analogue-filter selection is still active after SetMode."
            )

        return {
            "mode_flags_before": mode_flags_before,
            "mode_flags_after": mode_flags_after,
            "analog_filter_automatic_before": before_response[
                "analog_filter_automatic"
            ],
            "analog_filter_automatic_after": analog_filter_automatic_after,
            "mode_write_executed": write_response is not None,
        }

    def read_analog_filter(self) -> dict:
        """Read the configured analogue filter frequency."""
        response = self.device.request_ok(COMMAND.READ_ANALOG_FILTER)
        response["analog_filter_hz"] = ANALOG_FILTER.normalize_analog_filter(
            unpack_uint16_response(response)
        )
        return response

    def write_analog_filter(
        self,
        filter_selector: str | int | float,
    ) -> dict:
        """Write the configured analogue filter frequency.

        Automatic analogue-filter selection is disabled first. Otherwise the GSV
        may accept the write command but immediately keep or restore the filter
        value derived from the active data rate.

        The tested GSV-8 expects the analogue filter frequency as a big-endian
        uint16 value in Hz. The response to a float32 payload is a wrong
        parameter-count error on this device.
        """
        automatic_report = self.disable_analog_filter_automatic()
        normalized_filter_hz = ANALOG_FILTER.normalize_analog_filter(filter_selector)
        payload = pack_uint16(normalized_filter_hz)
        response = self.device.request_ok(COMMAND.WRITE_ANALOG_FILTER, payload)
        response["requested_analog_filter_hz"] = normalized_filter_hz
        response["analog_filter_automatic_before"] = automatic_report[
            "analog_filter_automatic_before"
        ]
        response["analog_filter_automatic_after"] = automatic_report[
            "analog_filter_automatic_after"
        ]
        response["mode_flags_before"] = automatic_report["mode_flags_before"]
        response["mode_flags_after"] = automatic_report["mode_flags_after"]
        response["mode_write_executed"] = automatic_report["mode_write_executed"]
        return response

    def configure_analog_filter(
        self,
        filter_selector: str | int | float,
        *,
        strict: bool = False,
    ) -> dict:
        """Write and read back one analogue filter frequency.

        In non-strict mode, write or read errors are returned in the result
        dictionary instead of aborting the surrounding measurement setup.
        """
        requested_filter_hz = ANALOG_FILTER.normalize_analog_filter(filter_selector)

        write_accepted = False
        write_error = None
        automatic_before = None
        automatic_after = None
        mode_flags_before = None
        mode_flags_after = None
        mode_write_executed = None

        try:
            write_response = self.write_analog_filter(requested_filter_hz)
            write_accepted = True
            automatic_before = write_response.get("analog_filter_automatic_before")
            automatic_after = write_response.get("analog_filter_automatic_after")
            mode_flags_before = write_response.get("mode_flags_before")
            mode_flags_after = write_response.get("mode_flags_after")
            mode_write_executed = write_response.get("mode_write_executed")
        except Exception as error:
            if strict:
                raise
            write_error = str(error)

        active_filter_hz = None
        read_error = None
        try:
            read_response = self.read_analog_filter()
            active_filter_hz = read_response["analog_filter_hz"]
        except Exception as error:
            if strict:
                raise
            read_error = str(error)

        matches_request = (
            active_filter_hz == requested_filter_hz
            if active_filter_hz is not None
            else False
        )

        if strict and not matches_request:
            raise ValueError(
                "Configured analogue filter does not match the requested value: "
                f"requested {requested_filter_hz} Hz, "
                f"read back {active_filter_hz} Hz."
            )

        return {
            "requested_analog_filter_hz": requested_filter_hz,
            "analog_filter_hz": active_filter_hz,
            "analog_filter_write_accepted": write_accepted,
            "analog_filter_matches_request": matches_request,
            "analog_filter_write_error": write_error,
            "analog_filter_read_error": read_error,
            "analog_filter_automatic_before": automatic_before,
            "analog_filter_automatic_after": automatic_after,
            "mode_flags_before": mode_flags_before,
            "mode_flags_after": mode_flags_after,
            "mode_write_executed": mode_write_executed,
        }
