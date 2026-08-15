"""Cross-platform path resolution using platformdirs."""

from __future__ import annotations

import hashlib
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "codeprism"


def get_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME))


def get_config_dir() -> Path:
    return Path(user_config_dir(APP_NAME))


def get_db_path(project_path: str | Path) -> Path:
    """Return the SQLite DB path for a given project (unique per resolved path)."""
    resolved = str(Path(project_path).resolve())
    project_hash = hashlib.sha256(resolved.encode()).hexdigest()[:16]
    return get_data_dir() / f"{project_hash}.db"


def get_default_config_path() -> Path:
    return get_config_dir() / "config.toml"


def get_project_config_path(project_path: str | Path) -> Path:
    return Path(project_path) / ".codeprism.toml"
