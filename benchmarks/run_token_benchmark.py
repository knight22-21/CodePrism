"""
Level 1 token reduction benchmark — run with:

    python -m benchmarks.run_token_benchmark [--tasks tasks/fixture_tasks.json]
                                              [--repo  <path-to-repo>]
                                              [--out   results/run.json]

Environment variables
---------------------
BENCHMARK_TOKEN_BACKEND   claude | tiktoken | approx  (default: auto)
BENCHMARK_SKIP_ACCURACY   1                            (default: 0 = run if key available)
BENCHMARK_JUDGE_MODEL     model-id                     (default: claude-haiku-4-5-20251001)
ANTHROPIC_API_KEY         required for accuracy + claude token backend
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from benchmarks.baseline import build_baseline_prompt
from benchmarks.codeprism_prompt import build_codeprism_prompt
from benchmarks.token_counter import count_tokens, backend_name
from benchmarks.accuracy import accuracy_available, evaluate_answer

# ── helpers ───────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _resolve_repo(task: dict, cli_repo: str | None) -> str:
    if cli_repo:
        return cli_repo
    rel = task.get("repo_path", ".")
    return str(_repo_root() / rel)


def _pct(a: int, b: int) -> str:
    if b == 0:
        return "  n/a"
    return f"{(1 - a / b) * 100:+.1f}%"


def _bar(ratio: float, width: int = 20) -> str:
    """Simple ASCII bar: ratio is codeprism/baseline (lower = better)."""
    filled = max(0, min(width, int(ratio * width)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


# ── per-task runner ───────────────────────────────────────────────────────────

async def run_task(task: dict, repo_path: str, run_accuracy: bool) -> dict:
    tid = task["id"]

    # baseline — sync
    t0 = time.perf_counter()
    baseline_prompt = build_baseline_prompt(repo_path, task)
    baseline_ms = (time.perf_counter() - t0) * 1000
    baseline_tokens = count_tokens(baseline_prompt)

    # codeprism — async
    t0 = time.perf_counter()
    try:
        cp_prompt = await build_codeprism_prompt(repo_path, task)
    except Exception as exc:
        cp_prompt = f"[ERROR: {exc}]"
    cp_ms = (time.perf_counter() - t0) * 1000
    cp_tokens = count_tokens(cp_prompt)

    reduction_pct = (1 - cp_tokens / baseline_tokens) * 100 if baseline_tokens else 0.0

    result: dict = {
        "id": tid,
        "type": task.get("type", ""),
        "baseline_tokens": baseline_tokens,
        "cp_tokens": cp_tokens,
        "reduction_pct": round(reduction_pct, 1),
        "baseline_ms": round(baseline_ms, 1),
        "cp_ms": round(cp_ms, 1),
    }

    if run_accuracy:
        try:
            baseline_score = await evaluate_answer(baseline_prompt, task["ground_truth"])
            cp_score = await evaluate_answer(cp_prompt, task["ground_truth"])
            result["baseline_accuracy"] = round(baseline_score, 2)
            result["cp_accuracy"] = round(cp_score, 2)
        except Exception as exc:
            result["accuracy_error"] = str(exc)

    return result


# ── terminal table ────────────────────────────────────────────────────────────

def print_table(results: list[dict], run_accuracy: bool) -> None:
    has_acc = run_accuracy and any("baseline_accuracy" in r for r in results)

    header = f"{'ID':<16} {'Baseline':>9} {'CodePrism':>9} {'Reduction':>10}"
    if has_acc:
        header += f"  {'Acc-BL':>6} {'Acc-CP':>6}"
    header += f"  Bar (CP/BL)"
    print()
    print(header)
    print("-" * len(header))

    total_baseline = 0
    total_cp = 0
    for r in results:
        baseline = r["baseline_tokens"]
        cp = r["cp_tokens"]
        total_baseline += baseline
        total_cp += cp
        ratio = cp / baseline if baseline else 1.0
        row = (
            f"{r['id']:<16}"
            f" {baseline:>9,}"
            f" {cp:>9,}"
            f" {r['reduction_pct']:>+9.1f}%"
        )
        if has_acc:
            ba = r.get("baseline_accuracy", float("nan"))
            ca = r.get("cp_accuracy", float("nan"))
            row += f"  {ba:>6.2f} {ca:>6.2f}"
        row += f"  {_bar(ratio)}"
        print(row)

    print("-" * len(header))
    total_reduction = (1 - total_cp / total_baseline) * 100 if total_baseline else 0.0
    summary = (
        f"{'TOTAL':<16}"
        f" {total_baseline:>9,}"
        f" {total_cp:>9,}"
        f" {total_reduction:>+9.1f}%"
    )
    print(summary)
    print()
    print(f"Token backend: {backend_name()}")
    if has_acc:
        avg_bl = sum(r.get("baseline_accuracy", 0) for r in results if "baseline_accuracy" in r)
        avg_cp = sum(r.get("cp_accuracy", 0) for r in results if "cp_accuracy" in r)
        n = sum(1 for r in results if "baseline_accuracy" in r)
        print(f"Avg accuracy  baseline={avg_bl/n:.2f}  codeprism={avg_cp/n:.2f}  (n={n})")


# ── main ──────────────────────────────────────────────────────────────────────

async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Level 1 token reduction benchmark")
    parser.add_argument(
        "--tasks",
        default=str(Path(__file__).parent / "tasks" / "fixture_tasks.json"),
        help="Path to JSON task file",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Override repo_path for all tasks",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "results" / "token_benchmark.json"),
        help="Output JSON file for results",
    )
    parser.add_argument(
        "--accuracy",
        action="store_true",
        default=False,
        help="Enable LLM-as-judge accuracy eval (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        default=None,
        help="Run only these task IDs",
    )
    args = parser.parse_args(argv)

    # Load tasks
    tasks_path = Path(args.tasks)
    if not tasks_path.exists():
        print(f"ERROR: tasks file not found: {tasks_path}", file=sys.stderr)
        sys.exit(1)
    with tasks_path.open(encoding="utf-8") as f:
        tasks: list[dict] = json.load(f)

    if args.ids:
        tasks = [t for t in tasks if t["id"] in args.ids]
        if not tasks:
            print(f"No tasks matched IDs: {args.ids}", file=sys.stderr)
            sys.exit(1)

    run_accuracy = args.accuracy and accuracy_available()
    if args.accuracy and not accuracy_available():
        print(
            "WARNING: --accuracy requested but ANTHROPIC_API_KEY not set or "
            "BENCHMARK_SKIP_ACCURACY=1. Skipping accuracy eval.",
            file=sys.stderr,
        )

    print(f"Running {len(tasks)} tasks  [backend={backend_name()}  accuracy={run_accuracy}]")
    print()

    results: list[dict] = []
    for i, task in enumerate(tasks, 1):
        repo = _resolve_repo(task, args.repo)
        print(f"  [{i}/{len(tasks)}] {task['id']} ...", end=" ", flush=True)
        r = await run_task(task, repo, run_accuracy)
        results.append(r)
        print(f"{r['baseline_tokens']:,} → {r['cp_tokens']:,} tokens  ({r['reduction_pct']:+.1f}%)")

    print_table(results, run_accuracy)

    # Save results
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token_backend": backend_name(),
        "accuracy_enabled": run_accuracy,
        "tasks": results,
        "summary": {
            "total_baseline_tokens": sum(r["baseline_tokens"] for r in results),
            "total_cp_tokens": sum(r["cp_tokens"] for r in results),
            "avg_reduction_pct": round(
                sum(r["reduction_pct"] for r in results) / len(results), 1
            ) if results else 0.0,
        },
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
