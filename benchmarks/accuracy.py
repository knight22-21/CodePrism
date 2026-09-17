"""
LLM-as-judge accuracy evaluator.

REQUIRES: ANTHROPIC_API_KEY environment variable.
COST:      ~2 API calls per task (one answer, one judge). ~$0.001-0.005 per task.

Set BENCHMARK_SKIP_ACCURACY=1 to skip accuracy evaluation entirely
and only measure token counts (free, no API calls).
"""

from __future__ import annotations

import os

# ── PENDING: needs ANTHROPIC_API_KEY confirmed by user ────────────────────────
# See BENCHMARKING.md §"Open Questions" for what is needed before enabling.
_SKIP = os.environ.get("BENCHMARK_SKIP_ACCURACY", "0") == "1"
_MODEL = os.environ.get("BENCHMARK_JUDGE_MODEL", "claude-haiku-4-5-20251001")


def accuracy_available() -> bool:
    """Returns True if the accuracy evaluator can run (API key present + not skipped)."""
    if _SKIP:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def evaluate_answer(prompt: str, ground_truth: str) -> float:
    """
    Ask the LLM to answer the task from *prompt*, then judge against *ground_truth*.
    Returns a float in [0.0, 1.0].

    Raises RuntimeError if ANTHROPIC_API_KEY is not set.
    """
    if not accuracy_available():
        raise RuntimeError(
            "Accuracy evaluation requires ANTHROPIC_API_KEY. "
            "Set BENCHMARK_SKIP_ACCURACY=1 to run token-only mode."
        )

    import anthropic
    client = anthropic.Anthropic()

    # Step 1 — get the LLM's answer to the task
    answer_resp = client.messages.create(
        model=_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = answer_resp.content[0].text.strip()

    # Step 2 — judge the answer against ground truth
    judge_prompt = (
        f"Ground truth answer: {ground_truth}\n\n"
        f"Candidate answer: {answer}\n\n"
        "Score the candidate answer from 0.0 (completely wrong) to 1.0 (fully correct). "
        "A score of 0.8+ means the key facts are present. "
        "Reply with ONLY a decimal number, nothing else."
    )
    judge_resp = client.messages.create(
        model=_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": judge_prompt}],
    )
    try:
        return min(1.0, max(0.0, float(judge_resp.content[0].text.strip())))
    except ValueError:
        return 0.0
