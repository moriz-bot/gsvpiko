"""Open GSV devices from device configuration presets."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic, sleep
from typing import Any, Callable

from ..constants import constants_baudrates as BAUDRATE
from ..transport import transport_nport as NPORT
from ..transport.transport_factory import (
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    TransportFactoryError,
    create_transport_from_device_config,
    normalize_connection_type,
)
from .device_gsv import GsvDevice
from .device_connection_report import (
    BaudrateProbeResult,
    DeviceConnectionReport,
    build_connection_report,
    format_connection_failure,
    mark_nport_data_path_verified,
)

BaudrateProbeCallback = Callable[["BaudrateProbeResult"], None]

TCP_GSV_VERIFY_RETRY_TIMEOUT_S = 8.0
TCP_GSV_VERIFY_RETRY_INTERVAL_S = 0.5
DEVICE_CONNECTION_TRANSPORT_TIMEOUT_S = 1.0


class DeviceConnectionError(RuntimeError):
    """Raised when a configured GSV device cannot be opened or verified."""


def _apply_nport_settings_before_open(
    device_config: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply optional NPort management settings before opening the GSV stream.

    Setup-level code may prepare all NPorts before opening any GSV stream. In
    that case the per-device opening layer reuses the stored report and does
    not repeat the NPort web-console action.
    """
    prepared_report = device_config.get("_nport_preparation_report")
    if prepared_report is not None:
        return dict(prepared_report)

    try:
        report = NPORT.apply_nport_settings_from_device_config(device_config)
    except Exception as error:
        report = NPORT.NportApplyReport(
            requested=bool(device_config.get("default_configure_nport", False)),
            attempted=True,
            ok=False,
            mode=NPORT.desired_nport_mode_for_connection_type(
                str(device_config.get("default_connection_type", CONNECTION_TYPE_SERIAL))
            ),
            ip_address=device_config.get("ip_address"),
            baudrate=device_config.get("default_baudrate"),
            tcp_port=device_config.get("tcp_port"),
            command_port=device_config.get("nport_command_port"),
            error=str(error),
        )
    return report.to_dict()


def get_configured_baudrate(
    device_config: dict[str, Any],
) -> int:
    """Return the configured target baudrate from a device preset."""
    if device_config.get("default_baudrate") is None:
        raise DeviceConnectionError(
            f"Device preset {device_config.get('name', '<unnamed>')!r} "
            "does not define default_baudrate."
        )

    return BAUDRATE.normalize_baudrate(device_config["default_baudrate"])


def open_gsv_device_from_config(
    device_config: dict[str, Any],
    *,
    timeout_s: float | None = None,
    verify_gsv_response: bool = True,
    auto_probe_baudrate: bool = True,
    on_probe_result: BaudrateProbeCallback | None = None,
) -> GsvDevice:
    """Open one configured GSV device and verify the GSV response if requested."""
    connection_type = normalize_connection_type(
        device_config.get("default_connection_type", CONNECTION_TYPE_SERIAL)
    )
    timeout = DEVICE_CONNECTION_TRANSPORT_TIMEOUT_S if timeout_s is None else float(timeout_s)
    configured_baudrate = get_configured_baudrate(device_config)
    probe_order = (
        BAUDRATE.build_probe_order(configured_baudrate)
        if auto_probe_baudrate
        else (configured_baudrate,)
    )

    initial_nport_report = _prepare_initial_nport_settings(
        device_config=device_config,
        connection_type=connection_type,
    )

    return _open_gsv_device_with_baudrate_probe(
        device_config=device_config,
        connection_type=connection_type,
        timeout_s=timeout,
        configured_baudrate=configured_baudrate,
        probe_order=probe_order,
        initial_nport_report=initial_nport_report,
        verify_gsv_response=verify_gsv_response,
        on_probe_result=on_probe_result,
    )


def _prepare_initial_nport_settings(
    *,
    device_config: dict[str, Any],
    connection_type: str,
) -> dict[str, Any] | None:
    """Prepare NPort once before the probe when the transport path allows it.

    Real COM mode opens the Windows COM port with each candidate baudrate; the
    NPort mode only has to be prepared for the requested setup state. TCP
    Server Mode is different: the NPort serial-side baudrate must follow each
    probe candidate and is therefore prepared inside the probe loop.
    """
    if connection_type == CONNECTION_TYPE_TCP:
        return None
    return _apply_nport_settings_before_open(device_config)


def _open_gsv_device_with_baudrate_probe(
    *,
    device_config: dict[str, Any],
    connection_type: str,
    timeout_s: float,
    configured_baudrate: int,
    probe_order: tuple[int, ...],
    initial_nport_report: dict[str, Any] | None,
    verify_gsv_response: bool,
    on_probe_result: BaudrateProbeCallback | None,
) -> GsvDevice:
    """Run the shared GSV communication baudrate probe for any transport."""
    probe_results: list[BaudrateProbeResult] = []
    last_nport_report: dict[str, Any] | None = initial_nport_report

    for baudrate in probe_order:
        nport_report = _prepare_nport_settings_for_probe_candidate(
            device_config=device_config,
            connection_type=connection_type,
            baudrate=baudrate,
            initial_nport_report=initial_nport_report,
        )
        last_nport_report = nport_report

        fatal_transport_error = _fatal_transport_preparation_error(nport_report)
        if fatal_transport_error is not None:
            _append_and_emit_probe_result(
                probe_results,
                BaudrateProbeResult(
                    baudrate=baudrate,
                    port_opened=False,
                    gsv_responded=False,
                    error=fatal_transport_error,
                ),
                on_probe_result,
            )
            raise DeviceConnectionError(
                format_connection_failure(
                    device_config=device_config,
                    configured_baudrate=configured_baudrate,
                    probe_results=probe_results,
                    nport_report=nport_report,
                )
            )

        try:
            device = _create_gsv_device_from_config(
                device_config,
                baudrate=baudrate,
                timeout_s=timeout_s,
            )
        except TransportFactoryError as error:
            _append_and_emit_probe_result(
                probe_results,
                BaudrateProbeResult(
                    baudrate=baudrate,
                    port_opened=False,
                    gsv_responded=False,
                    error=str(error),
                ),
                on_probe_result,
            )
            raise DeviceConnectionError(
                format_connection_failure(
                    device_config=device_config,
                    configured_baudrate=configured_baudrate,
                    probe_results=probe_results,
                    nport_report=nport_report,
                )
            ) from error

        try:
            device.open()
        except Exception as error:
            _append_and_emit_probe_result(
                probe_results,
                BaudrateProbeResult(
                    baudrate=baudrate,
                    port_opened=False,
                    gsv_responded=False,
                    error=str(error),
                ),
                on_probe_result,
            )
            raise DeviceConnectionError(
                format_connection_failure(
                    device_config=device_config,
                    configured_baudrate=configured_baudrate,
                    probe_results=probe_results,
                    nport_report=nport_report,
                )
            ) from error

        if not verify_gsv_response:
            device.connection_report = build_connection_report(
                device_config=device_config,
                connection_type=connection_type,
                configured_baudrate=configured_baudrate,
                active_baudrate=baudrate,
                probe_results=probe_results,
                nport_report=_mark_verified_nport_report(
                    nport_report,
                    connection_type=connection_type,
                ),
            )
            return device

        try:
            response = _verify_open_gsv_device_with_optional_retry(
                device=device,
                nport_report=nport_report,
            )
        except Exception as error:
            _append_and_emit_probe_result(
                probe_results,
                BaudrateProbeResult(
                    baudrate=baudrate,
                    port_opened=True,
                    gsv_responded=False,
                    error=str(error),
                ),
                on_probe_result,
            )
            device.close()
            continue

        _append_and_emit_probe_result(
            probe_results,
            BaudrateProbeResult(
                baudrate=baudrate,
                port_opened=True,
                gsv_responded=True,
                response_raw_hex=response.get("raw_hex", ""),
            ),
            on_probe_result,
        )
        device.connection_report = build_connection_report(
            device_config=device_config,
            connection_type=connection_type,
            configured_baudrate=configured_baudrate,
            active_baudrate=baudrate,
            probe_results=probe_results,
            nport_report=_mark_verified_nport_report(
                nport_report,
                connection_type=connection_type,
            ),
        )
        _store_configured_baudrate_if_needed(device)
        if not device.connection_report.baudrate_matches_config:
            nport_report = _apply_nport_settings_for_baudrate(
                device_config,
                baudrate=configured_baudrate,
                allow_prepared_report=False,
            )
            device.connection_report = replace(
                device.connection_report,
                nport_report=nport_report,
            )
        return device

    raise DeviceConnectionError(
        format_connection_failure(
            device_config=device_config,
            configured_baudrate=configured_baudrate,
            probe_results=probe_results,
            nport_report=last_nport_report,
        )
    )


def _prepare_nport_settings_for_probe_candidate(
    *,
    device_config: dict[str, Any],
    connection_type: str,
    baudrate: int,
    initial_nport_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prepare optional NPort settings for one baudrate candidate."""
    if connection_type != CONNECTION_TYPE_TCP:
        return initial_nport_report
    return _apply_nport_settings_for_baudrate(
        device_config,
        baudrate=baudrate,
        allow_prepared_report=True,
    )


def _fatal_transport_preparation_error(
    nport_report: dict[str, Any] | None,
) -> str | None:
    """Return a fatal preparation error when no usable transport path exists.

    A GSV baudrate probe is only meaningful when the byte transport path itself
    is usable. If the NPort management/data-path preparation already failed,
    trying more baudrates would only hide the real problem and can leave the
    NPort on the last candidate baudrate.
    """
    if nport_report is None:
        return None
    if not nport_report.get("requested") or not nport_report.get("attempted"):
        return None
    if nport_report.get("ok") is not False:
        return None

    error = nport_report.get("error") or nport_report.get("message") or "unknown error"
    return f"NPort management/data path not reachable: {error}"


def _apply_nport_settings_for_baudrate(
    device_config: dict[str, Any],
    *,
    baudrate: int,
    allow_prepared_report: bool,
) -> dict[str, Any] | None:
    """Apply NPort target settings for one candidate or requested baudrate."""
    prepared_report = device_config.get("_nport_preparation_report")
    if (
        allow_prepared_report
        and prepared_report is not None
        and prepared_report.get("baudrate") == baudrate
    ):
        return dict(prepared_report)

    candidate_config = dict(device_config)
    candidate_config["default_baudrate"] = baudrate
    candidate_config.pop("_nport_preparation_report", None)
    return _apply_nport_settings_before_open(candidate_config)


def _create_gsv_device_from_config(
    device_config: dict[str, Any],
    *,
    baudrate: int,
    timeout_s: float,
) -> GsvDevice:
    """Create one unopened GSV device from the configured transport factory."""
    transport = create_transport_from_device_config(
        device_config,
        baudrate=baudrate,
        timeout_s=timeout_s,
    )
    return GsvDevice(
        transport,
        name=device_config["name"],
    )


def _mark_verified_nport_report(
    nport_report: dict[str, Any] | None,
    *,
    connection_type: str,
) -> dict[str, Any] | None:
    """Return an NPort report marked as verified through the data path."""
    return mark_nport_data_path_verified(
        nport_report,
        mode=NPORT.desired_nport_mode_for_connection_type(connection_type),
        message=_verified_nport_message(connection_type),
    )


def _verified_nport_message(connection_type: str) -> str:
    """Return the connection-report message for a verified NPort data path."""
    if connection_type == CONNECTION_TYPE_TCP:
        return "TCP data path was verified through the configured TCP port."
    return (
        "RealCOM data path was verified through the configured COM port; "
        "NPort mode change was not required for this run."
    )


def _append_and_emit_probe_result(
    probe_results: list[BaudrateProbeResult],
    result: BaudrateProbeResult,
    on_probe_result: BaudrateProbeCallback | None,
) -> None:
    """Store one probe result and optionally emit it to a caller callback."""
    probe_results.append(result)

    if on_probe_result is not None:
        on_probe_result(result)


def _store_configured_baudrate_if_needed(
    device: GsvDevice,
) -> None:
    """Store the configured baudrate when it differs from the active baudrate."""
    report = device.connection_report

    if report.baudrate_matches_config:
        return

    baudrate_setting_report = None
    baudrate_setting_error = None

    try:
        baudrate_setting_report = (
            device.interface.store_serial_baudrate_for_next_power_cycle(
                report.configured_baudrate
            )
        )
    except Exception as error:
        baudrate_setting_error = str(error)

    if baudrate_setting_report is None:
        device.connection_report = replace(
            report,
            baudrate_setting_error=baudrate_setting_error,
        )
        return

    device.connection_report = replace(
        report,
        baudrate_setting_index=baudrate_setting_report["baudrate_setting_index"],
        stored_baudrate_before=baudrate_setting_report["stored_baudrate_before"],
        stored_baudrate_after=baudrate_setting_report["stored_baudrate_after"],
        baudrate_setting_matches_config=baudrate_setting_report[
            "stored_baudrate_matches_request"
        ],
        baudrate_setting_write_executed=baudrate_setting_report["write_executed"],
        baudrate_setting_error=baudrate_setting_error,
        baudrate_change_requires_power_cycle=baudrate_setting_report[
            "power_cycle_required"
        ],
    )


def _verify_open_gsv_device_with_optional_retry(
    *,
    device: GsvDevice,
    nport_report: dict[str, Any] | None,
) -> dict:
    """Verify an open GSV byte stream with retry after NPort changes."""
    should_retry = bool(nport_report and nport_report.get("attempted"))
    deadline = (
        monotonic() + TCP_GSV_VERIFY_RETRY_TIMEOUT_S
        if should_retry
        else monotonic()
    )
    last_error: Exception | None = None

    while True:
        try:
            return _verify_open_gsv_device(device)
        except Exception as error:
            last_error = error
            if not should_retry or monotonic() >= deadline:
                raise
            try:
                device.close()
            except Exception:
                pass
            sleep(TCP_GSV_VERIFY_RETRY_INTERVAL_S)
            device.open()

    if last_error is not None:
        raise last_error
    raise DeviceConnectionError("Could not verify GSV connection.")


def _verify_open_gsv_device(
    device: GsvDevice,
) -> dict:
    """Verify that an open byte stream talks to a GSV device."""
    device.clear_input_buffer()
    response = device.acquisition.stop_transmission()
    device.clear_input_buffer()
    return response
