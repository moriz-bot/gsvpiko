"""Restore common GSV measurement-stream settings."""

from __future__ import annotations

from ..config import config_devices as DEVICE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report

DEVICE_CONFIG = DEVICE.GSV_24456060
SAFE_SAMPLE_RATE_HZ = 100.0
DATATYPE = "float32"
TX_MAPPING_COUNT = 6
SAMPLE_RATE_HZ = 150.0


def main() -> None:
    """Restore common measurement-stream settings on one GSV device."""
    device = None

    print("Restore measurement stream defaults")
    print("-----------------------------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
    print(f"datatype: {DATATYPE}")
    print(f"tx_mapping_count: {TX_MAPPING_COUNT}")
    print(f"sample_rate_hz: {SAMPLE_RATE_HZ}")
    print()

    print("Opening device...")
    print("Connection probe")
    print("----------------")
    try:
        device = open_gsv_device_from_config(
            DEVICE_CONFIG,
            on_probe_result=print_baudrate_probe_result,
        )
    except DeviceConnectionError as error:
        print("Opening device failed.")
        print(error)
        return

    print()
    print("Device opened.")
    print_connection_report(device)

    try:
        device.clear_input_buffer()
        device.acquisition.stop_transmission()
        device.clear_input_buffer()

        response = device.acquisition.configure_sample_rate(SAFE_SAMPLE_RATE_HZ)
        print(f"safe_sample_rate_hz: {response['sample_rate_hz']}")

        response = device.acquisition.configure_datatype(DATATYPE)
        print(f"datatype: {response['datatype_name']}")

        response = device.acquisition.configure_tx_mapping_count(TX_MAPPING_COUNT)
        print(f"tx_mapping_count: {response['tx_mapping_count']}")

        response = device.acquisition.configure_sample_rate(SAMPLE_RATE_HZ)
        print(f"sample_rate_hz: {response['sample_rate_hz']}")

    finally:
        if device is not None:
            device.close()
            print("Device closed.")


if __name__ == "__main__":
    main()
