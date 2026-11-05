"""
Level 2 latency via pytest-benchmark.

Run with:

    pytest benchmarks/test_latency.py --benchmark-json=benchmarks/results/level2_pytest_benchmark.json

CI uses this file for regression detection. The full multi-corpus run still
goes through ``python -m benchmarks.run_latency_benchmark``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

pytest.importorskip("pytest_benchmark")

from benchmarks.codeprism_prompt import _resolve_file_path
from benchmarks.run_latency_benchmark import _run_baseline, _run_cp_query
from codeprism import CodePrism

FIXTURE_REPO = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_python_project"
FIXTURE_TASKS = Path(__file__).parent / "tasks" / "fixture_tasks.json"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
P95_CEILING_MS = 200.0


def _load_tool_tasks() -> dict[str, dict[str, Any]]:
    with FIXTURE_TASKS.open(encoding="utf-8") as handle:
        tasks = json.load(handle)
    by_tool: dict[str, dict[str, Any]] = {}
    for task in tasks:
        tools = task.get("cp_tools") or ["get_context"]
        if len(tools) == 1 and tools[0] not in by_tool:
            by_tool[tools[0]] = task
    return by_tool


TOOL_TASKS = _load_tool_tasks()


@pytest.fixture(scope="session")
def event_loop_session() -> Iterator[asyncio.AbstractEventLoop]:
    """Provide a session-scoped asyncio event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def prism(event_loop_session: asyncio.AbstractEventLoop) -> Iterator[CodePrism]:
    """Provide an indexed CodePrism instance for the sample Python fixture."""

    async def _open() -> CodePrism:
        instance = CodePrism(str(FIXTURE_REPO.resolve()))
        await instance.__aenter__()
        stats = await instance.engine.get_stats()
        if stats.get("file_count", 0) == 0:
            await instance.index()
        return instance

    instance = event_loop_session.run_until_complete(_open())
    yield instance
    event_loop_session.run_until_complete(instance.__aexit__(None, None, None))


@pytest.mark.parametrize("tool", sorted(TOOL_TASKS))
def test_query_latency(
    benchmark: BenchmarkFixture,
    prism: CodePrism,
    event_loop_session: asyncio.AbstractEventLoop,
    tool: str,
) -> None:
    """Benchmark CodePrism graph query latency for a specific tool."""
    task = TOOL_TASKS[tool]
    resolved = event_loop_session.run_until_complete(_resolve_file_path(prism.engine, task["file"]))

    def _once() -> None:
        event_loop_session.run_until_complete(_run_cp_query(prism.engine, resolved, task))

    benchmark.pedantic(_once, iterations=1, rounds=20, warmup_rounds=3)
    bench_stats: Any = benchmark.stats
    max_ms = bench_stats.stats.max * 1000
    assert max_ms < P95_CEILING_MS, f"{tool} max {max_ms:.1f}ms exceeds {P95_CEILING_MS}ms"


def test_baseline_file_read(benchmark: BenchmarkFixture) -> None:
    """Benchmark raw file read latency as a baseline."""
    task = TOOL_TASKS["get_context"]
    repo = str(FIXTURE_REPO.resolve())

    def _once() -> None:
        _run_baseline(repo, task)

    benchmark.pedantic(_once, iterations=1, rounds=20, warmup_rounds=3)
