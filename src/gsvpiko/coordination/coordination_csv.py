"""CSV output coordination for resolved setup runtime recordings."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from ..runtime.runtime_measurement_buffer import RuntimeMeasurementRecord
from .coordination_recording import RecordingRunResult
from .coordination_setup_resolution import ResolvedChannel, ResolvedSetup

FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RecordingFileContext:
    """File names and identifiers shared by CSV and matching report files."""

    session_name: str
    session_id: str
    timestamp_text: str
    csv_path: Path
    report_path: Path


def build_recording_file_context(
    *,
    resolved_setup: ResolvedSetup,
    session_name: str,
    timestamp: datetime | None = None,
) -> RecordingFileContext:
    """Build CSV/report paths from output settings and the session name."""
    cleaned_session_name = sanitize_filename_part(session_name)
    if not cleaned_session_name:
        raise ValueError("session_name is required for CSV output.")

    output = resolved_setup.output
    timestamp_value = timestamp or datetime.now()
    timestamp_text = timestamp_value.strftime(str(output["timestamp_format"]))
    filename_template = str(output["filename_template"])
    filename = filename_template.format(
        timestamp=timestamp_text,
        session_name=cleaned_session_name,
        setup_name=sanitize_filename_part(resolved_setup.name),
        sample_rate_hz=float(resolved_setup.sample_rate_hz),
        datatype=resolved_setup.datatype_name,
    )
    filename = _collapse_empty_filename_separators(filename)
    if not filename.lower().endswith(".csv"):
        filename = f"{filename}.csv"

    session_id = Path(filename).stem
    csv_path = Path(str(output["directory_csv"])) / filename
    report_path = Path(str(output["directory_report"])) / f"{session_id}_report.txt"
    return RecordingFileContext(
        session_name=cleaned_session_name,
        session_id=session_id,
        timestamp_text=timestamp_text,
        csv_path=csv_path,
        report_path=report_path,
    )


def write_recording_csv(
    *,
    recording_result: RecordingRunResult,
    file_context: RecordingFileContext,
    zero_before_recording: bool,
) -> Path:
    """Write one runtime recording result to a user-oriented CSV file."""
    if recording_result.runtime_result is None:
        raise ValueError("Cannot write CSV without a runtime recording result.")

    resolved_setup = recording_result.resolved_setup
    output = resolved_setup.output
    delimiter = str(output["csv_delimiter"])
    encoding = str(output["csv_encoding"])
    decimal_separator = str(output["csv_decimal_separator"])
    time_columns = list(output["time_columns"])

    file_context.csv_path.parent.mkdir(parents=True, exist_ok=True)
    channel_names = _ordered_channel_names(resolved_setup)
    device_records = {
        result.device_alias: result.records
        for result in recording_result.runtime_result.device_results
    }
    row_count = _common_row_count(device_records)
    first_reference_timestamp = (
        _reference_record_for_row(resolved_setup, device_records, 0).timestamp_unix_s
        if row_count
        else recording_result.runtime_result.started_at_unix_s
    )

    with file_context.csv_path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        if output.get("include_metadata_header", True):
            _write_metadata_header(
                writer,
                resolved_setup=resolved_setup,
                file_context=file_context,
                zero_before_recording=zero_before_recording,
                recording_result=recording_result,
                first_reference_timestamp=first_reference_timestamp,
            )

        writer.writerow(list(time_columns) + channel_names)
        for row_index in range(row_count):
            reference_record = _reference_record_for_row(
                resolved_setup,
                device_records,
                row_index,
            )
            row = [
                _format_time_column(
                    time_column,
                    reference_record,
                    first_reference_timestamp=first_reference_timestamp,
                    decimal_separator=decimal_separator,
                )
                for time_column in time_columns
            ]
            for channel in _ordered_channels(resolved_setup):
                record = device_records[channel.device_alias][row_index]
                row.append(
                    _format_csv_value(
                        record.channels.get(channel.column_name, ""),
                        decimal_separator=decimal_separator,
                    )
                )
            writer.writerow(row)

    return file_context.csv_path


def read_csv_preview(
    csv_path: str | Path,
) -> str:
    """Return a compact preview of one CSV file with the first data row."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)

    metadata_lines: list[str] = []
    table_header = ""
    first_data_row = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if stripped.startswith("#"):
                if len(metadata_lines) < 12:
                    metadata_lines.append(stripped)
                continue
            if not stripped:
                continue
            if not table_header:
                table_header = stripped
                continue
            first_data_row = stripped
            break

    lines = [f"csv_path: {path}"]
    lines.extend(metadata_lines)
    if table_header:
        lines.append(table_header)
    if first_data_row:
        lines.append(first_data_row)
    return "\n".join(lines)


def sanitize_filename_part(
    value: Any,
) -> str:
    """Return a compact filename-safe representation for one placeholder."""
    text = str(value or "").strip()
    text = text.replace(" ", "_")
    text = FILENAME_SAFE_RE.sub("_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("._-")


def _collapse_empty_filename_separators(
    filename: str,
) -> str:
    """Normalize repeated separators caused by optional filename parts."""
    filename = filename.replace("____", "__")
    filename = re.sub(r"_{3,}", "__", filename)
    filename = filename.replace("_.", ".")
    return filename


def _write_metadata_header(
    writer: csv.writer,
    *,
    resolved_setup: ResolvedSetup,
    file_context: RecordingFileContext,
    zero_before_recording: bool,
    recording_result: RecordingRunResult,
    first_reference_timestamp: float,
) -> None:
    """Write comment metadata above the normal CSV table body."""
    writer.writerow(["# session_id", file_context.session_id])
    writer.writerow(["# session_name", file_context.session_name])
    writer.writerow(["# setup_name", resolved_setup.name])
    writer.writerow(["# sample_rate_hz", _format_metadata_number(resolved_setup.sample_rate_hz)])
    writer.writerow(["# analog_filter_hz", resolved_setup.analog_filter_hz])
    writer.writerow(["# digital_filter", _format_none_as_off(resolved_setup.digital_filter)])
    writer.writerow(["# zero_before_recording", str(bool(zero_before_recording)).lower()])
    command_text = _format_commands_metadata(
        recording_result,
        first_reference_timestamp=first_reference_timestamp,
    )
    if command_text:
        writer.writerow(["# commands", command_text])
    writer.writerow(["# report_path", str(file_context.report_path)])
    writer.writerow(["#"])
    writer.writerow(["# gsv_alias", "gsv_serial_number"])
    for device in resolved_setup.devices:
        writer.writerow(["# " + device.alias, device.device_config["gsv_serial_number"]])
    writer.writerow(["#"])
    writer.writerow(["# sensor_alias", "sensor_serial_number", "compensation_matrix"])
    for sensor_alias, serial_number, compensation_matrix in _iter_unique_sensors(resolved_setup):
        writer.writerow(
            [
                "# " + sensor_alias,
                serial_number,
                _format_metadata_matrix(compensation_matrix),
            ]
        )
    writer.writerow(["#"])
    writer.writerow(["# channel_alias", "unit", "gsv_alias", "sensor_alias", "scaling_factor"])
    for channel in _ordered_channels(resolved_setup):
        writer.writerow(
            [
                "# " + channel.column_name,
                _unit_for_channel(channel),
                channel.device_alias,
                channel.sensor_alias,
                _format_metadata_number(channel.scaling_factor),
            ]
        )
    writer.writerow(["#"])



def _format_commands_metadata(
    recording_result: RecordingRunResult,
    *,
    first_reference_timestamp: float,
) -> str:
    """Return compact runtime-command metadata for the CSV header."""
    runtime_result = recording_result.runtime_result
    if runtime_result is None:
        return ""

    grouped: dict[str, dict[str, Any]] = {}
    for device_result in runtime_result.device_results:
        for report in device_result.runtime_command_reports:
            group_id = str(report.get("command_group_id") or id(report))
            current = grouped.setdefault(group_id, report)
            if float(report.get("started_at_unix_s") or 0.0) < float(
                current.get("started_at_unix_s") or 0.0
            ):
                grouped[group_id] = report

    entries: list[str] = []
    for report in sorted(
        grouped.values(),
        key=lambda item: float(item.get("started_at_unix_s") or 0.0),
    ):
        command_name = _csv_command_name(report.get("command_name"))
        started_at = float(report.get("started_at_unix_s") or runtime_result.started_at_unix_s)
        iso_text = datetime.fromtimestamp(started_at).isoformat(timespec="milliseconds")
        elapsed_s = started_at - first_reference_timestamp
        entries.append(f"{command_name}__{iso_text}__{elapsed_s:.3f}s")

    return "; ".join(entries)


def _csv_command_name(command_name: object) -> str:
    """Return compact user-facing command name for CSV metadata."""
    normalized = str(command_name or "").strip().upper()
    if normalized in {"SET_ZERO", "SETZERO"}:
        return "tare"
    return normalized.lower() or "command"

def _ordered_channels(
    resolved_setup: ResolvedSetup,
) -> list[ResolvedChannel]:
    """Return channels in setup-defined CSV order."""
    channels: list[ResolvedChannel] = []
    for device in resolved_setup.devices:
        channels.extend(device.channels)
    return channels


def _ordered_channel_names(
    resolved_setup: ResolvedSetup,
) -> list[str]:
    """Return channel column names in setup-defined CSV order."""
    return [channel.column_name for channel in _ordered_channels(resolved_setup)]


def _iter_unique_sensors(
    resolved_setup: ResolvedSetup,
) -> list[tuple[str, str, list[list[float]] | None]]:
    """Return unique sensor metadata in setup order."""
    seen: set[str] = set()
    result: list[tuple[str, str, list[list[float]] | None]] = []
    for channel in _ordered_channels(resolved_setup):
        if channel.sensor_alias in seen:
            continue
        seen.add(channel.sensor_alias)
        result.append(
            (
                channel.sensor_alias,
                channel.sensor_serial_number,
                channel.crosstalk_compensation_matrix,
            )
        )
    return result


def _common_row_count(
    device_records: dict[str, list[RuntimeMeasurementRecord]],
) -> int:
    """Return the common record count available for all devices."""
    if not device_records:
        return 0
    return min(len(records) for records in device_records.values())


def _reference_record_for_row(
    resolved_setup: ResolvedSetup,
    device_records: dict[str, list[RuntimeMeasurementRecord]],
    row_index: int,
) -> RuntimeMeasurementRecord:
    """Return the first setup device record for one CSV row."""
    reference_alias = resolved_setup.devices[0].alias
    return device_records[reference_alias][row_index]


def _format_time_column(
    time_column: str,
    record: RuntimeMeasurementRecord,
    *,
    first_reference_timestamp: float,
    decimal_separator: str,
) -> str:
    """Format one configured time column for a CSV row."""
    if time_column == "datetime_iso":
        return datetime.fromtimestamp(record.timestamp_unix_s).isoformat(timespec="milliseconds")
    if time_column == "timestamp_unix_s":
        return _format_csv_value(record.timestamp_unix_s, decimal_separator=decimal_separator)
    if time_column == "elapsed_s":
        return _format_csv_value(record.timestamp_unix_s - first_reference_timestamp, decimal_separator=decimal_separator)
    raise ValueError(f"Unsupported time column {time_column!r}.")


def _format_csv_value(
    value: Any,
    *,
    decimal_separator: str,
) -> str:
    """Format a CSV cell using the configured decimal separator."""
    if isinstance(value, float):
        text = f"{value:.12g}"
    else:
        text = str(value)
    if decimal_separator == ",":
        text = text.replace(".", ",")
    return text


def _format_metadata_number(value: Any) -> str:
    """Format optional numeric metadata compactly."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def _format_metadata_matrix(value: Any) -> str:
    """Format an optional matrix as compact JSON-like metadata."""
    if value is None:
        return "None"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _format_none_as_off(value: Any) -> str:
    """Return 'off' for unset optional filters."""
    if value is None:
        return "off"
    return str(value)


def _unit_for_channel(channel: ResolvedChannel) -> str:
    """Return a user-facing unit text for one channel."""
    if channel.unit_code is None:
        return ""
    # Unit code 3 is formatted as newtons. Additional unit codes should be
    # mapped through a dedicated unit-code lookup table.
    return "N"
