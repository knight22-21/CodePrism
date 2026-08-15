"""Detector: weak or deprecated cryptographic primitives."""

from __future__ import annotations

import re

from .base import BaseDetector, DetectionResult

_PATTERNS = [
    (
        re.compile(r'\bhashlib\.md5\s*\('),
        "WARN",
        "MD5 is cryptographically weak for security-sensitive contexts",
        "Use hashlib.sha256() or better; for passwords use bcrypt/argon2",
    ),
    (
        re.compile(r'\bhashlib\.sha1\s*\('),
        "WARN",
        "SHA-1 is cryptographically weak",
        "Use hashlib.sha256() or better; for passwords use bcrypt/argon2",
    ),
    (
        re.compile(r'\brandom\.(random|randint|choice|shuffle|sample)\s*\('),
        "INFO",
        "random module is not cryptographically secure",
        "Use the secrets module for security-sensitive randomness",
    ),
    (
        re.compile(r'\bDES\b.*\.new\s*\(|\bfrom\s+Crypto\.Cipher\s+import\s+DES\b'),
        "WARN",
        "DES is a deprecated and broken cipher",
        "Use AES-256-GCM or ChaCha20-Poly1305",
    ),
    (
        re.compile(r'\bRC4\b|\bRC2\b|\bARC4\b'),
        "WARN",
        "RC4/RC2 are broken stream ciphers",
        "Use AES-256-GCM or ChaCha20-Poly1305",
    ),
    (
        re.compile(r'\bECB\b|MODE_ECB'),
        "WARN",
        "ECB mode leaks plaintext patterns and is not semantically secure",
        "Use AES-GCM (authenticated) or AES-CBC with a random IV",
    ),
]


class WeakCryptoDetector(BaseDetector):
    name = "crypto"

    def scan(self, content: str, file_path: str = "") -> list[DetectionResult]:
        return self._scan_lines(content, _PATTERNS)
