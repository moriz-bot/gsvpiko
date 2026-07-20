"""Diagnose currently reachable non-mutating GSV connection paths."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options

from ..coordination.coordination_diagnostics import diagnose_setup_connection
from ..output.output_report_print import (
    format_connection_diagnostic_lines,
    format_title_lines,
)
from ..coordination.coordination_setup_resolution import resolve_setup
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY


def main() -> None:
    """Print non-mutating connection diagnostics for all devices in one setup."""
    args = _parse_args()
    setup_config = get_setup_config(args.setup)
    resolved_setup = resolve_setup(setup_config)
    results = diagnose_setup_connection(setup_config)

    lines = []
    lines.extend(format_title_lines("Setup connection diagnostics"))
    lines.append(f"setup_name: {resolved_setup.name}")
    lines.append("connection_policy: non_mutating_adaptive")
    lines.append("")
    for result in results:
        lines.extend(format_connection_diagnostic_lines(result))
        lines.append("")
    print("\n".join(lines).rstrip())


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Check currently reachable GSV connection paths for one setup."
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    args = parser.parse_args()
    print_cli_options(parser, args)
    return args


if __name__ == "__main__":
    main()
