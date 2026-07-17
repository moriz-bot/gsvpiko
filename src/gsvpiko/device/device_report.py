"""Terminal formatting for GSV device reports."""

from __future__ import annotations

from ..device.device_connection import BaudrateProbeResult
from ..device.device_gsv import GsvDevice
from ..transport import transport_nport as NPORT


def print_baudrate_probe_result(
    result: BaudrateProbeResult,
) -> None:
    """Print one baudrate probe result."""
    print(
        f"{result.baudrate:>6} baud | "
        f"port_opened={result.port_opened!s:<5} | "
        f"gsv_responded={result.gsv_responded!s:<5} | "
        f"response={result.response_raw_hex or '<none>'}",
        flush=True,
    )

    if result.error:
        print(f"    {result.error}", flush=True)


def print_connection_report(
    device: GsvDevice,
) -> None:
    """Print the transport and baudrate state used to open one GSV device."""
    report = getattr(device, "connection_report", None)
    print_connection_report_data(report)


def print_connection_report_data(
    report,
) -> None:
    """Print one stored connection report object."""
    if report is None:
        return

    print("Connection")
    print("----------")
    print(f"device_name: {report.device_name}")
    print(f"connection_type: {report.connection_type}")

    if report.com_port is not None:
        print(f"com_port: {report.com_port}")

    if report.configured_baudrate is not None:
        print(
            "baudrate: "
            f"configured={report.configured_baudrate}, "
            f"active={report.active_baudrate}, "
            f"matches={report.baudrate_matches_config}"
        )

    if report.ip_address is not None:
        print(f"ip_address: {report.ip_address}")

    if report.tcp_port is not None:
        print(f"tcp_port: {report.tcp_port}")

    nport_report = getattr(report, "nport_report", None)
    if nport_report is not None:
        _print_nport_report(nport_report)

    if report.used_baudrate_probe:
        print("baudrate_probe: used")

    if report.baudrate_setting_index is not None:
        print(
            "stored_baudrate: "
            f"index={report.baudrate_setting_index}, "
            f"before={report.stored_baudrate_before}, "
            f"after={report.stored_baudrate_after}, "
            f"matches_config={report.baudrate_setting_matches_config}"
        )
        print(
            "stored_baudrate_note: "
            "new value becomes active after the next power cycle"
        )

    if report.baudrate_setting_error is not None:
        print(f"stored_baudrate_error: {report.baudrate_setting_error}")

    print()


def _print_nport_report(
    nport_report: dict,
) -> None:
    """Print one NPort-management report using the same block layout everywhere."""
    requested = nport_report.get("requested")
    attempted = nport_report.get("attempted")
    ok = nport_report.get("ok")
    print("nport:")
    print(f"  requested={requested}, attempted={attempted}, ok={ok}")

    for key in (
        "mode",
        "ip_address",
        "baudrate",
        "tcp_port",
        "command_port",
        "message",
        "error",
    ):
        value = nport_report.get(key)
        if key == "mode":
            value = NPORT.format_nport_mode(value)
        if value is not None and value != "":
            print(f"  {key}: {value}")

    for warning in nport_report.get("warnings") or []:
        print(f"  warning: {warning}")

    transcript_tail = nport_report.get("transcript_tail")
    if transcript_tail:
        print("  transcript_tail:")
        for line in str(transcript_tail).splitlines()[-12:]:
            print(f"    {line}")


def print_baudrate_probe_results(
    device: GsvDevice,
) -> None:
    """Print baudrate probe attempts stored in the connection report."""
    report = getattr(device, "connection_report", None)

    if report is None or not report.probe_results:
        return

    print("Baudrate probe results")
    print("----------------------")
    for result in report.probe_results:
        print_baudrate_probe_result(result)
    print()


def print_configuration_report(
    report: dict,
) -> None:
    """Print settings applied to the GSV before measurement streaming."""
    print("Applied configuration")
    print("---------------------")

    if report.get("stream_channels") is not None:
        print(f"stream_channels: {report['stream_channels']}")

    if report.get("tx_mapping") is not None:
        print(f"tx_mapping_count: {report['tx_mapping']['tx_mapping_count']}")

    if report.get("sample_rate_range") is not None:
        sample_rate_range = report["sample_rate_range"]
        print(
            "sample_rate_range_hz: "
            f"min={sample_rate_range.get('minimum_sample_rate_hz')}, "
            f"max={sample_rate_range.get('maximum_sample_rate_hz')}"
        )
        if sample_rate_range.get("minimum_read_error"):
            print(f"sample_rate_range_min_error: {sample_rate_range['minimum_read_error']}")
        if sample_rate_range.get("maximum_read_error"):
            print(f"sample_rate_range_max_error: {sample_rate_range['maximum_read_error']}")

    if report.get("sample_rate") is not None:
        sample_rate = report["sample_rate"]
        print(
            "sample_rate_hz: "
            f"requested={sample_rate.get('requested_sample_rate_hz')}, "
            f"written={sample_rate.get('written_sample_rate_hz')}, "
            f"active={sample_rate.get('sample_rate_hz')}, "
            f"matches={sample_rate.get('sample_rate_matches_request')}, "
            f"write_accepted={sample_rate.get('sample_rate_write_accepted')}"
        )
        if sample_rate.get("maximum_sample_rate_hz") is not None:
            print(f"sample_rate_maximum_hz: {sample_rate['maximum_sample_rate_hz']}")
        if sample_rate.get("sample_rate_write_error"):
            print(f"sample_rate_write_error: {sample_rate['sample_rate_write_error']}")

    if report.get("datatype") is not None:
        datatype = report["datatype"]
        print(
            "datatype: "
            f"requested={datatype.get('requested_datatype_name')}, "
            f"active={datatype.get('datatype_name')}, "
            f"matches={datatype.get('datatype_matches_request')}"
        )

    if report.get("analog_filter") is not None:
        analog_filter = report["analog_filter"]
        print(
            "analog_filter_hz: "
            f"requested={analog_filter['requested_analog_filter_hz']}, "
            f"active={analog_filter['analog_filter_hz']}, "
            f"write_accepted={analog_filter['analog_filter_write_accepted']}, "
            f"matches={analog_filter['analog_filter_matches_request']}"
        )

    for entry in report.get("input_modes", []):
        print(
            "input_mode: "
            f"channel={entry['channel']}, "
            f"mode={entry['sensor_input_mode_name']}, "
            f"sensitivity_mv_per_v={entry['sensor_input_sensitivity_mv_per_v']}"
        )

    for entry in report.get("scaling_factors", []):
        print(
            "scaling_factor: "
            f"channel={entry['channel']}, "
            f"value={entry['scaling_factor']}"
        )

    if report.get("digital_filter") is not None:
        print(f"digital_filter: {report['digital_filter']}")

    print()


def print_channel_layout(
    device: GsvDevice,
) -> None:
    """Print configured measurement channels and their sensor assignments."""
    print("Channel layout")
    print("--------------")

    for entry in device.list_channels():
        print(
            f"channel={entry['channel']}, "
            f"channel_name={entry['channel_name']}, "
            f"sensor_serial_number={entry['sensor_serial_number']}, "
            f"scaling_factor={entry['scaling_factor']}"
        )

    print()
