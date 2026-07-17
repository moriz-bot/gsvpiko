"""Sensor attachment and channel layout helpers for one GSV device.

This module is limited to analogue GSV input channels. It connects sensor
definitions to physical amplifier channels and maps streamed measurement values
back to configured channel names.

The GSV-8 TX mapping command is used only for setting the number of leading
streamed channels. For example, a sensor on channels 4 and 5 is supported by
streaming channels 1..5 and exposing only channels 4..5 to the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any, Sequence

from ..constants import constants_analog_filters as ANALOG_FILTER
from ..constants import constants_datatypes as DATATYPE
from ..constants import constants_quantities as QUANTITY
from ..constants import constants_sensor_input_modes as SENSOR_INPUT_MODE


@dataclass
class SensorDefinition:
    """Normalized sensor metadata used by GSVpiko."""

    serial_number: str
    model_name: str
    sensor_type: str

    channel_count: int
    axis_labels: Sequence[str | None]
    quantity_types: Sequence[str]
    unit_codes: Sequence[int | None]
    scaling_factors: Sequence[float | None]
    calibration_reference: str | None = None
    calibration_date: str | None = None
    calibration_matrix: Sequence[Sequence[float]] | None = None
    crosstalk_compensation_matrix: Sequence[Sequence[float]] | None = None
    physical_full_scale: float | None = None
    rated_outputs_mv_per_v: Sequence[float | None] | None = None

    bridge_resistance_ohm: float | None = None
    sensor_input_mode: int | None = None
    sensor_input_sensitivity_mv_per_v: float | None = None

    default_analog_filter_hz: int | None = None
    default_digital_filter: dict[str, Any] | None = None
    default_sample_rate_hz: float | None = None
    default_datatype: int | None = None

    def __post_init__(self) -> None:
        """Validate per-channel fields immediately after object creation."""
        if self.channel_count <= 0:
            raise ValueError("channel_count must be positive.")

        expected_length = self.channel_count
        fields_to_check = {
            "axis_labels": self.axis_labels,
            "quantity_types": self.quantity_types,
            "unit_codes": self.unit_codes,
            "scaling_factors": self.scaling_factors,
        }

        for field_name, values in fields_to_check.items():
            if len(values) != expected_length:
                raise ValueError(
                    f"{field_name} length mismatch: "
                    f"expected {expected_length}, got {len(values)}."
                )

        if self.rated_outputs_mv_per_v is not None:
            if len(self.rated_outputs_mv_per_v) != expected_length:
                raise ValueError(
                    "rated_outputs_mv_per_v length mismatch: "
                    f"expected {expected_length}, got {len(self.rated_outputs_mv_per_v)}."
                )

        self._validate_square_matrix(
            self.calibration_matrix,
            matrix_name="calibration_matrix",
            expected_size=expected_length,
        )
        self._validate_square_matrix(
            self.crosstalk_compensation_matrix,
            matrix_name="crosstalk_compensation_matrix",
            expected_size=expected_length,
        )


    @staticmethod
    def _validate_square_matrix(
        matrix: Sequence[Sequence[float]] | None,
        *,
        matrix_name: str,
        expected_size: int,
    ) -> None:
        """Validate one optional square matrix shape."""
        if matrix is None:
            return

        if len(matrix) != expected_size:
            raise ValueError(
                f"{matrix_name} row count mismatch: "
                f"expected {expected_size}, got {len(matrix)}."
            )

        for row_index, row in enumerate(matrix):
            if len(row) != expected_size:
                raise ValueError(
                    f"{matrix_name}[{row_index}] length mismatch: "
                    f"expected {expected_size}, got {len(row)}."
                )

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any],
    ) -> "SensorDefinition":
        """Build a SensorDefinition from one config mapping."""
        sensor_input_mode = SENSOR_INPUT_MODE.normalize_sensor_input_mode(
            data.get("sensor_input_mode")
        )
        sensor_input_sensitivity_mv_per_v = cls._resolve_sensor_input_sensitivity(
            sensor_input_mode=sensor_input_mode,
            sensor_input_sensitivity_mv_per_v=data.get(
                "sensor_input_sensitivity_mv_per_v"
            ),
        )
        default_datatype = (
            None
            if data.get("default_datatype") is None
            else DATATYPE.normalize_datatype(data.get("default_datatype"))
        )

        return cls(
            serial_number=data["serial_number"],
            model_name=data["model_name"],
            sensor_type=data["sensor_type"],
            channel_count=data["channel_count"],
            axis_labels=list(data["axis_labels"]),
            quantity_types=list(data["quantity_types"]),
            unit_codes=list(data["unit_codes"]),
            scaling_factors=list(data["scaling_factors"]),
            calibration_reference=data.get("calibration_reference"),
            calibration_date=data.get("calibration_date"),
            calibration_matrix=data.get("calibration_matrix"),
            crosstalk_compensation_matrix=data.get("crosstalk_compensation_matrix"),
            physical_full_scale=data.get("physical_full_scale"),
            rated_outputs_mv_per_v=(
                list(data["rated_outputs_mv_per_v"])
                if data.get("rated_outputs_mv_per_v") is not None
                else None
            ),
            bridge_resistance_ohm=data.get("bridge_resistance_ohm"),
            sensor_input_mode=sensor_input_mode,
            sensor_input_sensitivity_mv_per_v=sensor_input_sensitivity_mv_per_v,
            default_analog_filter_hz=ANALOG_FILTER.normalize_analog_filter(
                data.get("default_analog_filter_hz")
            ),
            default_digital_filter=data.get("default_digital_filter"),
            default_sample_rate_hz=data.get("default_sample_rate_hz"),
            default_datatype=default_datatype,
        )

    @staticmethod
    def _resolve_sensor_input_sensitivity(
        *,
        sensor_input_mode: int | None,
        sensor_input_sensitivity_mv_per_v: float | None,
    ) -> float | None:
        """Resolve or validate the sensitivity that belongs to one input mode."""
        implied_sensitivity = SENSOR_INPUT_MODE.get_input_sensitivity_mv_per_v(sensor_input_mode)

        if sensor_input_sensitivity_mv_per_v is None:
            return implied_sensitivity

        if implied_sensitivity is None:
            return float(sensor_input_sensitivity_mv_per_v)

        if not isclose(
            float(sensor_input_sensitivity_mv_per_v),
            float(implied_sensitivity),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "sensor_input_mode and sensor_input_sensitivity_mv_per_v do not match."
            )

        return float(sensor_input_sensitivity_mv_per_v)


@dataclass(frozen=True)
class SensorAttachment:
    """One sensor attached to one device on specific analogue input channels."""

    sensor: SensorDefinition
    channels: tuple[int, ...]
    sensor_index: int
    channel_names: tuple[str, ...]
    sensor_alias: str | None = None


@dataclass
class DeviceChannelLayout:
    """Channel layout manager for one GSV device."""

    attachments: list[SensorAttachment] = field(default_factory=list)

    def add_sensor(
        self,
        sensor: SensorDefinition,
        channels: Sequence[int],
        sensor_index: int,
        *,
        sensor_alias: str | None = None,
    ) -> SensorAttachment:
        """Attach one sensor to specific physical input channels."""
        channels_tuple = tuple(channels)

        if len(channels_tuple) != sensor.channel_count:
            raise ValueError(
                f"Channel count mismatch: "
                f"sensor expects {sensor.channel_count}, got {len(channels_tuple)}."
            )

        if sensor_index <= 0:
            raise ValueError("sensor_index must be positive.")

        if len(set(channels_tuple)) != len(channels_tuple):
            raise ValueError("Channel numbers must be unique within one attachment.")

        self._ensure_channels_are_free(channels_tuple)

        channel_names = tuple(
            self._build_channel_name(
                quantity_type=sensor.quantity_types[index],
                sensor_index=sensor_index,
                axis_label=sensor.axis_labels[index],
            )
            for index in range(sensor.channel_count)
        )

        attachment = SensorAttachment(
            sensor=sensor,
            channels=channels_tuple,
            sensor_index=sensor_index,
            channel_names=channel_names,
            sensor_alias=sensor_alias,
        )
        self.attachments.append(attachment)
        return attachment

    def clear_sensors(self) -> None:
        """Remove all sensor attachments from the channel layout."""
        self.attachments.clear()

    def get_used_channels(self) -> list[int]:
        """Return all physical analogue channels used by the layout."""
        return sorted(
            {
                channel
                for attachment in self.attachments
                for channel in attachment.channels
            }
        )

    def get_stream_channel_count(self) -> int:
        """Return the number of leading analogue channels that must be streamed."""
        used_channels = self.get_used_channels()
        if not used_channels:
            return 0

        return max(used_channels)

    def get_streamed_channels(self) -> list[int]:
        """Return the physical analogue channels expected in the streamed frame."""
        return list(range(1, self.get_stream_channel_count() + 1))

    def validate_gsv8_stream_configuration(self) -> list[int]:
        """Validate that this layout can be represented by leading-channel TX mapping."""
        used_channels = self.get_used_channels()

        if not used_channels:
            return []

        highest_channel = max(used_channels)
        if highest_channel > 8:
            raise ValueError("GSV-8 analogue sensor channels are limited to 1..8.")

        return self.get_streamed_channels()

    def list_channels(self) -> list[dict]:
        """Return one entry per configured physical analogue input channel."""
        entries = []

        for attachment in self.attachments:
            for index, channel in enumerate(attachment.channels):
                entries.append(
                    {
                        "channel": channel,
                        "channel_name": attachment.channel_names[index],
                        "sensor_index": attachment.sensor_index,
                        "sensor_alias": attachment.sensor_alias,
                        "sensor_serial_number": attachment.sensor.serial_number,
                        "sensor_model_name": attachment.sensor.model_name,
                        "sensor_type": attachment.sensor.sensor_type,
                        "sensor_axis": attachment.sensor.axis_labels[index],
                        "quantity_type": attachment.sensor.quantity_types[index],
                        "unit_code": attachment.sensor.unit_codes[index],
                        "scaling_factor": attachment.sensor.scaling_factors[index],
                    }
                )

        return sorted(entries, key=lambda entry: entry["channel"])

    def build_channel_map(
        self,
        values: Sequence[int | float],
    ) -> dict[str, int | float]:
        """Map streamed values to configured channel names.

        The input sequence is interpreted as leading physical analogue channels
        1..N. Only channels configured by sensor attachments are returned.
        """
        if not self.attachments:
            return {
                f"CH{index + 1}": values[index]
                for index in range(len(values))
            }

        stream_channel_count = self.get_stream_channel_count()
        if len(values) != stream_channel_count:
            raise ValueError(
                f"Value count mismatch: expected {stream_channel_count}, got {len(values)}."
            )

        channel_map = {}
        for attachment in self.attachments:
            attachment_values = [
                values[channel - 1]
                for channel in attachment.channels
            ]
            mapped_values = _apply_crosstalk_compensation(
                attachment.sensor.crosstalk_compensation_matrix,
                attachment_values,
            )
            for index, value in enumerate(mapped_values):
                channel_map[attachment.channel_names[index]] = value

        return channel_map

    def _ensure_channels_are_free(
        self,
        new_channels: Sequence[int],
    ) -> None:
        """Reject overlapping physical channel assignments."""
        used_channels = {
            channel
            for attachment in self.attachments
            for channel in attachment.channels
        }

        overlaps = sorted(set(new_channels) & used_channels)
        if overlaps:
            raise ValueError(f"Channels already in use: {overlaps}")

    def _build_channel_name(
        self,
        *,
        quantity_type: str,
        sensor_index: int,
        axis_label: str | None,
    ) -> str:
        """Generate one final channel name."""
        symbol = QUANTITY.get_symbol(quantity_type)

        if axis_label is None:
            return f"{symbol}{sensor_index}"

        axis_text = str(axis_label).strip()
        return f"{symbol}{sensor_index}{axis_text}"


def _apply_crosstalk_compensation(
    matrix: Sequence[Sequence[float]] | None,
    values: Sequence[int | float],
) -> list[int | float]:
    """Apply one optional sensor-local compensation matrix to mapped channels."""
    if matrix is None:
        return list(values)

    if len(matrix) != len(values):
        raise ValueError(
            "crosstalk_compensation_matrix size does not match sensor channel count."
        )

    corrected_values: list[float] = []
    for row_index, row in enumerate(matrix):
        if len(row) != len(values):
            raise ValueError(
                "crosstalk_compensation_matrix row size does not match sensor channel count "
                f"at row {row_index}."
            )
        corrected_values.append(
            sum(float(factor) * float(value) for factor, value in zip(row, values))
        )

    return corrected_values
