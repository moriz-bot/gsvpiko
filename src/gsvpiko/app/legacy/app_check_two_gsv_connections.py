"""Check the serial connections for all devices in the two-GSV setup."""

from __future__ import annotations

from ..config import config_setups as SETUP
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report


SETUP_CONFIG = SETUP.TWO_GSVS_ONE_SENSOR_EACH


def main() -> None:
    """Open and verify each GSV in the two-GSV setup, then close it again."""
    resolved_setup = resolve_setup(SETUP_CONFIG)

    print("Two-GSV connection check")
    print("------------------------")
    print(f"setup_name: {resolved_setup.name}")
    print(f"baudrate: {resolved_setup.baudrate}")
    print()

    for device_entry, resolved_device in zip(
        SETUP_CONFIG["attached_devices"],
        resolved_setup.devices,
    ):
        device_config = dict(device_entry["device"])
        device_config["default_baudrate"] = resolved_setup.baudrate

        print(f"Checking {resolved_device.alias} = {device_config['name']}")
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

        print()


if __name__ == "__main__":
    main()
