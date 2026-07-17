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

    name_parts = [parts[0].upper()]
    index = 1
    if index < len(parts) and parts[index].upper() in {"LIST", "USE", "PATH?", "CONNECTION", "ERRORS", "ERROR"}:
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


def parse_bool(value: str, *, default: bool | None = None) -> bool:
    """Parse a protocol boolean value."""
    if value is None:
        if default is None:
            raise ValueError("Boolean value is missing.")
        return default

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value {value!r}.")


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
