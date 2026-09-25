"""Detector: SQL injection, command injection, eval/exec."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

_PATTERNS = [
    # Dynamic code execution — BLOCK: arbitrary code execution with user input is critical
    (
        re.compile(r"\beval\s*\("),
        "BLOCK",
        "eval() can execute arbitrary code with untrusted input",
        "Use ast.literal_eval() for safe literal evaluation",
    ),
    (
        re.compile(r"\bexec\s*\("),
        "BLOCK",
        "exec() can execute arbitrary code with untrusted input",
        "Avoid dynamic code execution; refactor to explicit logic",
    ),
    # Shell execution
    (
        re.compile(r"\bos\.system\s*\("),
        "WARN",
        "os.system() executes shell commands and is a command-injection risk",
        "Use subprocess.run(['cmd', 'arg'], check=True) with a list",
    ),
    # SQL injection
    (
        re.compile(r'\.execute\s*\(\s*f["\']'),
        "BLOCK",
        "SQL injection: f-string used in cursor.execute()",
        "Use parameterized queries: cursor.execute(query, (param,))",
    ),
    (
        re.compile(r"\.execute\s*\(.*\.format\s*\("),
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

# Multi-line patterns applied to full content with re.DOTALL
_MULTILINE_PATTERNS = [
    (
        re.compile(r"\bsubprocess\.(call|run|Popen)\s*\(.*?shell\s*=\s*True", re.DOTALL),
        "WARN",
        "shell=True in subprocess is a command-injection risk",
        "Pass arguments as a list: subprocess.run(['cmd', 'arg'])",
    ),
]


class InjectionDetector(BaseDetector):
    name = "injection"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        results = self._scan_lines(content, _PATTERNS)
        # Multi-line subprocess detection (crosses line boundaries)
        for pattern, severity, description, fix in _MULTILINE_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                if not any(r.line_number == line_num for r in results):
                    results.append(
                        DetectionResult(
                            severity=severity,
                            category=self.name,
                            line_number=line_num,
                            description=description,
                            fix_suggestion=fix,
                            detector=self.name,
                        )
                    )
        return results
