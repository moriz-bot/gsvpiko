"""Apply resolved setup configurations to real GSV devices.

This module turns a validated setup into configured device objects. It does not
perform long-running recording and it does not implement hard synchronization.
Those responsibilities belong to later recording/runtime layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..device.device_channels import SensorDefinition
from ..device.device_connection import (
    BaudrateProbeResult,
    open_gsv_device_from_config,
)
from ..device.device_gsv import GsvDevice, GsvResponseError
from ..transport import transport_nport as NPORT
from . import coordination_sensor_validation as SENSOR_VAL
from .coordination_setup_resolution import ResolvedDevice, ResolvedSetup

BaudrateProbeCallback = Callable[[BaudrateProbeResult], None]

SAFE_CONFIGURATION_SAMPLE_RATE_HZ = 100.0

SOURCE_SETUP = "setup"


class SetupApplicationError(RuntimeError):
    """Raised when a setup cannot be applied to real devices."""


@dataclass
class AppliedSetupDevice:
    """One open GSV device with its setup-derived configuration state."""

    device: GsvDevice
    resolved_device: ResolvedDevice
    configuration_report: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    can_start_transmission: bool = True


@dataclass
class AppliedSetup:
    """Result of applying one resolved setup to open GSV devices."""

    resolved_setup: ResolvedSetup
    devices: list[AppliedSetupDevice]

    @property
    def can_start_transmission(self) -> bool:
        """Return whether all devices may enter autonomous transmission."""
        return all(device.can_start_transmission for device in self.devices)

    @property
    def warnings(self) -> list[dict[str, Any]]:
        """Return all warnings collected while applying the setup."""
        result = []
        for applied_device in self.devices:
            result.extend(applied_device.warnings)
        return result


def open_and_apply_setup(
    *,
    setup_config: dict[str, Any],
    resolved_setup: ResolvedSetup,
    on_probe_result: BaudrateProbeCallback | None = None,
) -> AppliedSetup:
    """Open all setup devices and apply the resolved configuration."""
    applied_devices: list[AppliedSetupDevice] = []

    try:
        prepared_entries = []
        for device_entry, resolved_device in zip(
            setup_config["attached_devices"],
            resolved_setup.devices,
        ):
            device_config = _build_device_config_for_setup(
                device_entry["device"],
                resolved_setup=resolved_setup,
            )
            prepared_entries.append((device_entry, resolved_device, device_config))

        _prepare_nport_settings_for_all_devices(prepared_entries)

        for device_entry, resolved_device, device_config in prepared_entries:
            device = open_gsv_device_from_config(
                device_config,
                on_probe_result=on_probe_result,
            )
            applied_device = AppliedSetupDevice(
                device=device,
                resolved_device=resolved_device,
            )
            applied_devices.append(applied_device)

            _apply_baudrate_mismatch_policy(
                applied_device=applied_device,
                resolved_setup=resolved_setup,
            )
            _attach_setup_sensors(
                device=device,
                device_entry=device_entry,
                resolved_device=resolved_device,
            )
            if applied_device.can_start_transmission:
                _apply_resolved_device_configuration(
                    applied_device=applied_device,
                    resolved_setup=resolved_setup,
                )

    except Exception:
        close_applied_devices(applied_devices)
        raise

    return AppliedSetup(
        resolved_setup=resolved_setup,
        devices=applied_devices,
    )



def _prepare_nport_settings_for_all_devices(
    prepared_entries: list[tuple[dict[str, Any], ResolvedDevice, dict[str, Any]]],
) -> None:
    """Apply requested NPort settings for all setup devices before opening GSV streams.

    Mode changes such as Real COM Mode -> TCP Server Mode restart the NPort.
    Preparing all NPorts first prevents a partial setup state where the first
    device is switched and then the application aborts before the remaining
    NPorts are prepared. The device-opening layer receives the report through
    the private device-config key and does not repeat the management action.
    """
    for _device_entry, _resolved_device, device_config in prepared_entries:
        try:
            report = NPORT.apply_nport_settings_from_device_config(device_config)
        except Exception as error:
            report = NPORT.NportApplyReport(
                requested=bool(device_config.get("default_configure_nport", False)),
                attempted=True,
                ok=False,
                mode=NPORT.desired_nport_mode_for_connection_type(
                    str(device_config.get("default_connection_type", "serial"))
                ),
                ip_address=device_config.get("ip_address"),
                baudrate=device_config.get("default_baudrate"),
                tcp_port=device_config.get("tcp_port"),
                command_port=device_config.get("nport_command_port"),
                error=str(error),
            )
        device_config["_nport_preparation_report"] = report.to_dict()

def close_applied_devices(
    applied_devices: list[AppliedSetupDevice],
) -> None:
    """Stop transmission where possible and close all open setup devices."""
    for applied_device in reversed(applied_devices):
        device = applied_device.device
        try:
            device.acquisition.stop_transmission()
        except Exception:
            pass

        try:
            device.close()
        except Exception:
            pass



def set_zero_all_channels(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Tare all channels on all applied devices before measurement starts."""
    responses = []
    for applied_device in applied_setup.devices:
        response = applied_device.device.zero.set_zero_all_channels()
        responses.append(
            {
                "device_alias": applied_device.resolved_device.alias,
                "device_name": applied_device.device.name,
                "response": response,
            }
        )

    return responses

def start_transmission(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Start autonomous measurement transmission on all applied devices."""
    if not applied_setup.can_start_transmission:
        raise SetupApplicationError(
            "Setup application collected blocking warnings; transmission not started."
        )

    responses = []
    for applied_device in applied_setup.devices:
        response = applied_device.device.acquisition.start_transmission()
        responses.append(
            {
                "device_alias": applied_device.resolved_device.alias,
                "device_name": applied_device.device.name,
                "response": response,
            }
        )

    return responses


def stop_transmission(
    applied_setup: AppliedSetup,
) -> list[dict[str, Any]]:
    """Stop autonomous measurement transmission on all applied devices."""
    responses = []
    for applied_device in applied_setup.devices:
        response = applied_device.device.acquisition.stop_transmission()
        responses.append(
            {
                "device_alias": applied_device.resolved_device.alias,
                "device_name": applied_device.device.name,
                "response": response,
            }
        )

    return responses


def _build_device_config_for_setup(
    device_config: dict[str, Any],
    *,
    resolved_setup: ResolvedSetup,
) -> dict[str, Any]:
    """Return a device config copy with setup-level overrides applied."""
    result = dict(device_config)
    result["default_connection_type"] = resolved_setup.connection_type
    result["default_serial_interface"] = resolved_setup.serial_interface
    result["default_use_nport"] = resolved_setup.use_nport
    result["default_configure_nport"] = resolved_setup.configure_nport
    result["default_baudrate"] = resolved_setup.baudrate
    return result


def _attach_setup_sensors(
    *,
    device: GsvDevice,
    device_entry: dict[str, Any],
    resolved_device: ResolvedDevice,
) -> None:
    """Attach setup sensors to one open GSV device for channel mapping."""
    sensor_channels = _group_channels_by_sensor_alias(resolved_device)

    for sensor_entry in device_entry["attached_sensors"]:
        sensor_alias = sensor_entry["alias"]
        channels = sensor_channels[sensor_alias]
        sensor_index = _get_sensor_index_from_resolved_channels(
            sensor_alias=sensor_alias,
            resolved_device=resolved_device,
        )
        resolved_sensor_config = SENSOR_VAL.resolve_sensor_config(
            sensor_entry["sensor"]
        ).sensor_config
        device.add_sensor(
            sensor=SensorDefinition.from_mapping(resolved_sensor_config),
            channels=channels,
            sensor_index=sensor_index,
            sensor_alias=sensor_alias,
        )


def _apply_baudrate_mismatch_policy(
    *,
    applied_device: AppliedSetupDevice,
    resolved_setup: ResolvedSetup,
) -> None:
    """Collect warning state when the active baudrate differs from setup."""
    report = getattr(applied_device.device, "connection_report", None)
    if report is None:
        return

    if report.baudrate_matches_config is not False:
        return

    should_abort = resolved_setup.baudrate_source == SOURCE_SETUP
    applied_device.warnings.append(
        {
            "warning_key": "BAUDRATE_POWER_CYCLE_REQUIRED",
            "context": {
                "device_alias": applied_device.resolved_device.alias,
                "device_name": applied_device.device.name,
                "configured_baudrate": report.configured_baudrate,
                "active_baudrate": report.active_baudrate,
                "baudrate_source": resolved_setup.baudrate_source,
            },
            "blocking": should_abort,
        }
    )

    if should_abort:
        applied_device.can_start_transmission = False


def _apply_resolved_device_configuration(
    *,
    applied_device: AppliedSetupDevice,
    resolved_setup: ResolvedSetup,
) -> None:
    """Write all setup-derived configuration values to one open device."""
    device = applied_device.device
    report = {
        "safe_sample_rate": None,
        "datatype": None,
        "stream_channels": None,
        "tx_mapping": None,
        "input_modes": [],
        "scaling_factors": [],
        "analog_filter": None,
        "digital_filter": None,
        "sample_rate_range": None,
        "sample_rate": None,
    }

    device.clear_input_buffer()
    device.acquisition.stop_transmission()
    device.clear_input_buffer()

    report["safe_sample_rate"] = device.acquisition.configure_sample_rate(
        SAFE_CONFIGURATION_SAMPLE_RATE_HZ,
        strict=False,
    )
    report["datatype"] = device.acquisition.configure_datatype(
        resolved_setup.datatype
    )

    if applied_device.resolved_device.streamed_channels:
        report["stream_channels"] = list(applied_device.resolved_device.streamed_channels)
        report["tx_mapping"] = device.acquisition.configure_tx_mapping_count(
            len(applied_device.resolved_device.streamed_channels)
        )

    for attachment in device.channels.attachments:
        for channel_index, channel in enumerate(attachment.channels):
            if attachment.sensor.sensor_input_mode is not None:
                report["input_modes"].append(
                    device.input.configure_input_mode(
                        channel=channel,
                        sensor_input_mode=attachment.sensor.sensor_input_mode,
                    )
                )

            scaling_factor = attachment.sensor.scaling_factors[channel_index]
            if scaling_factor is not None:
                report["scaling_factors"].append(
                    device.scaling.configure_scaling_factor(
                        channel=channel,
                        scaling_factor=scaling_factor,
                    )
                )

    if resolved_setup.analog_filter_hz is not None:
        report["analog_filter"] = device.filters.configure_analog_filter(
            resolved_setup.analog_filter_hz
        )

    if resolved_setup.digital_filter is not None:
        raise NotImplementedError("Digital filter configuration is not implemented yet.")

    report["sample_rate_range"] = _read_sample_rate_range(device)
    report["sample_rate"] = _configure_sample_rate_with_readback(
        device=device,
        requested_sample_rate_hz=resolved_setup.sample_rate_hz,
        sample_rate_range=report["sample_rate_range"],
    )
    report["sample_rate"]["sample_rate_source"] = resolved_setup.sample_rate_source

    applied_device.configuration_report = report
    _apply_sample_rate_mismatch_policy(
        applied_device=applied_device,
        resolved_setup=resolved_setup,
    )


def _read_sample_rate_range(
    device: GsvDevice,
) -> dict[str, Any]:
    """Return the currently adjustable sample-rate range reported by the GSV."""
    result: dict[str, Any] = {
        "minimum": None,
        "maximum": None,
        "minimum_sample_rate_hz": None,
        "maximum_sample_rate_hz": None,
        "minimum_read_error": None,
        "maximum_read_error": None,
    }

    try:
        minimum_response = device.acquisition.read_min_sample_rate()
        result["minimum"] = minimum_response
        result["minimum_sample_rate_hz"] = minimum_response["minimum_sample_rate_hz"]
    except Exception as error:
        result["minimum_read_error"] = str(error)

    try:
        maximum_response = device.acquisition.read_max_sample_rate()
        result["maximum"] = maximum_response
        result["maximum_sample_rate_hz"] = maximum_response["maximum_sample_rate_hz"]
    except Exception as error:
        result["maximum_read_error"] = str(error)

    return result


def _configure_sample_rate_with_readback(
    *,
    device: GsvDevice,
    requested_sample_rate_hz: float,
    sample_rate_range: dict[str, Any],
) -> dict[str, Any]:
    """Write an applicable sample rate and return the final readback report.

    If the GSV reports a maximum below the requested setup value, the request is
    not sent because the device already declared that value outside its current
    range. Instead, the reported maximum is written and read back so the user can
    see the effective value for the current frame layout.
    """
    requested = float(requested_sample_rate_hz)
    maximum = _positive_float_or_none(sample_rate_range.get("maximum_sample_rate_hz"))

    if maximum is not None and maximum < requested:
        target = maximum
        response = _write_and_readback_sample_rate(
            device=device,
            written_sample_rate_hz=target,
        )
        active = response.get("active_sample_rate_hz")
        response.update(
            {
                "requested_sample_rate_hz": requested,
                "written_sample_rate_hz": target,
                "maximum_sample_rate_hz": target,
                "sample_rate_range": sample_rate_range,
                "sample_rate_matches_request": False,
                "sample_rate_difference_hz": _calculate_difference(
                    active,
                    requested,
                ),
                "sample_rate_request_above_range": True,
                "warning_key": "SAMPLE_RATE_ABOVE_DEVICE_RANGE",
            }
        )
        return response

    response = _write_and_readback_sample_rate(
        device=device,
        written_sample_rate_hz=requested,
    )
    response["sample_rate_range"] = sample_rate_range
    response["maximum_sample_rate_hz"] = maximum
    return response



def _positive_float_or_none(
    value: Any,
) -> float | None:
    """Return a positive float value, or None if no usable value is available."""
    if value is None:
        return None

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if result <= 0:
        return None

    return result

def _write_and_readback_sample_rate(
    *,
    device: GsvDevice,
    written_sample_rate_hz: float,
) -> dict[str, Any]:
    """Write one sample rate and return the best available readback report."""
    written = float(written_sample_rate_hz)

    try:
        response = device.acquisition.configure_sample_rate(
            written,
            strict=False,
        )
        response["written_sample_rate_hz"] = written
        response["sample_rate_write_accepted"] = True
        response["sample_rate_write_error"] = None
        response["active_sample_rate_hz"] = response.get("sample_rate_hz")
        response["warning_key"] = (
            None
            if response.get("sample_rate_matches_request", True)
            else "SAMPLE_RATE_ADJUSTED_BY_DEVICE"
        )
        return response

    except GsvResponseError as error:
        readback_response = _read_sample_rate_after_failed_write(device)
        active_sample_rate_hz = readback_response.get("sample_rate_hz")

        return {
            "requested_sample_rate_hz": written,
            "written_sample_rate_hz": written,
            "sample_rate_hz": active_sample_rate_hz,
            "active_sample_rate_hz": active_sample_rate_hz,
            "sample_rate_matches_request": False,
            "sample_rate_difference_hz": _calculate_difference(
                active_sample_rate_hz,
                written,
            ),
            "sample_rate_write_accepted": False,
            "sample_rate_write_error": str(error),
            "sample_rate_readback_after_failed_write": readback_response,
            "warning_key": "SAMPLE_RATE_REJECTED_BY_DEVICE",
        }


def _read_sample_rate_after_failed_write(
    device: GsvDevice,
) -> dict[str, Any]:
    """Return the active sample-rate readback after a failed write attempt."""
    try:
        return device.acquisition.read_sample_rate()
    except Exception as error:
        return {
            "sample_rate_hz": None,
            "sample_rate_read_error": str(error),
        }


def _calculate_difference(
    active_value: Any,
    requested_value: Any,
) -> float | None:
    """Return active minus requested sample rate, if both values are numeric."""
    if active_value is None or requested_value is None:
        return None

    try:
        return float(active_value) - float(requested_value)
    except (TypeError, ValueError):
        return None


def _add_sample_rate_warning_text_fields(
    context: dict[str, Any],
) -> None:
    """Add preformatted text fields for sample-rate warning messages."""
    context["requested_sample_rate_hz_text"] = _format_hz_value(
        context.get("requested_sample_rate_hz")
    )
    context["written_sample_rate_hz_text"] = _format_hz_value(
        context.get("written_sample_rate_hz")
    )
    context["active_sample_rate_hz_text"] = _format_hz_value(
        context.get("active_sample_rate_hz", context.get("sample_rate_hz"))
    )
    context["maximum_sample_rate_hz_text"] = _format_hz_value(
        context.get("maximum_sample_rate_hz")
    )
    context["sample_rate_difference_hz_text"] = _format_hz_value(
        context.get("sample_rate_difference_hz")
    )
    context["sample_rate_write_error_text"] = (
        context.get("sample_rate_write_error") or "-"
    )


def _format_hz_value(
    value: Any,
) -> str:
    """Return one sample-rate value for terminal warnings."""
    if value is None:
        return "unknown"

    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _apply_sample_rate_mismatch_policy(
    *,
    applied_device: AppliedSetupDevice,
    resolved_setup: ResolvedSetup,
) -> None:
    """Collect warning state after final sample-rate write/readback."""
    sample_rate_report = applied_device.configuration_report.get("sample_rate")
    if sample_rate_report is None:
        return

    if sample_rate_report.get("sample_rate_matches_request", True):
        return

    source = resolved_setup.sample_rate_source
    should_abort = source == SOURCE_SETUP
    sample_rate_report["sample_rate_mismatch_aborts_measurement"] = should_abort

    warning_context = dict(sample_rate_report)
    warning_context["device_alias"] = applied_device.resolved_device.alias
    warning_context["device_name"] = applied_device.device.name
    warning_context["sample_rate_source"] = source
    _add_sample_rate_warning_text_fields(warning_context)

    applied_device.warnings.append(
        {
            "warning_key": sample_rate_report.get(
                "warning_key",
                "SAMPLE_RATE_ADJUSTED_BY_DEVICE",
            ),
            "context": warning_context,
            "blocking": should_abort,
        }
    )

    if should_abort:
        applied_device.can_start_transmission = False


def _group_channels_by_sensor_alias(
    resolved_device: ResolvedDevice,
) -> dict[str, list[int]]:
    """Return physical channels grouped by sensor alias."""
    result: dict[str, list[int]] = {}
    for channel in resolved_device.channels:
        result.setdefault(channel.sensor_alias, []).append(channel.channel)

    for channels in result.values():
        channels.sort()

    return result


def _get_sensor_index_from_resolved_channels(
    *,
    sensor_alias: str,
    resolved_device: ResolvedDevice,
) -> int:
    """Return the compact numeric sensor index used in output channel names."""
    for channel in resolved_device.channels:
        if channel.sensor_alias != sensor_alias:
            continue

        return _extract_first_integer(channel.column_name)

    raise SetupApplicationError(
        f"No resolved channels found for sensor alias {sensor_alias!r}."
    )


def _extract_first_integer(
    text: str,
) -> int:
    """Return the first integer in a string."""
    import re

    match = re.search(r"(\d+)", text)
    if match is None:
        raise SetupApplicationError(f"No sensor index found in {text!r}.")

    return int(match.group(1))


class _SafeWarningFormatDict(dict):
    """Dictionary that keeps unknown placeholders visible in warning text."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_setup_application_warning(warning: dict[str, Any]) -> str:
    """Return one setup-application warning as plain terminal text."""
    key = warning.get("warning_key")
    context = warning.get("context") or {}
    if key == "BAUDRATE_POWER_CYCLE_REQUIRED":
        return _format_structured_setup_warning(
            title="Baudrate active after power cycle",
            message=(
                "The requested baudrate has been stored, but it is not active yet. "
                "Power-cycle the GSV device so the new baudrate is used."
            ),
            details=(
                "Device: {device_alias}",
                "Requested baudrate: {configured_baudrate}",
                "Active baudrate: {active_baudrate}",
                "Requested value source: {baudrate_source}",
                "The connection was opened with another working baudrate.",
                "GSVpiko can store the requested baudrate for the next power cycle.",
                "Measurement is not started while the setup baudrate is not active.",
            ),
            context=context,
        )
    if key == "SAMPLE_RATE_ABOVE_DEVICE_RANGE":
        return _format_structured_setup_warning(
            title="Sample rate not applicable to this setup",
            message=(
                "The GSV reports a smaller maximum adjustable sample rate for the "
                "currently applied configuration than the setup requested. The requested "
                "setup value is therefore outside the range reported by the GSV. "
                "GSVpiko wrote the reported maximum and read the active value back."
            ),
            details=(
                "Device: {device_alias}",
                "Requested: {requested_sample_rate_hz_text} Hz",
                "> Maximum adjustable sample rate: {maximum_sample_rate_hz_text} Hz",
                "Active sample rate after readback: {active_sample_rate_hz_text} Hz",
                "Requested value source: {sample_rate_source}",
            ),
            context=context,
        )
    if key == "SAMPLE_RATE_ADJUSTED_BY_DEVICE":
        return _format_structured_setup_warning(
            title="Sample rate adjusted",
            message=(
                "The requested sample rate is inside the range reported by the GSV, "
                "but it was not taken over exactly as the active sample rate. "
                "The read-back value is the actually active sample rate."
            ),
            details=(
                "Device: {device_alias}",
                "Requested: {requested_sample_rate_hz_text} Hz",
                "Maximum adjustable sample rate: {maximum_sample_rate_hz_text} Hz",
                "\tActive sample rate: {active_sample_rate_hz_text} Hz",
                "Difference: {sample_rate_difference_hz_text} Hz",
                "Requested value source: {sample_rate_source}",
            ),
            context=context,
        )
    if key == "SAMPLE_RATE_REJECTED_BY_DEVICE":
        return _format_structured_setup_warning(
            title="Sample rate rejected by the GSV",
            message=(
                "The GSV rejected the sample-rate write command. The active value read "
                "back afterwards is the current device state after the failed write, not "
                "an adjusted request value."
            ),
            details=(
                "Device: {device_alias}",
                "Requested: {requested_sample_rate_hz_text} Hz",
                "Written: {written_sample_rate_hz_text} Hz",
                "> Maximum adjustable sample rate: {maximum_sample_rate_hz_text} Hz",
                "Active sample rate after failed write: {active_sample_rate_hz_text} Hz",
                "Requested value source: {sample_rate_source}",
                "Technical GSV error: {sample_rate_write_error_text}",
            ),
            context=context,
        )
    return f"Unknown setup application warning: {key!r}"


def setup_application_warning_action_text(action_key: str) -> str:
    """Return one setup-application warning action line."""
    if action_key == "blocking":
        return (
            "Blocking warning: the setup is not applicable with the requested setting. "
            "Transmission will not be started."
        )
    if action_key == "non_blocking":
        return "Non-blocking warning: measurement continues with the active value."
    if action_key == "measurement_not_started":
        return "Measurement not started because the setup is not fully applicable."
    raise KeyError(f"Unknown setup application warning action {action_key!r}.")


def _format_structured_setup_warning(
    *,
    title: str,
    message: str,
    details: tuple[str, ...],
    context: dict[str, Any],
) -> str:
    """Return a warning block with title, message and detail lines."""
    lines = [title, "-" * len(title), _format_setup_warning_line(message, context), ""]
    for detail in details:
        line = _format_setup_warning_line(detail, context)
        if line.startswith((">", "\t")):
            lines.append(line)
        else:
            lines.append(f"- {line}")
    return "\n".join(lines)


def _format_setup_warning_line(text: str, context: dict[str, Any]) -> str:
    """Format one setup-warning line while preserving unknown placeholders."""
    return text.format_map(_SafeWarningFormatDict(context))
