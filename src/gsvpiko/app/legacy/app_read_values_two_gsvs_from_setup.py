"""Read measurement values using the two-GSV setup preset."""

from __future__ import annotations

from ..config import config_setups as SETUP
from .app_read_values_from_setup import run_setup_read_values


def main() -> None:
    """Read one frame per device from the two-GSV setup."""
    run_setup_read_values(
        SETUP.TWO_GSVS_ONE_SENSOR_EACH,
        title="Two-GSV setup read-values app",
    )


if __name__ == "__main__":
    main()
