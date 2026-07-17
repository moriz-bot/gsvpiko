"""Smoke test using the default configured GSV device."""

from ..config.config_devices import DEFAULT_DEVICE
from ..device.device_gsv import GsvDevice
from ..protocol import protocol_error_text
from ..transport.transport_serial import SerialTransport

SMOKE_TEST_TRANSPORT_TIMEOUT_S = 1.0


def print_response_summary(response: dict) -> None:
    """Print a compact response summary."""
    print(f"Request:  {response['request_raw_hex']}")
    print(f"Response: {response['raw_hex']}")
    print(f"kind: {response['kind']}")
    print(f"status: 0x{response['status']:02X}")
    print(f"status_text: {protocol_error_text.get_error_text(response['status'])}")
    print(f"payload: {response['payload'].hex(' ').upper() if response['payload'] else '<empty>'}")

    preceding_measurements = response.get("preceding_measurements", [])
    print(f"preceding_measurements: {len(preceding_measurements)}")


def main() -> None:
    transport = SerialTransport(
        port=str(DEFAULT_DEVICE["com_port"]),
        baudrate=int(DEFAULT_DEVICE["default_baudrate"]),
        timeout=SMOKE_TEST_TRANSPORT_TIMEOUT_S,
    )
    device = GsvDevice(transport)

    print("Opening device...")
    device.open()
    print("Device opened.")

    try:
        device.clear_input_buffer()

        response = device.acquisition.stop_transmission()

        print()
        print("StopTransmission result")
        print("----------------------")
        print_response_summary(response)
        print()

    finally:
        device.close()
        print("Device closed.")


if __name__ == "__main__":
    main()
