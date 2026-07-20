"""Resolve reusable setup presets into runtime configuration objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import constants_analog_filters as ANALOG_FILTER
from ..constants import constants_baudrates as BAUDRATE
from ..constants import constants_datatypes as DATATYPE
from ..constants import constants_quantities as QUANTITY
from ..constants import constants_sockets as SOCKET
from . import coordination_sample_rate_limit as SRL
from . import coordination_sensor_validation as SENSOR_VAL
from . import coordination_setup_validation as VAL


DEFAULT_OUTPUT = {
    "directory_csv": "gsvpiko_data",
    "directory_report": "gsvpiko_logs",
    "csv_decimal_separator": ".",
    "csv_delimiter": ",",
    "csv_encoding": "utf-8",
    "timestamp_format": "%Y%m%d_%H%M%S",
    "filename_template": "{timestamp}_{session_name}__{setup_name}_{sample_rate_hz:g}Hz.csv",
    "include_metadata_header": True,
    "time_columns": ["datetime_iso", "timestamp_unix_s", "elapsed_s"],
    "write_report_with_csv": True,
}


@dataclass(frozen=True)
class ResolvedChannel:
    """One resolved output channel in a setup."""

    column_name: str
    device_alias: str
    device_name: str
    gsv_serial_number: int
    sensor_alias: str
    sensor_name: str
    sensor_serial_number: str
    socket: str
    channel: int
    quantity_type: str
    unit_code: int | None
    scaling_factor: float | None
    calibration_matrix: list[list[float]] | None = None
    crosstalk_compensation_matrix: list[list[float]] | None = None


@dataclass(frozen=True)
class ResolvedDevice:
    """One resolved GSV device entry in a setup."""

    alias: str
    device_config: dict[str, Any]
    used_channels: tuple[int, ...]
    streamed_channels: tuple[int, ...]
    channels: tuple[ResolvedChannel, ...]


@dataclass(frozen=True)
class ResolvedSetup:
    """Resolved runtime configuration derived from one setup preset."""

    name: str
    description: str | None
    connection_type: str
    connection_type_source: str
    serial_interface: str
    serial_interface_source: str
    use_nport: bool
    use_nport_source: str
    configure_nport: bool
    configure_nport_source: str
    start_mode: str
    sync_mode: str
    timebase_mode: str
    discard_initial_frames: int
    zero_before_recording: bool
    baudrate: int
    baudrate_source: str
    sample_rate_hz: float
    sample_rate_source: str
    datatype: int
    datatype_source: str
    datatype_name: str
    analog_filter_hz: int | None
    analog_filter_source: str
    digital_filter: dict[str, Any] | None
    crc_enabled: bool
    crc_enabled_source: str
    output: dict[str, Any]
    devices: tuple[ResolvedDevice, ...]
    sample_rate_limit_reports: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "connection_type": self.connection_type,
            "connection_type_source": self.connection_type_source,
            "serial_interface": self.serial_interface,
            "serial_interface_source": self.serial_interface_source,
            "use_nport": self.use_nport,
            "use_nport_source": self.use_nport_source,
            "configure_nport": self.configure_nport,
            "configure_nport_source": self.configure_nport_source,
            "start_mode": self.start_mode,
            "sync_mode": self.sync_mode,
            "timebase_mode": self.timebase_mode,
            "discard_initial_frames": self.discard_initial_frames,
            "zero_before_recording": self.zero_before_recording,
            "baudrate": self.baudrate,
            "baudrate_source": self.baudrate_source,
            "sample_rate_hz": self.sample_rate_hz,
            "sample_rate_source": self.sample_rate_source,
            "datatype": self.datatype,
            "datatype_source": self.datatype_source,
            "datatype_name": self.datatype_name,
            "analog_filter_hz": self.analog_filter_hz,
            "analog_filter_source": self.analog_filter_source,
            "digital_filter": self.digital_filter,
            "crc_enabled": self.crc_enabled,
            "crc_enabled_source": self.crc_enabled_source,
            "output": dict(self.output),
            "devices": [
                {
                    "alias": device.alias,
                    "device_name": device.device_config["name"],
                    "gsv_serial_number": device.device_config["gsv_serial_number"],
                    "used_channels": list(device.used_channels),
                    "streamed_channels": list(device.streamed_channels),
                    "channels": [
                        channel.__dict__
                        for channel in device.channels
                    ],
                }
                for device in self.devices
            ],
            "sample_rate_limit_reports": list(self.sample_rate_limit_reports),
        }


def resolve_setup(
    setup_config: dict[str, Any],
) -> ResolvedSetup:
    """Resolve one setup preset and validate all static constraints."""
    VAL.validate_setup_config_shape(setup_config)

    attached_devices = setup_config["attached_devices"]
    output = _resolve_output(setup_config.get("output", {}))
    connection_type, connection_type_source = _resolve_setup_device_field_with_source(
        setup_config,
        attached_devices,
        setup_key="connection_type",
        device_key="default_connection_type",
        fallback="serial",
    )
    serial_interface, serial_interface_source = _resolve_setup_device_field_with_source(
        setup_config,
        attached_devices,
        setup_key="serial_interface",
        device_key="default_serial_interface",
        fallback="uart",
    )
    use_nport, use_nport_source = _resolve_setup_device_field_with_source(
        setup_config,
        attached_devices,
        setup_key="use_nport",
        device_key="default_use_nport",
        fallback=False,
    )
    configure_nport, configure_nport_source = _resolve_setup_device_field_with_source(
        setup_config,
        attached_devices,
        setup_key="configure_nport",
        device_key="default_configure_nport",
        fallback=False,
    )
    start_mode = str(setup_config.get("start_mode") or "software_parallel")
    sync_mode = str(setup_config.get("sync_mode") or "free_run")
    timebase_mode = str(setup_config.get("timebase_mode") or "receive_time")
    discard_initial_frames = int(setup_config.get("discard_initial_frames") or 0)
    zero_before_recording = bool(setup_config.get("zero_before_recording", True))
    baudrate, baudrate_source = _resolve_baudrate(setup_config, attached_devices)
    sample_rate_hz, sample_rate_source = _resolve_sample_rate(setup_config, attached_devices)
    datatype, datatype_source = _resolve_datatype(setup_config, attached_devices)
    analog_filter_hz, analog_filter_source = _resolve_analog_filter(setup_config, attached_devices)
    digital_filter = _resolve_defaulted_field(
        setup_config,
        attached_devices,
        setup_key="digital_filter",
        sensor_key="default_digital_filter",
        device_key="default_digital_filter",
        fallback=None,
    )
    crc_enabled_value, crc_enabled_source = _resolve_defaulted_field_with_source(
        setup_config,
        attached_devices,
        setup_key="crc_enabled",
        sensor_key="default_crc_enabled",
        device_key="default_crc_enabled",
        fallback=False,
    )
    crc_enabled = bool(crc_enabled_value)

    resolved_devices = []
    sensor_index = 1
    for device_entry in attached_devices:
        resolved_device, sensor_index = _resolve_attached_device(
            device_entry,
            first_sensor_index=sensor_index,
            resolved_connection_type=connection_type,
            resolved_serial_interface=serial_interface,
            resolved_use_nport=bool(use_nport),
            resolved_configure_nport=bool(configure_nport),
        )
        resolved_devices.append(resolved_device)

    _ensure_unique_column_names(resolved_devices)

    sample_rate_reports = tuple(
        SRL.check_sample_rate_limit(
            requested_sample_rate_hz=sample_rate_hz,
            baudrate=baudrate,
            streamed_value_count=len(device.streamed_channels),
            datatype=datatype,
            crc_enabled=crc_enabled,
        )
        for device in resolved_devices
        if device.streamed_channels
    )

    return ResolvedSetup(
        name=str(setup_config["name"]),
        description=setup_config.get("description"),
        connection_type=str(connection_type),
        connection_type_source=connection_type_source,
        serial_interface=str(serial_interface),
        serial_interface_source=serial_interface_source,
        use_nport=bool(use_nport),
        use_nport_source=use_nport_source,
        configure_nport=bool(configure_nport),
        configure_nport_source=configure_nport_source,
        start_mode=start_mode,
        sync_mode=sync_mode,
        timebase_mode=timebase_mode,
        discard_initial_frames=discard_initial_frames,
        zero_before_recording=zero_before_recording,
        baudrate=baudrate,
        baudrate_source=baudrate_source,
        sample_rate_hz=sample_rate_hz,
        sample_rate_source=sample_rate_source,
        datatype=datatype,
        datatype_source=datatype_source,
        datatype_name=DATATYPE.get_name(datatype),
        analog_filter_hz=analog_filter_hz,
        analog_filter_source=analog_filter_source,
        digital_filter=digital_filter,
        crc_enabled=crc_enabled,
        crc_enabled_source=crc_enabled_source,
        output=output,
        devices=tuple(resolved_devices),
        sample_rate_limit_reports=sample_rate_reports,
    )


def build_setup_metadata_lines(
    resolved_setup: ResolvedSetup,
) -> list[str]:
    """Return compact setup metadata lines for terminal or CSV headers."""
    lines = [
        f"setup_name: {resolved_setup.name}",
        "",
        "device_order:",
    ]

    for index, device in enumerate(resolved_setup.devices, start=1):
        lines.append(
            f"  {index}: {device.alias} = {device.device_config['name'].lower()}"
        )

    lines.extend(
        [
            "",
            "channel_mapping:",
        ]
    )
    for device in resolved_setup.devices:
        for channel in device.channels:
            lines.append(
                f"  {channel.column_name} -> "
                f"{channel.sensor_alias} = {channel.sensor_name}, "
                f"{channel.device_alias} = {channel.device_name.lower()}, "
                f"socket={channel.socket}, channel={channel.channel}"
            )

    return lines


def _resolve_output(
    output_config: dict[str, Any],
) -> dict[str, Any]:
    """Return validated output settings with defaults filled in."""
    output = dict(DEFAULT_OUTPUT)
    output.update(output_config)
    return output


def _resolve_baudrate(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
) -> tuple[int, str]:
    """Resolve the setup baudrate and its source."""
    value = setup_config.get("baudrate")
    if value is not None:
        return BAUDRATE.normalize_baudrate(value), "setup"

    values = [
        device_entry["device"].get("default_baudrate")
        for device_entry in attached_devices
        if device_entry["device"].get("default_baudrate") is not None
    ]
    return (
        BAUDRATE.normalize_baudrate(_require_uniform_value(values, "default_baudrate")),
        "device_default",
    )


def _resolve_sample_rate(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
) -> tuple[float, str]:
    """Resolve the setup sample rate and its source."""
    value, source = _resolve_defaulted_field_with_source(
        setup_config,
        attached_devices,
        setup_key="sample_rate_hz",
        sensor_key="default_sample_rate_hz",
        device_key="default_sample_rate_hz",
        fallback=None,
    )
    if value is None:
        raise ValueError("No sample_rate_hz or default_sample_rate_hz is configured.")

    sample_rate_hz = float(value)
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")

    return sample_rate_hz, source


def _resolve_datatype(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
) -> tuple[int, str]:
    """Resolve the autonomous-frame datatype and its source."""
    value, source = _resolve_defaulted_field_with_source(
        setup_config,
        attached_devices,
        setup_key="datatype",
        sensor_key="default_datatype",
        device_key="default_datatype",
        fallback="float32",
    )
    return DATATYPE.normalize_datatype(value), source


def _resolve_analog_filter(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
) -> tuple[int | None, str]:
    """Resolve the analogue filter cutoff frequency and its source."""
    value, source = _resolve_defaulted_field_with_source(
        setup_config,
        attached_devices,
        setup_key="analog_filter_hz",
        sensor_key="default_analog_filter_hz",
        device_key="default_analog_filter_hz",
        fallback=None,
    )
    return ANALOG_FILTER.normalize_analog_filter(value), source


def _resolve_setup_device_field_with_source(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
    *,
    setup_key: str,
    device_key: str,
    fallback: Any,
) -> tuple[Any, str]:
    """Resolve a setup-wide value from setup override or device defaults."""
    if setup_key in setup_config and setup_config[setup_key] is not None:
        return setup_config[setup_key], "setup"

    device_values = [
        device_entry["device"].get(device_key)
        for device_entry in attached_devices
        if device_entry["device"].get(device_key) is not None
    ]
    if device_values:
        return _require_uniform_value(device_values, device_key), "device_default"

    return fallback, "fallback"


def _resolve_defaulted_field(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
    *,
    setup_key: str,
    sensor_key: str,
    device_key: str,
    fallback: Any,
) -> Any:
    """Resolve a value using setup, sensor defaults, then device defaults."""
    value, _source = _resolve_defaulted_field_with_source(
        setup_config,
        attached_devices,
        setup_key=setup_key,
        sensor_key=sensor_key,
        device_key=device_key,
        fallback=fallback,
    )
    return value


def _resolve_defaulted_field_with_source(
    setup_config: dict[str, Any],
    attached_devices: list[dict[str, Any]],
    *,
    setup_key: str,
    sensor_key: str,
    device_key: str,
    fallback: Any,
) -> tuple[Any, str]:
    """Resolve a value and report where it came from."""
    if setup_key in setup_config and setup_config[setup_key] is not None:
        return setup_config[setup_key], "setup"

    sensor_values = []
    for device_entry in attached_devices:
        for sensor_entry in device_entry.get("attached_sensors", []):
            value = sensor_entry["sensor"].get(sensor_key)
            if value is not None:
                sensor_values.append(value)

    if sensor_values:
        return _require_uniform_value(sensor_values, sensor_key), "sensor_default"

    device_values = [
        device_entry["device"].get(device_key)
        for device_entry in attached_devices
        if device_entry["device"].get(device_key) is not None
    ]
    if device_values:
        return _require_uniform_value(device_values, device_key), "device_default"

    return fallback, "fallback"


def _resolve_attached_device(
    device_entry: dict[str, Any],
    *,
    first_sensor_index: int,
    resolved_connection_type: str,
    resolved_serial_interface: str,
    resolved_use_nport: bool,
    resolved_configure_nport: bool,
) -> tuple[ResolvedDevice, int]:
    """Resolve one attached GSV device and its sensor-to-channel mapping."""
    device_config = dict(device_entry["device"])
    device_config["default_connection_type"] = resolved_connection_type
    device_config["default_serial_interface"] = resolved_serial_interface
    device_config["default_use_nport"] = resolved_use_nport
    device_config["default_configure_nport"] = resolved_configure_nport
    device_alias = device_entry["alias"]
    attached_sensors = device_entry.get("attached_sensors", [])

    channels_by_socket = {}
    socket_offsets = {}
    resolved_channels = []
    used_channels = []
    sensor_index = first_sensor_index

    for sensor_entry in attached_sensors:
        sensor_config = sensor_entry["sensor"]
        socket_name = SOCKET.normalize_socket_name(sensor_entry["socket"])
        socket_channels = channels_by_socket.setdefault(
            socket_name,
            SOCKET.get_socket_channels(socket_name),
        )
        channel_count = int(sensor_config["channel_count"])
        offset = socket_offsets.get(socket_name, 0)
        next_offset = offset + channel_count

        if next_offset > len(socket_channels):
            raise ValueError(
                f"Socket {socket_name!r} does not provide enough analogue channels."
            )

        assigned_channels = socket_channels[offset:next_offset]
        socket_offsets[socket_name] = next_offset
        used_channels.extend(assigned_channels)

        resolved_channels.extend(
            _build_resolved_channels(
                device_config=device_config,
                device_alias=device_alias,
                sensor_entry=sensor_entry,
                socket_name=socket_name,
                channels=assigned_channels,
                sensor_index=sensor_index,
            )
        )
        sensor_index += 1

    streamed_channels = tuple(range(1, max(used_channels) + 1)) if used_channels else ()

    return (
        ResolvedDevice(
            alias=device_alias,
            device_config=device_config,
            used_channels=tuple(sorted(used_channels)),
            streamed_channels=streamed_channels,
            channels=tuple(sorted(resolved_channels, key=lambda item: item.channel)),
        ),
        sensor_index,
    )


def _build_resolved_channels(
    *,
    device_config: dict[str, Any],
    device_alias: str,
    sensor_entry: dict[str, Any],
    socket_name: str,
    channels: list[int],
    sensor_index: int,
) -> list[ResolvedChannel]:
    """Build resolved channel entries for one sensor attachment."""
    sensor_config = sensor_entry["sensor"]
    sensor_name = _build_sensor_name(sensor_config)
    entries = []

    resolved_sensor_config = SENSOR_VAL.resolve_sensor_config(sensor_config).sensor_config

    for index, channel in enumerate(channels):
        quantity_type = resolved_sensor_config["quantity_types"][index]
        axis_label = resolved_sensor_config["axis_labels"][index]
        entries.append(
            ResolvedChannel(
                column_name=_build_channel_name(
                    sensor_index=sensor_index,
                    quantity_type=quantity_type,
                    axis_label=axis_label,
                ),
                device_alias=device_alias,
                device_name=device_config["name"],
                gsv_serial_number=int(device_config["gsv_serial_number"]),
                sensor_alias=sensor_entry["alias"],
                sensor_name=sensor_name,
                sensor_serial_number=str(resolved_sensor_config["serial_number"]),
                socket=socket_name,
                channel=int(channel),
                quantity_type=quantity_type,
                unit_code=resolved_sensor_config["unit_codes"][index],
                scaling_factor=resolved_sensor_config["scaling_factors"][index],
                calibration_matrix=resolved_sensor_config.get("calibration_matrix"),
                crosstalk_compensation_matrix=resolved_sensor_config.get("crosstalk_compensation_matrix"),
            )
        )

    return entries


def _build_sensor_name(
    sensor_config: dict[str, Any],
) -> str:
    """Return a compact preset-like sensor name."""
    model = str(sensor_config["model_name"]).lower()
    serial = str(sensor_config["serial_number"])
    return f"sensor_{model}_{serial}"


def _build_channel_name(
    *,
    sensor_index: int,
    quantity_type: str,
    axis_label: str | None,
) -> str:
    """Return one output column name."""
    symbol = QUANTITY.get_symbol(quantity_type)
    if axis_label is None:
        return f"{symbol}{sensor_index}"

    return f"{symbol}{sensor_index}{axis_label}"


def _ensure_unique_column_names(
    resolved_devices: list[ResolvedDevice],
) -> None:
    """Reject duplicate output column names."""
    names = [
        channel.column_name
        for device in resolved_devices
        for channel in device.channels
    ]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate output column names: {duplicates}.")


def _require_uniform_value(
    values: list[Any],
    field_name: str,
) -> Any:
    """Return one value if all non-None values are equal."""
    if not values:
        raise ValueError(f"No value available for {field_name!r}.")

    first_value = values[0]
    for value in values[1:]:
        if value != first_value:
            raise ValueError(f"Conflicting values for {field_name!r}: {values}.")

    return first_value
