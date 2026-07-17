"""Shared measurement-readout runner for command-line apps."""

from __future__ import annotations

from typing import Any, Sequence

from ..device.device_channels import SensorDefinition
from ..device.device_connection import DeviceConnectionError, open_gsv_device_from_config
from ..device.device_gsv import GsvDevice
from ..device.device_measurement import (
    create_measurement_record,
    format_measurement_record,
)
from ..device.device_report import (
    print_baudrate_probe_result,
    print_channel_layout,
    print_configuration_report,
    print_connection_report,
)

SensorAttachmentConfig = tuple[dict[str, Any], Sequence[int], int]


def attach_sensors(
    device: GsvDevice,
    sensor_attachments: Sequence[SensorAttachmentConfig],
) -> None:
    """Attach sensor presets to one GSV device before configuration writes."""
    for sensor_mapping, channels, sensor_index in sensor_attachments:
        device.add_sensor(
            sensor=SensorDefinition.from_mapping(sensor_mapping),
            channels=channels,
            sensor_index=sensor_index,
        )


def run_read_values(
    *,
    device_config: dict[str, Any],
    sensor_attachments: Sequence[SensorAttachmentConfig],
    frame_count: int,
) -> None:
    """Open one GSV, apply settings, print reports, and print measurement frames."""
    device = None

    print("Opening device...", flush=True)
    print("Connection probe", flush=True)
    print("----------------", flush=True)
    try:
        device = open_gsv_device_from_config(
            device_config,
            on_probe_result=print_baudrate_probe_result,
        )
        print()
        print("Device opened.")
        print()

        attach_sensors(
            device,
            sensor_attachments,
        )

        print_connection_report(device)
        print_channel_layout(device)

        device.clear_input_buffer()
        device.acquisition.stop_transmission()
        device.clear_input_buffer()

        configuration_report = device.apply_attached_sensor_configuration()
        print_configuration_report(configuration_report)

        print("Taring all channels...")
        tare_response = device.zero.set_zero_all_channels()
        print(f"SetZero response: {tare_response['raw_hex']}")
        print()

        print("Starting transmission...")
        start_response = device.acquisition.start_transmission()
        print(f"StartTransmission response: {start_response['raw_hex']}")
        print()

        for frame_index in range(1, frame_count + 1):
            measurement_frame = device.acquisition.read_next_measurement_frame()
            measurement_record = create_measurement_record(
                measurement_frame,
                device=device,
            )

            print(f"Frame {frame_index}")
            print("-------")
            print(format_measurement_record(measurement_record))
            print()

    except DeviceConnectionError as error:
        print()
        print("Opening device failed.")
        print(error)

    finally:
        if device is None:
            return

        print("Stopping transmission...")
        try:
            stop_response = device.acquisition.stop_transmission()
            print(f"StopTransmission response: {stop_response['raw_hex']}")
        except Exception as error:
            print(f"StopTransmission failed: {error}")

        device.close()
        print("Device closed.")


def main() -> None:
    """Print a message when this helper module is executed directly."""
    raise SystemExit(
        "app_read_values_common provides run_read_values(...). "
        "Run app_read_values, app_read_values_second_socket, "
        "or app_read_values_two_sensors instead."
    )


if __name__ == "__main__":
    main()
