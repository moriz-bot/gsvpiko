"""Plot selected channels from a GSVpiko CSV recording."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._cli_options import print_cli_options
from ..output.output_plot import (
    available_channels,
    format_channel_list,
    plot_gsvpiko_csv,
)


def main() -> None:
    """Plot all or selected measurement channels from one CSV file."""
    args = _parse_args()
    csv_path = Path(args.csv_path)

    if args.list_channels:
        print("\n".join(format_channel_list(available_channels(csv_path))))
        return

    output_path = plot_gsvpiko_csv(
        csv_path,
        output_path=args.output,
        channels=args.channels,
        channel_indices=args.channel_indices,
    )
    print(f"graph: {output_path}")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Plot all or selected channels from a GSVpiko CSV recording."
    )
    parser.add_argument("csv_path", help="Path to the GSVpiko CSV file.")
    parser.add_argument(
        "--channels",
        nargs="+",
        default=None,
        help="Channel names to plot, for example F1z,F2z or F1z F2z.",
    )
    parser.add_argument(
        "--channel-indices",
        default=None,
        help=(
            "1-based channel indices to plot, excluding time columns. "
            "Comma lists and ranges are supported, for example 3,6,9,12 or 1-4."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output PNG path. If omitted, a name is derived from the CSV path.",
    )
    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="Print available channel names and exit without plotting.",
    )
    args = parser.parse_args()
    print_cli_options(parser, args)
    if args.channels and args.channel_indices:
        parser.error("--channels and --channel-indices cannot be used together.")
    return args


if __name__ == "__main__":
    main()
