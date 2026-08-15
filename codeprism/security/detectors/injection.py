"""Detector: SQL injection, command injection, eval/exec."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

_PATTERNS = [
    # Dynamic code execution
    (
        re.compile(r'\beval\s*\('),
        "WARN",
        "eval() can execute arbitrary code with untrusted input",
        "Use ast.literal_eval() for safe literal evaluation",
    ),
    (
        re.compile(r'\bexec\s*\('),
        "WARN",
        "exec() can execute arbitrary code with untrusted input",
        "Avoid dynamic code execution; refactor to explicit logic",
    ),
    # Shell execution
    (
        re.compile(r'\bos\.system\s*\('),
        "WARN",
        "os.system() executes shell commands and is a command-injection risk",
        "Use subprocess.run(['cmd', 'arg'], check=True) with a list",
    ),
    (
        re.compile(r'\bsubprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True'),
        "WARN",
        "shell=True in subprocess is a command-injection risk",
        "Pass arguments as a list: subprocess.run(['cmd', 'arg'])",
    ),
    # SQL injection
    (
        re.compile(r'\.execute\s*\(\s*f["\']'),
        "BLOCK",
        "SQL injection: f-string used in cursor.execute()",
        "Use parameterized queries: cursor.execute(query, (param,))",
    ),
    (
        re.compile(r'\.execute\s*\(.*\.format\s*\('),
        "BLOCK",
        "SQL injection: .format() used to build SQL query",
        "Use parameterized queries: cursor.execute(query, (param,))",
    ),
    (
        re.compile(r'\.execute\s*\(["\'][^"\']*["\'\s]*\+'),
        "BLOCK",
        "SQL injection: string concatenation used to build SQL query",
        "Use parameterized queries: cursor.execute(query, (param,))",
    ),
]


class InjectionDetector(BaseDetector):
    name = "injection"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
