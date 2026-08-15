"""Base detector contract and shared result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectionResult:
    """A single security finding from one detector on one line."""

    severity: str           # INFO | WARN | BLOCK
    category: str           # detector family name
    line_number: Optional[int]
    description: str
    fix_suggestion: Optional[str] = None
    detector: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "line_number": self.line_number,
            "description": self.description,
            "fix_suggestion": self.fix_suggestion,
            "detector": self.detector,
        }


class BaseDetector(ABC):
    """Scan a block of source text and return zero or more findings."""

    name: str = "base"

    @abstractmethod
    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        ...

    def _scan_lines(
        self,
        content: str,
        patterns: list[tuple],  # (compiled_re, severity, description, fix)
    ) -> list[DetectionResult]:
        """Helper: iterate lines, match each pattern, return findings."""
        results: list[DetectionResult] = []
        for lineno, line in enumerate(content.splitlines(), start=1):
            for pattern, severity, description, fix in patterns:
                if pattern.search(line):
                    results.append(
                        DetectionResult(
                            severity=severity,
                            category=self.name,
                            line_number=lineno,
                            description=description,
                            fix_suggestion=fix,
                            detector=self.name,
                        )
                    )
        return results
