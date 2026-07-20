"""ASCII command parsing for the external GSVpiko control interface."""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex


@dataclass(frozen=True)
class ExternalCommand:
    """One parsed ASCII command line."""

    name: str
    args: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)
    raw: str = ""


def parse_command(line: str) -> ExternalCommand:
    """Parse one ASCII command line into name, positional args, and key values."""
    raw = line.rstrip("\r\n")
    parts = shlex.split(raw)
    if not parts:
        return ExternalCommand(name="", raw=raw)

    first = parts[0].upper()
    name_parts = [first]
    index = 1
    second_command_words = _second_command_words(first)
    if index < len(parts) and parts[index].upper() in second_command_words:
        name_parts.append(parts[index].upper())
        index += 1

    args: list[str] = []
    options: dict[str, str] = {}
    for part in parts[index:]:
        if "=" in part:
            key, value = part.split("=", 1)
            options[key.strip().lower()] = value.strip()
        else:
            args.append(part)

    return ExternalCommand(
        name=" ".join(name_parts),
        args=args,
        options=options,
        raw=raw,
    )


def _second_command_words(first: str) -> set[str]:
    """Return allowed second command words for a first command token."""
    if first == "SETUP":
        return {"LIST", "USE"}
    if first == "PATH":
        return {"SET", "RESET"}
    if first in {"CSV", "REPORT"}:
        return {"PATH"}
    if first == "DIAG":
        return {"CONNECTION", "ERRORS", "ERROR"}
    return set()


def ok(message: str, **fields: object) -> str:
    """Return one OK response line."""
    return _format_response("OK", message, fields)


def err(message: str, **fields: object) -> str:
    """Return one ERR response line."""
    return _format_response("ERR", message, fields)


def _format_response(prefix: str, message: str, fields: dict[str, object]) -> str:
    """Format a machine-readable single-line response."""
    parts = [prefix, message]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ")
        if any(char.isspace() for char in text):
            text = shlex.quote(text)
        parts.append(f"{key}={text}")
    return " ".join(parts)
