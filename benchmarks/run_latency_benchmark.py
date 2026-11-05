"""
Level 2 latency benchmark — run with:

    python -m benchmarks.run_latency_benchmark
    python -m benchmarks.run_latency_benchmark --repos requests,flask,express,gin
    python -m benchmarks.run_latency_benchmark --tasks tasks/requests_tasks.json --reps 30

Measures p50 / p95 / p99 query latency for CodePrism graph queries vs baseline
file reads.  The CodePrism engine is held open across all tasks for a given repo
so indexing time is NOT included — only pure query latency is timed.

Warmup runs are discarded before measurement begins.

Per-corpus JSON is written to benchmarks/results/level2_latency_<corpus>.json
(matching the Level 1 level1_full_* artifact layout). A combined summary is
written to benchmarks/results/level2_latency_all.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from benchmarks.baseline import build_baseline_prompt
from benchmarks.codeprism_prompt import _resolve_file_path
from codeprism import CodePrism
from codeprism import __version__ as CODEPRISM_VERSION

TASKS_DIR = Path(__file__).parent / "tasks"
RESULTS_DIR = Path(__file__).parent / "results"

# Language + task-file map for every Level 1 corpus. TypeScript uses the same
# bounded compiler subset documented for Level 1 (not the full checkout).
CORPORA: dict[str, dict[str, str]] = {
    "fixture": {
        "tasks": "fixture_tasks.json",
        "language": "python",
        "label": "sample Python fixture",
    },
    "requests": {
        "tasks": "requests_tasks.json",
        "language": "python",
        "label": "psf/requests v2.32.3",
    },
    "flask": {
        "tasks": "flask_tasks.json",
        "language": "python",
        "label": "pallets/flask 3.0.3",
    },
    "httpx": {
        "tasks": "httpx_tasks.json",
        "language": "python",
        "label": "encode/httpx 0.27.2",
    },
    "fastapi": {
        "tasks": "fastapi_tasks.json",
        "language": "python",
        "label": "tiangolo/fastapi 0.115.0",
    },
    "pydantic": {
        "tasks": "pydantic_tasks.json",
        "language": "python",
        "label": "pydantic v2.9.2",
    },
    "express": {
        "tasks": "express_tasks.json",
        "language": "javascript",
        "label": "expressjs/express v4.22.3",
    },
    "react": {
        "tasks": "react_tasks.json",
        "language": "javascript",
        "label": "facebook/react v18.3.1",
    },
    "typescript": {
        "tasks": "typescript_tasks.json",
        "language": "typescript",
        "label": "TypeScript compiler subset (v5.6.3)",
    },
    "gin": {
        "tasks": "gin_tasks.json",
        "language": "go",
        "label": "gin-gonic/gin v1.10.0",
    },
    "cobra": {
        "tasks": "cobra_tasks.json",
        "language": "go",
        "label": "spf13/cobra v1.8.1",
    },
}


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
        "min": round(min(samples), 2),
        "mean": round(statistics.mean(samples), 2),
        "p50": round(_pct(samples, 50), 2),
        "p95": round(_pct(samples, 95), 2),
        "p99": round(_pct(samples, 99), 2),
        "max": round(max(samples), 2),
    }


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def summarize(results: list[dict]) -> dict:
    if not results:
        return {
            "task_count": 0,
            "mean_cp_p50_ms": 0.0,
            "mean_cp_p95_ms": 0.0,
            "mean_bl_p50_ms": 0.0,
            "mean_overhead_p50_ms": 0.0,
        }
    return {
        "task_count": len(results),
        "mean_cp_p50_ms": _mean([r["codeprism"]["p50"] for r in results]),
        "mean_cp_p95_ms": _mean([r["codeprism"]["p95"] for r in results]),
        "mean_bl_p50_ms": _mean([r["baseline"]["p50"] for r in results]),
        "mean_overhead_p50_ms": _mean([r["overhead_p50_ms"] for r in results]),
    }


def tool_breakdown(results: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        grouped["+".join(r["tools"])].append(r)
    rows = []
    for tool, items in sorted(grouped.items()):
        rows.append(
            {
                "tool": tool,
                "n": len(items),
                "mean_cp_p50_ms": _mean([r["codeprism"]["p50"] for r in items]),
                "mean_cp_p95_ms": _mean([r["codeprism"]["p95"] for r in items]),
                "mean_bl_p50_ms": _mean([r["baseline"]["p50"] for r in items]),
            }
        )
    return rows


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

    for _ in range(warmup):
        await _run_cp_query(engine, resolved_file, task)
        _run_baseline(repo_path, task)

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
        "id": task["id"],
        "corpus": task.get("_corpus", task.get("repo", "")),
        "language": task.get("_language", ""),
        "type": task.get("type", ""),
        "tools": task.get("cp_tools", ["get_context"]),
        "reps": reps,
        "baseline": bl,
        "codeprism": cp,
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

    print()
    print("By tool (mean p50 across tasks):")
    for row in tool_breakdown(results):
        overhead = row["mean_cp_p50_ms"] - row["mean_bl_p50_ms"]
        sign = "+" if overhead >= 0 else ""
        print(
            f"  {row['tool']:<20}  CP mean-p50={row['mean_cp_p50_ms']:6.1f}ms  "
            f"BL mean-p50={row['mean_bl_p50_ms']:5.1f}ms  "
            f"overhead={sign}{overhead:.1f}ms  (n={row['n']})"
        )

    summary = summarize(results)
    print()
    if results:
        print(
            f"Overall  CP p50={summary['mean_cp_p50_ms']:.1f}ms  "
            f"CP p95={summary['mean_cp_p95_ms']:.1f}ms  "
            f"BL p50={summary['mean_bl_p50_ms']:.1f}ms  "
            f"(n={summary['task_count']} tasks, {results[0]['reps']} reps each)"
        )
    else:
        print("Overall  (no tasks)")
    print()


def print_corpus_table(corpus_summaries: list[dict]) -> None:
    if not corpus_summaries:
        return
    print("By corpus:")
    header = f"  {'Corpus':<14} {'Lang':<12} {'n':>4}  {'CP-p50':>8} {'CP-p95':>8} {'BL-p50':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in corpus_summaries:
        s = row["summary"]
        print(
            f"  {row['corpus']:<14} {row['language']:<12} {s['task_count']:>4}  "
            f"{s['mean_cp_p50_ms']:>7.1f}ms {s['mean_cp_p95_ms']:>7.1f}ms "
            f"{s['mean_bl_p50_ms']:>7.1f}ms"
        )
    print()


def print_language_table(results: list[dict]) -> None:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        lang = r.get("language") or "unknown"
        grouped[lang].append(r)
    if len(grouped) < 2:
        return
    print("By language:")
    for lang, items in sorted(grouped.items()):
        s = summarize(items)
        print(
            f"  {lang:<12}  CP p50={s['mean_cp_p50_ms']:6.1f}ms  "
            f"CP p95={s['mean_cp_p95_ms']:6.1f}ms  "
            f"(n={s['task_count']} tasks)"
        )
    print()


# ── corpus loading ────────────────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _resolve_repo(task: dict, cli_repo: str | None) -> str:
    if cli_repo:
        return cli_repo
    rel = task.get("repo_path", ".")
    return str(_repo_root() / rel)


def _annotate_tasks(tasks: list[dict], corpus: str, language: str) -> list[dict]:
    annotated = []
    for task in tasks:
        item = dict(task)
        item["_corpus"] = corpus
        item["_language"] = language
        annotated.append(item)
    return annotated


def _load_task_file(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_corpus(name: str) -> tuple[str, str, str, list[dict]]:
    if name not in CORPORA:
        raise KeyError(name)
    meta = CORPORA[name]
    task_path = TASKS_DIR / meta["tasks"]
    if not task_path.exists():
        raise FileNotFoundError(task_path)
    tasks = _annotate_tasks(_load_task_file(task_path), name, meta["language"])
    repo_path = _resolve_repo(tasks[0], None)
    return name, meta["language"], repo_path, tasks


def parse_repo_names(raw: str) -> list[str]:
    if raw.strip().lower() in {"all", "*"}:
        return list(CORPORA)
    names = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [n for n in names if n not in CORPORA]
    if unknown:
        raise ValueError(
            f"Unknown corpus name(s): {', '.join(unknown)}. Choose from: {', '.join(CORPORA)}"
        )
    return names


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def corpus_payload(
    *,
    corpus: str,
    language: str,
    label: str,
    repo_path: str,
    reps: int,
    warmup: int,
    results: list[dict],
) -> dict:
    return {
        "level": 2,
        "corpus": corpus,
        "language": language,
        "label": label,
        "repo_path": repo_path,
        "version": CODEPRISM_VERSION,
        "reps": reps,
        "warmup": warmup,
        "tasks": results,
        "tools": tool_breakdown(results),
        "summary": summarize(results),
    }


# ── main ──────────────────────────────────────────────────────────────────────


async def _run_repo(
    *,
    corpus: str,
    language: str,
    repo_path: str,
    tasks: list[dict],
    reps: int,
    warmup: int,
) -> list[dict]:
    repo = Path(repo_path).resolve()
    print(f"\nCorpus: {corpus} ({language})")
    print(f"  Repo: {repo}")
    if not repo.exists():
        print(f"  SKIP — repo path does not exist: {repo}", file=sys.stderr)
        return []

    print("  Connecting to graph ...", end=" ", flush=True)
    results: list[dict] = []
    async with CodePrism(str(repo)) as prism:
        stats = await prism.engine.get_stats()
        if stats.get("file_count", 0) == 0:
            print("indexing ...", end=" ", flush=True)
            await prism.index()
            stats = await prism.engine.get_stats()
        print(f"ready ({stats.get('file_count', 0)} files, {stats.get('symbol_count', 0)} symbols)")

        engine = prism.engine
        for i, task in enumerate(tasks, 1):
            print(
                f"  [{i}/{len(tasks)}] {task['id']} ({warmup} warmup + {reps} reps) ...",
                end=" ",
                flush=True,
            )
            try:
                result = await measure_task(engine, repo_path, task, reps, warmup)
            except Exception as exc:
                print(f"ERROR: {exc}")
                continue
            results.append(result)
            print(
                f"CP p50={result['codeprism']['p50']:.1f}ms  "
                f"p95={result['codeprism']['p95']:.1f}ms  "
                f"BL p50={result['baseline']['p50']:.1f}ms"
            )
    return results


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Level 2 latency benchmark")
    parser.add_argument(
        "--tasks",
        default=None,
        help="Path to JSON task file (comma-separated). Overrides --repos.",
    )
    parser.add_argument(
        "--repos",
        default="all",
        help=f"Comma-separated corpus names, or 'all' (default). Known: {', '.join(CORPORA)}",
    )
    parser.add_argument("--repo", default=None, help="Override repo_path for all tasks")
    parser.add_argument("--reps", type=int, default=20, help="Measurement reps per task")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup reps to discard")
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for per-corpus JSON artifacts",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Combined JSON path (default: <out-dir>/level2_latency_all.json)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    combined_path = Path(args.out) if args.out else out_dir / "level2_latency_all.json"

    jobs: list[tuple[str, str, str, list[dict]]] = []
    if args.tasks:
        task_files = [p.strip() for p in args.tasks.split(",")]
        grouped: dict[str, list[dict]] = defaultdict(list)
        for tf in task_files:
            tp = Path(tf)
            if not tp.exists():
                print(f"ERROR: task file not found: {tp}", file=sys.stderr)
                sys.exit(1)
            stem = tp.stem.replace("_tasks", "")
            language = CORPORA.get(stem, {}).get("language", "unknown")
            for task in _load_task_file(tp):
                corpus = task.get("repo", stem)
                item = dict(task)
                item["_corpus"] = corpus
                item["_language"] = CORPORA.get(corpus, {}).get("language", language)
                grouped[_resolve_repo(item, args.repo)].append(item)
        for repo_path, tasks in grouped.items():
            corpus = tasks[0].get("_corpus", "custom")
            language = tasks[0].get("_language", "unknown")
            jobs.append((corpus, language, repo_path, tasks))
    else:
        try:
            names = parse_repo_names(args.repos)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        for name in names:
            try:
                corpus, language, repo_path, tasks = load_corpus(name)
            except FileNotFoundError as exc:
                print(f"ERROR: task file not found: {exc}", file=sys.stderr)
                sys.exit(1)
            if args.repo:
                repo_path = args.repo
            jobs.append((corpus, language, repo_path, tasks))

    total_tasks = sum(len(tasks) for _, _, _, tasks in jobs)
    print(
        f"Level 2 latency benchmark — {total_tasks} tasks across {len(jobs)} corpus(es)  "
        f"[reps={args.reps}  warmup={args.warmup}  version={CODEPRISM_VERSION}]"
    )

    all_results: list[dict] = []
    corpus_summaries: list[dict] = []
    skipped: list[str] = []

    for corpus, language, repo_path, tasks in jobs:
        results = await _run_repo(
            corpus=corpus,
            language=language,
            repo_path=repo_path,
            tasks=tasks,
            reps=args.reps,
            warmup=args.warmup,
        )
        if not results:
            skipped.append(corpus)
            continue
        print_table(results)
        label = CORPORA.get(corpus, {}).get("label", corpus)
        payload = corpus_payload(
            corpus=corpus,
            language=language,
            label=label,
            repo_path=repo_path,
            reps=args.reps,
            warmup=args.warmup,
            results=results,
        )
        artifact = out_dir / f"level2_latency_{corpus}.json"
        write_json(artifact, payload)
        print(f"Results saved to {artifact}")
        all_results.extend(results)
        corpus_summaries.append(
            {
                "corpus": corpus,
                "language": language,
                "label": label,
                "artifact": str(artifact),
                "summary": payload["summary"],
                "tools": payload["tools"],
            }
        )

    if all_results and len(corpus_summaries) > 1:
        print_corpus_table(corpus_summaries)
        print_language_table(all_results)
        print_table(all_results)

    combined = {
        "level": 2,
        "version": CODEPRISM_VERSION,
        "reps": args.reps,
        "warmup": args.warmup,
        "skipped": skipped,
        "corpora": corpus_summaries,
        "tasks": all_results,
        "summary": summarize(all_results),
        "tools": tool_breakdown(all_results),
    }
    write_json(combined_path, combined)
    print(f"Combined results saved to {combined_path}")
    if skipped:
        print(f"Skipped corpora: {', '.join(skipped)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
