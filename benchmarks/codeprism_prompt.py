"""
CodePrism prompt builder.

Uses CodePrism's Python API to answer the same task that baseline.py
answers by reading raw files. The MCP tool result is serialized to the
same text format the LLM would receive it over the wire.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from codeprism import CodePrism
from codeprism.core.storage import StorageManager


async def _resolve_file_path(engine, task_file: str) -> str:
    """
    Map a short task file path (e.g. 'processor.py') to the actual path
    stored in the graph (e.g. 'tests/fixtures/sample_python_project/processor.py').
    Falls back to the original task_file if no match found.
    """
    all_files = await engine._storage.get_all_files()
    task_suffix = task_file.replace("/", os.sep).replace("\\", os.sep)
    for f in all_files:
        stored = f.path.replace("/", os.sep).replace("\\", os.sep)
        if stored == task_suffix or stored.endswith(os.sep + task_suffix):
            return f.path
    return task_file


async def build_codeprism_prompt(repo_path: str, task: dict) -> str:
    """
    Build a context prompt using only CodePrism graph queries.

    task schema:
      file:     str          -- file path (relative to repo_path)
      function: str          -- symbol name to query
      query:    str          -- the natural-language question
      cp_tools: list[str]    -- which tools to call: get_context | get_impact |
                                get_callers | get_dependencies | search_symbol
    """
    repo = Path(repo_path).resolve()
    results: list[dict] = []

    async with CodePrism(str(repo)) as prism:
        # Index if the graph is empty (first run against this project).
        stats = await prism.engine.get_stats()
        if stats.get("file_count", 0) == 0:
            await prism.index()

        engine = prism.engine
        tools = task.get("cp_tools", ["get_context"])

        # Resolve short task file path to actual stored path
        resolved_file = await _resolve_file_path(engine, task["file"])

        for tool in tools:
            if tool == "get_context":
                ctx = await engine.get_context(resolved_file, task["function"], depth=2)
                if ctx:
                    results.append({
                        "tool": "get_context",
                        "symbol": ctx.symbol.name,
                        "signature": ctx.symbol.signature,
                        "docstring": ctx.symbol.docstring,
                        "kind": ctx.symbol.kind.value,
                        "line_start": ctx.symbol.line_start,
                        "direct_callers": [
                            {"name": c.name, "file": c.file_id} for c in ctx.direct_callers
                        ],
                        "direct_callees": [
                            {"name": c.name, "file": c.file_id} for c in ctx.direct_callees
                        ],
                        "related_types": [t.name for t in ctx.related_types],
                    })

            elif tool == "get_impact":
                impact = await engine.get_impact(resolved_file, task["function"])
                if impact:
                    results.append({
                        "tool": "get_impact",
                        "symbol": impact.symbol.name,
                        "severity": impact.severity,
                        "direct_dependents": [s.name for s in impact.direct_dependents],
                        "transitive_dependents": [s.name for s in impact.transitive_dependents],
                        "affected_test_files": impact.affected_test_files,
                    })

            elif tool == "get_callers":
                callers = await engine.get_callers(resolved_file, task["function"])
                results.append({
                    "tool": "get_callers",
                    "function": task["function"],
                    "callers": [{"name": c.name} for c in callers],
                    "count": len(callers),
                })

            elif tool == "get_dependencies":
                deps = await engine.get_dependencies(resolved_file)
                if deps:
                    results.append({
                        "tool": "get_dependencies",
                        "file": resolved_file,
                        "internal_deps": deps.internal_deps,
                        "external_deps": deps.external_deps,
                        "circular_deps": deps.circular_deps,
                    })

            elif tool == "search_symbol":
                q = task.get("search_query", task["function"])
                matches = await engine.search_symbols(q)
                results.append({
                    "tool": "search_symbol",
                    "query": q,
                    "matches": [
                        {"name": m.symbol.name, "file": m.file_path, "kind": m.symbol.kind.value}
                        for m in matches[:10]
                    ],
                })

    context = json.dumps(results, indent=2)
    return (
        f"You are a code analysis assistant. "
        f"The following is a structured knowledge graph query result -- "
        f"not raw source code.\n\n"
        f"## CodePrism graph result\n\n```json\n{context}\n```\n\n"
        f"## Task\n\n{task['query']}"
    )
