"""Detector: environment variable exposure (logged, printed, or returned raw)."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

_PATTERNS = [
    (
        re.compile(r'\bprint\s*\(.*os\.environ'),
        "WARN",
        "Environment variable exposed via print()",
        "Never print env vars — they may contain secrets",
    ),
    (
        re.compile(r'\blogging\.\w+\s*\(.*os\.environ'),
        "WARN",
        "Environment variable written to logs",
        "Log a safe placeholder; never log raw env values",
    ),
    (
        re.compile(r'\breturn\s+.*os\.environ\['),
        "WARN",
        "Environment variable returned directly from function",
        "Validate and sanitize env values before returning to callers",
    ),
    (
        re.compile(r'\bjson\.dumps\s*\(.*os\.environ'),
        "WARN",
        "Environment variables serialized to JSON",
        "Only expose specific, non-sensitive config values",
    ),
    (
        re.compile(r'\bresponse\b.*os\.environ|os\.environ.*\bresponse\b'),
        "WARN",
        "Environment variable may be included in HTTP response",
        "Never expose raw env vars in API responses",
    ),
]


class EnvVarDetector(BaseDetector):
    name = "env_vars"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
