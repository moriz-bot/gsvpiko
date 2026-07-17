"""Measurement-frame datatype constants."""

from __future__ import annotations

INT16 = 0b001
INT24 = 0b010
FLOAT32 = 0b011

BYTES_PER_VALUE = {
    INT16: 2,
    INT24: 3,
    FLOAT32: 4,
}

NAMES = {
    INT16: "int16",
    INT24: "int24",
    FLOAT32: "float32",
}

SUPPORTED_DATATYPES = (
    INT16,
    INT24,
    FLOAT32,
)

SUPPORTED_DATATYPE_NAMES = tuple(
    NAMES[value]
    for value in SUPPORTED_DATATYPES
)

ALIASES = {
    INT16: ("int16", "i16", 1, "1"),
    INT24: ("int24", "s24", "i24", 2, "2"),
    FLOAT32: ("float32", "float", "f32", 3, "3"),
}

_ALIAS_TO_DATATYPE = {}
for _datatype, _aliases in ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_DATATYPE[_alias] = _datatype


def normalize_datatype(
    datatype: int | str,
) -> int:
    """Return one supported measurement-frame datatype enum."""
    if isinstance(datatype, str):
        normalized = datatype.strip().lower()
    else:
        normalized = int(datatype)

    try:
        result = _ALIAS_TO_DATATYPE[normalized]
    except KeyError as error:
        raise ValueError(
            f"Unsupported datatype {datatype!r}. "
            f"Supported datatype names are: {SUPPORTED_DATATYPE_NAMES}."
        ) from error

    return result


def get_name(
    datatype: int | str,
) -> str:
    """Return the canonical datatype name."""
    return NAMES[normalize_datatype(datatype)]


def get_value_byte_count(
    datatype: int | str,
) -> int:
    """Return the number of payload bytes used by one measurement value."""
    return BYTES_PER_VALUE[normalize_datatype(datatype)]
