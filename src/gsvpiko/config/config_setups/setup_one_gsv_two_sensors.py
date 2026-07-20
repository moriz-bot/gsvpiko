"""Setup preset for one GSV-8 with two 3-axis force sensors."""

from __future__ import annotations

from .. import config_devices as DEVICE
from .. import config_sensors as SENSOR

SETUP = {
    "name": "one_gsv_two_sensors",
    "description": "One GSV-8 with two connected 3-axis force sensors.",
    "connection_type": None,
    "serial_interface": None,
    "use_nport": None,
    "configure_nport": None,

    "start_mode": "software_parallel",
    "sync_mode": "free_run",
    "timebase_mode": "receive_time",

    "attached_devices": [
        {
            "device": DEVICE.GSV_24456060,
            "alias": "gsv_ship",
            "attached_sensors": [
                {
                    "sensor": SENSOR.K3D40_24200767,
                    "alias": "sensor_ship_front",
                    "socket": "1/3",
                },
                {
                    "sensor": SENSOR.K3D40_24200770,
                    "alias": "sensor_ship_back",
                    "socket": "4/6",
                },
            ],
        },
    ],

    "baudrate": 230400,
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
