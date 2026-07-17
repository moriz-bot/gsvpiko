"""Plot selected channels from a GSVpiko CSV recording."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re
from typing import Iterable

import matplotlib.pyplot as plt

TIME_COLUMN = "elapsed_s"
NON_CHANNEL_COLUMNS = {"datetime_iso", TIME_COLUMN}


def main() -> None:
    """Plot all or selected measurement channels from one CSV file."""
    args = _parse_args()
    csv_path = Path(args.csv_path)
    header, rows = _read_csv_data(csv_path)
    channel_names = [name for name in header if name not in NON_CHANNEL_COLUMNS]

    if args.list_channels:
        _print_channel_list(channel_names)
        return

    selected_names, selection_mode, selected_indices = _select_channels(
        channel_names,
        requested_names=args.channels,
        requested_indices=args.channel_indices,
    )
    x_values, y_values_by_channel = _extract_series(header, rows, selected_names)
    output_path = _resolve_output_path(
        csv_path,
        explicit_output=args.output,
        selected_names=selected_names,
        selected_indices=selected_indices,
        selection_mode=selection_mode,
    )
    _plot_series(
        x_values=x_values,
        y_values_by_channel=y_values_by_channel,
        output_path=output_path,
        title=csv_path.stem,
    )
    print(f"graph: {output_path}")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Plot all or selected channels from a GSVpiko CSV recording."
    )
    parser.add_argument("csv_path", help="Path to the GSVpiko CSV file.")
    parser.add_argument(
        "--channels",
        nargs="+",
        default=None,
        help="Channel names to plot, for example F1z,F2z or F1z F2z.",
    )
    parser.add_argument(
        "--channel-indices",
        default=None,
        help=(
            "1-based channel indices to plot, excluding datetime_iso and elapsed_s. "
            "Comma lists and ranges are supported, for example 3,6,9,12 or 1-4."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output PNG path. If omitted, a name is derived from the CSV path.",
    )
    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="Print available channel names and exit without plotting.",
    )
    args = parser.parse_args()
    _print_cli_options(parser, args)
    if args.channels and args.channel_indices:
        parser.error("--channels and --channel-indices cannot be used together.")
    return args


def _print_cli_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
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
        names = ", ".join(action.option_strings)
        hint = _value_hint(action)
        print(f"{names}{hint}: current={_format_value(getattr(args, action.dest, None))}")
    print()


def _value_hint(action: argparse.Action) -> str:
    """Return a compact value hint for one argparse option."""
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return ""
    if action.metavar is not None:
        return f" {action.metavar}"
    if action.nargs in {"+", "*"}:
        return f" <{action.dest}>..."
    return f" <{action.dest}>"


def _format_value(value: object) -> str:
    """Return a compact one-line value representation."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _read_csv_data(csv_path: Path) -> tuple[list[str], list[list[str]]]:
    """Return data header and data rows from a GSVpiko CSV file."""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            header = [column.strip() for column in row]
            break
        else:
            raise ValueError(f"No data header found in {csv_path}")

        rows = [row for row in reader if row]
    return header, rows


def _select_channels(
    channel_names: list[str],
    *,
    requested_names: list[str] | None,
    requested_indices: str | None,
) -> tuple[list[str], str, list[int]]:
    """Return selected channel names, selection mode, and numeric indices."""
    if requested_names:
        names = _split_channel_names(requested_names)
        missing = [name for name in names if name not in channel_names]
        if missing:
            available = ", ".join(channel_names)
            raise ValueError(f"Unknown channel(s): {', '.join(missing)}. Available: {available}")
        indices = [channel_names.index(name) + 1 for name in names]
        return names, "names", indices

    if requested_indices:
        indices = _parse_channel_indices(requested_indices)
        invalid = [index for index in indices if index < 1 or index > len(channel_names)]
        if invalid:
            raise ValueError(
                f"Channel index out of range: {', '.join(str(index) for index in invalid)}. "
                f"Valid range: 1-{len(channel_names)}"
            )
        return [channel_names[index - 1] for index in indices], "indices", indices

    return list(channel_names), "all", list(range(1, len(channel_names) + 1))


def _split_channel_names(tokens: Iterable[str]) -> list[str]:
    """Return channel names from comma-separated and whitespace-separated tokens."""
    names: list[str] = []
    for token in tokens:
        names.extend(part.strip() for part in token.split(",") if part.strip())
    if not names:
        raise ValueError("No channel names supplied.")
    return names


def _parse_channel_indices(text: str) -> list[int]:
    """Parse comma-separated 1-based channel indices and ranges."""
    indices: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            step = 1 if end >= start else -1
            indices.extend(range(start, end + step, step))
        else:
            indices.append(int(part))
    if not indices:
        raise ValueError("No channel indices supplied.")
    return indices


def _extract_series(
    header: list[str],
    rows: list[list[str]],
    selected_names: list[str],
) -> tuple[list[float], dict[str, list[float]]]:
    """Return x values and selected y series from data rows."""
    column_indices = {name: header.index(name) for name in selected_names}
    time_index = header.index(TIME_COLUMN) if TIME_COLUMN in header else None
    x_values: list[float] = []
    y_values_by_channel = {name: [] for name in selected_names}

    for row_index, row in enumerate(rows):
        if len(row) < len(header):
            continue
        try:
            x_value = float(row[time_index]) if time_index is not None else float(row_index)
            y_values = {name: float(row[column_indices[name]]) for name in selected_names}
        except ValueError:
            continue
        x_values.append(x_value)
        for name, value in y_values.items():
            y_values_by_channel[name].append(value)

    if not x_values:
        raise ValueError("No numeric samples found for selected channels.")
    return x_values, y_values_by_channel


def _resolve_output_path(
    csv_path: Path,
    *,
    explicit_output: str | None,
    selected_names: list[str],
    selected_indices: list[int],
    selection_mode: str,
) -> Path:
    """Return output path for the plot PNG."""
    if explicit_output:
        return Path(explicit_output)

    suffix = ""
    if selection_mode == "names":
        suffix = "__only_" + "_".join(_safe_filename_part(name) for name in selected_names)
    elif selection_mode == "indices":
        suffix = "__only_channels_" + "_".join(str(index) for index in selected_indices)
    return csv_path.with_name(f"{csv_path.stem}{suffix}.png")


def _safe_filename_part(text: str) -> str:
    """Return a filename-safe channel-name token."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return value.strip("_") or "channel"


def _plot_series(
    *,
    x_values: list[float],
    y_values_by_channel: dict[str, list[float]],
    output_path: Path,
    title: str,
) -> None:
    """Write a PNG plot for the selected series."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(12, 6))
    for channel_name, y_values in y_values_by_channel.items():
        plt.plot(x_values, y_values, label=channel_name)
    plt.xlabel("elapsed_s")
    plt.ylabel("value")
    plt.title(title)
    plt.grid(True)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def _print_channel_list(channel_names: list[str]) -> None:
    """Print available channel names with 1-based indices."""
    print("Available channels")
    print("------------------")
    for index, channel_name in enumerate(channel_names, start=1):
        print(f"{index}: {channel_name}")


if __name__ == "__main__":
    main()
