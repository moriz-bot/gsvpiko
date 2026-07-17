"""Template device configuration for GSVpiko.

Resolution order:
1. setup value, if it is not None
2. sensor default, if it exists and is not None
3. device default, if it exists and is not None

The source configuration dictionaries are not modified. GSVpiko builds a
resolved runtime configuration before writing settings to the device.

Device-only values, such as com_port, ip_address, tcp_port, default_connection_type, and
gsv_serial_number, are not overwritten by sensor presets. Setup-level values
apply to all attached devices in the setup. Per-device overrides require
explicit validation support before they are introduced.
"""

GSV8_SERIAL_REALCOM_TEMPLATE = {
    "name": "GSV_00000000",
    "manufacturer": "ME-Messsysteme GmbH",
    "model_name": "GSV-8DS SubD44HD",
    "gsv_serial_number": 0,

    # Supported connection types in GSVpiko: "serial", "tcp".
    "default_connection_type": "serial",
    "default_serial_interface": "uart",  # "uart" or "rs422"
    "default_use_nport": True,
    "default_configure_nport": True,
    "default_nport_username": "admin",
    "default_nport_password": "moxa",

    # Target baudrate for serial communication.
    # Allowed baudrates are defined in constants_baudrates.GSV8_UART_BAUDRATES or GSV8_RS422_BAUDRATES.
    # If the active GSV baudrate differs, GSVpiko can store this value for the
    # next power cycle. A setup measurement must not start until the active
    # baudrate matches the setup baudrate.
    "default_baudrate": 460800,

    # sample_rate_hz is the requested GSV output sample/frame rate, not the
    # fixed internal ADC conversion rate. Setup-level values override this default.
    "default_sample_rate_hz": None,

    # Datatypes are defined in constants_datatypes.SUPPORTED_DATATYPE_NAMES.
    "default_datatype": "float32",

    # CRC adds bytes to each frame and lowers the serial sample-rate limit.
    "default_crc_enabled": False,

    # RealCOM / serial-device-server metadata.
    # For default_connection_type="serial", com_port is used by pyserial.
    # For default_connection_type="tcp", ip_address and tcp_port are used by the TCP
    # transport.
    "ip_address": "192.168.10.000",
    "com_port": "COM0",
    "tcp_port": 4001,
    "nport_realcom_data_port": 950,
    "nport_command_port": 966,
    "nport_http_port": 80,
}
