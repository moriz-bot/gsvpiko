"""Small helpers for showing app command-line options at startup."""

from __future__ import annotations

import argparse
from collections.abc import Iterable


def print_cli_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Print supported command-line options and their active values."""
    option_actions = [
        action
        for action in parser._actions
        if action.option_strings and not isinstance(action, argparse._HelpAction)
    ]
    if not option_actions:
        return

    print("Command-line options")
    print("--------------------")
    for action in option_actions:
        option_text = ", ".join(action.option_strings)
        hint = _value_hint(action)
        value = getattr(args, action.dest, None)
        print(f"{option_text}{hint}: current={_format_value(value)}")
    print()


def _value_hint(action: argparse.Action) -> str:
    """Return a compact value hint for one argparse option."""
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return ""
    if action.metavar is not None:
        if isinstance(action.metavar, tuple):
            return " " + " ".join(str(part) for part in action.metavar)
        return f" {action.metavar}"
    if action.nargs in {"+", "*"}:
        return f" <{action.dest}>..."
    return f" <{action.dest}>"


def _format_value(value: object) -> str:
    """Return a stable one-line representation for CLI option values."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return ",".join(str(item) for item in value)
    return str(value)
