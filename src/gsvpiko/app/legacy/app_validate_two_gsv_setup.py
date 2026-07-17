"""Validate the two-GSV setup without opening hardware connections."""

from __future__ import annotations

from ..config import config_setups as SETUP
from .app_validate_setup import run_setup_validation


def main() -> None:
    """Validate the two-GSV setup."""
    run_setup_validation(
        SETUP.TWO_GSVS_ONE_SENSOR_EACH,
        title="Two-GSV setup validation",
    )


if __name__ == "__main__":
    main()
