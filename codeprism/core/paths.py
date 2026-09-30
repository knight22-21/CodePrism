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


_PROJECT_MARKERS = (".git", ".codeprism.toml")


def find_project_root(start: str | Path) -> Path | None:
    """Nearest directory at or above *start* that looks like a project.

    A project has a ``.git`` (directory or worktree file) or ``.codeprism.toml``.
    The home directory and filesystem roots are never treated as projects, so a
    server launched from ``~`` doesn't index the whole disk.
    """
    current = Path(start).resolve()
    home = Path.home().resolve()
    for candidate in (current, *current.parents):
        if candidate == home or candidate.parent == candidate:
            return None
        if any((candidate / marker).exists() for marker in _PROJECT_MARKERS):
            return candidate
    return None


def get_project_config_path(project_path: str | Path) -> Path:
    return Path(project_path) / ".codeprism.toml"


def get_chroma_path(project_path: str | Path) -> Path:
    """Return the ChromaDB directory for a given project (sibling of the SQLite db)."""
    resolved = str(Path(project_path).resolve())
    project_hash = hashlib.sha256(resolved.encode()).hexdigest()[:16]
    return get_data_dir() / f"{project_hash}_chroma"
