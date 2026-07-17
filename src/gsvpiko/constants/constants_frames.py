"""Frame-level constants for the GSV protocol."""

# Serial framing bytes
PREFIX = 0xAA
SUFFIX = 0x85

# Header byte layout
# Bits <7:6> = frame type
# Bits <5:4> = interface
# Bits <3:0> = length / object count field
FRAME_TYPE_SHIFT = 6
FRAME_TYPE_MASK = 0b11000000
INTERFACE_SHIFT = 4
INTERFACE_MASK = 0b00110000
LENGTH_MASK = 0b00001111

# Frame type values
MEASUREMENT = 0b00
RESPONSE = 0b01
REQUEST = 0b10
RESERVED = 0b11

# Interface values
CAN = 0b00
SERIAL = 0b01
LOGICAL = 0b10
SERIAL_WITH_CRC = 0b11

# Measurement status byte layout
# Bit 7    = indicator
# Bits 6:4 = datatype
# Bits 3:0 = error bits
# Bits 3:2 = reserved
# Bit 1    = six-axis error
# Bit 0    = input saturation
STATUS_INDICATOR_BIT = 7
STATUS_INDICATOR_MASK = 0b10000000
STATUS_DATATYPE_SHIFT = 4
STATUS_DATATYPE_MASK = 0b01110000
STATUS_ERROR_MASK = 0b00001111
STATUS_RESERVED_ERROR_BITS_MASK = 0b00001100
STATUS_SIX_AXIS_ERROR_BIT = 1
STATUS_SIX_AXIS_ERROR_MASK = 0b00000010
STATUS_INPUT_SATURATION_BIT = 0
STATUS_INPUT_SATURATION_MASK = 0b00000001

# Interface-dependent indicator values for measurement frames
CAN_MEASUREMENT_INDICATOR = 0
SERIAL_MEASUREMENT_INDICATOR = 1
CAN_MEASUREMENT_INDICATOR_MASKED = 0b00000000
SERIAL_MEASUREMENT_INDICATOR_MASKED = 0b10000000


# Length/object-count field semantics
# Request / response:
#   lower nibble = payload length
#
# Measurement frame:
#   lower nibble = object count minus 1
MEASUREMENT_OBJECT_COUNT_OFFSET = 1
