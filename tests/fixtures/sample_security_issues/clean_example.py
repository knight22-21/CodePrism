"""Clean file with no security issues — control case for detector tests."""

import hashlib
import os
import secrets


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def generate_token() -> str:
    return secrets.token_hex(32)


def get_config(key: str) -> str:
    return os.environ.get(key, "")
