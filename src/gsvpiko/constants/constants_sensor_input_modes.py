"""Sensor input mode constants and helpers for GSV-8 analogue inputs.

The first three bridge modes can be addressed in two equivalent ways:
- by bridge excitation voltage
- by the resulting input sensitivity

Examples:
- "bridge_8_75v" == "bridge_2_0_mv_per_v"
- "bridge_5v"    == "bridge_3_5_mv_per_v"
- "bridge_2_5v"  == "bridge_7_0_mv_per_v"
"""

BRIDGE_8_75V = 0
BRIDGE_5V = 1
BRIDGE_2_5V = 2
SINGLE_ENDED = 3
PT1000 = 4
K_TYPE_ABSOLUTE = 5
K_TYPE_RELATIVE = 6
COUNTER_FREQUENCY = 7


MODE_DEFINITIONS = {
    BRIDGE_8_75V: {
        "canonical_name": "bridge_8_75v",
        "aliases": {"bridge_8_75v", "bridge_2_0_mv_per_v", 0},
        "excitation_voltage_v": 8.75,
        "input_sensitivity_mv_per_v": 2.0,
    },
    BRIDGE_5V: {
        "canonical_name": "bridge_5v",
        "aliases": {"bridge_5v", "bridge_3_5_mv_per_v", 1},
        "excitation_voltage_v": 5.0,
        "input_sensitivity_mv_per_v": 3.5,
    },
    BRIDGE_2_5V: {
        "canonical_name": "bridge_2_5v",
        "aliases": {"bridge_2_5v", "bridge_7_0_mv_per_v", 2},
        "excitation_voltage_v": 2.5,
        "input_sensitivity_mv_per_v": 7.0,
    },
    SINGLE_ENDED: {
        "canonical_name": "single_ended",
        "aliases": {"single_ended", 3},
        "excitation_voltage_v": None,
        "input_sensitivity_mv_per_v": None,
    },
    PT1000: {
        "canonical_name": "pt1000",
        "aliases": {"pt1000", 4},
        "excitation_voltage_v": None,
        "input_sensitivity_mv_per_v": None,
    },
    K_TYPE_ABSOLUTE: {
        "canonical_name": "k_type_absolute",
        "aliases": {"k_type_absolute", 5},
        "excitation_voltage_v": None,
        "input_sensitivity_mv_per_v": None,
    },
    K_TYPE_RELATIVE: {
        "canonical_name": "k_type_relative",
        "aliases": {"k_type_relative", 6},
        "excitation_voltage_v": None,
        "input_sensitivity_mv_per_v": None,
    },
    COUNTER_FREQUENCY: {
        "canonical_name": "counter_frequency",
        "aliases": {"counter_frequency", 7},
        "excitation_voltage_v": None,
        "input_sensitivity_mv_per_v": None,
    },
}


ALIASES = {
    alias: mode
    for mode, definition in MODE_DEFINITIONS.items()
    for alias in definition["aliases"]
}


def normalize_sensor_input_mode(value: str | int | None) -> int | None:
    """Normalize one sensor-input-mode selector to its canonical enum value."""
    if value is None:
        return None

    key = value.strip().lower() if isinstance(value, str) else value

    try:
        return ALIASES[key]
    except KeyError as error:
        raise ValueError(f"Unsupported sensor input mode: {value!r}") from error


def get_input_sensitivity_mv_per_v(mode: int | None) -> float | None:
    """Return the input sensitivity linked to one canonical mode."""
    if mode is None:
        return None

    try:
        return MODE_DEFINITIONS[mode]["input_sensitivity_mv_per_v"]
    except KeyError as error:
        raise ValueError(f"Unsupported sensor input mode: {mode!r}") from error


def get_excitation_voltage_v(mode: int | None) -> float | None:
    """Return the bridge excitation voltage linked to one canonical mode."""
    if mode is None:
        return None

    try:
        return MODE_DEFINITIONS[mode]["excitation_voltage_v"]
    except KeyError as error:
        raise ValueError(f"Unsupported sensor input mode: {mode!r}") from error
