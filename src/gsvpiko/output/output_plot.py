"""Plot GSVpiko CSV recordings and command/event markers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import matplotlib.pyplot as plt

TIME_COLUMN = "elapsed_s"
NON_CHANNEL_COLUMNS = {"datetime_iso", "timestamp_unix_s", TIME_COLUMN}
COMMANDS_METADATA_KEY = "# commands"


@dataclass(frozen=True)
class CsvEventMarker:
    """One event marker parsed from CSV metadata."""

    name: str
    datetime_iso: str
    elapsed_s: float


@dataclass(frozen=True)
class CsvPlotData:
    """Parsed numeric CSV data and metadata needed for plotting."""

    header: list[str]
    rows: list[list[str]]
    events: list[CsvEventMarker]


def plot_gsvpiko_csv(
    csv_path: str | Path,
    *,
    output_path: str | Path | None = None,
    channels: Iterable[str] | None = None,
    channel_indices: str | None = None,
    title: str | None = None,
) -> Path:
    """Plot selected channels from a GSVpiko CSV file and return the PNG path."""
    path = Path(csv_path)
    data = read_gsvpiko_csv_plot_data(path)
    channel_names = [name for name in data.header if name not in NON_CHANNEL_COLUMNS]
    selected_names, selection_mode, selected_indices = select_channels(
        channel_names,
        requested_names=list(channels) if channels is not None else None,
        requested_indices=channel_indices,
    )
    x_values, y_values_by_channel = extract_series(data.header, data.rows, selected_names)
    resolved_output_path = resolve_plot_output_path(
        path,
        explicit_output=output_path,
        selected_names=selected_names,
        selected_indices=selected_indices,
        selection_mode=selection_mode,
    )
    write_plot(
        x_values=x_values,
        y_values_by_channel=y_values_by_channel,
        event_markers=data.events,
        output_path=resolved_output_path,
        title=title or path.stem,
    )
    return resolved_output_path


def read_gsvpiko_csv_plot_data(csv_path: str | Path) -> CsvPlotData:
    """Return data header, data rows, and parsed event markers from a CSV file."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)

    metadata_rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                metadata_rows.append(row)
                continue
            header = [column.strip() for column in row]
            break
        else:
            raise ValueError(f"No data header found in {path}")

        rows = [row for row in reader if row]

    return CsvPlotData(
        header=header,
        rows=rows,
        events=parse_event_markers(metadata_rows),
    )


def available_channels(csv_path: str | Path) -> list[str]:
    """Return available channel names from one GSVpiko CSV file."""
    data = read_gsvpiko_csv_plot_data(csv_path)
    return [name for name in data.header if name not in NON_CHANNEL_COLUMNS]


def parse_event_markers(metadata_rows: list[list[str]]) -> list[CsvEventMarker]:
    """Parse command/event metadata rows into plot markers."""
    events: list[CsvEventMarker] = []
    for row in metadata_rows:
        if not row:
            continue
        key = row[0].strip().lower()
        if key != COMMANDS_METADATA_KEY:
            continue
        command_text = row[1] if len(row) >= 2 else ""
        events.extend(_parse_commands_metadata(command_text))
    return events


def select_channels(
    channel_names: list[str],
    *,
    requested_names: list[str] | None,
    requested_indices: str | None,
) -> tuple[list[str], str, list[int]]:
    """Return selected channel names, selection mode, and 1-based indices."""
    if requested_names:
        names = split_channel_names(requested_names)
        missing = [name for name in names if name not in channel_names]
        if missing:
            available = ", ".join(channel_names)
            raise ValueError(f"Unknown channel(s): {', '.join(missing)}. Available: {available}")
        indices = [channel_names.index(name) + 1 for name in names]
        return names, "names", indices

    if requested_indices:
        indices = parse_channel_indices(requested_indices)
        invalid = [index for index in indices if index < 1 or index > len(channel_names)]
        if invalid:
            raise ValueError(
                f"Channel index out of range: {', '.join(str(index) for index in invalid)}. "
                f"Valid range: 1-{len(channel_names)}"
            )
        return [channel_names[index - 1] for index in indices], "indices", indices

    return list(channel_names), "all", list(range(1, len(channel_names) + 1))


def split_channel_names(tokens: Iterable[str]) -> list[str]:
    """Return channel names from comma-separated and whitespace-separated tokens."""
    names: list[str] = []
    for token in tokens:
        names.extend(part.strip() for part in token.split(",") if part.strip())
    if not names:
        raise ValueError("No channel names supplied.")
    return names


def parse_channel_indices(text: str) -> list[int]:
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


def extract_series(
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


def resolve_plot_output_path(
    csv_path: Path,
    *,
    explicit_output: str | Path | None,
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


def write_plot(
    *,
    x_values: list[float],
    y_values_by_channel: dict[str, list[float]],
    event_markers: list[CsvEventMarker],
    output_path: Path,
    title: str,
) -> None:
    """Write a PNG plot for selected series and event markers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(12, 6))
    for channel_name, y_values in y_values_by_channel.items():
        plt.plot(x_values, y_values, label=channel_name)
    _draw_event_markers(event_markers)
    plt.xlabel("elapsed_s")
    plt.ylabel("value")
    plt.title(title)
    plt.grid(True)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def format_channel_list(channel_names: list[str]) -> list[str]:
    """Return available channel names with 1-based indices."""
    lines = ["Available channels", "------------------"]
    lines.extend(f"{index}: {channel_name}" for index, channel_name in enumerate(channel_names, 1))
    return lines


def _parse_commands_metadata(command_text: str) -> list[CsvEventMarker]:
    """Parse the compact '# commands' metadata cell."""
    events: list[CsvEventMarker] = []
    for raw_entry in command_text.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = entry.split("__")
        if len(parts) < 3:
            continue
        elapsed_text = parts[2].strip()
        if elapsed_text.endswith("s"):
            elapsed_text = elapsed_text[:-1]
        try:
            elapsed_s = float(elapsed_text)
        except ValueError:
            continue
        events.append(
            CsvEventMarker(
                name=parts[0].strip() or "event",
                datetime_iso=parts[1].strip(),
                elapsed_s=elapsed_s,
            )
        )
    return events


def _draw_event_markers(event_markers: list[CsvEventMarker]) -> None:
    """Draw event markers as vertical dashed lines."""
    if not event_markers:
        return
    axis = plt.gca()
    transform = axis.get_xaxis_transform()
    seen_labels: set[str] = set()
    for marker in event_markers:
        label = marker.name if marker.name not in seen_labels else None
        axis.axvline(marker.elapsed_s, linestyle="--", linewidth=1.0, label=label)
        axis.text(
            marker.elapsed_s,
            0.98,
            marker.name,
            rotation=90,
            va="top",
            ha="right",
            transform=transform,
        )
        seen_labels.add(marker.name)


def _safe_filename_part(text: str) -> str:
    """Return a filename-safe channel-name token."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return value.strip("_") or "channel"
