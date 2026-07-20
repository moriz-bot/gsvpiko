"""Manual TCP client for the GSVpiko external control interface."""

from __future__ import annotations

import argparse
import socket

from ._cli_options import print_cli_options

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_TIMEOUT_S = 180.0


def main() -> None:
    """Run an interactive line-based TCP control client."""
    parser = argparse.ArgumentParser(
        description="Run a manual TCP client for the GSVpiko external control interface."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    print_cli_options(parser, args)

    with socket.create_connection((args.host, args.port), timeout=args.timeout_s) as socket_connection:
        socket_connection.settimeout(args.timeout_s)
        file = socket_connection.makefile("rw", encoding="utf-8", newline="\n")

        while True:
            command = input(">>> ").strip()
            if not command:
                continue

            file.write(command + "\n")
            file.flush()

            response = file.readline()
            if response == "":
                print("<<< <connection closed>")
                break

            print("<<<", response.strip())
            if command.upper() == "QUIT":
                break


if __name__ == "__main__":
    main()
