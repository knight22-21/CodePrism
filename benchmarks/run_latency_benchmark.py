"""
Level 2 latency benchmark — run with:

    python -m benchmarks.run_latency_benchmark
    python -m benchmarks.run_latency_benchmark --tasks tasks/requests_tasks.json --reps 30

Measures p50 / p95 / p99 query latency for CodePrism graph queries vs baseline
file reads.  The CodePrism engine is held open across all tasks for a given repo
so indexing time is NOT included — only pure query latency is timed.

Warmup runs are discarded before measurement begins.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

from benchmarks.baseline import build_baseline_prompt
from benchmarks.codeprism_prompt import _resolve_file_path
from codeprism import CodePrism

# ── percentile helpers ────────────────────────────────────────────────────────

def _pct(samples: list[float], p: float) -> float:
    """Return the p-th percentile (0–100) of samples."""
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = (p / 100) * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _stats(samples: list[float]) -> dict:
    return {
        "min":  round(min(samples), 2),
        "mean": round(statistics.mean(samples), 2),
        "p50":  round(_pct(samples, 50), 2),
        "p95":  round(_pct(samples, 95), 2),
        "p99":  round(_pct(samples, 99), 2),
        "max":  round(max(samples), 2),
    }


# ── single query runner (no CodePrism context overhead) ──────────────────────

async def _run_cp_query(engine, resolved_file: str, task: dict) -> None:
    """Execute the graph queries for a task once (timing target)."""
    tools = task.get("cp_tools", ["get_context"])
    for tool in tools:
        if tool == "get_context":
            await engine.get_context(resolved_file, task["function"], depth=2)
        elif tool == "get_impact":
            await engine.get_impact(resolved_file, task["function"])
        elif tool == "get_callers":
            await engine.get_callers(resolved_file, task["function"])
        elif tool == "get_dependencies":
            await engine.get_dependencies(resolved_file)
        elif tool == "search_symbol":
            q = task.get("search_query", task["function"])
            await engine.search_symbols(q)


def _run_baseline(repo_path: str, task: dict) -> None:
    """Read relevant files once (timing target for baseline)."""
    build_baseline_prompt(repo_path, task)


# ── per-task latency measurement ──────────────────────────────────────────────

async def measure_task(
    engine,
    repo_path: str,
    task: dict,
    reps: int,
    warmup: int,
) -> dict:
    resolved_file = await _resolve_file_path(engine, task["file"])

    # Warmup — results discarded
    for _ in range(warmup):
        await _run_cp_query(engine, resolved_file, task)
        _run_baseline(repo_path, task)

    # Measurement
    cp_samples: list[float] = []
    bl_samples: list[float] = []

    for _ in range(reps):
        t0 = time.perf_counter()
        await _run_cp_query(engine, resolved_file, task)
        cp_samples.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        _run_baseline(repo_path, task)
        bl_samples.append((time.perf_counter() - t0) * 1000)

    cp = _stats(cp_samples)
    bl = _stats(bl_samples)
    overhead = round(cp["p50"] - bl["p50"], 2)

    return {
        "id":         task["id"],
        "type":       task.get("type", ""),
        "tools":      task.get("cp_tools", ["get_context"]),
        "reps":       reps,
        "baseline":   bl,
        "codeprism":  cp,
        "overhead_p50_ms": overhead,
    }


# ── terminal table ────────────────────────────────────────────────────────────

def print_table(results: list[dict]) -> None:
    header = (
        f"{'Task':<20} {'Type':<16} "
        f"{'BL-p50':>7} {'BL-p95':>7}  "
        f"{'CP-p50':>7} {'CP-p95':>7}  "
        f"{'Overhead':>9}"
    )
    sep = "-" * len(header)
    print()
    print(header)
    print(sep)
    for r in results:
        bl = r["baseline"]
        cp = r["codeprism"]
        overhead = r["overhead_p50_ms"]
        sign = "+" if overhead >= 0 else ""
        print(
            f"{r['id']:<20} {r['type']:<16} "
            f"{bl['p50']:>6.1f}ms {bl['p95']:>6.1f}ms  "
            f"{cp['p50']:>6.1f}ms {cp['p95']:>6.1f}ms  "
            f"{sign}{overhead:>7.1f}ms"
        )
    print(sep)

    # Per-tool aggregate
    from collections import defaultdict
    tool_cp: dict[str, list[float]] = defaultdict(list)
    tool_bl: dict[str, list[float]] = defaultdict(list)
    for r in results:
        key = "+".join(r["tools"])
        tool_cp[key].append(r["codeprism"]["p50"])
        tool_bl[key].append(r["baseline"]["p50"])

    print()
    print("By tool (mean p50 across tasks):")
    for tool, cp_vals in sorted(tool_cp.items()):
        bl_vals = tool_bl[tool]
        n = len(cp_vals)
        mean_cp = statistics.mean(cp_vals)
        mean_bl = statistics.mean(bl_vals)
        overhead = mean_cp - mean_bl
        sign = "+" if overhead >= 0 else ""
        print(
            f"  {tool:<20}  CP mean-p50={mean_cp:6.1f}ms  "
            f"BL mean-p50={mean_bl:5.1f}ms  "
            f"overhead={sign}{overhead:.1f}ms  (n={n})"
        )

    # Overall
    all_cp_p50 = [r["codeprism"]["p50"] for r in results]
    all_cp_p95 = [r["codeprism"]["p95"] for r in results]
    all_bl_p50 = [r["baseline"]["p50"] for r in results]
    print()
    print(
        f"Overall  CP p50={statistics.mean(all_cp_p50):.1f}ms  "
        f"CP p95={statistics.mean(all_cp_p95):.1f}ms  "
        f"BL p50={statistics.mean(all_bl_p50):.1f}ms  "
        f"(n={len(results)} tasks, {results[0]['reps']} reps each)"
    )
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _resolve_repo(task: dict, cli_repo: str | None) -> str:
    if cli_repo:
        return cli_repo
    rel = task.get("repo_path", ".")
    return str(_repo_root() / rel)


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Level 2 latency benchmark")
    parser.add_argument(
        "--tasks",
        default=str(Path(__file__).parent / "tasks" / "fixture_tasks.json"),
        help="Path to JSON task file (can pass multiple comma-separated)",
    )
    parser.add_argument("--repo", default=None, help="Override repo_path for all tasks")
    parser.add_argument("--reps", type=int, default=20, help="Measurement reps per task")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup reps to discard")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "results" / "latency_benchmark.json"),
        help="Output JSON file",
    )
    args = parser.parse_args(argv)

    # Support comma-separated task files
    task_files = [p.strip() for p in args.tasks.split(",")]
    all_tasks: list[dict] = []
    for tf in task_files:
        tp = Path(tf)
        if not tp.exists():
            print(f"ERROR: task file not found: {tp}", file=sys.stderr)
            sys.exit(1)
        with tp.open(encoding="utf-8") as f:
            all_tasks.extend(json.load(f))

    # Group tasks by resolved repo_path so we open each CodePrism instance once
    from collections import defaultdict
    repo_groups: dict[str, list[dict]] = defaultdict(list)
    for task in all_tasks:
        repo_path = _resolve_repo(task, args.repo)
        repo_groups[repo_path].append(task)

    print(
        f"Level 2 latency benchmark — "
        f"{len(all_tasks)} tasks across {len(repo_groups)} repo(s)  "
        f"[reps={args.reps}  warmup={args.warmup}]"
    )

    all_results: list[dict] = []

    for repo_path, tasks in repo_groups.items():
        repo = Path(repo_path).resolve()
        print(f"\nRepo: {repo_path}")
        print(f"  Connecting to graph ...", end=" ", flush=True)

        async with CodePrism(str(repo)) as prism:
            stats = await prism.engine.get_stats()
            if stats.get("file_count", 0) == 0:
                print("indexing ...", end=" ", flush=True)
                await prism.index()
                stats = await prism.engine.get_stats()
            print(f"ready ({stats.get('file_count', 0)} files, {stats.get('symbol_count', 0)} symbols)")

            engine = prism.engine

            for i, task in enumerate(tasks, 1):
                print(f"  [{i}/{len(tasks)}] {task['id']} ({args.warmup} warmup + {args.reps} reps) ...", end=" ", flush=True)
                result = await measure_task(engine, repo_path, task, args.reps, args.warmup)
                all_results.append(result)
                print(
                    f"CP p50={result['codeprism']['p50']:.1f}ms  "
                    f"p95={result['codeprism']['p95']:.1f}ms  "
                    f"BL p50={result['baseline']['p50']:.1f}ms"
                )

    print_table(all_results)

    # Save results
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reps": args.reps,
        "warmup": args.warmup,
        "tasks": all_results,
        "summary": {
            "task_count": len(all_results),
            "mean_cp_p50_ms": round(statistics.mean(r["codeprism"]["p50"] for r in all_results), 2),
            "mean_cp_p95_ms": round(statistics.mean(r["codeprism"]["p95"] for r in all_results), 2),
            "mean_bl_p50_ms": round(statistics.mean(r["baseline"]["p50"] for r in all_results), 2),
            "mean_overhead_p50_ms": round(
                statistics.mean(r["overhead_p50_ms"] for r in all_results), 2
            ),
        },
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
