"""Shared setup-selection helpers for command-line entry points.

The apps keep a small in-file default setup key for the common case. The
optional --setup argument is only a convenience override, so changing the macro
in an app remains enough for repeated project-specific runs.
"""

from __future__ import annotations

import argparse
from typing import Iterable

from ..config import config_setups as SETUP

DEFAULT_SETUP_KEY = "TWO_GSVS_TWO_SENSORS_EACH"
# "ONE_GSV_ONE_SENSOR_1_3"
# "ONE_GSV_ONE_SENSOR_1_6"
# "THREE_GSVS_FOUR_SENSORS"
# "TWO_GSVS_ONE_SENSOR_EACH"
# "TWO_GSVS_TWO_SENSORS_EACH"


def setup_keys() -> tuple[str, ...]:
    """Return available setup preset keys, excluding the template preset."""
    return tuple(key for key in SETUP.__all__ if key != "SETUP_TEMPLATE")


def parse_setup_key(value: str) -> str:
    """Normalize one user-provided setup key.

    Users commonly type setup names in lowercase from logs. The project exports
    setup presets as uppercase constants, so accepting both keeps CLI use simple
    without introducing aliases in the setup registry.
    """
    normalized = value.strip().upper().replace("-", "_")
    if normalized not in setup_keys():
        valid = ", ".join(setup_keys())
        raise argparse.ArgumentTypeError(
            f"unknown setup {value!r}; valid values: {valid}"
        )
    return normalized


def add_setup_argument(
    parser: argparse.ArgumentParser,
    *,
    default_setup_key: str,
) -> None:
    """Add the shared optional setup selector to an argument parser."""
    parser.add_argument(
        "--setup",
        type=parse_setup_key,
        default=parse_setup_key(default_setup_key),
        help=(
            "Setup preset key. Valid values: "
            + ", ".join(key.lower() for key in setup_keys())
            + "."
        ),
    )


def get_setup_config(setup_key: str) -> dict:
    """Return the setup preset dictionary for a normalized setup key."""
    return getattr(SETUP, parse_setup_key(setup_key))


def format_setup_keys(keys: Iterable[str] | None = None) -> str:
    """Return setup keys in a compact, user-facing format."""
    return ", ".join((keys or setup_keys()))
