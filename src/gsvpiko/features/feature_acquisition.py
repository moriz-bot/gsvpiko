"""Acquisition-related feature methods for one GSV device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import constants_commands as COMMAND
from ..constants import constants_datatypes as DATATYPE
from ..coordination import coordination_sample_rate_limit as SRL
from ..protocol.protocol_payload_codec import (
    pack_float32,
    pack_uint8,
    pack_uint8_uint16,
    unpack_float32_response,
    unpack_uint16_response,
)

if TYPE_CHECKING:
    from ..device.device_gsv import GsvDevice


class AcquisitionFeature:
    """Toolbox for transmission, sample-rate, datatype, and TX-mapping commands."""

    def __init__(
        self,
        device: "GsvDevice",
    ) -> None:
        self.device = device

    def stop_transmission(self) -> dict:
        """Stop autonomous measurement transmission."""
        return self.device.request_ok(COMMAND.STOP_TRANSMISSION)

    def start_transmission(self) -> dict:
        """Start autonomous measurement transmission."""
        return self.device.request_ok(COMMAND.START_TRANSMISSION)

    def get_value(self) -> dict:
        """Request one value response frame."""
        return self.device.request_ok(COMMAND.GET_VALUE)

    def get_raw_value(self) -> dict:
        """Request one raw-value response frame."""
        return self.device.request_ok(COMMAND.GET_RAW_VALUE)

    def read_sample_rate(self) -> dict:
        """Read the configured GSV output sample/frame rate."""
        response = self.device.request_ok(COMMAND.READ_DATA_RATE)
        response["sample_rate_hz"] = unpack_float32_response(response)
        return response

    def read_sample_rate_range(
        self,
        index: int,
    ) -> dict:
        """Read one GSV output sample-rate range value.

        Index 0 returns the currently adjustable maximum sample rate. Index 1
        returns the currently adjustable minimum sample rate. The range depends
        on the active frame layout and device configuration.
        """
        response = self.device.request_ok(
            COMMAND.READ_DATA_RATE_RANGE,
            pack_uint8(index),
        )
        response["sample_rate_range_index"] = int(index)
        response["sample_rate_hz"] = unpack_float32_response(response)
        return response

    def read_max_sample_rate(self) -> dict:
        """Read the currently adjustable maximum output sample/frame rate."""
        response = self.read_sample_rate_range(0)
        response["maximum_sample_rate_hz"] = response["sample_rate_hz"]
        return response

    def read_min_sample_rate(self) -> dict:
        """Read the currently adjustable minimum output sample/frame rate."""
        response = self.read_sample_rate_range(1)
        response["minimum_sample_rate_hz"] = response["sample_rate_hz"]
        return response

    def write_sample_rate(
        self,
        sample_rate_hz: float,
    ) -> dict:
        """Write the configured GSV output sample/frame rate."""
        payload = pack_float32(sample_rate_hz)
        response = self.device.request_ok(COMMAND.WRITE_DATA_RATE, payload)
        response["requested_sample_rate_hz"] = float(sample_rate_hz)
        return response

    def configure_sample_rate(
        self,
        sample_rate_hz: float,
        *,
        strict: bool = False,
        rel_tol: float = 1e-6,
        abs_tol: float = 1e-3,
    ) -> dict:
        """Write and read back one GSV output sample/frame rate."""
        requested_sample_rate_hz = float(sample_rate_hz)

        self.write_sample_rate(requested_sample_rate_hz)
        response = self.read_sample_rate()

        readback = SRL.check_sample_rate_readback(
            requested_sample_rate_hz=requested_sample_rate_hz,
            active_sample_rate_hz=float(response["sample_rate_hz"]),
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        )
        response.update(readback)

        if strict and not response["sample_rate_matches_request"]:
            raise ValueError(
                "Configured sample rate does not match the requested value: "
                f"requested {requested_sample_rate_hz} Hz, "
                f"read back {response['sample_rate_hz']} Hz."
            )

        return response

    def read_tx_mapping_count(self) -> dict:
        """Read the number of mapped measurement objects."""
        payload = pack_uint8(0)
        response = self.device.request_ok(COMMAND.GET_TX_MAPPING, payload)
        response["tx_mapping_count"] = unpack_uint16_response(response)
        return response

    def write_tx_mapping_count(
        self,
        object_count: int,
    ) -> dict:
        """Write the number of mapped measurement objects."""
        payload = pack_uint8_uint16(0, object_count)
        response = self.device.request_ok(COMMAND.SET_TX_MAPPING, payload)
        response["tx_mapping_count"] = int(object_count)
        return response

    def configure_tx_mapping_count(
        self,
        object_count: int,
    ) -> dict:
        """Write and read back the TX mapping count."""
        self.write_tx_mapping_count(object_count)
        response = self.read_tx_mapping_count()

        if response["tx_mapping_count"] != int(object_count):
            raise ValueError(
                "Configured TX mapping count does not match the requested value: "
                f"requested {int(object_count)}, "
                f"read back {response['tx_mapping_count']}."
            )

        return response

    def read_tx_mode(
        self,
        index: int,
    ) -> dict:
        """Read one TX-mode setting."""
        response = self.device.request_ok(
            COMMAND.GET_TX_MODE,
            pack_uint8(index),
        )
        response["tx_mode_index"] = int(index)
        response["tx_mode_value"] = unpack_uint16_response(response)
        return response

    def write_tx_mode(
        self,
        index: int,
        value: int,
    ) -> dict:
        """Write one TX-mode setting."""
        response = self.device.request_ok(
            COMMAND.SET_TX_MODE,
            pack_uint8_uint16(index, value),
        )
        response["tx_mode_index"] = int(index)
        response["tx_mode_value"] = int(value)
        return response

    def read_datatype(self) -> dict:
        """Read the datatype used in autonomous measurement frames."""
        response = self.read_tx_mode(1)
        datatype = DATATYPE.normalize_datatype(response["tx_mode_value"])
        response["datatype"] = datatype
        response["datatype_name"] = DATATYPE.get_name(datatype)
        return response

    def write_datatype(
        self,
        datatype: int | str,
    ) -> dict:
        """Write the datatype used in autonomous measurement frames."""
        normalized_datatype = DATATYPE.normalize_datatype(datatype)
        response = self.write_tx_mode(1, normalized_datatype)
        response["datatype"] = normalized_datatype
        response["datatype_name"] = DATATYPE.get_name(normalized_datatype)
        return response

    def configure_datatype(
        self,
        datatype: int | str,
    ) -> dict:
        """Write and read back the autonomous-frame datatype."""
        normalized_datatype = DATATYPE.normalize_datatype(datatype)
        self.write_datatype(normalized_datatype)
        response = self.read_datatype()
        response["requested_datatype"] = normalized_datatype
        response["requested_datatype_name"] = DATATYPE.get_name(normalized_datatype)
        response["datatype_matches_request"] = response["datatype"] == normalized_datatype
        return response

    def read_next_measurement_frame(self) -> dict:
        """Wait for the next measurement frame."""
        return self.device.wait_for_measurement_frame()
