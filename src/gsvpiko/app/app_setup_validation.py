"""Validate and print one reusable GSVpiko setup."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options

from ..output.output_report_print import (
    format_sample_rate_limit_lines,
    format_setup_metadata_block_lines,
    format_setup_overview_lines,
    format_streamed_channels_lines,
    format_title_lines,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY


def run_setup_validation(
    setup_config: dict,
    *,
    title: str = "Setup validation",
) -> None:
    """Resolve one setup and print the resulting static configuration."""
    try:
        resolved = resolve_setup(setup_config)
    except Exception as error:
        lines = []
        lines.extend(format_title_lines(title))
        lines.append("validation: invalid")
        lines.append(f"error_type: {type(error).__name__}")
        lines.extend(str(error).splitlines())
        print("\n".join(lines).rstrip())
        return

    lines = []
    lines.extend(format_title_lines(title))
    lines.extend(format_setup_overview_lines(resolved))
    lines.append("validation: valid")
    lines.append("")
    lines.extend(format_setup_metadata_block_lines(resolved))
    lines.append("")
    lines.extend(format_streamed_channels_lines(resolved))
    lines.append("")
    lines.extend(format_sample_rate_limit_lines(resolved))
    print("\n".join(lines).rstrip())


def main() -> None:
    """Validate the selected setup preset."""
    args = _parse_args()
    run_setup_validation(
        get_setup_config(args.setup),
        title="Setup validation",
    )


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Validate one GSVpiko setup preset.")
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    args = parser.parse_args()
    print_cli_options(parser, args)
    return args


if __name__ == "__main__":
    main()
