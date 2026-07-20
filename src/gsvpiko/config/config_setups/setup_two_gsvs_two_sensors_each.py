"""Setup preset for two GSV-8 devices with two 3-axis force sensors each."""

from __future__ import annotations

from .. import config_devices as DEVICE
from .. import config_sensors as SENSOR

SETUP = {
    "name": "two_gsvs_two_sensors_each",
    "description": (
        "Two GSV-8 devices with front/back 3-axis force sensors, "
        "using NPort TCP Server Mode at 150 Hz."
    ),
    "connection_type": "tcp",
    "serial_interface": "uart",
    "use_nport": True,
    "configure_nport": True,

    "start_mode": "software_parallel",
    "sync_mode": "free_run",
    "timebase_mode": "receive_time",

    "attached_devices": [
        {
            "device": DEVICE.GSV_24456057,
            "alias": "gsv_dock",
            "attached_sensors": [
                {
                    "sensor": SENSOR.K3D40_24200767,
                    "alias": "sensor_dock_front",
                    "socket": "1/3",
                },
                {
                    "sensor": SENSOR.K3D40_24200770,
                    "alias": "sensor_dock_back",
                    "socket": "4/6",
                },
            ],
        },
        {
            "device": DEVICE.GSV_24456060,
            "alias": "gsv_ship",
            "attached_sensors": [
                {
                    "sensor": SENSOR.K3D40_25202514,
                    "alias": "sensor_ship_front",
                    "socket": "1/3",
                },
                {
                    "sensor": SENSOR.K3D40_25202515,
                    "alias": "sensor_ship_back",
                    "socket": "4/6",
                },
            ],
        },
    ],

    "baudrate": 460800,
    "sample_rate_hz": 150.0,
    "datatype": "float32",
    "analog_filter_hz": 28,
    "digital_filter": None,
    "crc_enabled": False,

    "discard_initial_frames": 0,
    "zero_before_recording": True,

    "output": {
        "directory_csv": "gsvpiko_data",
        "directory_report": "gsvpiko_logs",
        "csv_decimal_separator": ".",
        "csv_delimiter": ",",
        "csv_encoding": "utf-8",
        "timestamp_format": "%Y%m%d_%H%M%S",
        "filename_template": (
            "{timestamp}_{session_name}__{setup_name}_{sample_rate_hz:g}Hz.csv"
        ),
        "include_metadata_header": True,
        "time_columns": ["datetime_iso", "timestamp_unix_s", "elapsed_s"],
        "write_report_with_csv": True,
    },
}
