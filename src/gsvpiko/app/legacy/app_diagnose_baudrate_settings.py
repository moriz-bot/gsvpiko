"""Diagnose stored and active GSV baudrate settings for two-GSV setups.

This app is intentionally read-heavy. It opens each configured GSV, reports the
active baudrate found by probing, reads the serial baudrate interface setting,
stores the diagnostic target baudrate for the next power cycle, and reads the
setting again.

Run it once before a power cycle and once after a power cycle. The comparison
shows whether the requested baudrate is stored but not activated, not stored, or
activated successfully.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import config_setups as SETUP
from ..constants import constants_baudrates as BAUDRATE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result

SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH
TARGET_BAUDRATE = 921600
INTERFACE_SETTING_INDEX = BAUDRATE.ACTIVE_SERIAL_INTERFACE_SETTING_INDEX
SCAN_MAX_INDEX = 24


def main() -> None:
    """Run the baudrate diagnostics for all devices in the setup."""
    title = "Two-GSV baudrate diagnostics"
    print(title)
    print("-" * len(title))
    print(f"target_baudrate: {TARGET_BAUDRATE}")
    print(f"serial_interface_setting_index: {INTERFACE_SETTING_INDEX}")
    print(f"uart_baudrates: {BAUDRATE.GSV8_UART_BAUDRATES}")
    print(f"rs422_baudrates: {BAUDRATE.GSV8_RS422_BAUDRATES}")
    print()

    for device_entry in SETUP_CONFIG["attached_devices"]:
        alias = device_entry["alias"]
        device_config = deepcopy(device_entry["device"])
        device_config["default_baudrate"] = TARGET_BAUDRATE

        print(f"{alias} = {device_config['name']}")
        print("-" * (len(alias) + len(device_config["name"]) + 3))
        print(f"com_port: {device_config.get('com_port')}")
        print(f"ip_address: {device_config.get('ip_address')}")
        print("Connection probe")
        print("----------------")

        device = None
        try:
            device = open_gsv_device_from_config(
                device_config,
                on_probe_result=print_baudrate_probe_result,
            )
            report = device.connection_report
            print()
            print("Connection result")
            print("-----------------")
            print(f"configured_baudrate: {report.configured_baudrate}")
            print(f"active_baudrate: {report.active_baudrate}")
            print(f"baudrate_matches_config: {report.baudrate_matches_config}")
            print(f"stored_baudrate_before_open_helper: {report.stored_baudrate_before}")
            print(f"stored_baudrate_after_open_helper: {report.stored_baudrate_after}")
            print(
                "baudrate_setting_matches_config: "
                f"{report.baudrate_setting_matches_config}"
            )
            print(
                "baudrate_setting_write_executed: "
                f"{report.baudrate_setting_write_executed}"
            )
            print(f"baudrate_setting_error: {report.baudrate_setting_error or '-'}")
            print()

            _print_serial_baudrate_setting(
                device,
                label="Index 10 after opening",
                index=INTERFACE_SETTING_INDEX,
            )

            print()
            print("Explicit store attempt")
            print("----------------------")
            try:
                store_report = device.interface.store_serial_baudrate_for_next_power_cycle(
                    TARGET_BAUDRATE,
                    index=INTERFACE_SETTING_INDEX,
                )
                _print_store_report(store_report)
            except Exception as error:
                print(f"store_error: {error}")

            print()
            _print_serial_baudrate_setting(
                device,
                label="Index 10 after explicit store attempt",
                index=INTERFACE_SETTING_INDEX,
            )

            print()
            print("Relevant interface-setting entries")
            print("----------------------------------")
            _print_relevant_interface_settings(device)

            print()
            print("Interpretation")
            print("--------------")
            if report.active_baudrate == TARGET_BAUDRATE:
                print("Active baudrate already equals the diagnostic target.")
            else:
                print(
                    "If index 10 stores the target but the device still answers only "
                    "at the old baudrate after a power cycle, index 10 is not sufficient "
                    "for this firmware/interface combination or the device falls back "
                    "during boot."
                )

        except DeviceConnectionError as error:
            print()
            print("Opening device failed.")
            print(error)
        finally:
            if device is not None:
                device.close()

        print()


def _print_serial_baudrate_setting(
    device,
    *,
    label: str,
    index: int,
) -> None:
    """Read and print one baudrate interface-setting entry."""
    print(label)
    print("-" * len(label))
    try:
        setting = device.interface.read_serial_baudrate_setting(index=index)
        _print_interface_setting(setting)
    except Exception as error:
        print(f"read_error: {error}")


def _print_store_report(
    report: dict[str, Any],
) -> None:
    """Print the result of storing a serial baudrate."""
    print(f"baudrate_setting_index: {report['baudrate_setting_index']}")
    print(f"requested_baudrate: {report['requested_baudrate']}")
    print(f"stored_baudrate_before: {report['stored_baudrate_before']}")
    print(f"stored_baudrate_after: {report['stored_baudrate_after']}")
    print(
        "stored_baudrate_matches_request: "
        f"{report['stored_baudrate_matches_request']}"
    )
    print(f"write_executed: {report['write_executed']}")
    print(f"write_response_raw_hex: {report['write_response_raw_hex'] or '-'}")
    print(f"power_cycle_required: {report['power_cycle_required']}")


def _print_relevant_interface_settings(
    device,
) -> None:
    """Scan interface settings and print entries that look baudrate-related."""
    found = False

    for index in range(SCAN_MAX_INDEX + 1):
        try:
            setting = device.interface.read_interface_setting(index)
        except Exception as error:
            print(f"index={index}: read_error={error}")
            continue

        data = setting["data"]
        relevant = (
            setting["is_active_baudrate_entry"]
            or setting["is_writable_active_baudrate_entry"]
            or data in BAUDRATE.ALLOWED
            or data == TARGET_BAUDRATE
        )
        if not relevant:
            continue

        found = True
        _print_interface_setting(setting)

    if not found:
        print("No relevant entries found in the scanned range.")


def _print_interface_setting(
    setting: dict[str, Any],
) -> None:
    """Print one decoded interface-setting entry on one line."""
    print(
        f"index={setting.get('request_index')}, "
        f"next_index={setting.get('next_index')}, "
        f"writable={setting.get('writable')}, "
        f"data_type={setting.get('data_type')}, "
        f"is_active_baudrate_entry={setting.get('is_active_baudrate_entry')}, "
        f"is_writable_active_baudrate_entry="
        f"{setting.get('is_writable_active_baudrate_entry')}, "
        f"data={setting.get('data')}"
    )


if __name__ == "__main__":
    main()
