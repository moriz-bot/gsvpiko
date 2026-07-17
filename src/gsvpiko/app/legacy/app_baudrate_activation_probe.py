"""Probe how written interface baudrate settings become active.

The app writes one writable active-baudrate setting, reads the same setting back
before closing the connection, optionally releases the interface, and then tries
to verify the configured target baudrate. Failed candidates are restored when
the device can be recovered.
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
CALL_RELEASE_INTERFACE_AFTER_WRITE = True
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
    entries.sort(key=lambda entry: entry["request_index"])
    return entries


def read_candidate_again(
    *,
    device: GsvDevice,
    index: int,
    label: str,
) -> dict[str, Any] | None:
    """Read one candidate again and print the decoded value."""
    try:
        entry = device.interface.read_interface_setting(index)
    except Exception as error:
        print(f"{label}: readback failed: {error}")
        return None

    print(f"{label}: {describe_baudrate_entry(entry)}")
    return entry


def verify_target_baudrate() -> bool:
    """Return whether the GSV answers at the configured target baudrate only."""
    target_device = None

    try:
        target_device = open_device(
            auto_probe_baudrate=False,
        )
    except DeviceConnectionError as error:
        print("Target-baudrate verification failed.")
        print(error)
        return False
    finally:
        close_device_quietly(target_device)

    print("Target-baudrate verification succeeded.")
    return True


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
        response = device.interface.write_baudrate_setting(
            index=index,
            baudrate=original_baudrate,
        )
        print(f"Restore response: {response['raw_hex']}")
        read_candidate_again(
            device=device,
            index=index,
            label="restore_readback",
        )
    except Exception as error:
        print(f"Restore failed: {error}")


def try_candidate(
    *,
    candidate: dict[str, Any],
    target_baudrate: int,
) -> bool:
    """Try one baudrate setting candidate and report each activation step."""
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
        read_candidate_again(
            device=device,
            index=index,
            label="before_write_readback",
        )

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

        after_write_entry = read_candidate_again(
            device=device,
            index=index,
            label="after_write_readback",
        )

        if CALL_RELEASE_INTERFACE_AFTER_WRITE:
            try:
                response = device.interface.release_interface()
                print(f"ReleaseInterface response: {response['raw_hex']}")
            except Exception as error:
                print(f"ReleaseInterface failed: {error}")

    finally:
        close_device_quietly(device)

    print("Verifying configured target baudrate...")
    if verify_target_baudrate():
        print()
        print("Candidate succeeded.")
        return True

    recovery_device = recover_device_with_probe()
    if recovery_device is None:
        return False

    try:
        print()
        print("Candidate did not produce a verified target-baudrate connection.")
        print_connection_report(recovery_device)

        read_candidate_again(
            device=recovery_device,
            index=index,
            label="recovery_readback",
        )

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
    """Run the baudrate activation probe."""
    target_baudrate = BAUDRATE.normalize_baudrate(DEVICE_CONFIG["default_baudrate"])
    device = None

    print("Baudrate activation probe")
    print("-------------------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print(f"com_port: {DEVICE_CONFIG['com_port']}")
    print(f"target_baudrate: {target_baudrate}")
    print(f"ip_address: {DEVICE_CONFIG.get('ip_address')}")
    print(f"release_after_write: {CALL_RELEASE_INTERFACE_AFTER_WRITE}")
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
