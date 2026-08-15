"""SecurityGate — intercepts proposed writes before they hit disk."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .scanner import SecurityReport, SecurityScanner

if TYPE_CHECKING:
    pass


class SecurityGate:
    """
    High-level write guard: check proposed file content before writing.

    Usage::

        gate = SecurityGate()
        report = await gate.check_write("payments/processor.py", new_content)
        if report.is_blocked:
            raise ValueError(f"Write blocked: {report.issues[0].description}")

    Decision logic (spec §11):
        BLOCK  — hardcoded secrets, SQL injection, eval(user_input), …
        WARN   — weak crypto, new external dep, broad exception suppression, …
        PASS   — no new issues introduced by this change
    """

    def __init__(self, scanner: SecurityScanner | None = None) -> None:
        self._scanner = scanner or SecurityScanner()

    async def check_write(
        self,
        file: str,
        proposed_content: str,
    ) -> SecurityReport:
        """
        Diff-scan: report only issues *introduced* by the proposed change.

        Reads the current file from disk to compute the baseline.
        If the file does not yet exist the baseline is empty.
        """
        try:
            current_content = Path(file).read_text(encoding="utf-8")
        except FileNotFoundError:
            current_content = ""
        return self._scanner.scan_diff(current_content, proposed_content, file)

    async def check_content(
        self,
        content: str,
        file: str = "",
    ) -> SecurityReport:
        """Full scan of content with no diff — use for new files or raw checks."""
        return self._scanner.scan_content(content, file)
