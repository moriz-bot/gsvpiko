"""Template setup configuration for GSVpiko.

Resolution order:
1. setup value, if it is not None
2. sensor default, if it exists and is not None
3. device default, if it exists and is not None

The source configuration dictionaries are not modified. GSVpiko builds a
resolved runtime configuration before writing settings to the device.

Order matters:
- attached_devices order defines GSV order in reports and CSV metadata.
- attached_sensors order defines channel allocation within the same socket.
- If several sensors share the same socket, they occupy that socket's channels
  sequentially according to their channel_count.
"""

from __future__ import annotations

from .. import config_devices as DEVICE
from .. import config_sensors as SENSOR

SETUP = {
    "name": "setup_template",
    "description": "Template with two GSV devices and several sensor examples.",
    # Connection overrides apply to all attached devices. None means: use the
    # corresponding default_* value from the device preset.
    "connection_type": None,
    "serial_interface": None,
    "use_nport": None,
    "configure_nport": None,

    # Runtime start/synchronization settings. Implemented combination:
    # software_parallel + free_run + receive_time. Hardware synchronization
    # modes are reserved configuration values.
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

                    # GSV-8 sockets are defined in constants_sockets.SOCKETS:
                    # "1/3"      = analogue channels 1, 2, 3
                    # "4/6"      = analogue channels 4, 5, 6
                    # "1/6"      = analogue channels 1..6, exclusive with "1/3" and "4/6"
                    # "7/8"      = analogue channels 7, 8
                    # "digital_io" = digital input/output lines, reserved for trigger/sync wiring
                    #
                    # Several sensors may share the same socket if their
                    # combined channel_count fits into the socket channel count.
                    "socket": "1/3",
                },
                {
                    "sensor": SENSOR.K3D40_24200770,
                    "alias": "sensor_ship_back",
                    "socket": "4/6",
                },
                # Digital sensors are represented as attached sensors for the
                # setup model, but the analogue setup application does not use
                # them.
                # {
                #     "sensor": SENSOR.DIGITAL_INPUT_TEMPLATE,
                #     "alias": "wind_tunnel_trigger",
                #     "socket": "digital_io",
                # },
            ],
        },
        {
            "device": DEVICE.GSV_24456057,
            "alias": "gsv_dock",
            "attached_sensors": [
                {
                    "sensor": SENSOR.K3D40_24200767,
                    "alias": "sensor_dock_front",
                    "socket": "1/3",
                },
            ],
        },
    ],

    # Allowed baudrates are defined in constants_baudrates.GSV8_UART_BAUDRATES or GSV8_RS422_BAUDRATES.
    "baudrate": 460800,

    # sample_rate_hz is the requested GSV output sample/frame rate, not the
    # fixed internal ADC conversion rate.
    "sample_rate_hz": 150.0,

    # Datatypes are defined in constants_datatypes.SUPPORTED_DATATYPE_NAMES:
    # "float32" = largest frame, directly parsed as float values
    # "int24"   = smaller frame, raw integer values
    # "int16"   = smallest frame, raw integer values
    "datatype": "float32",

    # Analogue filter cutoff frequency:
    # "low" = 28 Hz, "medium" = 850/885 Hz, "high" = 11400/11700 Hz,
    # or an integer Hz value accepted by the device.
    "analog_filter_hz": 28,

    "digital_filter": None,
    "crc_enabled": False,

    "discard_initial_frames": 0,
    "zero_before_recording": True,

    "output": {
        "directory_csv": "data",  # CSV measurement files.
        "directory_report": "logs",  # Text reports matching CSV sessions.
        "csv_decimal_separator": ".",  # supported: "." or ","; must differ from csv_delimiter
        "csv_delimiter": ",",  # supported: ",", ";", or "\t"; use ";" when decimal separator is ","
        "csv_encoding": "utf-8",  # Text encoding used for CSV and report files.
        "timestamp_format": "%Y%m%d_%H%M%S",  # Compact timestamp used in file names.
        "filename_template": (
            "{timestamp}_{session_name}__{setup_name}_{sample_rate_hz:g}Hz.csv"
        ),
        # supported filename placeholders: timestamp, session_name, setup_name, sample_rate_hz, datatype
        "include_metadata_header": True,  # Write setup/channel metadata as # comment lines.
        # supported: "datetime_iso", "timestamp_unix_s", "elapsed_s"
        "time_columns": ["datetime_iso", "elapsed_s"],
        "write_report_with_csv": True,  # Write a matching report file for each CSV recording.
    },
}
