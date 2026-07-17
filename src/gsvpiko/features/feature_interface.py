"""Interface-related feature methods for one GSV device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import constants_baudrates as BAUDRATE
from ..constants import constants_commands as COMMAND
from ..protocol.protocol_payload_codec import (
    pack_uint8,
    pack_uint8_uint32,
    unpack_uint32_payload,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


INTERFACE_SETTING_WRITABLE_MASK = 0x80
INTERFACE_SETTING_DATA_TYPE_MASK = 0x7F
INTERFACE_SETTING_TYPE_ACTIVE_BAUDRATE = 4


class InterfaceFeature:
    """Commands related to device identity and interface settings."""

    def __init__(self, device: "GsvDevice") -> None:
        self.device = device

    def get_interface(self) -> dict:
        """Read the current interface selection / state."""
        return self.device.request_ok(COMMAND.GET_INTERFACE)

    def get_firmware_version(self) -> dict:
        """Read the firmware version."""
        return self.device.request_ok(COMMAND.FIRMWARE_VERSION)

    def get_hardware_version(self) -> dict:
        """Read the hardware version."""
        return self.device.request_ok(COMMAND.GET_HARDWARE_VERSION)

    def release_interface(self) -> dict:
        """Release the current communication interface.

        The command ends the current communication session from the device
        perspective. This can matter for interface-setting experiments because
        another interface may otherwise keep or request write access.
        """
        command = getattr(COMMAND, "RELEASE_INTERFACE", 0x7A)
        return self.device.request_ok(command)

    def read_interface_setting(
        self,
        index: int | bytes,
    ) -> dict:
        """Read and decode one interface-setting entry.

        The older internal helper accepted a pre-encoded payload. Bytes are still
        accepted for compatibility, but new code should pass the integer index.
        """
        payload = index if isinstance(index, bytes) else pack_uint8(index)
        response = self.device.request_ok(COMMAND.READ_INTERFACE_SETTING, payload)
        decoded = self.decode_interface_setting_payload(
            request_index=index if isinstance(index, int) else None,
            response=response,
        )
        response.update(decoded)
        return response

    def write_interface_setting(
        self,
        index: int,
        data: int,
    ) -> dict:
        """Write one raw uint32 interface-setting value.

        This low-level method is intentionally generic. Higher-level code should
        first identify the correct writable setting index by reading the current
        interface-setting table.
        """
        payload = pack_uint8_uint32(index, data)
        response = self.device.request_ok(COMMAND.WRITE_INTERFACE_SETTING, payload)
        response["index"] = int(index)
        response["data"] = int(data)
        return response

    def decode_interface_setting_payload(
        self,
        *,
        request_index: int | None,
        response: dict,
    ) -> dict:
        """Decode a ReadInterfaceSetting response payload."""
        payload = response["payload"]

        if len(payload) != 6:
            raise ValueError(
                f"ReadInterfaceSetting returned {len(payload)} bytes, expected 6."
            )

        next_index = payload[0]
        type_byte = payload[1]
        data = unpack_uint32_payload(payload[2:6])
        data_type = type_byte & INTERFACE_SETTING_DATA_TYPE_MASK
        writable = bool(type_byte & INTERFACE_SETTING_WRITABLE_MASK)

        return {
            "request_index": request_index,
            "next_index": next_index,
            "type_byte": type_byte,
            "writable": writable,
            "data_type": data_type,
            "data": data,
            "is_active_baudrate_entry": (
                data_type == INTERFACE_SETTING_TYPE_ACTIVE_BAUDRATE
            ),
            "is_writable_active_baudrate_entry": (
                writable and data_type == INTERFACE_SETTING_TYPE_ACTIVE_BAUDRATE
            ),
        }

    def scan_interface_settings(
        self,
        *,
        max_index: int,
    ) -> list[dict]:
        """Read interface-setting entries from index 0 through max_index."""
        entries = []

        for index in range(max_index + 1):
            entries.append(self.read_interface_setting(index))

        return entries

    def find_writable_baudrate_settings(
        self,
        *,
        max_index: int,
    ) -> list[dict]:
        """Return writable interface-setting entries for active baudrate values."""
        result = []

        for index in range(max_index + 1):
            try:
                entry = self.read_interface_setting(index)
            except Exception:
                continue

            if not entry["is_writable_active_baudrate_entry"]:
                continue

            result.append(entry)

        return result

    def write_baudrate_setting(
        self,
        *,
        index: int,
        baudrate: int | str,
    ) -> dict:
        """Write one writable active-baudrate interface-setting entry.

        On the tested GSV-8, interface-setting index 10 controls the UART
        baudrate used by the NPort RealCOM path. The written value is stored
        immediately, but the active serial connection keeps the old baudrate
        until the next power-on cycle.
        """
        normalized_baudrate = BAUDRATE.normalize_baudrate(baudrate)
        response = self.write_interface_setting(
            index=index,
            data=normalized_baudrate,
        )
        response["baudrate"] = normalized_baudrate
        return response

    def read_serial_baudrate_setting(
        self,
        *,
        index: int = BAUDRATE.ACTIVE_SERIAL_INTERFACE_SETTING_INDEX,
    ) -> dict:
        """Read the interface-setting entry used for the active serial baudrate."""
        return self.read_interface_setting(index)

    def store_serial_baudrate_for_next_power_cycle(
        self,
        baudrate: int | str,
        *,
        index: int = BAUDRATE.ACTIVE_SERIAL_INTERFACE_SETTING_INDEX,
    ) -> dict:
        """Store the serial baudrate that becomes active after a power cycle."""
        requested_baudrate = BAUDRATE.normalize_baudrate(baudrate)
        before_response = self.read_serial_baudrate_setting(index=index)
        write_response = None

        if before_response["data"] != requested_baudrate:
            write_response = self.write_baudrate_setting(
                index=index,
                baudrate=requested_baudrate,
            )

        after_response = self.read_serial_baudrate_setting(index=index)

        return {
            "baudrate_setting_index": index,
            "requested_baudrate": requested_baudrate,
            "stored_baudrate_before": before_response["data"],
            "stored_baudrate_after": after_response["data"],
            "stored_baudrate_matches_request": (
                after_response["data"] == requested_baudrate
            ),
            "write_executed": write_response is not None,
            "write_response_raw_hex": (
                None if write_response is None else write_response.get("raw_hex")
            ),
            "power_cycle_required": BAUDRATE.POWER_CYCLE_REQUIRED_FOR_STORED_CHANGE,
        }
