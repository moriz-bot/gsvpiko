"""Read measurement values using a reusable GSVpiko setup preset."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options

from ..coordination.coordination_report_print import (
    format_sample_rate_limit_lines,
    format_setup_application_warning_lines,
    format_setup_metadata_block_lines,
    format_setup_overview_lines,
    format_title_lines,
)
from ..coordination.coordination_setup_application import (
    close_applied_devices,
    open_and_apply_setup,
    setup_application_warning_action_text,
    set_zero_all_channels,
    start_transmission,
    stop_transmission,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError
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
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY
FRAME_COUNT = 1


def run_setup_read_values(
    setup_config: dict,
    *,
    frame_count: int = FRAME_COUNT,
    title: str = "Setup read-values app",
) -> None:
    """Open setup devices, apply configuration, and print measurement frames."""
    applied_setup = None
    transmission_started = False

    resolved_setup = resolve_setup(setup_config)
    lines = []
    lines.extend(format_title_lines(title))
    lines.extend(
        format_setup_overview_lines(
            resolved_setup,
            include_connection=False,
            include_runtime=False,
        )
    )
    lines.append("")
    lines.extend(format_setup_metadata_block_lines(resolved_setup))
    lines.append("")
    lines.extend(format_sample_rate_limit_lines(resolved_setup))
    print("\n".join(lines).rstrip())
    print()

    try:
        print("Opening and applying setup...")
        print("Connection probe")
        print("----------------")
        applied_setup = open_and_apply_setup(
            setup_config=setup_config,
            resolved_setup=resolved_setup,
            on_probe_result=print_baudrate_probe_result,
        )
        print()
        print("Setup applied.")
        print()

        for applied_device in applied_setup.devices:
            print_connection_report(applied_device.device)
            print_channel_layout(applied_device.device)
            print_configuration_report(applied_device.configuration_report)

        if applied_setup.warnings:
            print(
                "\n".join(
                    format_setup_application_warning_lines(applied_setup.warnings)
                ).rstrip()
            )
            print()
        if not applied_setup.can_start_transmission:
            print(setup_application_warning_action_text("measurement_not_started"))
            return

        print("Taring all channels...")
        for entry in set_zero_all_channels(applied_setup):
            print(
                f"{entry['device_alias']}: "
                f"SetZero response: {entry['response']['raw_hex']}"
            )
        print()

        print("Starting transmission...")
        for entry in start_transmission(applied_setup):
            print(
                f"{entry['device_alias']}: "
                f"StartTransmission response: {entry['response']['raw_hex']}"
            )
        transmission_started = True
        print()

        for frame_index in range(1, frame_count + 1):
            for applied_device in applied_setup.devices:
                measurement_frame = (
                    applied_device.device.acquisition.read_next_measurement_frame()
                )
                measurement_record = create_measurement_record(
                    measurement_frame,
                    device=applied_device.device,
                )

                header = f"Frame {frame_index} - {applied_device.resolved_device.alias}"
                print(header)
                print("-" * len(header))
                print(format_measurement_record(measurement_record))
                print()

    except DeviceConnectionError as error:
        print()
        print("Opening device failed.")
        print(error)

    finally:
        if applied_setup is not None:
            if transmission_started:
                print("Stopping transmission...")
                try:
                    for entry in stop_transmission(applied_setup):
                        print(
                            f"{entry['device_alias']}: "
                            f"StopTransmission response: {entry['response']['raw_hex']}"
                        )
                except Exception as error:
                    print(f"StopTransmission failed: {error}")

            close_applied_devices(applied_setup.devices)
            print("Devices closed.")


def main() -> None:
    """Read values from the selected setup preset."""
    args = _parse_args()
    run_setup_read_values(
        get_setup_config(args.setup),
        frame_count=args.frame_count,
    )


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Apply one setup and print a small number of live frames."
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    parser.add_argument("--frame-count", type=int, default=FRAME_COUNT)
    args = parser.parse_args()
    if args.frame_count <= 0:
        parser.error("--frame-count must be positive.")
    print_cli_options(parser, args)
    return args



if __name__ == "__main__":
    main()
