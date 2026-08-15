"""Detector: hardcoded secrets, API keys, tokens, and passwords."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

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
        re.compile(r'AKIA[0-9A-Z]{16}'),
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
        re.compile(r'\bsk-[a-zA-Z0-9]{20,}'),
        "BLOCK",
        "Possible OpenAI API key",
        "Revoke at platform.openai.com and load from environment",
    ),
    (
        re.compile(r'\bghp_[a-zA-Z0-9]{36}\b'),
        "BLOCK",
        "GitHub personal access token",
        "Revoke at github.com/settings/tokens immediately",
    ),
]


class SecretsDetector(BaseDetector):
    name = "secrets"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
