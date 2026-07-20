"""Output path settings for GSVpiko files.

The module centralizes user-facing output folders for CSV, plot, and text-report
artifacts. Command-line overrides are deliberately process-local. Persistent
settings are stored per user and can be managed from interactive apps.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = "gsvpiko_data"
DEFAULT_LOG_DIR = "gsvpiko_logs"
SETTINGS_DIR_NAME = "GSVpiko"
SETTINGS_FILE_NAME = "settings.json"


@dataclass(frozen=True)
class OutputDirectories:
    """Resolved output folders for CSV/plot files and text reports."""

    data_dir: Path
    log_dir: Path
    settings_path: Path


def settings_path() -> Path:
    """Return the per-user GSVpiko settings file path."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / SETTINGS_DIR_NAME
    else:
        base = Path.home() / ".config" / "gsvpiko"
    return base / SETTINGS_FILE_NAME


def load_output_settings() -> dict[str, str]:
    """Load persistent output folder settings."""
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    output = data.get("output", {}) if isinstance(data, dict) else {}
    if not isinstance(output, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("data_dir", "log_dir"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def save_output_settings(settings: dict[str, str]) -> Path:
    """Save persistent output folder settings and return the settings path."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data.update(existing)
        except (OSError, json.JSONDecodeError):
            data = {}
    data["output"] = dict(settings)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def set_persistent_output_path(kind: str, directory: str | Path) -> OutputDirectories:
    """Set one persistent output folder and return the resulting directories."""
    normalized = _normalize_kind(kind)
    settings = load_output_settings()
    settings[normalized] = str(Path(directory).expanduser())
    save_output_settings(settings)
    return resolve_output_directories()


def reset_persistent_output_paths() -> OutputDirectories:
    """Remove persistent output folder overrides and return default directories."""
    path = settings_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data.update(existing)
        except (OSError, json.JSONDecodeError):
            data = {}
    data.pop("output", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return resolve_output_directories()


def resolve_output_directories(
    *,
    data_dir: str | Path | None = None,
    log_dir: str | Path | None = None,
) -> OutputDirectories:
    """Resolve active output folders using CLI, persistent, then default values."""
    settings = load_output_settings()
    resolved_data_dir = _resolve_directory(data_dir, settings.get("data_dir"), DEFAULT_DATA_DIR)
    resolved_log_dir = _resolve_directory(log_dir, settings.get("log_dir"), DEFAULT_LOG_DIR)
    return OutputDirectories(
        data_dir=resolved_data_dir,
        log_dir=resolved_log_dir,
        settings_path=settings_path(),
    )


def ensure_output_directories(directories: OutputDirectories) -> None:
    """Create output folders if they do not exist."""
    directories.data_dir.mkdir(parents=True, exist_ok=True)
    directories.log_dir.mkdir(parents=True, exist_ok=True)


def apply_output_directories_to_setup_config(
    setup_config: dict[str, Any],
    *,
    data_dir: str | Path | None = None,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a shallow setup copy with resolved output folders applied."""
    directories = resolve_output_directories(data_dir=data_dir, log_dir=log_dir)
    setup_copy = dict(setup_config)
    output = dict(setup_copy.get("output", {}))
    output["directory_csv"] = str(directories.data_dir)
    output["directory_report"] = str(directories.log_dir)
    setup_copy["output"] = output
    return setup_copy


def format_output_directories_lines(directories: OutputDirectories) -> list[str]:
    """Return human-readable output path lines."""
    return [
        f"data_dir: {directories.data_dir}",
        f"log_dir: {directories.log_dir}",
        f"settings_path: {directories.settings_path}",
    ]


def _resolve_directory(
    explicit: str | Path | None,
    persistent: str | None,
    default: str,
) -> Path:
    """Resolve a directory value to a normalized path without creating it."""
    value = explicit if explicit not in (None, "") else persistent or default
    return Path(value).expanduser()


def _normalize_kind(kind: str) -> str:
    """Normalize a user-facing path kind."""
    normalized = kind.strip().lower().replace("-", "_")
    if normalized in {"data", "csv", "plot", "graph", "data_dir"}:
        return "data_dir"
    if normalized in {"log", "logs", "report", "reports", "log_dir"}:
        return "log_dir"
    raise ValueError("Path kind must be data or logs.")
