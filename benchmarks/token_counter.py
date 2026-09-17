"""
Token counting utilities.

Priority order:
  1. tiktoken (fast, free, GPT-4 tokenizer — close enough for comparison purposes)
  2. anthropic count_tokens API (exact Claude tokens — requires ANTHROPIC_API_KEY)
  3. word-based approximation (always available, ~15% error margin)

Set BENCHMARK_TOKEN_BACKEND=claude|tiktoken|approx to force one backend.
"""

from __future__ import annotations

import benchmarks._env  # noqa: F401 — loads .env before os.environ is read
import os
import re

_BACKEND = os.environ.get("BENCHMARK_TOKEN_BACKEND", "auto").lower()


def count_tokens(text: str) -> int:
    """Count tokens in *text* using the best available backend."""
    if _BACKEND == "claude":
        return _count_claude(text)
    if _BACKEND == "tiktoken":
        return _count_tiktoken(text)
    if _BACKEND == "approx":
        return _count_approx(text)

    # auto: tiktoken > approx (claude needs explicit opt-in due to API cost)
    try:
        return _count_tiktoken(text)
    except ImportError:
        return _count_approx(text)


def backend_name() -> str:
    """Return a human-readable string describing which backend is active."""
    if _BACKEND == "claude":
        return "claude-tokenizer (API)"
    if _BACKEND == "tiktoken":
        return "tiktoken (cl100k_base)"
    if _BACKEND == "approx":
        return "word-approximation"
    try:
        import tiktoken  # noqa: F401
        return "tiktoken (cl100k_base)"
    except ImportError:
        return "word-approximation"


# ── Backends ──────────────────────────────────────────────────────────────────


def _count_tiktoken(text: str) -> int:
    """Count using tiktoken with the cl100k_base encoding (GPT-4 / Claude-compatible)."""
    import tiktoken  # pip install tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _count_claude(text: str) -> int:
    """Count using Anthropic's real tokenizer via the API.

    Requires:  ANTHROPIC_API_KEY env var.
    Cost:      One lightweight API call per invocation (~$0.000001).
    """
    import anthropic
    client = anthropic.Anthropic()
    response = client.beta.messages.count_tokens(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": text}],
        betas=["token-counting-2024-11-01"],
    )
    return response.input_tokens


def _count_approx(text: str) -> int:
    """Rough approximation: words × 1.3 (adequate for large-ratio comparisons)."""
    words = len(re.findall(r"\S+", text))
    return int(words * 1.3)
