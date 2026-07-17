"""Diagnose GSV device status flags and error memories without changing setup."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from ._cli_options import print_cli_options

from ..coordination.coordination_diagnostics import (
    diagnose_setup_errors,
    format_device_status_error_report_lines,
)
from ..coordination.coordination_report_print import format_title_lines
from ._setup_selection import DEFAULT_SETUP_KEY, add_setup_argument, get_setup_config

SETUP_KEY = DEFAULT_SETUP_KEY
DEFAULT_ERROR_INDICES = tuple(range(84))
DEFAULT_HISTORY_WINDOW_H = 4.0


@dataclass(frozen=True)
class _Section:
    """One formatted diagnostic section with parsed addressing metadata."""

    title: str
    lines: list[str]
    kind: str
    index: int | None


def main() -> None:
    """Run status/error diagnostics for all devices in the selected setup."""
    args = _parse_args()
    setup_config = get_setup_config(args.setup)
    results = diagnose_setup_errors(setup_config, error_indices=DEFAULT_ERROR_INDICES)

    lines = []
    lines.extend(format_title_lines("Setup status and error diagnostics"))
    lines.append(f"diagnostic_time_utc: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"setup_name: {setup_config.get('name', '<unnamed>')}")
    lines.append("protocol_errors: index 0=synchronous, index 1=asynchronous")
    lines.append("connection_policy: non_mutating_adaptive")
    lines.append("erase_error_memory: False")
    lines.append(f"display: {'all_entries' if args.show_all else 'current_plus_recent_history'}")
    lines.append(f"history_window_h: {args.history_window_h:g}")
    lines.append(f"show_frames: {str(args.show_frames or args.show_all).lower()}")
    lines.append("")

    for result in results:
        device_lines = format_device_status_error_report_lines(result)
        hours = result.device_hours_h
        device_lines = _annotate_value_error_times(device_lines, device_hours_h=hours)
        if not args.show_all:
            device_lines = _filter_error_report_lines(
                device_lines,
                show_history=args.show_history,
                history_window_h=args.history_window_h,
            )
        device_lines = _insert_device_hours_after_header(device_lines, hours)
        device_lines = _format_user_facing_lines(
            device_lines,
            show_frames=args.show_frames or args.show_all,
        )
        lines.extend(device_lines)
        lines.append("")
    print("\n".join(lines).rstrip())


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read non-destructive GSV status and error diagnostics."
    )
    add_setup_argument(parser, default_setup_key=SETUP_KEY)
    parser.add_argument(
        "--show-all",
        action="store_true",
        help=(
            "Show all diagnostic entries, including OK entries, empty value-error "
            "entries, unavailable indices, mode flags, and connection details."
        ),
    )
    parser.add_argument(
        "--show-history",
        action="store_true",
        help=(
            "Show all read nonvolatile value-error history entries. Without this option, "
            "history is limited to entries since power-on and entries within the recent "
            "history window."
        ),
    )
    parser.add_argument(
        "--history-window-h",
        type=float,
        default=DEFAULT_HISTORY_WINDOW_H,
        help="Recent-history window in device operating hours. Default: 4.",
    )
    parser.add_argument(
        "--show-frames",
        action="store_true",
        help="Show raw request/response/payload hex fields and OK request statuses.",
    )
    args = parser.parse_args()
    if args.history_window_h < 0:
        parser.error("--history-window-h must be non-negative.")
    print_cli_options(parser, args)
    return args


def _filter_error_report_lines(
    lines: list[str],
    *,
    show_history: bool,
    history_window_h: float,
) -> list[str]:
    """Keep current/recent diagnostic sections and hide old EEPROM history by default."""
    if len(lines) < 2:
        return lines

    header = lines[:2]
    body = lines[2:]
    sections = [_parse_section(section) for section in _split_sections(body)]
    value_power_on_count = _power_on_error_count(sections)
    newest_history_indices = _newest_history_indices(sections, value_power_on_count)

    kept: list[_Section] = []
    for section in sections:
        if _keep_section(
            section,
            show_history=show_history,
            history_window_h=history_window_h,
            newest_history_indices=newest_history_indices,
        ):
            kept.append(section)

    if not kept:
        return [*header, "no current or recent diagnostic error entries"]

    filtered = list(header)
    for section in kept:
        if filtered and filtered[-1] != "":
            filtered.append("")
        filtered.extend(section.lines)
    return filtered


def _keep_section(
    section: _Section,
    *,
    show_history: bool,
    history_window_h: float,
    newest_history_indices: set[int],
) -> bool:
    """Return whether one section belongs in the default diagnostic view."""
    text = "\n".join(section.lines)

    if section.kind == "protocol":
        return section.index in {0, 1}

    if section.kind == "value":
        if section.index == 0:
            return True
        if section.index == 1:
            return True
        if section.index is None or section.index < 2:
            return False
        if not _is_relevant_value_error_text(text):
            return False
        if show_history:
            return True
        if section.index in newest_history_indices:
            return True
        age_h = _parse_float_after_label(text, "age_h")
        return age_h is not None and age_h <= history_window_h

    if "diagnostic_error:" in text and "PARAMETER_ADDRESS_ERROR" not in text:
        return True

    return False


def _is_relevant_value_error_text(text: str) -> bool:
    """Return whether a value-error section contains a real error entry."""
    if "decoded_summary: no value errors since power-on" in text:
        return False
    if "decoded_summary: no current error" in text:
        return False
    if "decoded_error_type: NO_CURRENT_VALUE_ERROR" in text:
        return False
    if "PARAMETER_ADDRESS_ERROR" in text:
        return False
    return "decoded_summary:" in text or "diagnostic_error:" in text


def _power_on_error_count(sections: list[_Section]) -> int:
    """Return the value-error power-on counter from index 0 if available."""
    for section in sections:
        if section.kind != "value" or section.index != 0:
            continue
        text = "\n".join(section.lines)
        match = re.search(r"decoded_counters: power_on=(\d+),", text)
        if match:
            return int(match.group(1))
    return 0


def _newest_history_indices(sections: list[_Section], count: int) -> set[int]:
    """Return the newest nonvolatile history indices represented by read sections."""
    if count <= 0:
        return set()
    indices = sorted(
        section.index
        for section in sections
        if section.kind == "value"
        and section.index is not None
        and section.index >= 2
        and _is_relevant_value_error_text("\n".join(section.lines))
    )
    return set(indices[-count:])


def _annotate_value_error_times(
    lines: list[str],
    *,
    device_hours_h: float | None,
) -> list[str]:
    """Add device-hour context and less misleading LED hint labels."""
    sections = _split_sections(lines[2:]) if len(lines) >= 2 else []
    if not sections:
        return lines

    result = list(lines[:2])
    for raw_section in sections:
        section = _parse_section(raw_section)
        section_lines = _rewrite_led_hint_lines(list(section.lines))
        if section.kind == "value":
            section_lines = _add_value_error_time_context(
                section_lines,
                index=section.index,
                device_hours_h=device_hours_h,
            )
        if result and result[-1] != "":
            result.append("")
        result.extend(section_lines)
    return result


def _add_value_error_time_context(
    lines: list[str],
    *,
    index: int | None,
    device_hours_h: float | None,
) -> list[str]:
    """Insert scope and age fields into one value-error section."""
    if index == 0:
        return [*lines, "entry_scope: counters"]

    if index == 1:
        scope = "current_and_not_saved"
    elif index is not None and index >= 2:
        scope = "nonvolatile_history"
    else:
        scope = "unknown"

    no_current_error = any(
        "NO_CURRENT_VALUE_ERROR" in line or "no current error" in line
        for line in lines
    )

    result: list[str] = []
    inserted_scope = False
    inserted_age = False
    decoded_error_time_min: float | None = None

    for line in lines:
        if line.startswith("decoded_error_time_min:"):
            decoded_error_time_min = _parse_float_from_line(line)
            continue

        if line.startswith("decoded_error_time_h:"):
            if no_current_error:
                continue
            error_h = _parse_float_from_line(line)
            if error_h is not None:
                error_min = decoded_error_time_min if decoded_error_time_min is not None else error_h * 60.0
                if device_hours_h is None:
                    result.append(f"error_time_h: {error_h:.3f}; age_h: unavailable")
                    result.append(f"error_time_min: {error_min:.1f}; age_min: unavailable")
                else:
                    device_hours_min = device_hours_h * 60.0
                    if error_min <= device_hours_min + 1.0:
                        age_min = max(0.0, device_hours_min - error_min)
                        age_h = age_min / 60.0
                        result.append(f"error_time_h: {error_h:.3f}; age_h: {age_h:.3f} ago")
                        result.append(f"error_time_min: {error_min:.1f}; age_min: {age_min:.1f} ago")
                    else:
                        result.append(
                            f"error_time_h: {error_h:.3f}; age_h: unavailable "
                            "(error_time_exceeds_device_hours)"
                        )
                        result.append(
                            f"error_time_min: {error_min:.1f}; age_min: unavailable "
                            "(error_time_exceeds_device_hours)"
                        )
            inserted_age = True
            continue

        result.append(line)
        if not inserted_scope and line.startswith("payload_hex:"):
            result.append(f"entry_scope: {scope}")
            inserted_scope = True

    if not inserted_scope:
        result.append(f"entry_scope: {scope}")
    if not inserted_age and decoded_error_time_min is not None and not no_current_error:
        result.append(f"error_time_min: {decoded_error_time_min:.1f}; age_min: unavailable")
    return result

def _rewrite_led_hint_lines(lines: list[str]) -> list[str]:
    """Rename historical LED hints so they are not read as current-state claims."""
    result = []
    for line in lines:
        if "led_hint=" in line:
            line = line.replace("led_hint=", "led_hint_if_current=")
            line = line.replace(" while the error is current", "")
            line = line.replace(" while the error is current.", ".")
        result.append(line)
    return result



def _insert_device_hours_after_header(lines: list[str], device_hours_h: float | None) -> list[str]:
    """Put device operating hours once below the device header."""
    if len(lines) < 2:
        return lines
    value = "unavailable" if device_hours_h is None else f"{device_hours_h:.3f}"
    return [lines[0], lines[1], f"device_hours_h: {value}", *lines[2:]]


def _format_user_facing_lines(lines: list[str], *, show_frames: bool) -> list[str]:
    """Rename and order request/response fields for the user-facing report."""
    if len(lines) < 2:
        return lines

    sections = _split_sections(lines[2:])
    formatted = list(lines[:2])
    for section in sections:
        if formatted and formatted[-1] != "":
            formatted.append("")
        formatted.extend(_format_section_user_facing(section, show_frames=show_frames))
    return formatted


def _format_section_user_facing(section: list[str], *, show_frames: bool) -> list[str]:
    """Format one diagnostic section."""
    if len(section) < 2 or not _is_underline(section[1]):
        return [_rewrite_single_user_line(line, kind="other") for line in section]

    parsed = _parse_section(section)
    title = section[0]
    underline = section[1]
    no_current_value_error = parsed.kind == "value" and any(
        "NO_CURRENT_VALUE_ERROR" in line or "no current error" in line
        for line in section
    )
    fields: dict[str, str] = {}
    remaining: list[str] = []

    for line in section[2:]:
        stripped = line.strip()
        if not stripped:
            remaining.append(line)
            continue
        if stripped.startswith("request_raw_hex:"):
            fields["request"] = "request:" + stripped[len("request_raw_hex:"):]
            continue
        if stripped.startswith("raw_hex:"):
            fields["response"] = "response:" + stripped[len("raw_hex:"):]
            continue
        if stripped.startswith("status:"):
            fields["request_status"] = "request_status:" + stripped[len("status:"):]
            continue
        if stripped.startswith("payload_hex:"):
            fields["payload"] = "payload:" + stripped[len("payload_hex:"):]
            continue
        if stripped.startswith("decoded_summary:") or stripped.startswith("summary:"):
            continue
        if no_current_value_error and (
            stripped.startswith("decoded_error_time_min:")
            or stripped.startswith("decoded_error_time_h:")
            or stripped.startswith("decoded_error_flags:")
            or stripped.startswith("decoded_error_flag_details:")
            or stripped.startswith("error_flags:")
            or stripped.startswith("error_flag_details:")
        ):
            continue
        remaining.append(_rewrite_single_user_line(line, kind=parsed.kind))

    ordered = [title, underline]
    if show_frames:
        for key in ("request", "request_status", "response", "payload"):
            if key in fields:
                ordered.append(fields[key])
    elif _request_status_is_error(fields.get("request_status")):
        ordered.append(fields["request_status"])
    ordered.extend(remaining)
    return ordered


def _request_status_is_error(line: str | None) -> bool:
    """Return whether a formatted request_status line is non-OK."""
    if line is None:
        return False
    match = re.search(r"0x([0-9A-Fa-f]{2})", line)
    if not match:
        return False
    return int(match.group(1), 16) not in {0x00, 0x01}


def _rewrite_single_user_line(line: str, *, kind: str) -> str:
    """Rewrite one report line to user-facing names."""
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    replacements = {
        "decoded_protocol_error:": "protocol_error:",
        "decoded_counters:": "value_error_counters:",
        "decoded_error_type:": "error_type:",
        "decoded_error_flags:": "error_flags:",
        "decoded_error_flag_details:": "error_flag_details:",
    }
    if kind == "protocol" and stripped.startswith("value_uint32:"):
        return indent + "protocol_error_code:" + stripped[len("value_uint32:"):]
    for old, new in replacements.items():
        if stripped.startswith(old):
            value = stripped[len(old):].replace("nonvolatile=", "history=")
            return indent + new + value
    return line


def _parse_section(section: list[str]) -> _Section:
    """Parse section title, kind and error index."""
    title = section[0] if section else ""
    kind = "other"
    if title.startswith("GetLastProtocolError"):
        kind = "protocol"
    elif title.startswith("GetLastValueError"):
        kind = "value"
    return _Section(title=title, lines=section, kind=kind, index=_index_from_title(title))


def _index_from_title(title: str) -> int | None:
    """Return index=... parsed from one formatted diagnostic section title."""
    match = re.search(r"index=(\d+)", title)
    if not match:
        return None
    return int(match.group(1))


def _split_sections(lines: list[str]) -> list[list[str]]:
    """Split formatted diagnostic text into title-underlined sections."""
    sections: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        starts_section = bool(line) and _is_underline(next_line)
        if starts_section and current:
            while current and current[-1] == "":
                current.pop()
            if current:
                sections.append(current)
            current = [line, next_line]
            index += 2
            continue
        current.append(line)
        index += 1

    while current and current[-1] == "":
        current.pop()
    if current:
        sections.append(current)
    return sections


def _is_underline(line: str) -> bool:
    """Return whether a line is a dashed section underline."""
    stripped = line.strip()
    return bool(stripped) and set(stripped) == {"-"}


def _device_alias_from_header(lines: list[str]) -> str | None:
    """Return the device alias from a formatted device header."""
    if not lines:
        return None
    header = lines[0]
    if " = " in header:
        return header.split(" = ", 1)[0].strip()
    return header.strip() or None


def _parse_float_after_label(text: str, label: str) -> float | None:
    """Parse a float after a label in a section text."""
    match = re.search(rf"\b{re.escape(label)}:\s*([0-9.+\-Ee]+)", text)
    if not match:
        match = re.search(rf"\b{re.escape(label)}=\s*([0-9.+\-Ee]+)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_float_from_line(line: str) -> float | None:
    """Parse the final float-like token in a line."""
    match = re.search(r"([0-9.+\-Ee]+)\s*$", line)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None



if __name__ == "__main__":
    main()
