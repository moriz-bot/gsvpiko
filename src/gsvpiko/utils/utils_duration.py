"""Small duration parsing helpers for command-line recording commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedDuration:
    """A parsed user-facing duration."""

    seconds: float
    text: str


_UNIT_SECONDS = {
    "s": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}


def parse_optional_duration(tokens: list[str]) -> ParsedDuration | None:
    """Parse an optional duration from command tokens.

    Supported forms are ``20 s``, ``20s``, ``30 m``, ``30m``, ``4 h`` and
    ``4h``. An empty token list means no duration was requested.
    """
    if not tokens:
        return None
    if len(tokens) == 1:
        number_text, unit_text = _split_number_and_unit(tokens[0])
    elif len(tokens) == 2:
        number_text, unit_text = tokens[0], tokens[1]
    else:
        raise ValueError("Use start, start 20 s, start 20s, start 30 m, start 30m, start 4 h or start 4h.")

    try:
        value = float(number_text)
    except ValueError as error:
        raise ValueError(f"Invalid duration value: {number_text!r}.") from error
    if value <= 0:
        raise ValueError("Duration must be greater than zero.")

    unit = unit_text.strip().lower()
    if unit not in _UNIT_SECONDS:
        raise ValueError("Invalid duration unit. Use s, m or h.")

    seconds = value * _UNIT_SECONDS[unit]
    return ParsedDuration(seconds=seconds, text=_format_duration_text(value, unit))


def _split_number_and_unit(token: str) -> tuple[str, str]:
    """Split a compact duration token into value and unit."""
    text = token.strip()
    if not text:
        raise ValueError("Duration token is empty.")
    index = 0
    while index < len(text) and (text[index].isdigit() or text[index] in ".,"):
        index += 1
    if index == 0 or index == len(text):
        raise ValueError("Use a duration such as 20 s or 20s.")
    return text[:index].replace(",", "."), text[index:]


def _format_duration_text(value: float, unit: str) -> str:
    """Return a compact normalized duration text."""
    normalized_unit = "s"
    if _UNIT_SECONDS[unit] == 60.0:
        normalized_unit = "m"
    elif _UNIT_SECONDS[unit] == 3600.0:
        normalized_unit = "h"
    value_text = f"{value:g}"
    return f"{value_text} {normalized_unit}"
