"""Probe which interface-setting index changes the GSV serial baudrate.

The app changes one writable active-baudrate setting at a time, closes the
current connection, and verifies whether the device answers at the configured
target baudrate. Failed candidates are restored when the device can be reopened.
"""

from __future__ import annotations

from typing import Any

from ..config import config_devices as DEVICE
from ..constants import constants_baudrates as BAUDRATE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_gsv import GsvDevice
from ..device.device_report import print_baudrate_probe_result, print_connection_report


DEVICE_CONFIG = DEVICE.GSV_24456060
MAX_INDEX_TO_SCAN = 64
RESTORE_FAILED_CANDIDATES = True


def describe_baudrate_entry(
    entry: dict[str, Any],
) -> str:
    """Return a compact description of one writable baudrate setting."""
    return (
        f"index={entry['request_index']:>2}, "
        f"next={entry['next_index']:>2}, "
        f"type_byte=0x{entry['type_byte']:02X}, "
        f"data={entry['data']}, "
        f"raw={entry['raw_hex']}"
    )


def open_device(
    *,
    auto_probe_baudrate: bool,
) -> GsvDevice:
    """Open the configured GSV device."""
    return open_gsv_device_from_config(
        DEVICE_CONFIG,
        auto_probe_baudrate=auto_probe_baudrate,
        on_probe_result=print_baudrate_probe_result,
    )


def open_device_at_target_baudrate() -> GsvDevice | None:
    """Open the device only at the configured target baudrate."""
    try:
        return open_device(
            auto_probe_baudrate=False,
        )
    except DeviceConnectionError as error:
        print("Target-baudrate verification failed.")
        print(error)
        return None


def recover_device_with_probe() -> GsvDevice | None:
    """Recover the device by probing all supported baudrates."""
    print("Recovering connection with baudrate probe...")
    try:
        return open_device(
            auto_probe_baudrate=True,
        )
    except DeviceConnectionError as error:
        print("Recovery failed.")
        print(error)
        return None


def close_device_quietly(
    device: GsvDevice | None,
) -> None:
    """Close a device object and ignore close errors."""
    if device is None:
        return

    try:
        device.close()
    except Exception:
        pass


def read_writable_baudrate_entries(
    device: GsvDevice,
) -> list[dict[str, Any]]:
    """Read writable active-baudrate entries from the interface-setting table."""
    entries = device.interface.find_writable_baudrate_settings(
        max_index=MAX_INDEX_TO_SCAN,
    )

    entries.sort(
        key=lambda entry: (
            entry["data"] != device.connection_report.active_baudrate,
            entry["request_index"],
        )
    )
    return entries


def restore_candidate(
    *,
    device: GsvDevice,
    index: int,
    original_baudrate: int,
) -> None:
    """Restore one tested baudrate setting to its original value."""
    print(
        f"Restoring index {index} to original baudrate "
        f"{original_baudrate}..."
    )
    try:
        device.interface.write_baudrate_setting(
            index=index,
            baudrate=original_baudrate,
        )
        print("Restore command accepted.")
    except Exception as error:
        print(f"Restore command failed: {error}")


def try_candidate(
    *,
    candidate: dict[str, Any],
    target_baudrate: int,
) -> bool:
    """Try one candidate index and return whether target-baudrate verification works."""
    index = candidate["request_index"]
    original_baudrate = candidate["data"]

    print()
    print(f"Trying baudrate setting index {index}")
    print("----------------------------------")
    print(f"original_baudrate: {original_baudrate}")
    print(f"target_baudrate:   {target_baudrate}")

    device = recover_device_with_probe()
    if device is None:
        return False

    try:
        try:
            response = device.interface.write_baudrate_setting(
                index=index,
                baudrate=target_baudrate,
            )
            print(f"WriteInterfaceSetting response: {response['raw_hex']}")
        except Exception as error:
            print(
                "WriteInterfaceSetting did not return a valid response. "
                "The device may still have applied the baudrate change."
            )
            print(error)
    finally:
        close_device_quietly(device)

    print("Verifying target baudrate...")
    target_device = open_device_at_target_baudrate()
    if target_device is not None:
        print()
        print("Candidate succeeded.")
        print_connection_report(target_device)
        close_device_quietly(target_device)
        return True

    recovery_device = recover_device_with_probe()
    if recovery_device is None:
        return False

    try:
        print()
        print("Candidate did not produce a verified target-baudrate connection.")
        print_connection_report(recovery_device)
        if RESTORE_FAILED_CANDIDATES and original_baudrate != target_baudrate:
            restore_candidate(
                device=recovery_device,
                index=index,
                original_baudrate=original_baudrate,
            )
    finally:
        close_device_quietly(recovery_device)

    return False


def main() -> None:
    target_baudrate = BAUDRATE.normalize_baudrate(DEVICE_CONFIG["default_baudrate"])
    device = None

    print("Baudrate change probe")
    print("---------------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print(f"com_port: {DEVICE_CONFIG['com_port']}")
    print(f"target_baudrate: {target_baudrate}")
    print(f"ip_address: {DEVICE_CONFIG.get('ip_address')}")
    print()

    print("Opening device with baudrate probe...")
    try:
        device = open_device(
            auto_probe_baudrate=True,
        )
    except DeviceConnectionError as error:
        print("Opening device failed.")
        print(error)
        return

    print()
    print("Device opened.")
    print_connection_report(device)

    active_baudrate = device.connection_report.active_baudrate
    if active_baudrate == target_baudrate:
        print("The active baudrate already matches the configured target baudrate.")
        close_device_quietly(device)
        return

    entries = read_writable_baudrate_entries(device)

    print("Writable baudrate setting candidates")
    print("------------------------------------")
    if not entries:
        print("No writable active-baudrate entries were found.")
        close_device_quietly(device)
        return

    for entry in entries:
        print(describe_baudrate_entry(entry))

    close_device_quietly(device)
    device = None

    for candidate in entries:
        if try_candidate(
            candidate=candidate,
            target_baudrate=target_baudrate,
        ):
            print()
            print(
                f"Use interface-setting index {candidate['request_index']} "
                "for automatic baudrate changes."
            )
            return

    print()
    print("No candidate produced a verified target-baudrate connection.")


if __name__ == "__main__":
    main()
