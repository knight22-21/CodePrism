"""
List models available on the configured Ollama cloud account.

    python -m benchmarks.list_models

Reads OLLAMA_API_KEY and OLLAMA_BASE_URL from .env / environment.
Prints each model with a suitability rating for LLM-as-judge tasks.
"""

from __future__ import annotations

import benchmarks._env  # noqa: F401
import os
import sys

_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1").rstrip("/")
_API_KEY = os.environ.get("OLLAMA_API_KEY", "")

# Confirmed Ollama cloud models (ollama.com/search?c=cloud) — 2026-09-17
# rating: A = excellent, B = good, C = adequate for structured 0-1 judge scoring
_JUDGE_RATINGS: dict[str, tuple[str, str]] = {
    # -- Tier A: best for judging (instruction-following + output format) --
    "llama3.3:70b":      ("A", "Best balance quality/speed for judge tasks; top pick"),
    "llama3.3":          ("A", "Same as 70b if cloud routes to it automatically"),
    "qwen3.5":           ("A", "Strong reasoning, strict format adherence"),
    "qwen3-coder":       ("A", "Excellent at structured output"),
    "deepseek-v4-flash": ("A", "Fastest + cheapest on Ollama cloud; 1M ctx; great for high-volume"),
    # -- Tier B: good, minor caveats --
    "llama3.1":          ("B", "Widely tested as judge, slightly older"),
    "llama3.2":          ("B", "Smaller, fast, adequate for binary scoring"),
    "qwen3-coder-480b":  ("B", "Huge model, excellent reasoning but slower + heavier"),
    "nemotron-3-super":  ("B", "Good reasoning, less tested as judge"),
    "glm-5.1":           ("B", "Good structured output"),
    "glm4":              ("B", "Predecessor, still solid"),
    "gemma4":            ("B", "Good but may not follow decimal-only format strictly"),
    "minimax-m3":        ("B", "Good for comparison tasks"),
    "minimax-m2.7":      ("B", "Lighter minimax variant"),
    "kimi-k2.6":         ("B", "Strong reasoning; format compliance variable"),
    # -- Tier C: usable but not ideal --
    "deepseek-r1":       ("C", "Excellent reasoning but verbose — often ignores score-only format"),
    "phi4-mini":         ("C", "Very fast, adequate for rough scoring"),
    "mistral":           ("C", "Adequate general judge"),
}


def _rate(name: str) -> tuple[str, str]:
    # Check exact then prefix match
    if name in _JUDGE_RATINGS:
        return _JUDGE_RATINGS[name]
    for k, v in _JUDGE_RATINGS.items():
        if name.startswith(k.split(":")[0]):
            return v
    return ("?", "Unknown — test before using as judge")


def main() -> None:
    if not _API_KEY:
        print("ERROR: OLLAMA_API_KEY not set.")
        print("       Add it to your .env file and re-run.")
        sys.exit(1)

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL)

    try:
        models_page = client.models.list()
        models = sorted(m.id for m in models_page.data)
    except Exception as exc:
        print(f"ERROR fetching models: {exc}")
        sys.exit(1)

    if not models:
        print("No models returned. Check your API key and base URL.")
        sys.exit(1)

    print(f"\nModels available on {_BASE_URL}")
    print(f"{'Model':<30} {'Judge rating':<14} Notes")
    print("-" * 80)
    for name in models:
        rating, notes = _rate(name)
        print(f"{name:<30} [{rating}]          {notes}")

    print()
    a_models = [m for m in models if _rate(m)[0] == "A"]
    b_models = [m for m in models if _rate(m)[0] == "B"]

    if a_models:
        print(f"Recommended for judging (A-rated): {', '.join(a_models)}")
        print(f"Set in .env:  BENCHMARK_JUDGE_MODEL={a_models[0]}")
    elif b_models:
        print(f"Recommended for judging (B-rated): {', '.join(b_models)}")
        print(f"Set in .env:  BENCHMARK_JUDGE_MODEL={b_models[0]}")
    else:
        print("No known-good judge models found in your account. Try llama3.1 or qwen2.5.")
    print()


if __name__ == "__main__":
    main()
