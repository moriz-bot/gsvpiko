"""Apply one reusable setup to connected GSV devices without recording."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options

from ..output.output_report_print import (
    format_setup_application_warning_lines,
    format_setup_metadata_block_lines,
    format_setup_overview_lines,
    format_title_lines,
)
from ..coordination.coordination_setup_application import (
    close_applied_devices,
    open_and_apply_setup,
    setup_application_warning_action_text,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ..device.device_connection import DeviceConnectionError
from ..device.device_report import (
    print_baudrate_probe_result,
    print_channel_layout,
    print_configuration_report,
    print_connection_report,
)
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY


def main() -> None:
    """Open all setup devices, apply configuration, print reports, and close."""
    args = _parse_args()
    setup_config = get_setup_config(args.setup)
    resolved_setup = resolve_setup(setup_config)
    applied_setup = None

    lines = []
    lines.extend(format_title_lines("Setup application"))
    lines.extend(format_setup_overview_lines(resolved_setup, include_runtime=False))
    lines.append("")
    lines.extend(format_setup_metadata_block_lines(resolved_setup))
    print("\n".join(lines))
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

        warning_lines = format_setup_application_warning_lines(applied_setup.warnings)
        if warning_lines:
            print("\n".join(warning_lines).rstrip())
            print()

        if applied_setup.can_start_transmission:
            print("setup_application: ready_for_transmission=True")
        else:
            print("setup_application: ready_for_transmission=False")
            print(setup_application_warning_action_text("measurement_not_started"))

    except DeviceConnectionError as error:
        print()
        print("Opening device failed.")
        print(error)
    finally:
        if applied_setup is not None:
            close_applied_devices(applied_setup.devices)
            print("Devices closed.")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Apply one setup to hardware without starting transmission."
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    args = parser.parse_args()
    print_cli_options(parser, args)
    return args


if __name__ == "__main__":
    main()
