"""Deterministic Level 4 size-scaling benchmark.

The benchmark uses source-file subsets from the checked-out Level 1/2 corpora,
so it needs no network access or Ollama calls. Each tier is indexed into a
fresh temporary SQLite database, then measured with the same QueryEngine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import tempfile
import threading
import time
from pathlib import Path

import psutil

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.storage import StorageManager
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.query.engine import QueryEngine

ROOT = Path(__file__).resolve().parent.parent
CORPORA = {
    name: ROOT / "benchmarks" / "repos" / name
    for name in ("cobra", "httpx", "requests", "flask", "gin", "fastapi", "express", "react", "pydantic", "typescript")
}
EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php", ".c", ".h", ".cpp", ".hpp"}
THRESHOLDS = {
    "min_files_per_second": 50.0,
    "max_query_p95_ms": 200.0,
    "max_memory_kb_per_file": 50.0,
    "max_db_kb_per_file": 100.0,
}


class RSSSampler:
    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
        self.maximum = self.process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.01):
            self.maximum = max(self.maximum, self.process.memory_info().rss)

    def __enter__(self) -> "RSSSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self.maximum = max(self.maximum, self.process.memory_info().rss)


def source_files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def make_subset(source: Path, destination: Path, limit: int) -> tuple[int, int, int]:
    files = source_files(source)[:limit]
    lines = 0
    source_bytes = 0
    for file in files:
        target = destination / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        data = file.read_bytes()
        source_bytes += len(data)
        lines += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return len(files), lines, source_bytes


def db_size(db_path: Path) -> int:
    return sum(p.stat().st_size for p in db_path.parent.glob(db_path.name + "*") if p.exists())


async def query_p95(engine: QueryEngine, symbols: list[object], files: dict[str, object], repetitions: int) -> tuple[float, int]:
    if not symbols or repetitions <= 0:
        return 0.0, 0
    symbol = symbols[0]
    file = files.get(symbol.file_id)
    if file is None:
        return 0.0, 0
    samples: list[float] = []
    query = str(getattr(symbol, "name", "main"))[:24]
    for _ in range(repetitions):
        start = time.perf_counter()
        await engine.search_symbols(query)
        await engine.get_context(str(getattr(file, "path", "")), query, depth=1)
        samples.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(samples, n=20, method="inclusive")[18] if len(samples) > 1 else samples[0]
    return p95, len(samples)


async def measure(repo: str, source: Path, max_files: int, repetitions: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="codeprism-scale-") as temp:
        root = Path(temp) / "project"
        root.mkdir()
        file_count, lines, source_bytes = make_subset(source, root, max_files)
        db_path = Path(temp) / "index.db"
        storage = StorageManager(db_path)
        await storage.initialize()
        graph = GraphEngine()
        config = CodePrismConfig(respect_gitignore=False, parse_workers=1)
        process = psutil.Process(os.getpid())
        rss_before = process.memory_info().rss
        with RSSSampler() as sampler:
            started = time.perf_counter()
            result = await ProjectIndexer(graph, storage, config).index(str(root), force=True)
            elapsed = time.perf_counter() - started
        rss_after = process.memory_info().rss
        files = {f.id: f for f in await storage.get_all_files()}
        symbols = await storage.get_all_symbols()
        p95_ms, query_count = await query_p95(QueryEngine(graph, storage), symbols, files, repetitions)
        await storage.close()
        database_bytes = db_size(db_path)
        peak_delta = max(0, sampler.maximum - rss_before)
        memory_kb_per_file = peak_delta / 1024 / max(file_count, 1)
        db_kb_per_file = database_bytes / 1024 / max(file_count, 1)
        rate = file_count / elapsed if elapsed else 0.0
        return {
            "repo": repo,
            "source": str(source),
            "requested_files": max_files,
            "file_count": file_count,
            "line_count": lines,
            "source_bytes": source_bytes,
            "indexed_files": getattr(result, "file_count", file_count),
            "index_seconds": round(elapsed, 6),
            "files_per_second": round(rate, 3),
            "rss_before_mb": round(rss_before / 1024 / 1024, 3),
            "rss_after_mb": round(rss_after / 1024 / 1024, 3),
            "peak_rss_delta_mb": round(peak_delta / 1024 / 1024, 3),
            "memory_kb_per_file": round(memory_kb_per_file, 3),
            "database_bytes": database_bytes,
            "database_kb_per_file": round(db_kb_per_file, 3),
            "query_p95_ms": round(p95_ms, 3),
            "query_samples": query_count,
            "thresholds": {
                "index_rate_pass": rate >= THRESHOLDS["min_files_per_second"],
                "query_p95_pass": p95_ms < THRESHOLDS["max_query_p95_ms"],
                "memory_pass": memory_kb_per_file < THRESHOLDS["max_memory_kb_per_file"],
                "database_pass": db_kb_per_file < THRESHOLDS["max_db_kb_per_file"],
            },
        }


async def run(repos: list[str], limits: list[int], repetitions: int) -> dict[str, object]:
    started = time.perf_counter()
    tiers: list[dict[str, object]] = []
    for repo in repos:
        source = CORPORA[repo]
        if not source.exists():
            tiers.append({"repo": repo, "error": f"missing corpus: {source}"})
            continue
        for limit in limits:
            tiers.append(await measure(repo, source, limit, repetitions))
    return {
        "benchmark": "level4_size_scaling",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ollama_calls": 0,
        "thresholds": THRESHOLDS,
        "repos": repos,
        "limits": limits,
        "query_repetitions": repetitions,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "tiers": tiers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", nargs="+", choices=sorted(CORPORA), default=["httpx", "requests", "flask"])
    parser.add_argument("--max-files", nargs="+", type=int, default=[10, 25, 50, 100])
    parser.add_argument("--query-repetitions", type=int, default=30)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results" / "level4_size_scaling_current.json")
    args = parser.parse_args()
    result = asyncio.run(run(args.repos, args.max_files, args.query_repetitions))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
