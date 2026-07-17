"""Protocol response status codes for GSV command replies.

Each constant behaves like the integer status byte returned by the GSV, but also
keeps a stable name and an English protocol description for diagnostics.
"""

from __future__ import annotations


class ProtocolError(int):
    """Integer GSV response status code with name and protocol description."""

    def __new__(cls, code: int, name: str, description: str):
        obj = int.__new__(cls, code)
        obj.name = name
        obj.description = description
        return obj

    def __str__(self) -> str:
        return self.name


OK = ProtocolError(
    0x00, "OK",
    "Command executed without error.",
)
OK_CHANGED = ProtocolError(
    0x01, "OK_CHANGED",
    "Command executed successfully; the device changed an additional value.",
)
CMD_NOT_KNOWN = ProtocolError(
    0x40, "CMD_NOT_KNOWN",
    "The command is unknown to the device.",
)
CMD_NOT_IMPLEMENTED = ProtocolError(
    0x41, "CMD_NOT_IMPLEMENTED",
    "The command is known but not implemented by this device or firmware.",
)
FRAME_ERROR = ProtocolError(
    0x42, "FRAME_ERROR",
    "The command frame is malformed or incomplete.",
)
COMMAND_CRC_ERROR = ProtocolError(
    0x43, "COMMAND_CRC_ERROR",
    "The command frame contains an invalid CRC.",
)
PARAMETER_ERROR = ProtocolError(
    0x50, "PARAMETER_ERROR",
    "One or more command parameters are invalid.",
)
PARAMETER_ADDRESS_ERROR = ProtocolError(
    0x51, "PARAMETER_ADDRESS_ERROR",
    "A parameter index or address is invalid.",
)
PARAMETER_DATA_ERROR = ProtocolError(
    0x52, "PARAMETER_DATA_ERROR",
    "A parameter value is invalid.",
)
PARAMETER_BITS_ERROR = ProtocolError(
    0x53, "PARAMETER_BITS_ERROR",
    "A parameter bit field is invalid.",
)
PARAMETER_ABSOLUTE_TOO_LARGE = ProtocolError(
    0x54, "PARAMETER_ABSOLUTE_TOO_LARGE",
    "A parameter value is above the absolute allowed range.",
)
PARAMETER_ABSOLUTE_TOO_SMALL = ProtocolError(
    0x55, "PARAMETER_ABSOLUTE_TOO_SMALL",
    "A parameter value is below the absolute allowed range.",
)
PARAMETER_COMBINATION_ERROR = ProtocolError(
    0x56, "PARAMETER_COMBINATION_ERROR",
    "The given parameter combination is invalid.",
)
PARAMETER_RELATIVE_TOO_LARGE = ProtocolError(
    0x57, "PARAMETER_RELATIVE_TOO_LARGE",
    "A parameter value is too high relative to another parameter or setting.",
)
PARAMETER_RELATIVE_TOO_SMALL = ProtocolError(
    0x58, "PARAMETER_RELATIVE_TOO_SMALL",
    "A parameter value is too low relative to another parameter or setting.",
)
PARAMETER_NOT_IMPLEMENTED = ProtocolError(
    0x59, "PARAMETER_NOT_IMPLEMENTED",
    "The parameter is not implemented for this command or device.",
)
PARAMETER_TIMEOUT = ProtocolError(
    0x5A, "PARAMETER_TIMEOUT",
    "The command parameters were not received within the required time.",
)
WRONG_PARAMETER_COUNT = ProtocolError(
    0x5B, "WRONG_PARAMETER_COUNT",
    "The command was sent with the wrong number of parameters.",
)
PARAMETER_DOES_NOT_MATCH_SETTINGS = ProtocolError(
    0x5C, "PARAMETER_DOES_NOT_MATCH_SETTINGS",
    "The parameter does not match the current device settings.",
)
PARAMETER_HARDWARE_COLLISION = ProtocolError(
    0x5D, "PARAMETER_HARDWARE_COLLISION",
    "The requested parameter or function conflicts with the available hardware.",
)
NO_DATA_AVAILABLE = ProtocolError(
    0x60, "NO_DATA_AVAILABLE",
    "Rejected upon read request because data is not available.",
)
DATA_INCONSISTENT = ProtocolError(
    0x61, "DATA_INCONSISTENT",
    "The stored data is inconsistent with the requested state.",
)
WRONG_MODULE_STATE = ProtocolError(
    0x62, "WRONG_MODULE_STATE",
    "The device or module is currently in an unsuitable state for the command.",
)
FUNCTION_NOT_SUPPORTED = ProtocolError(
    0x63, "FUNCTION_NOT_SUPPORTED",
    "The requested function is not supported by this device or firmware.",
)
DATA_RATE_TOO_HIGH = ProtocolError(
    0x64, "DATA_RATE_TOO_HIGH",
    "The requested data rate is too high for the device or communication path.",
)
MEMORY_WRONG_CONDITION = ProtocolError(
    0x6E, "MEMORY_WRONG_CONDITION",
    "The memory operation was requested under the wrong operating condition.",
)
MEMORY_ACCESS_DENIED = ProtocolError(
    0x6F, "MEMORY_ACCESS_DENIED",
    "The memory access was denied.",
)
ACCESS_DENIED = ProtocolError(
    0x70, "ACCESS_DENIED",
    "The command was rejected because access rights are missing.",
)
ACCESS_BLOCKED = ProtocolError(
    0x71, "ACCESS_BLOCKED",
    "The command was rejected because write access is currently blocked.",
)
ACCESS_PASSWORD_ERROR = ProtocolError(
    0x72, "ACCESS_PASSWORD_ERROR",
    "The password is wrong or not set.",
)
ACCESS_MAX_WRITE_EXCEEDED = ProtocolError(
    0x74, "ACCESS_MAX_WRITE_EXCEEDED",
    "The maximum number of allowed write operations was exceeded.",
)
ACCESS_PORT_DENIED = ProtocolError(
    0x75, "ACCESS_PORT_DENIED",
    "This communication port does not allow the requested access.",
)
ACCESS_READ_ONLY = ProtocolError(
    0x76, "ACCESS_READ_ONLY",
    "The command tried to write to a read-only parameter or state.",
)
INTERNAL = ProtocolError(
    0x80, "INTERNAL",
    "An internal device error occurred.",
)
ARITHMETIC = ProtocolError(
    0x81, "ARITHMETIC",
    "An internal arithmetic error occurred.",
)
ADC = ProtocolError(
    0x82, "ADC",
    "An A/D converter related device error occurred.",
)
MEASUREMENT_VALUE_ERROR = ProtocolError(
    0x83, "MEASUREMENT_VALUE_ERROR",
    "A measurement value was unsuitable for the requested command execution.",
)
EEPROM = ProtocolError(
    0x84, "EEPROM",
    "An EEPROM related device error occurred.",
)
EXTERNAL_HARDWARE = ProtocolError(
    0x85, "EXTERNAL_HARDWARE",
    "Required external hardware is missing or faulty.",
)
FILESYSTEM = ProtocolError(
    0x86, "FILESYSTEM",
    "A file-system driver error occurred.",
)
WRONG_DIRECTORY = ProtocolError(
    0x87, "WRONG_DIRECTORY",
    "The selected directory or directory setting is invalid.",
)
RETURN_TX_BUFFER_FULL = ProtocolError(
    0x91, "RETURN_TX_BUFFER_FULL",
    "Device transmission buffer is full.",
)
RETURN_BUSY = ProtocolError(
    0x92, "RETURN_BUSY",
    "The device CPU is busy and cannot execute the command now.",
)
RETURN_RX_BUFFER_FULL = ProtocolError(
    0x99, "RETURN_RX_BUFFER_FULL",
    "The receive buffer for command requests is full.",
)
TEDS_NO_SENSOR = ProtocolError(
    0xB0, "TEDS_NO_SENSOR",
    "No sensor is connected for the requested TEDS operation.",
)
TEDS_NO_TEDS_EEPROM = ProtocolError(
    0xB1, "TEDS_NO_TEDS_EEPROM",
    "No TEDS EEPROM was found on the connected sensor.",
)
TEDS_BASIC_ONLY = ProtocolError(
    0xB2, "TEDS_BASIC_ONLY",
    "Only Basic TEDS data is available.",
)
TEDS_INVALID_DATA = ProtocolError(
    0xB3, "TEDS_INVALID_DATA",
    "The TEDS data is invalid.",
)
TEDS_ENTRY_INVALID = ProtocolError(
    0xB4, "TEDS_ENTRY_INVALID",
    "The selected TEDS entry is invalid.",
)
TEDS_TIMEOUT = ProtocolError(
    0xB5, "TEDS_TIMEOUT",
    "The TEDS operation timed out.",
)
TEDS_CHECKSUM = ProtocolError(
    0xB6, "TEDS_CHECKSUM",
    "The TEDS checksum is invalid.",
)
TEDS_UNKNOWN_TEMPLATE = ProtocolError(
    0xB7, "TEDS_UNKNOWN_TEMPLATE",
    "The TEDS template is unknown.",
)
TEDS_VERIFY_FAILED = ProtocolError(
    0xB8, "TEDS_VERIFY_FAILED",
    "The TEDS verification failed.",
)
BLUETOOTH_CONFIG = ProtocolError(
    0xC0, "BLUETOOTH_CONFIG",
    "A Bluetooth configuration error occurred.",
)

_PROTOCOL_ERRORS_BY_CODE = {
    int(value): value
    for value in globals().values()
    if isinstance(value, ProtocolError)
}


def protocol_error_from_code(code: int) -> ProtocolError | None:
    """Return the protocol-error object for one response status code."""
    return _PROTOCOL_ERRORS_BY_CODE.get(int(code))
