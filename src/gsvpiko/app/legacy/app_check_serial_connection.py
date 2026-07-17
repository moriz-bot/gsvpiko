"""Optional diagnostic app for one configured GSV connection."""

from __future__ import annotations

from ..config import config_devices as DEVICE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report

DEVICE_CONFIG = DEVICE.GSV_24456060


def main() -> None:
    """Open one configured device and print the connection report."""
    device = None

    print("Connection check", flush=True)
    print("----------------", flush=True)
    print(f"device_name: {DEVICE_CONFIG['name']}", flush=True)
    print(f"com_port: {DEVICE_CONFIG.get('com_port')}", flush=True)
    print(f"default_baudrate: {DEVICE_CONFIG.get('default_baudrate')}", flush=True)
    print(f"ip_address: {DEVICE_CONFIG.get('ip_address')}", flush=True)
    print()

    try:
        device = open_gsv_device_from_config(
            DEVICE_CONFIG,
            on_probe_result=print_baudrate_probe_result,
        )
        print()
        print("Connection check successful.")
        print()
        print_connection_report(device)
    except DeviceConnectionError as error:
        print()
        print("Connection check failed.")
        print(error)
    finally:
        if device is not None:
            device.close()


if __name__ == "__main__":
    main()
