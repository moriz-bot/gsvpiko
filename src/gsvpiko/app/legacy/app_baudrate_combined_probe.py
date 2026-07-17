"""Probe whether all writable baudrate settings must be changed together.

The app writes every writable active-baudrate interface-setting entry to the
configured target baudrate, reads the changed entries back, releases the
interface, closes the connection, and verifies whether the device answers at the
target baudrate. Failed attempts are restored when the device can be recovered.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import config_devices as DEVICE
from ..constants import constants_baudrates as BAUDRATE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_gsv import GsvDevice
from ..device.device_report import print_baudrate_probe_result, print_connection_report


DEVICE_CONFIG = DEVICE.GSV_24456060
MAX_INDEX_TO_SCAN = 64
CALL_RELEASE_INTERFACE_AFTER_WRITE = True
RESTORE_AFTER_FAILED_VERIFICATION = False
WAIT_AFTER_CLOSE_S = 2.0


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


def verify_target_baudrate() -> GsvDevice | None:
    """Open the device only at the configured target baudrate."""
    try:
        return open_device(
            auto_probe_baudrate=False,
        )
    except DeviceConnectionError as error:
        print("Target-baudrate verification failed.")
        print(error)
        return None


def read_writable_baudrate_entries(
    device: GsvDevice,
) -> list[dict[str, Any]]:
    """Read writable active-baudrate entries from the interface-setting table."""
    entries = device.interface.find_writable_baudrate_settings(
        max_index=MAX_INDEX_TO_SCAN,
    )
    entries.sort(key=lambda entry: entry["request_index"])
    return entries


def read_entries_again(
    *,
    device: GsvDevice,
    entries: list[dict[str, Any]],
    label: str,
) -> None:
    """Read the selected entries again and print their decoded values."""
    print(label)
    print("-" * len(label))

    for entry in entries:
        index = entry["request_index"]
        try:
            readback = device.interface.read_interface_setting(index)
            print(describe_baudrate_entry(readback))
        except Exception as error:
            print(f"index={index:>2}: readback failed: {error}")

    print()


def write_entries_to_baudrate(
    *,
    device: GsvDevice,
    entries: list[dict[str, Any]],
    baudrate: int,
) -> None:
    """Write all selected entries to one baudrate."""
    for entry in entries:
        index = entry["request_index"]
        response = device.interface.write_baudrate_setting(
            index=index,
            baudrate=baudrate,
        )
        print(
            f"WriteInterfaceSetting index={index}: "
            f"{response['raw_hex']}"
        )


def restore_entries(
    *,
    entries: list[dict[str, Any]],
) -> None:
    """Restore selected entries to their original values after a failed test."""
    device = recover_device_with_probe()
    if device is None:
        print("Restore skipped because the device could not be recovered.")
        return

    try:
        print()
        print("Restoring original baudrate settings")
        print("------------------------------------")
        for entry in entries:
            index = entry["request_index"]
            original_baudrate = entry["data"]
            response = device.interface.write_baudrate_setting(
                index=index,
                baudrate=original_baudrate,
            )
            print(
                f"restore index={index}, baudrate={original_baudrate}: "
                f"{response['raw_hex']}"
            )

        read_entries_again(
            device=device,
            entries=entries,
            label="Restore readback",
        )
    finally:
        close_device_quietly(device)


def main() -> None:
    """Run the combined baudrate-setting probe."""
    target_baudrate = BAUDRATE.normalize_baudrate(DEVICE_CONFIG["default_baudrate"])
    device = None

    print("Combined baudrate setting probe")
    print("-------------------------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print(f"com_port: {DEVICE_CONFIG['com_port']}")
    print(f"target_baudrate: {target_baudrate}")
    print(f"ip_address: {DEVICE_CONFIG.get('ip_address')}")
    print(f"release_after_write: {CALL_RELEASE_INTERFACE_AFTER_WRITE}")
    print(f"restore_after_failed_verification: {RESTORE_AFTER_FAILED_VERIFICATION}")
    print(f"wait_after_close_s: {WAIT_AFTER_CLOSE_S}")
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

    if device.connection_report.active_baudrate == target_baudrate:
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
    print()

    read_entries_again(
        device=device,
        entries=entries,
        label="Before write readback",
    )

    print("Writing all writable baudrate settings")
    print("--------------------------------------")
    write_entries_to_baudrate(
        device=device,
        entries=entries,
        baudrate=target_baudrate,
    )
    print()

    read_entries_again(
        device=device,
        entries=entries,
        label="After write readback",
    )

    if CALL_RELEASE_INTERFACE_AFTER_WRITE:
        try:
            response = device.interface.release_interface()
            print(f"ReleaseInterface response: {response['raw_hex']}")
        except Exception as error:
            print(f"ReleaseInterface failed: {error}")

    close_device_quietly(device)
    device = None

    if WAIT_AFTER_CLOSE_S > 0:
        print(f"Waiting {WAIT_AFTER_CLOSE_S} s before verification...")
        time.sleep(WAIT_AFTER_CLOSE_S)

    print("Verifying configured target baudrate...")
    target_device = verify_target_baudrate()
    if target_device is not None:
        print()
        print("Combined write succeeded.")
        print_connection_report(target_device)
        close_device_quietly(target_device)
        return

    print()
    print("Combined write did not produce a verified target-baudrate connection.")

    recovery_device = recover_device_with_probe()
    if recovery_device is not None:
        try:
            print()
            print("Recovered connection")
            print("--------------------")
            print_connection_report(recovery_device)
            read_entries_again(
                device=recovery_device,
                entries=entries,
                label="Recovery readback",
            )
        finally:
            close_device_quietly(recovery_device)

    if RESTORE_AFTER_FAILED_VERIFICATION:
        restore_entries(
            entries=entries,
        )
    else:
        print()
        print("Original values were not restored.")
        print("A power-cycle test can now be performed with the written settings.")


if __name__ == "__main__":
    main()
