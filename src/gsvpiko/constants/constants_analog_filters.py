"""Analog filter constants for GSV-8.

Accepted user-facing values:
- low / 28
- medium / 850 / 885
- high / 11400 / 11700

The normalized values follow the GSVmulti display style:
- 28
- 850
- 11700
"""

HIGH = 11700
LOW = 28
MEDIUM = 850

ALIASES = {
    "high": HIGH,
    "low": LOW,
    "medium": MEDIUM,
    28: LOW,
    850: MEDIUM,
    885: MEDIUM,
    11400: HIGH,
    11700: HIGH,
}


def normalize_analog_filter(value: str | int | float | None) -> int | None:
    """Normalize one analog filter selector to the GSVmulti-style Hz value."""
    if value is None:
        return None

    if isinstance(value, float):
        value = int(round(value))

    if isinstance(value, int):
        try:
            return ALIASES[value]
        except KeyError as error:
            raise ValueError(f"Unsupported analog filter value: {value!r}") from error

    if isinstance(value, str):
        key = value.strip().lower()
        try:
            return ALIASES[key]
        except KeyError as error:
            raise ValueError(f"Unsupported analog filter value: {value!r}") from error

    raise TypeError(f"Unsupported analog filter selector type: {type(value).__name__}")
