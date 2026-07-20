"""Run the external TCP control interface for GSVpiko."""

from __future__ import annotations

import argparse

from ._cli_options import print_cli_options
from ..external.external_tcp_interface import DEFAULT_HOST, DEFAULT_PORT, run_server


def main() -> None:
    """Start the external TCP control interface."""
    parser = argparse.ArgumentParser(description="Run the GSVpiko external TCP interface.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    print_cli_options(parser, args)
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
