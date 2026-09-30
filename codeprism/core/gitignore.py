"""Honour the project's .gitignore by asking git itself.

Git's ignore rules (nested .gitignore files, .git/info/exclude, the global
excludes file, negations) are subtle; asking git is exact and fast, and never
walks into ignored trees such as node_modules or vendored checkouts.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_TIMEOUT = 60


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # git missing, timeout, ...
        return None


def git_listed_files(root: str | Path) -> list[Path] | None:
    """Tracked + untracked-but-not-ignored files under *root*, or None outside git.

    None also covers "git not installed", so callers fall back to a plain walk.
    """
    root = Path(root).resolve()
    proc = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if proc is None or proc.returncode != 0:
        return None
    names = proc.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return [(root / name).resolve() for name in names if name]


class IgnoreChecker:
    """Per-path "is this ignored by git?" for the file watcher."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        probe = _git(self._root, "rev-parse", "--is-inside-work-tree")
        self._enabled = probe is not None and probe.returncode == 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_ignored(self, path: str | Path) -> bool:
        if not self._enabled:
            return False
        return self._check(str(Path(path).resolve()))

    @lru_cache(maxsize=4096)  # noqa: B019 - one checker per watcher; bounded cache
    def _check(self, path: str) -> bool:
        proc = _git(self._root, "check-ignore", "-q", "--", path)
        # exit 0 = ignored, 1 = not ignored, anything else = can't tell -> keep it
        return proc is not None and proc.returncode == 0
