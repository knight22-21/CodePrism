"""FastMCP server — exposes the knowledge graph as MCP tools."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastmcp import FastMCP

from ..query.engine import QueryEngine
from .tools import (
    context_to_dict,
    data_flow_to_dict,
    deps_to_dict,
    dependents_to_dict,
    file_map_to_dict,
    impact_to_dict,
    search_matches_to_dict,
    summary_to_dict,
)

# ── Module-level state ────────────────────────────────────────────────────────
# Set by configure() before mcp.run(), or replaced by index_project() at runtime.

_project_path: str = "."
_engine: Optional[QueryEngine] = None


def configure(project_path: str) -> None:
    """Call before mcp.run() to point the server at a project directory."""
    global _project_path
    _project_path = project_path


def init_engine(engine: QueryEngine) -> None:
    """Directly inject an engine (used in tests or custom embeddings)."""
    global _engine
    _engine = engine


def _get() -> QueryEngine:
    if _engine is None:
        raise RuntimeError(
            "CodePrism server is not initialized. "
            "Run `codeprism index <path>` then `codeprism serve <path>` first."
        )
    return _engine


# ── Lifespan: initialize storage + graph inside FastMCP's event loop ──────────


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    global _engine
    from ..core.graph import GraphEngine
    from ..core.paths import get_db_path
    from ..core.storage import StorageManager

    db_path = get_db_path(_project_path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    await graph.load_from_storage(storage)
    _engine = QueryEngine(graph, storage)
    try:
        yield
    finally:
        await storage.close()
        _engine = None


# ── FastMCP application ───────────────────────────────────────────────────────

mcp = FastMCP(
    "CodePrism",
    instructions=(
        "CodePrism maintains a persistent knowledge graph of a codebase. "
        "Use get_context to understand a symbol, get_impact to assess change risk, "
        "get_module_summary for a file overview, and search_symbol to locate code. "
        "All results are structured and token-efficient."
    ),
    lifespan=_lifespan,
)


# ── Indexing & management ─────────────────────────────────────────────────────


@mcp.tool()
async def index_project(path: str, languages: Optional[list[str]] = None) -> dict[str, Any]:
    """Build or rebuild the knowledge graph for a project directory."""
    global _engine
    from ..core.config import CodePrismConfig
    from ..core.graph import GraphEngine
    from ..core.paths import get_db_path
    from ..core.storage import StorageManager
    from ..indexer.project_indexer import ProjectIndexer

    cfg = CodePrismConfig(languages=languages) if languages else CodePrismConfig()
    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    indexer = ProjectIndexer(graph, storage, cfg)
    result = await indexer.index(path)

    # Swap the live engine so subsequent query tools see the new project
    old_storage = _engine._storage if _engine else None
    _engine = QueryEngine(graph, storage)
    if old_storage is not None and old_storage is not storage:
        await old_storage.close()

    return {
        "file_count": result.file_count,
        "symbol_count": result.symbol_count,
        "edge_count": result.edge_count,
        "duration_seconds": round(result.duration_seconds, 3),
        "errors": result.errors,
        "success": result.success,
    }


@mcp.tool()
async def update_file(path: str) -> dict[str, Any]:
    """Incrementally update the graph for a single changed file."""
    from ..indexer.incremental_updater import IncrementalUpdater

    engine = _get()
    updater = IncrementalUpdater(engine._graph, engine._storage)
    result = await updater.update_file(path)
    return {
        "nodes_added": result.nodes_added,
        "nodes_removed": result.nodes_removed,
        "edges_updated": result.edges_updated,
        "skipped": result.skipped,
    }


@mcp.tool()
async def get_graph_stats() -> dict[str, Any]:
    """Return aggregate statistics about the indexed knowledge graph."""
    stats = await _get().get_stats()
    return stats


# ── Context retrieval ─────────────────────────────────────────────────────────


@mcp.tool()
async def get_context(file: str, symbol: str, depth: int = 2) -> dict[str, Any]:
    """Get structured context for a symbol: callers, callees, types, variables.

    depth=1: symbol + direct callers/callees
    depth=2: + their neighbours (recommended)
    depth=3: full transitive neighbourhood
    """
    result = await _get().get_context(file, symbol, depth)
    if result is None:
        return {"error": f"Symbol '{symbol}' not found in {file}"}
    return context_to_dict(result)


@mcp.tool()
async def get_module_summary(file: str) -> dict[str, Any]:
    """Return a high-level narrative summary of a source file."""
    result = await _get().get_module_summary(file)
    if result is None:
        return {"error": f"File '{file}' not indexed"}
    return summary_to_dict(result)


@mcp.tool()
async def get_file_map(project_path: str = "") -> dict[str, Any]:
    """Return the file tree with per-file role summaries (token-efficient entry point)."""
    result = await _get().get_file_map(project_path)
    return file_map_to_dict(result)


# ── Impact analysis ───────────────────────────────────────────────────────────


@mcp.tool()
async def get_impact(file: str, symbol: str) -> dict[str, Any]:
    """Transitive impact analysis: what breaks if this symbol changes?"""
    result = await _get().get_impact(file, symbol)
    if result is None:
        return {"error": f"Symbol '{symbol}' not found in {file}"}
    return impact_to_dict(result)


@mcp.tool()
async def get_callers(file: str, function: str) -> dict[str, Any]:
    """All functions that call this function, with call-site metadata."""
    callers = await _get().get_callers(file, function)
    return {
        "function": function,
        "file": file,
        "callers": [
            {"name": s.name, "file_id": s.file_id, "line_start": s.line_start}
            for s in callers
        ],
        "count": len(callers),
    }


@mcp.tool()
async def get_callees(file: str, function: str) -> dict[str, Any]:
    """All functions called by this function."""
    callees = await _get().get_callees(file, function)
    return {
        "function": function,
        "file": file,
        "callees": [
            {"name": s.name, "file_id": s.file_id, "line_start": s.line_start}
            for s in callees
        ],
        "count": len(callees),
    }


@mcp.tool()
async def get_data_flow(file: str, symbol: str) -> dict[str, Any]:
    """Trace where data from this symbol flows (sources, sinks, paths)."""
    result = await _get().get_data_flow(file, symbol)
    if result is None:
        return {"error": f"Symbol '{symbol}' not found in {file}"}
    return data_flow_to_dict(result)


# ── Symbol search ─────────────────────────────────────────────────────────────


@mcp.tool()
async def search_symbol(
    query: str,
    kind: Optional[str] = None,
) -> dict[str, Any]:
    """Find symbols by name (substring match). kind: function|class|variable|import."""
    matches = await _get().search_symbols(query, kind)
    return search_matches_to_dict(matches)


@mcp.tool()
async def get_dependencies(file: str) -> dict[str, Any]:
    """All modules/packages this file depends on (internal vs external)."""
    result = await _get().get_dependencies(file)
    if result is None:
        return {"error": f"File '{file}' not indexed"}
    return deps_to_dict(result)


@mcp.tool()
async def get_dependents(file: str) -> dict[str, Any]:
    """All files that transitively depend on this file."""
    result = await _get().get_dependents(file)
    if result is None:
        return {"error": f"File '{file}' not indexed"}
    return dependents_to_dict(result)
