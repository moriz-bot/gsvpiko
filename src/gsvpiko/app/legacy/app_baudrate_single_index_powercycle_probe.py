"""Set and verify selected baudrate entries across manual power cycles.

The app writes selected writable active-baudrate interface-setting entries and
then exits. The changed baudrate becomes testable after the device has been
powered off and powered on again.
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

BAUDRATE_INDEX_A = 10
BAUDRATE_INDEX_B = 21
BASELINE_BAUDRATE = 115200
TARGET_BAUDRATE = DEVICE_CONFIG["default_baudrate"]

TEST_MODE = "verify"
# Supported modes:
# "verify"
# "set_both_baseline"
# "set_index_10"
# "set_index_21"
# "set_both_target"


def normalize_test_mode(
    test_mode: str,
) -> str:
    """Return the normalized test-mode name."""
    normalized = test_mode.strip().lower()
    allowed_modes = {
        "verify",
        "set_both_baseline",
        "set_index_10",
        "set_index_21",
        "set_both_target",
    }

    if normalized not in allowed_modes:
        raise ValueError(
            f"Unknown TEST_MODE {test_mode!r}. "
            f"Allowed modes: {sorted(allowed_modes)}"
        )

    return normalized


def describe_baudrate_entry(
    entry: dict[str, Any],
) -> str:
    """Return a compact description of one baudrate setting entry."""
    return (
        f"index={entry['request_index']:>2}, "
        f"next={entry['next_index']:>2}, "
        f"type_byte=0x{entry['type_byte']:02X}, "
        f"data={entry['data']}, "
        f"raw={entry['raw_hex']}"
    )


def open_device() -> GsvDevice:
    """Open the configured GSV device with baudrate probing enabled."""
    return open_gsv_device_from_config(
        DEVICE_CONFIG,
        auto_probe_baudrate=True,
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


def read_selected_entries(
    device: GsvDevice,
) -> list[dict[str, Any]]:
    """Read the two selected active-baudrate setting entries."""
    entries = []
    for index in (BAUDRATE_INDEX_A, BAUDRATE_INDEX_B):
        entries.append(device.interface.read_interface_setting(index))

    return entries


def print_selected_entries(
    *,
    title: str,
    entries: list[dict[str, Any]],
) -> None:
    """Print selected baudrate setting entries."""
    print(title)
    print("-" * len(title))
    for entry in entries:
        print(describe_baudrate_entry(entry))
    print()


def find_writable_baudrate_entries(
    device: GsvDevice,
) -> list[dict[str, Any]]:
    """Read writable active-baudrate entries from the interface-setting table."""
    entries = device.interface.find_writable_baudrate_settings(
        max_index=MAX_INDEX_TO_SCAN,
    )
    entries.sort(key=lambda entry: entry["request_index"])
    return entries


def print_available_writable_entries(
    device: GsvDevice,
) -> None:
    """Print writable active-baudrate entries available on the device."""
    entries = find_writable_baudrate_entries(device)

    print("Writable baudrate setting entries")
    print("---------------------------------")
    if not entries:
        print("No writable active-baudrate entries were found.")
        print()
        return

    for entry in entries:
        print(describe_baudrate_entry(entry))
    print()


def target_values_for_mode(
    test_mode: str,
) -> dict[int, int]:
    """Return the index-to-baudrate write plan for one test mode."""
    target_baudrate = BAUDRATE.normalize_baudrate(TARGET_BAUDRATE)
    baseline_baudrate = BAUDRATE.normalize_baudrate(BASELINE_BAUDRATE)

    if test_mode == "set_both_baseline":
        return {
            BAUDRATE_INDEX_A: baseline_baudrate,
            BAUDRATE_INDEX_B: baseline_baudrate,
        }

    if test_mode == "set_index_10":
        return {
            BAUDRATE_INDEX_A: target_baudrate,
            BAUDRATE_INDEX_B: baseline_baudrate,
        }

    if test_mode == "set_index_21":
        return {
            BAUDRATE_INDEX_A: baseline_baudrate,
            BAUDRATE_INDEX_B: target_baudrate,
        }

    if test_mode == "set_both_target":
        return {
            BAUDRATE_INDEX_A: target_baudrate,
            BAUDRATE_INDEX_B: target_baudrate,
        }

    return {}


def write_target_values(
    *,
    device: GsvDevice,
    target_values: dict[int, int],
) -> None:
    """Write selected baudrate setting entries."""
    print("Writing selected baudrate settings")
    print("----------------------------------")
    for index, baudrate in target_values.items():
        response = device.interface.write_baudrate_setting(
            index=index,
            baudrate=baudrate,
        )
        print(
            f"index={index}, baudrate={baudrate}: "
            f"{response['raw_hex']}"
        )
    print()


def release_interface(
    device: GsvDevice,
) -> None:
    """Send ReleaseInterface after interface-setting writes."""
    try:
        response = device.interface.release_interface()
        print(f"ReleaseInterface response: {response['raw_hex']}")
    except Exception as error:
        print(f"ReleaseInterface failed: {error}")
    print()


def print_next_step(
    test_mode: str,
) -> None:
    """Print the next manual step after the current mode."""
    if test_mode == "verify":
        print("Verification finished.")
        return

    print("Next manual step")
    print("----------------")
    print("1. Close this terminal command if it is still running.")
    print("2. Power the GSV device off.")
    print("3. Wait until the device is fully off.")
    print("4. Power the GSV device on again.")
    print("5. Run this app with TEST_MODE = 'verify'.")
    print()


def run_verify_mode(
    device: GsvDevice,
) -> None:
    """Print active connection state and selected baudrate-setting values."""
    print("Verification result")
    print("-------------------")
    print_connection_report(device)

    print_available_writable_entries(device)
    print_selected_entries(
        title="Selected entry readback",
        entries=read_selected_entries(device),
    )


def run_set_mode(
    *,
    device: GsvDevice,
    test_mode: str,
) -> None:
    """Write the selected test-mode values and print readback."""
    target_values = target_values_for_mode(test_mode)

    print_available_writable_entries(device)
    print_selected_entries(
        title="Before write readback",
        entries=read_selected_entries(device),
    )

    write_target_values(
        device=device,
        target_values=target_values,
    )

    print_selected_entries(
        title="After write readback",
        entries=read_selected_entries(device),
    )

    release_interface(device)


def main() -> None:
    """Run one manual power-cycle test step."""
    test_mode = normalize_test_mode(TEST_MODE)
    target_baudrate = BAUDRATE.normalize_baudrate(TARGET_BAUDRATE)
    baseline_baudrate = BAUDRATE.normalize_baudrate(BASELINE_BAUDRATE)
    device = None

    print("Single-index baudrate power-cycle probe")
    print("---------------------------------------")
    print(f"test_mode: {test_mode}")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print(f"com_port: {DEVICE_CONFIG['com_port']}")
    print(f"baseline_baudrate: {baseline_baudrate}")
    print(f"target_baudrate: {target_baudrate}")
    print(f"ip_address: {DEVICE_CONFIG.get('ip_address')}")
    print()

    print("Opening device with baudrate probe...")
    try:
        device = open_device()
    except DeviceConnectionError as error:
        print("Opening device failed.")
        print(error)
        return

    print()
    print("Device opened.")
    print_connection_report(device)

    try:
        if test_mode == "verify":
            run_verify_mode(device)
        else:
            run_set_mode(
                device=device,
                test_mode=test_mode,
            )
    finally:
        close_device_quietly(device)

    print_next_step(test_mode)


if __name__ == "__main__":
    main()
