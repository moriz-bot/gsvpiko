"""Probe autonomous-frame datatypes on one GSV device."""

from __future__ import annotations

from ..config import config_devices as DEVICE
from ..constants import constants_datatypes as DATATYPE
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_report import print_baudrate_probe_result, print_connection_report

DEVICE_CONFIG = DEVICE.GSV_24456060
DATATYPES_TO_TEST = ("float32", "int24", "int16")


def main() -> None:
    """Write, read back, and restore autonomous-frame datatypes."""
    device = None

    print("Datatype probe")
    print("--------------")
    print(f"device_name: {DEVICE_CONFIG['name']}")
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

    original = device.acquisition.read_datatype()
    original_datatype = original["datatype"]
    print(f"original_datatype: {original['datatype_name']}")
    print()

    try:
        for datatype in DATATYPES_TO_TEST:
            print("Testing datatype")
            print("----------------")
            print(f"requested: {datatype}")
            response = device.acquisition.configure_datatype(datatype)
            print(
                f"readback: {response['datatype_name']}, "
                f"matches={response['datatype_matches_request']}"
            )

            device.clear_input_buffer()
            tare_response = device.zero.set_zero_all_channels()
            print(f"SetZero response: {tare_response['raw_hex']}")
            device.clear_input_buffer()
            start_response = device.acquisition.start_transmission()
            print(f"StartTransmission response: {start_response['raw_hex']}")
            frame = device.acquisition.read_next_measurement_frame()
            print(
                "frame_datatype: "
                f"{DATATYPE.get_name(frame['datatype'])} ({frame['datatype']})"
            )
            print(f"value_count: {len(frame['values'])}")
            stop_response = device.acquisition.stop_transmission()
            print(f"StopTransmission response: {stop_response['raw_hex']}")
            print()

    finally:
        if device is not None:
            print("Restoring original datatype...")
            response = device.acquisition.configure_datatype(original_datatype)
            print(f"restored_datatype: {response['datatype_name']}")
            device.close()
            print("Device closed.")


if __name__ == "__main__":
    main()
