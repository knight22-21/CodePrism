"""SecurityScanner — orchestrates all detectors and computes aggregate reports."""

from __future__ import annotations

from dataclasses import dataclass, field

from .detectors import (
    BaseDetector,
    DependenciesDetector,
    DetectionResult,
    EnvVarDetector,
    GitSafetyDetector,
    InjectionDetector,
    SecretsDetector,
    WeakCryptoDetector,
)


def _compute_status(issues: list[DetectionResult]) -> str:
    for issue in issues:
        if issue.severity == "BLOCK":
            return "BLOCK"
    for issue in issues:
        if issue.severity == "WARN":
            return "WARN"
    return "PASS"


@dataclass
class SecurityReport:
    """Aggregate result of running all detectors against a piece of content."""

    status: str  # PASS | WARN | BLOCK
    issues: list[DetectionResult] = field(default_factory=list)
    file: str = ""

    @property
    def is_blocked(self) -> bool:
        return self.status == "BLOCK"

    @property
    def has_warnings(self) -> bool:
        return self.status in {"WARN", "BLOCK"}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "file": self.file,
            "issues": [i.to_dict() for i in self.issues],
        }


class SecurityScanner:
    """
    Runs the full detector suite against source content.

    Two entry-points:
    - scan_content(): scan a single content blob, return all findings
    - scan_diff(): scan both original and proposed, return *only new* findings
    """

    def __init__(self, detectors: list[BaseDetector] | None = None) -> None:
        self._detectors: list[BaseDetector] = detectors or [
            SecretsDetector(),
            InjectionDetector(),
            WeakCryptoDetector(),
            EnvVarDetector(),
            DependenciesDetector(),
            GitSafetyDetector(),
        ]

    def scan_content(self, content: str, file_path: str = "") -> SecurityReport:
        """Scan content with all detectors and return every finding."""
        issues: list[DetectionResult] = []
        for detector in self._detectors:
            issues.extend(detector.scan(content, file_path))
        return SecurityReport(
            status=_compute_status(issues),
            issues=issues,
            file=file_path,
        )

    def scan_diff(
        self, original: str, proposed: str, file_path: str = ""
    ) -> SecurityReport:
        """
        Return only findings that are *new* in proposed (not present in original).

        Matching is by (description, stripped line content) so issues that shift
        line numbers due to inserted content are not re-reported as new.
        """
        orig_lines = original.splitlines()
        orig_report = self.scan_content(original, file_path)
        orig_signatures = set()
        for issue in orig_report.issues:
            line_content = ""
            if issue.line_number and issue.line_number <= len(orig_lines):
                line_content = orig_lines[issue.line_number - 1].strip()
            orig_signatures.add((issue.description, line_content))

        proposed_lines = proposed.splitlines()
        proposed_report = self.scan_content(proposed, file_path)
        new_issues: list[DetectionResult] = []
        for issue in proposed_report.issues:
            line_content = ""
            if issue.line_number and issue.line_number <= len(proposed_lines):
                line_content = proposed_lines[issue.line_number - 1].strip()
            if (issue.description, line_content) not in orig_signatures:
                new_issues.append(issue)

        return SecurityReport(
            status=_compute_status(new_issues),
            issues=new_issues,
            file=file_path,
        )

    def scan_secrets_only(self, content: str, file_path: str = "") -> SecurityReport:
        """Run only the SecretsDetector — used by check_secret_exposure."""
        issues = SecretsDetector().scan(content, file_path)
        return SecurityReport(
            status=_compute_status(issues),
            issues=issues,
            file=file_path,
        )
