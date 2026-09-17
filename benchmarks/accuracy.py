"""
LLM-as-judge accuracy evaluator.

Supports three backends (set BENCHMARK_JUDGE_BACKEND):
  anthropic  -- Anthropic API (ANTHROPIC_API_KEY required)
  ollama     -- Ollama cloud or local, OpenAI-compatible (OLLAMA_API_KEY + OLLAMA_BASE_URL)
  openai     -- OpenAI-compatible endpoint (OPENAI_API_KEY + optional OPENAI_BASE_URL)

Cost per task:
  ~2 API calls (one answer, one judge).

Set BENCHMARK_SKIP_ACCURACY=1 to skip accuracy evaluation entirely
and only measure token counts (free, no API calls).
"""

from __future__ import annotations

import benchmarks._env  # noqa: F401 — loads .env before os.environ is read
import os

_SKIP = os.environ.get("BENCHMARK_SKIP_ACCURACY", "0") == "1"
_BACKEND = os.environ.get("BENCHMARK_JUDGE_BACKEND", "auto").lower()

# Ollama cloud settings (https://ollama.com/v1 — OpenAI-compatible)
_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
_OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
_OLLAMA_MODEL = os.environ.get("BENCHMARK_JUDGE_MODEL", "gpt-oss:120b")

# Anthropic settings
_ANTHROPIC_MODEL = os.environ.get("BENCHMARK_JUDGE_MODEL", "claude-haiku-4-5-20251001")

# OpenAI-compatible settings
_OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
_OPENAI_MODEL = os.environ.get("BENCHMARK_JUDGE_MODEL", "gpt-4o-mini")


def accuracy_available() -> bool:
    """Returns True if any accuracy backend is configured and not skipped."""
    if _SKIP:
        return False
    resolved = _resolve_backend()
    if resolved == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if resolved == "ollama":
        return bool(_OLLAMA_API_KEY)
    if resolved == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return False


def active_backend() -> str:
    """Return a human-readable description of the active judge backend."""
    if _SKIP:
        return "disabled (BENCHMARK_SKIP_ACCURACY=1)"
    b = _resolve_backend()
    if b == "ollama":
        return f"ollama ({_OLLAMA_BASE_URL}, model={_OLLAMA_MODEL})"
    if b == "anthropic":
        return f"anthropic (model={_ANTHROPIC_MODEL})"
    if b == "openai":
        return f"openai-compatible (model={_OPENAI_MODEL})"
    return "none configured"


def _resolve_backend() -> str:
    if _BACKEND != "auto":
        return _BACKEND
    if _OLLAMA_API_KEY:
        return "ollama"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "none"


async def evaluate_answer(prompt: str, ground_truth: str) -> float:
    """
    Ask the LLM to answer the task from *prompt*, then judge against *ground_truth*.
    Returns a float in [0.0, 1.0].

    Raises RuntimeError if no backend is configured.
    """
    if not accuracy_available():
        raise RuntimeError(
            "No LLM backend configured for accuracy evaluation. "
            "Set OLLAMA_API_KEY (+ OLLAMA_BASE_URL), ANTHROPIC_API_KEY, or OPENAI_API_KEY. "
            "Or set BENCHMARK_SKIP_ACCURACY=1 to run token-only mode."
        )

    backend = _resolve_backend()

    if backend == "anthropic":
        return await _evaluate_anthropic(prompt, ground_truth)
    elif backend in ("ollama", "openai"):
        return await _evaluate_openai_compat(prompt, ground_truth)
    else:
        raise RuntimeError(f"Unknown backend: {backend}")


# ── Backends ──────────────────────────────────────────────────────────────────

async def _evaluate_anthropic(prompt: str, ground_truth: str) -> float:
    import anthropic
    client = anthropic.Anthropic()

    answer_resp = client.messages.create(
        model=_ANTHROPIC_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = answer_resp.content[0].text.strip()

    judge_prompt = _judge_prompt(ground_truth, answer)
    judge_resp = client.messages.create(
        model=_ANTHROPIC_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": judge_prompt}],
    )
    return _parse_score(judge_resp.content[0].text)


async def _evaluate_openai_compat(prompt: str, ground_truth: str) -> float:
    """Works for both Ollama cloud and any OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI

    backend = _resolve_backend()
    if backend == "ollama":
        # _OLLAMA_BASE_URL already includes /v1 (https://ollama.com/v1)
        client = AsyncOpenAI(
            api_key=_OLLAMA_API_KEY,
            base_url=_OLLAMA_BASE_URL.rstrip("/"),
        )
        model = _OLLAMA_MODEL
    else:
        client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=_OPENAI_BASE_URL.rstrip("/"),
        )
        model = _OPENAI_MODEL

    answer_resp = await client.chat.completions.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = answer_resp.choices[0].message.content or ""

    judge_resp = await client.chat.completions.create(
        model=model,
        max_tokens=10,
        messages=[{"role": "user", "content": _judge_prompt(ground_truth, answer)}],
    )
    return _parse_score(judge_resp.choices[0].message.content or "0")


def _judge_prompt(ground_truth: str, answer: str) -> str:
    return (
        f"Ground truth answer: {ground_truth}\n\n"
        f"Candidate answer: {answer}\n\n"
        "Score the candidate answer from 0.0 (completely wrong) to 1.0 (fully correct). "
        "A score of 0.8+ means the key facts are present. "
        "Reply with ONLY a decimal number, nothing else."
    )


def _parse_score(text: str) -> float:
    try:
        return min(1.0, max(0.0, float(text.strip())))
    except ValueError:
        return 0.0
