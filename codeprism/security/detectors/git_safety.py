"""Detector: unsafe coding patterns — broad exception suppression, debug leftovers."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

# Broad exception suppression — catches every line starting with bare `except:` or
# `except Exception` / `except BaseException` with an empty or pass-only body.
_PATTERNS = [
    (
        re.compile(r"^\s*except\s*:\s*$"),
        "WARN",
        "Broad exception suppression",
        "Catch specific exceptions (e.g., except ValueError:) to avoid hiding bugs",
    ),
    (
        re.compile(r"^\s*except\s+(Exception|BaseException)\s*:\s*$"),
        "WARN",
        "Overly broad exception catch",
        "Catch specific exceptions; if you must catch Exception, at least log it",
    ),
    (
        re.compile(r"^\s*except\s+(Exception|BaseException)\s+as\s+\w+\s*:\s*$"),
        "INFO",
        "Catching Exception as variable — ensure it is logged",
        "Log or re-raise the exception rather than silently suppressing it",
    ),
    # except clause with only `pass` on next line is caught by broad-content scan below
    (
        re.compile(r"^\s*except.*:\s*pass\s*$"),
        "WARN",
        "Silent exception swallow (pass)",
        "Log the exception or re-raise instead of silently ignoring it",
    ),
    # Leftover debug utilities
    (
        re.compile(r"\bpdb\.set_trace\(\)"),
        "WARN",
        "Debugger breakpoint left in code",
        "Remove pdb.set_trace() before committing",
    ),
    (
        re.compile(r"\bbreakpoint\(\)"),
        "WARN",
        "Built-in breakpoint() left in code",
        "Remove breakpoint() before committing",
    ),
    # .gitignore-class concern: hardcoded local paths
    (
        re.compile(r'["\']C:\\\\Users\\\\'),
        "INFO",
        "Hardcoded Windows user path",
        "Use pathlib or environment variables instead of absolute user paths",
    ),
    (
        re.compile(r'["\']\/home\/\w+\/'),
        "INFO",
        "Hardcoded Unix home path",
        "Use Path.home() or environment variables instead of absolute home paths",
    ),
]


class GitSafetyDetector(BaseDetector):
    name = "git_safety"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
