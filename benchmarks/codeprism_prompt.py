"""
CodePrism prompt builder.

Uses CodePrism's Python API to answer the same task that baseline.py
answers by reading raw files. The MCP tool result is serialized to the
same text format the LLM would receive it over the wire.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from codeprism import CodePrism


async def build_codeprism_prompt(repo_path: str, task: dict) -> str:
    """
    Build a context prompt using only CodePrism graph queries.

    task schema:
      file:     str          — file path (relative to repo_path)
      function: str          — symbol name to query
      query:    str          — the natural-language question
      cp_tools: list[str]    — which tools to call: get_context | get_impact |
                               get_callers | get_dependencies | search_symbol
    """
    repo = Path(repo_path).resolve()
    results: list[dict] = []

    async with CodePrism(str(repo)) as prism:
        tools = task.get("cp_tools", ["get_context"])

        for tool in tools:
            if tool == "get_context":
                ctx = await prism.get_context(task["file"], task["function"], depth=2)
                if ctx:
                    results.append({
                        "tool": "get_context",
                        "symbol": ctx.symbol.name,
                        "signature": ctx.symbol.signature,
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
                impact = await prism.get_impact(task["file"], task["function"])
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
                callers = await prism.get_callers(task["file"], task["function"])
                results.append({
                    "tool": "get_callers",
                    "function": task["function"],
                    "callers": [{"name": c.name} for c in callers],
                    "count": len(callers),
                })

            elif tool == "get_dependencies":
                deps = await prism.get_dependencies(task["file"])
                if deps:
                    results.append({
                        "tool": "get_dependencies",
                        "file": task["file"],
                        "internal_deps": deps.internal_deps,
                        "external_deps": deps.external_deps,
                        "circular_deps": deps.circular_deps,
                    })

            elif tool == "search_symbol":
                q = task.get("search_query", task["function"])
                matches = await prism.search_symbols(q)
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
        f"The following is a structured knowledge graph query result — "
        f"not raw source code.\n\n"
        f"## CodePrism graph result\n\n```json\n{context}\n```\n\n"
        f"## Task\n\n{task['query']}"
    )
