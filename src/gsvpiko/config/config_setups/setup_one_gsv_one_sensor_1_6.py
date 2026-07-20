"""Setup preset for one GSV-8 device with one 3-axis force sensor on socket 1/6."""

from __future__ import annotations

from .. import config_devices as DEVICE
from .. import config_sensors as SENSOR

SETUP = {
    "name": "one_gsv_one_sensor_1_6",
    "description": (
        "One GSV-8 device with one 3-axis force sensor on the 1/6 SubD44HD socket, "
        "using NPort TCP Server Mode at 10 Hz."
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
            "device": DEVICE.GSV_24456060,
            "alias": "gsv_ship",
            "attached_sensors": [
                {
                    "sensor": SENSOR.K3D40_25202514,
                    "alias": "sensor_ship_front",
                    "socket": "1/6",
                },
            ],
        },
    ],

    "baudrate": 460800,
    "sample_rate_hz": 10.0,
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
