"""Physical quantity constants and channel symbol helpers."""

FORCE = "force"
TORQUE = "torque"
TEMPERATURE = "temperature"
PRESSURE = "pressure"
DISPLACEMENT = "displacement"
VOLTAGE = "voltage"
CURRENT = "current"
FREQUENCY = "frequency"
STRAIN = "strain"
ACCELERATION = "acceleration"

SYMBOLS = {
    FORCE: "F",
    TORQUE: "M",
    TEMPERATURE: "T",
    PRESSURE: "P",
    DISPLACEMENT: "D",
    VOLTAGE: "U",
    CURRENT: "I",
    FREQUENCY: "FRQ",
    STRAIN: "E",
    ACCELERATION: "A",
}


def get_symbol(quantity_type: str) -> str:
    """Return the short channel symbol for one physical quantity."""
    try:
        return SYMBOLS[quantity_type]
    except KeyError as error:
        raise ValueError(f"Unsupported quantity type: {quantity_type!r}") from error
