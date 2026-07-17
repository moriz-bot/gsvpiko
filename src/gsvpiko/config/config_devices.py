"""Known GSV amplifier connection presets."""

GSV_24456057 = {
    "name": "GSV_24456057",
    "manufacturer": "ME-Messsysteme GmbH",
    "model_name": "GSV-8DS SubD44HD",
    "gsv_serial_number": 24456057,

    "default_connection_type": "serial",  # "serial" or "tcp"
    "default_serial_interface": "uart",
    "default_use_nport": True,
    "default_configure_nport": True,
    "default_nport_username": "admin",
    "default_nport_password": "moxa",
    "default_baudrate": 460800,
    "default_sample_rate_hz": 10.0,
    "default_datatype": "float32",
    "default_crc_enabled": False,

    "ip_address": "192.168.10.113",
    "com_port": "COM1",
    "tcp_port": 4001,
    "nport_realcom_data_port": 950,
    "nport_command_port": 966,
    "nport_http_port": 80,
}

GSV_24456060 = {
    "name": "GSV_24456060",
    "manufacturer": "ME-Messsysteme GmbH",
    "model_name": "GSV-8DS SubD44HD",
    "gsv_serial_number": 24456060,

    "default_connection_type": "serial",  # "serial" or "tcp"
    "default_serial_interface": "uart",
    "default_use_nport": True,
    "default_configure_nport": True,
    "default_nport_username": "admin",
    "default_nport_password": "moxa",
    "default_baudrate": 460800,
    "default_sample_rate_hz": 10.0,
    "default_datatype": "float32",
    "default_crc_enabled": False,

    "ip_address": "192.168.10.115",
    "com_port": "COM2",
    "tcp_port": 4001,
    "nport_realcom_data_port": 950,
    "nport_command_port": 966,
    "nport_http_port": 80,
}

GSV_24456058 = {
    "name": "GSV_24456058",
    "manufacturer": "ME-Messsysteme GmbH",
    "model_name": "GSV-8DS SubD44HD",
    "gsv_serial_number": 24456058,

    "default_connection_type": "serial",  # "serial" or "tcp"
    "default_serial_interface": "uart",
    "default_use_nport": True,
    "default_configure_nport": True,
    "default_nport_username": "admin",
    "default_nport_password": "moxa",
    "default_baudrate": 460800,
    "default_sample_rate_hz": 10.0,
    "default_datatype": "float32",
    "default_crc_enabled": False,

    "ip_address": "192.168.10.116",
    "com_port": "COM3",
    "tcp_port": 4001,
    "nport_realcom_data_port": 950,
    "nport_command_port": 966,
    "nport_http_port": 80,
}

DEFAULT_DEVICE = GSV_24456060

DEVICE_PRESETS = {
    "GSV_24456057": GSV_24456057,
    "GSV_24456060": GSV_24456060,
    "GSV_24456058": GSV_24456058,
}
