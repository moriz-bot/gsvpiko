"""Static setup validation helpers for the GSVpiko coordination layer."""

from __future__ import annotations

from dataclasses import dataclass, field
import string
from typing import Any

from ..constants import constants_baudrates as BAUDRATE
from ..constants import constants_datatypes as DATATYPE
from ..constants import constants_sockets as SOCKET
from . import coordination_sensor_validation as SENSOR_VAL

ALLOWED_TIME_COLUMNS = {
    "timestamp_unix_s",
    "elapsed_s",
    "datetime_iso",
}


class SetupValidationError(ValueError):
    """Raised when a setup is structurally invalid or contradictory."""


@dataclass
class SetupValidationResult:
    """Collected setup-validation messages."""

    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return whether no validation errors were collected."""
        return not self.errors

    def add_error(
        self,
        message: str,
    ) -> None:
        """Add one validation error."""
        self.errors.append(message)

    def raise_if_invalid(self) -> None:
        """Raise a combined validation error if any errors exist."""
        if self.errors:
            raise SetupValidationError("\n".join(self.errors))


def validate_setup_config_shape(
    setup_config: dict[str, Any],
) -> None:
    """Validate top-level setup structure before resolution."""
    result = SetupValidationResult()

    for key in ("name", "attached_devices", "output"):
        if key not in setup_config:
            result.add_error(f"Setup is missing required key {key!r}.")


    attached_devices = setup_config.get("attached_devices", [])
    if not isinstance(attached_devices, list) or not attached_devices:
        result.add_error("attached_devices must be a non-empty list.")
    else:
        _ensure_unique_aliases(
            [entry.get("alias") for entry in attached_devices],
            label="attached device alias",
            result=result,
        )
        for device_entry in attached_devices:
            validate_attached_device_entry(device_entry, result=result)

    try:
        validate_baudrate(setup_config)
    except Exception as error:
        result.add_error(str(error))

    validate_setup_connection_and_sync_fields(setup_config, result=result)

    if "datatype" in setup_config and setup_config["datatype"] is not None:
        try:
            DATATYPE.normalize_datatype(setup_config["datatype"])
        except Exception as error:
            result.add_error(str(error))

    if "sample_rate_hz" in setup_config and setup_config["sample_rate_hz"] is not None:
        try:
            if float(setup_config["sample_rate_hz"]) <= 0:
                result.add_error("sample_rate_hz must be positive.")
        except Exception as error:
            result.add_error(f"sample_rate_hz is invalid: {error}")

    if "output" in setup_config:
        validate_output_config(setup_config["output"], result=result)

    result.raise_if_invalid()


def validate_attached_device_entry(
    device_entry: dict[str, Any],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate one attached-device setup entry."""
    for key in ("device", "alias", "attached_sensors"):
        if key not in device_entry:
            result.add_error(f"attached_device entry is missing {key!r}.")

    device_config = device_entry.get("device")
    if not isinstance(device_config, dict):
        result.add_error("attached_device device must be a device preset dictionary.")
        return

    for key in ("name", "gsv_serial_number", "default_connection_type"):
        if key not in device_config:
            result.add_error(f"Device preset is missing {key!r}.")

    if "default_baudrate" not in device_config:
        result.add_error("Device preset is missing 'default_baudrate'.")

    if "default_configure_nport" in device_config and not isinstance(
        device_config["default_configure_nport"], bool
    ):
        result.add_error("Device preset 'default_configure_nport' must be a bool.")

    connection_type = device_config.get("default_connection_type")
    if connection_type == "serial":
        if not device_config.get("com_port"):
            result.add_error("Serial device preset requires com_port.")
    elif connection_type == "tcp":
        if not device_config.get("ip_address") or not device_config.get("tcp_port"):
            result.add_error("TCP device preset requires ip_address and tcp_port.")
    else:
        result.add_error(f"Unsupported default_connection_type {connection_type!r}.")

    serial_interface = device_config.get("default_serial_interface")
    if serial_interface is not None and serial_interface not in ("uart", "rs422"):
        result.add_error(
            f"Unsupported default_serial_interface {serial_interface!r}."
        )

    attached_sensors = device_entry.get("attached_sensors", [])
    if not isinstance(attached_sensors, list):
        result.add_error("attached_sensors must be a list.")
        return

    _ensure_unique_aliases(
        [entry.get("alias") for entry in attached_sensors],
        label="attached sensor alias",
        result=result,
    )
    for sensor_entry in attached_sensors:
        validate_attached_sensor_entry(sensor_entry, result=result)

    validate_socket_usage(attached_sensors, result=result)


def validate_attached_sensor_entry(
    sensor_entry: dict[str, Any],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate one attached-sensor setup entry."""
    for key in ("sensor", "alias", "socket"):
        if key not in sensor_entry:
            result.add_error(f"attached_sensor entry is missing {key!r}.")

    sensor_config = sensor_entry.get("sensor")
    if not isinstance(sensor_config, dict):
        result.add_error("attached_sensor sensor must be a sensor preset dictionary.")
        return

    validate_sensor_preset(sensor_config, result=result)

    try:
        socket_name = SOCKET.normalize_socket_name(sensor_entry.get("socket"))
        socket_definition = SOCKET.get_socket_definition(socket_name)
    except Exception as error:
        result.add_error(str(error))
        return

    if not socket_definition["implemented"]:
        result.add_error(f"Socket {socket_name!r} is not implemented yet.")

    sensor_type = str(sensor_config.get("sensor_type", "")).lower()
    socket_type = socket_definition["type"]

    if "digital" in sensor_type and socket_type != "digital":
        result.add_error(
            f"Digital sensor {sensor_entry.get('alias')!r} requires a digital socket."
        )

    if "digital" not in sensor_type and socket_type != "analog":
        result.add_error(
            f"Analogue sensor {sensor_entry.get('alias')!r} requires an analogue socket."
        )


def validate_sensor_preset(
    sensor_config: dict[str, Any],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate and resolve fields that every sensor preset must provide."""
    for key in (
        "serial_number",
        "model_name",
        "sensor_type",
        "channel_count",
        "axis_labels",
        "quantity_types",
        "unit_codes",
    ):
        if key not in sensor_config:
            result.add_error(f"Sensor preset is missing {key!r}.")

    if "channel_count" not in sensor_config:
        return

    try:
        channel_count = int(sensor_config["channel_count"])
    except Exception as error:
        result.add_error(f"Sensor channel_count is invalid: {error}")
        return

    if channel_count <= 0:
        result.add_error("Sensor channel_count must be positive.")

    for key in ("axis_labels", "quantity_types", "unit_codes"):
        values = sensor_config.get(key)
        if not isinstance(values, list):
            result.add_error(f"Sensor {key!r} must be a list.")
            continue
        if len(values) != channel_count:
            result.add_error(
                f"Sensor {key!r} length mismatch: "
                f"expected {channel_count}, got {len(values)}."
            )

    sensor_report = SENSOR_VAL.resolve_sensor_config(sensor_config)
    for error in sensor_report.errors:
        result.add_error(error.message)

    if sensor_config.get("default_datatype") is not None:
        try:
            DATATYPE.normalize_datatype(sensor_config["default_datatype"])
        except Exception as error:
            result.add_error(str(error))

def validate_socket_usage(
    attached_sensors: list[dict[str, Any]],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate per-device socket combinations and channel occupancy."""
    normalized_sockets = []
    socket_channel_use = {}

    for sensor_entry in attached_sensors:
        try:
            socket_name = SOCKET.normalize_socket_name(sensor_entry.get("socket"))
        except Exception:
            continue

        normalized_sockets.append(socket_name)
        sensor_config = sensor_entry.get("sensor", {})
        channel_count = int(sensor_config.get("channel_count", 0) or 0)
        socket_channels = SOCKET.get_socket_channels(socket_name)

        if socket_channels:
            used_count = socket_channel_use.get(socket_name, 0) + channel_count
            socket_channel_use[socket_name] = used_count
            if used_count > len(socket_channels):
                result.add_error(
                    f"Attached sensors on socket {socket_name!r} need "
                    f"{used_count} channels, but the socket provides "
                    f"{len(socket_channels)} channels."
                )

    used_socket_set = set(normalized_sockets)
    for socket_name in used_socket_set:
        conflicts = sorted(
            used_socket_set & set(SOCKET.get_exclusive_sockets(socket_name))
        )
        if conflicts:
            result.add_error(
                f"Socket {socket_name!r} cannot be used together with {conflicts}."
            )


def validate_setup_connection_and_sync_fields(
    setup_config: dict[str, Any],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate setup-level connection and synchronization selectors."""
    connection_type = setup_config.get("connection_type")
    if connection_type is not None and connection_type not in ("serial", "tcp"):
        result.add_error(f"Unsupported setup connection_type {connection_type!r}.")

    serial_interface = setup_config.get("serial_interface")
    if serial_interface is not None and serial_interface not in ("uart", "rs422"):
        result.add_error(f"Unsupported setup serial_interface {serial_interface!r}.")

    for key in ("start_mode", "sync_mode", "timebase_mode"):
        value = setup_config.get(key)
        if value is not None and not isinstance(value, str):
            result.add_error(f"Setup {key!r} must be a string or None.")

    discard_initial_frames = setup_config.get("discard_initial_frames")
    if discard_initial_frames is not None:
        try:
            if int(discard_initial_frames) < 0:
                result.add_error("Setup 'discard_initial_frames' must not be negative.")
        except Exception as error:
            result.add_error(f"Setup 'discard_initial_frames' is invalid: {error}")

    zero_before_recording = setup_config.get("zero_before_recording")
    if zero_before_recording is not None and not isinstance(zero_before_recording, bool):
        result.add_error("Setup 'zero_before_recording' must be a bool.")

    use_nport = setup_config.get("use_nport")
    if use_nport is not None and not isinstance(use_nport, bool):
        result.add_error("Setup 'use_nport' must be True, False, or None.")

    configure_nport = setup_config.get("configure_nport")
    if configure_nport is not None and not isinstance(configure_nport, bool):
        result.add_error("Setup 'configure_nport' must be True, False, or None.")


def validate_baudrate(
    setup_config: dict[str, Any],
) -> None:
    """Validate the setup baudrate if it is defined."""
    if setup_config.get("baudrate") is None:
        return

    BAUDRATE.normalize_baudrate(setup_config["baudrate"])


def validate_output_config(
    output_config: dict[str, Any],
    *,
    result: SetupValidationResult,
) -> None:
    """Validate output settings."""
    if not isinstance(output_config, dict):
        result.add_error("output must be a dictionary.")
        return

    decimal_separator = output_config.get("csv_decimal_separator", ".")
    delimiter = output_config.get("csv_delimiter", ",")

    if decimal_separator not in (".", ","):
        result.add_error("csv_decimal_separator must be '.' or ','.")

    if delimiter not in (",", ";", "\t"):
        result.add_error("csv_delimiter must be ',', ';', or tab.")

    if delimiter == decimal_separator:
        result.add_error("csv_delimiter must differ from csv_decimal_separator.")

    for directory_key in ("directory_csv", "directory_report"):
        if directory_key in output_config and not str(output_config[directory_key]).strip():
            result.add_error(f"{directory_key} must not be empty.")

    if "write_report_with_csv" in output_config and not isinstance(output_config["write_report_with_csv"], bool):
        result.add_error("write_report_with_csv must be a bool.")

    time_columns = output_config.get("time_columns", [])
    if not isinstance(time_columns, list) or not time_columns:
        result.add_error("time_columns must be a non-empty list.")

    for time_column in time_columns:
        if time_column not in ALLOWED_TIME_COLUMNS:
            result.add_error(f"Unknown time column {time_column!r}.")

    if "filename_template" in output_config:
        try:
            validate_filename_template(output_config["filename_template"])
        except Exception as error:
            result.add_error(str(error))


def validate_filename_template(
    filename_template: str,
) -> None:
    """Validate placeholders in an output filename template."""
    allowed = {
        "timestamp",
        "setup_name",
        "sample_rate_hz",
        "datatype",
        "session_name",
    }

    formatter = string.Formatter()
    for _, field_name, _, _ in formatter.parse(filename_template):
        if field_name is None:
            continue

        root_name = field_name.split(".")[0].split("[")[0]
        if root_name not in allowed:
            raise SetupValidationError(
                f"Unknown filename_template placeholder {field_name!r}."
            )


def _ensure_unique_aliases(
    aliases: list[str],
    *,
    label: str,
    result: SetupValidationResult,
) -> None:
    """Validate alias uniqueness."""
    cleaned_aliases = [alias for alias in aliases if alias is not None]
    duplicates = sorted(
        {
            alias
            for alias in cleaned_aliases
            if cleaned_aliases.count(alias) > 1
        }
    )

    if duplicates:
        result.add_error(f"Duplicate {label} values: {duplicates}.")


@dataclass(frozen=True)
class SetupValidationStatus:
    """Compact setup validation status for CLI and external responses."""

    setup_validated: bool
    reason: str = "valid"

    @property
    def token(self) -> str:
        """Return a compact machine-readable status token."""
        return "valid" if self.setup_validated else self.reason


def evaluate_setup_validation_status(
    setup_config: dict[str, Any],
) -> SetupValidationStatus:
    """Evaluate static setup validity without opening devices."""
    try:
        from .coordination_setup_resolution import resolve_setup

        resolved = resolve_setup(setup_config)
    except Exception as error:
        return SetupValidationStatus(
            setup_validated=False,
            reason=_validation_reason_from_error(error),
        )

    if not resolved.sample_rate_hz:
        return SetupValidationStatus(setup_validated=False, reason="missing_sample_rate_hz")
    if not resolved.devices:
        return SetupValidationStatus(setup_validated=False, reason="missing_devices")
    if not any(device.streamed_channels for device in resolved.devices):
        return SetupValidationStatus(setup_validated=False, reason="missing_streamed_channels")

    return SetupValidationStatus(setup_validated=True)


def format_setup_validation_token(
    setup_key: str,
    setup_config: dict[str, Any],
) -> str:
    """Return '<SETUP_KEY>:<validation-status>' for external responses."""
    return f"{setup_key}:{evaluate_setup_validation_status(setup_config).token}"


def _validation_reason_from_error(error: Exception) -> str:
    """Map common setup-resolution failures to compact status tokens."""
    text = str(error).lower()
    if "sample_rate_hz" in text:
        return "missing_sample_rate_hz"
    if "datatype" in text:
        return "missing_datatype"
    if "baudrate" in text:
        return "missing_or_invalid_baudrate"
    if "stream" in text or "channel" in text:
        return "invalid_channels"
    if "scaling_factors" in text:
        return "invalid_scaling_factors"
    if "crosstalk_compensation_matrix" in text:
        return "invalid_crosstalk_compensation_matrix"
    if "calibration_matrix" in text:
        return "invalid_calibration_matrix"
    return "invalid_setup"
