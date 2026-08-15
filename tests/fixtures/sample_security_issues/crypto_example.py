"""Intentionally insecure — used only in detector tests."""

import hashlib
import random


def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()


def hash_content(content: str) -> str:
    return hashlib.sha1(content.encode()).hexdigest()


def generate_pin() -> int:
    return random.randint(100000, 999999)
