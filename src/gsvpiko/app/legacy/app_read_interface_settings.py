"""Read raw GSV interface settings.

This app prints interface-setting entries so the writable baudrate entry can be
identified before implementing automatic interface-baudrate writes.
"""

from __future__ import annotations

from typing import Any

from ..config import config_devices as DEVICE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report


DEVICE_CONFIG = DEVICE.GSV_24456060
MAX_INDEX_TO_SCAN = 64


def describe_entry(
    entry: dict[str, Any],
) -> str:
    """Return a compact description of one interface-setting entry."""
    data_type_note = ""
    if entry["is_active_baudrate_entry"]:
        data_type_note = " active_baudrate_candidate"

    return (
        f"index={entry['request_index']:>2}, "
        f"next={entry['next_index']:>2}, "
        f"type_byte=0x{entry['type_byte']:02X}, "
        f"writable={entry['writable']}, "
        f"data_type={entry['data_type']}, "
        f"data={entry['data']}, "
        f"data_hex=0x{entry['data']:08X}, "
        f"raw={entry['raw_hex']}"
        f"{data_type_note}"
    )


def main() -> None:
    device = None

    print("Opening device...", flush=True)
    print("Connection probe", flush=True)
    print("----------------", flush=True)
    try:
        device = open_gsv_device_from_config(
            DEVICE_CONFIG,
            on_probe_result=print_baudrate_probe_result,
        )
        print()
        print("Device opened.")
        print()
        print_connection_report(device)

        print("ReadInterfaceSetting scan")
        print("-------------------------")
        for index in range(MAX_INDEX_TO_SCAN + 1):
            try:
                entry = device.interface.read_interface_setting(index)
            except Exception as error:
                print(f"index={index:>2}: {error}")
                continue

            print(describe_entry(entry))

    except DeviceConnectionError as error:
        print()
        print("Opening device failed.")
        print(error)

    finally:
        if device is not None:
            device.close()
            print()
            print("Device closed.")


if __name__ == "__main__":
    main()
