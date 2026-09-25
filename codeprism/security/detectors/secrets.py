"""Detector: hardcoded secrets, API keys, tokens, and passwords."""

from __future__ import annotations

import math
import re

from .base import BaseDetector, DetectionResult

# Strings shorter than this are never flagged by entropy analysis (too many false positives).
_ENTROPY_MIN_LEN = 20
# Shannon entropy threshold in bits-per-character. Random 62-char strings score ~5.9;
# typical passwords/tokens score 4.0–5.5. We flag at 4.5 to catch real secrets with
# some headroom above common English words (which score < 3.5).
_ENTROPY_THRESHOLD = 4.5
# Matches quoted string literals that look like they could be secret values.
_ENTROPY_STRING_RE = re.compile(r"""(?:["'])([A-Za-z0-9+/=_\-]{20,})(?:["'])""")

# Patterns without strict \b word boundaries so compound names like
# DATABASE_PASSWORD, MY_API_KEY, etc. are also caught.
_PATTERNS = [
    (
        re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']'),
        "BLOCK",
        "Hardcoded password",
        "Load from environment: os.environ.get('PASSWORD')",
    ),
    (
        re.compile(r'(?i)(api[_-]?key|apikey)\s*=\s*["\'][^"\']{8,}["\']'),
        "BLOCK",
        "Hardcoded API key",
        "Load from environment: os.environ.get('API_KEY')",
    ),
    (
        re.compile(r'(?i)(secret[_-]?key|client_secret)\s*=\s*["\'][^"\']{8,}["\']'),
        "BLOCK",
        "Hardcoded secret key",
        "Use a secrets manager or environment variable",
    ),
    (
        re.compile(r'(?i)(access_token|auth_token)\s*=\s*["\'][^"\']{16,}["\']'),
        "BLOCK",
        "Hardcoded access token",
        "Load from a secrets manager or environment variable",
    ),
    # Well-known key formats
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "BLOCK",
        "AWS access key ID",
        "Remove immediately and rotate via IAM console",
    ),
    (
        re.compile(r'(?i)aws_secret_access_key\s*=\s*["\'][^"\']+["\']'),
        "BLOCK",
        "AWS secret access key",
        "Use IAM roles or AWS Secrets Manager",
    ),
    (
        re.compile(r"\bsk-[a-zA-Z0-9]{20,}"),
        "BLOCK",
        "Possible OpenAI API key",
        "Revoke at platform.openai.com and load from environment",
    ),
    (
        re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),
        "BLOCK",
        "GitHub personal access token",
        "Revoke at github.com/settings/tokens immediately",
    ),
    (
        re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{32,}"),
        "BLOCK",
        "Anthropic API key",
        "Revoke at console.anthropic.com and load from environment",
    ),
    (
        re.compile(r"\bxox[baprs]-[0-9A-Za-z-]+"),
        "BLOCK",
        "Slack token",
        "Revoke at api.slack.com/apps and load from environment",
    ),
    (
        re.compile(r"\bsk_live_[a-zA-Z0-9]{24,}"),
        "BLOCK",
        "Stripe live secret key",
        "Revoke at dashboard.stripe.com/apikeys and load from environment",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "WARN",
        "Possible JWT token",
        "JWTs contain encoded claims — avoid hardcoding in source files",
    ),
]


def _shannon_entropy(s: str) -> float:
    """Return Shannon entropy in bits per character."""
    if not s:
        return 0.0
    freq = {c: s.count(c) / len(s) for c in set(s)}
    return -sum(p * math.log2(p) for p in freq.values())


class SecretsDetector(BaseDetector):
    name = "secrets"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        results = self._scan_lines(content, _PATTERNS)
        already_flagged = {r.line_number for r in results}

        # Entropy pass: flag high-entropy quoted strings not already caught by patterns.
        for lineno, line in enumerate(content.splitlines(), start=1):
            if lineno in already_flagged:
                continue
            for match in _ENTROPY_STRING_RE.finditer(line):
                candidate = match.group(1)
                if (
                    len(candidate) >= _ENTROPY_MIN_LEN
                    and _shannon_entropy(candidate) >= _ENTROPY_THRESHOLD
                ):
                    results.append(
                        DetectionResult(
                            severity="WARN",
                            category=self.name,
                            line_number=lineno,
                            description=(
                                f"High-entropy string (entropy={_shannon_entropy(candidate):.2f}) "
                                "— possible hardcoded secret"
                            ),
                            fix_suggestion="Load from environment variable or secrets manager",
                            detector="secrets-entropy",
                        )
                    )
        return results
