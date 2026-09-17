"""
Baseline prompt builder.

Simulates what an LLM agent does WITHOUT CodePrism:
reads every file that a human would need to answer the task,
concatenates them into a single context block.
"""

from __future__ import annotations

from pathlib import Path


def build_baseline_prompt(repo_path: str, task: dict) -> str:
    """
    Build a context prompt by reading raw file content.

    task schema:
      relevant_files: list[str]   — paths relative to repo_path
      query: str                  — the natural-language question
    """
    repo = Path(repo_path)
    context_parts: list[str] = []

    for rel in task["relevant_files"]:
        fp = repo / rel
        if not fp.exists():
            context_parts.append(f"### {rel}\n[file not found]")
            continue
        content = fp.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"### {rel}\n```\n{content}\n```")

    context = "\n\n".join(context_parts)
    return (
        f"You are a code analysis assistant.\n\n"
        f"## Codebase context\n\n{context}\n\n"
        f"## Task\n\n{task['query']}"
    )


def count_baseline_files(task: dict) -> int:
    return len(task["relevant_files"])


def baseline_total_chars(repo_path: str, task: dict) -> int:
    repo = Path(repo_path)
    total = 0
    for rel in task["relevant_files"]:
        fp = repo / rel
        if fp.exists():
            total += fp.stat().st_size
    return total
