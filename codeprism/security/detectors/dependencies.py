"""Detector: dangerous import patterns and unsafe deserialization libraries."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

_PATTERNS = [
    (
        re.compile(r'\bimport\s+pickle\b|from\s+pickle\s+import'),
        "WARN",
        "pickle deserialization is unsafe with untrusted data",
        "Use json or a schema-validated format (e.g. pydantic) instead",
    ),
    (
        re.compile(r'\byaml\.load\s*\([^,)]+\)(?!\s*,\s*Loader)'),
        "BLOCK",
        "yaml.load() without Loader= is arbitrary code execution",
        "Use yaml.safe_load() or yaml.load(f, Loader=yaml.SafeLoader)",
    ),
    (
        re.compile(r'\bimport\s+marshal\b|from\s+marshal\s+import'),
        "WARN",
        "marshal is not safe for untrusted data",
        "Use json or protobuf for external data serialization",
    ),
    (
        re.compile(r'\bimport\s+shelve\b|from\s+shelve\s+import'),
        "INFO",
        "shelve uses pickle internally — unsafe with untrusted data",
        "Use a proper database (SQLite, Redis) for external data",
    ),
    (
        re.compile(r'\b__import__\s*\('),
        "WARN",
        "__import__() with dynamic strings is a code injection risk",
        "Use importlib.import_module() with a validated module name",
    ),
]


class DependenciesDetector(BaseDetector):
    name = "dependencies"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
