"""Read measurement frames from one sensor on the first GSV socket."""

from __future__ import annotations

from ..config import config_devices as DEVICE
from ..config import config_sensors as SENSOR
from .app_read_values_common import run_read_values


DEVICE_CONFIG = DEVICE.GSV_24456060
FRAME_COUNT = 1


def main() -> None:
    run_read_values(
        device_config=DEVICE_CONFIG,
        sensor_attachments=[
            (SENSOR.K3D40_24200767, [1, 2, 3], 1),
        ],
        frame_count=FRAME_COUNT,
    )


if __name__ == "__main__":
    main()
