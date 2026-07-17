"""Validate and print one reusable GSVpiko setup."""

from __future__ import annotations

from ..config import config_setups as SETUP
from ..coordination.coordination_setup_resolution import (
    build_setup_metadata_lines,
    resolve_setup,
)
from ..messages.messages_warning_text import format_warning

SETUP_CONFIG = SETUP.ONE_GSV_TWO_SENSORS


def run_setup_validation(
    setup_config: dict,
    *,
    title: str = "Setup validation",
) -> None:
    """Resolve one setup and print the resulting static configuration."""
    resolved = resolve_setup(setup_config)

    print(title)
    print("-" * len(title))
    print(f"setup_name: {resolved.name}")
    print(f"language: {resolved.language}")
    print(
        f"connection_type: {resolved.connection_type} "
        f"(source={resolved.connection_type_source})"
    )
    print(
        f"serial_interface: {resolved.serial_interface} "
        f"(source={resolved.serial_interface_source})"
    )
    print(f"use_nport: {resolved.use_nport} (source={resolved.use_nport_source})")
    print(f"start_mode: {resolved.start_mode}")
    print(f"sync_mode: {resolved.sync_mode}")
    print(f"timebase_mode: {resolved.timebase_mode}")
    print(f"baudrate: {resolved.baudrate} (source={resolved.baudrate_source})")
    print(
        f"sample_rate_hz: {resolved.sample_rate_hz} "
        f"(source={resolved.sample_rate_source})"
    )
    print(f"datatype: {resolved.datatype_name} (source={resolved.datatype_source})")
    print(
        f"analog_filter_hz: {resolved.analog_filter_hz} "
        f"(source={resolved.analog_filter_source})"
    )
    print(f"crc_enabled: {resolved.crc_enabled}")
    print()

    print("\n".join(build_setup_metadata_lines(resolved)))
    print()

    print("streamed_channels:")
    for device in resolved.devices:
        print(
            f"  {device.alias}: "
            f"used={list(device.used_channels)}, "
            f"streamed={list(device.streamed_channels)}"
        )
    print()

    print("sample_rate_limit:")
    for device_alias, report in _iter_sample_rate_limit_reports(resolved):
        print(
            f"  {device_alias}: "
            f"streamed_values={report['streamed_value_count']}, "
            f"datatype={report['datatype_name']}, "
            f"requested={report['requested_sample_rate_hz']:g} Hz, "
            f"estimated_limit={report['estimated_serial_limit_hz']:.1f} Hz, "
            f"plausible={report['request_plausible']}"
        )
        if report["warning_key"] is not None:
            print()
            print(
                format_warning(
                    report["warning_key"],
                    language=resolved.language,
                    context=report,
                )
            )
            print()


def main() -> None:
    """Validate the default one-GSV setup."""
    run_setup_validation(SETUP_CONFIG)


def _iter_sample_rate_limit_reports(
    resolved_setup,
):
    """Yield sample-rate reports together with the matching device alias.

    Older resolved-setup objects do not store device_alias inside each report.
    The reports are produced in device order, so the alias can be paired from
    resolved_setup.devices without changing the resolution layer.
    """
    for index, report in enumerate(resolved_setup.sample_rate_limit_reports):
        if "device_alias" in report:
            yield report["device_alias"], report
            continue

        if index < len(resolved_setup.devices):
            yield resolved_setup.devices[index].alias, report
            continue

        yield f"device_{index + 1}", report


if __name__ == "__main__":
    main()
