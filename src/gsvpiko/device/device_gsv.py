"""Device object for one GSV amplifier."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ..constants import constants_errors as ERROR
from ..protocol.protocol_frame_builder import build_command_frame
from ..protocol.protocol_frame_parser import parse_frame, read_next_serial_frame
from ..features.feature_acquisition import AcquisitionFeature
from ..features.feature_admin import AdminFeature
from ..features.feature_filters import FiltersFeature
from ..features.feature_input import InputFeature
from ..features.feature_interface import InterfaceFeature
from ..features.feature_scaling import ScalingFeature
from ..features.feature_zero import ZeroFeature
from ..transport.transport_base import BaseTransport
from ..utils.utils_hex import to_hex
from .device_channels import DeviceChannelLayout, SensorDefinition


class GsvResponseError(RuntimeError):
    """Raised when the device returns a non-success response status."""


class GsvDevice:
    """High-level object representing one GSV amplifier."""

    def __init__(
        self,
        transport: BaseTransport,
        *,
        name: str = "GSV",
    ) -> None:
        self.transport = transport
        self.name = name
        self.channels = DeviceChannelLayout()
        self._command_exchange: Any | None = None

        self.acquisition = AcquisitionFeature(self)
        self.admin = AdminFeature(self)
        self.filters = FiltersFeature(self)
        self.input = InputFeature(self)
        self.interface = InterfaceFeature(self)
        self.scaling = ScalingFeature(self)
        self.zero = ZeroFeature(self)

    def open(self) -> None:
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def clear_input_buffer(self) -> None:
        self.transport.clear_input_buffer()

    def add_sensor(
        self,
        sensor: SensorDefinition,
        channels: Sequence[int],
        *,
        sensor_index: int,
        sensor_alias: str | None = None,
    ) -> None:
        """Attach one sensor to this device."""
        self.channels.add_sensor(
            sensor=sensor,
            channels=channels,
            sensor_index=sensor_index,
            sensor_alias=sensor_alias,
        )

    def clear_sensors(self) -> None:
        """Remove all attached sensors from this device."""
        self.channels.clear_sensors()

    def list_channels(self) -> list[dict]:
        """Return the current configured channel layout."""
        return self.channels.list_channels()

    def build_command_frame(
        self,
        command: int,
        payload: bytes = b"",
    ) -> bytes:
        return build_command_frame(command, payload)

    def send_command(
        self,
        command: int,
        payload: bytes = b"",
    ) -> bytes:
        frame = self.build_command_frame(command, payload)
        self.transport.write(frame)
        return frame

    def read_next_frame(self) -> dict:
        raw_frame = read_next_serial_frame(self.transport)
        parsed_frame = parse_frame(raw_frame)
        parsed_frame["raw_hex"] = to_hex(raw_frame)
        return parsed_frame

    def read_until_response(
        self,
        on_measurement: Callable[[dict], None] | None = None,
    ) -> dict:
        preceding_measurements = []

        while True:
            parsed_frame = self.read_next_frame()

            if parsed_frame["kind"] == "measurement":
                preceding_measurements.append(parsed_frame)
                if on_measurement is not None:
                    on_measurement(parsed_frame)
                continue

            if parsed_frame["kind"] == "response":
                parsed_frame["preceding_measurements"] = preceding_measurements
                return parsed_frame

    def request(
        self,
        command: int,
        payload: bytes = b"",
        *,
        on_measurement: Callable[[dict], None] | None = None,
    ) -> dict:
        if self._command_exchange is not None:
            return self._command_exchange.request(
                command,
                payload,
                on_measurement=on_measurement,
            )

        request_frame = self.send_command(command, payload)
        response = self.read_until_response(on_measurement=on_measurement)
        response["request_raw_hex"] = to_hex(request_frame)
        return response

    def ensure_ok(
        self,
        response: dict,
    ) -> dict:
        if response["kind"] != "response":
            raise TypeError("Expected a response frame.")

        status = response["status"]
        if status in (ERROR.OK, ERROR.OK_CHANGED):
            return response

        error = ERROR.protocol_error_from_code(status)
        if error is None:
            raise GsvResponseError(
                f"Response status 0x{status:02X}: UNKNOWN_PROTOCOL_ERROR_0x{status:02X}"
            )

        raise GsvResponseError(
            f"Response status 0x{status:02X}: {error.name}: {error.description}"
        )

    def request_ok(
        self,
        command: int,
        payload: bytes = b"",
        *,
        on_measurement: Callable[[dict], None] | None = None,
    ) -> dict:
        response = self.request(
            command,
            payload,
            on_measurement=on_measurement,
        )
        return self.ensure_ok(response)


    def attach_command_exchange(
        self,
        exchange: Any,
    ) -> None:
        """Attach a command exchange that owns response routing for this device."""
        if self._command_exchange is not None and self._command_exchange is not exchange:
            raise RuntimeError("A command exchange is already attached to this device.")
        self._command_exchange = exchange

    def detach_command_exchange(
        self,
        exchange: Any,
    ) -> None:
        """Detach a command exchange if it is still the active exchange."""
        if self._command_exchange is exchange:
            self._command_exchange = None

    @property
    def command_exchange(self) -> Any | None:
        """Return the active command exchange, if any."""
        return self._command_exchange

    def wait_for_measurement_frame(self) -> dict:
        while True:
            parsed_frame = self.read_next_frame()
            if parsed_frame["kind"] == "measurement":
                return parsed_frame

    def apply_attached_sensor_configuration(self) -> dict:
        """Apply settings derived from attached sensor presets."""
        report = {
            "analog_filter": None,
            "sample_rate": None,
            "datatype": None,
            "digital_filter": None,
            "input_modes": [],
            "scaling_factors": [],
            "stream_channels": None,
            "tx_mapping": None,
        }

        if not self.channels.attachments:
            return report

        for attachment in self.channels.attachments:
            for channel_index, channel in enumerate(attachment.channels):
                if attachment.sensor.sensor_input_mode is not None:
                    report["input_modes"].append(
                        self.input.configure_input_mode(
                            channel=channel,
                            sensor_input_mode=attachment.sensor.sensor_input_mode,
                        )
                    )

                scaling_factor = attachment.sensor.scaling_factors[channel_index]
                if scaling_factor is not None:
                    report["scaling_factors"].append(
                        self.scaling.configure_scaling_factor(
                            channel=channel,
                            scaling_factor=scaling_factor,
                        )
                    )

        default_datatype = self._get_uniform_attached_sensor_value("default_datatype")
        if default_datatype is not None:
            report["datatype"] = self.acquisition.configure_datatype(default_datatype)

        default_analog_filter_hz = self._get_uniform_attached_sensor_value(
            "default_analog_filter_hz"
        )
        if default_analog_filter_hz is not None:
            try:
                report["analog_filter"] = self.filters.configure_analog_filter(
                    default_analog_filter_hz
                )
            except Exception as error:
                report["analog_filter"] = {
                    "requested_analog_filter_hz": default_analog_filter_hz,
                    "analog_filter_hz": None,
                    "analog_filter_write_accepted": False,
                    "analog_filter_matches_request": False,
                    "analog_filter_write_error": str(error),
                    "analog_filter_read_error": None,
                }

        default_digital_filter = self._get_uniform_attached_sensor_value(
            "default_digital_filter"
        )
        if default_digital_filter is not None:
            raise NotImplementedError(
                "Digital filter configuration is not implemented yet."
            )

        stream_channels = self.channels.validate_gsv8_stream_configuration()
        if stream_channels:
            report["stream_channels"] = stream_channels
            report["tx_mapping"] = self.acquisition.configure_tx_mapping_count(
                len(stream_channels)
            )

        default_sample_rate_hz = self._get_uniform_attached_sensor_value(
            "default_sample_rate_hz"
        )
        if default_sample_rate_hz is not None:
            report["sample_rate"] = self.acquisition.configure_sample_rate(
                default_sample_rate_hz
            )

        return report

    def _get_uniform_attached_sensor_value(
        self,
        field_name: str,
    ):
        """Return one shared non-None sensor value across all attachments."""
        values = [
            getattr(attachment.sensor, field_name)
            for attachment in self.channels.attachments
            if getattr(attachment.sensor, field_name) is not None
        ]

        if not values:
            return None

        first_value = values[0]
        for value in values[1:]:
            if value != first_value:
                raise ValueError(
                    f"Conflicting attached sensor values for {field_name!r}."
                )

        return first_value
