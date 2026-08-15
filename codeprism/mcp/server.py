"""FastMCP server — exposes the knowledge graph as MCP tools."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastmcp import FastMCP

from ..query.engine import QueryEngine
from .session import SessionManager
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

_project_path: str = "."
_engine: Optional[QueryEngine] = None
_session_manager: Optional[SessionManager] = None


def configure(project_path: str) -> None:
    """Call before mcp.run() to point the server at a project directory."""
    global _project_path
    _project_path = project_path


def init_engine(engine: QueryEngine) -> None:
    """Directly inject an engine (used in tests or custom embeddings)."""
    global _engine
    _engine = engine


def init_session_manager(manager: SessionManager) -> None:
    """Directly inject a SessionManager (used in tests)."""
    global _session_manager
    _session_manager = manager


def _get() -> QueryEngine:
    if _engine is None:
        raise RuntimeError(
            "CodePrism server is not initialized. "
            "Run `codeprism index <path>` then `codeprism serve <path>` first."
        )
    return _engine


def _get_session() -> SessionManager:
    if _session_manager is None:
        raise RuntimeError(
            "SessionManager is not initialized. "
            "Run `codeprism serve <path>` to start the server."
        )
    return _session_manager


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    global _engine, _session_manager
    from ..core.graph import GraphEngine
    from ..core.paths import get_db_path
    from ..core.storage import StorageManager
    from ..indexer.incremental_updater import IncrementalUpdater

    db_path = get_db_path(_project_path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    await graph.load_from_storage(storage)
    _engine = QueryEngine(graph, storage)
    updater = IncrementalUpdater(graph, storage)
    _session_manager = SessionManager(storage, updater)
    try:
        yield
    finally:
        await storage.close()
        _engine = None
        _session_manager = None


# ── FastMCP application ───────────────────────────────────────────────────────

mcp = FastMCP(
    "CodePrism",
    instructions=(
        "CodePrism maintains a persistent knowledge graph of a codebase. "
        "Use get_context to understand a symbol, get_impact to assess change risk, "
        "get_module_summary for a file overview, and search_symbol to locate code. "
        "Use scan_file/scan_diff/check_secret_exposure before writing code. "
        "Use record_read/record_write/undo_write to track and revert session changes."
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
async def get_graph_stats(path: Optional[str] = None) -> dict[str, Any]:
    """Return aggregate statistics about the indexed knowledge graph.

    path: optional project path filter — scopes stats to files under that directory.
    """
    stats = await _get().get_stats()
    if path:
        stats["filter_path"] = path
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


# ── Security ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def scan_file(file: str, content: Optional[str] = None) -> dict[str, Any]:
    """Run all security detectors on a file.

    content: if provided, scans this proposed content (pre-write check);
             otherwise reads the file from disk.
    Returns: status (PASS/WARN/BLOCK), issues[] with line, severity, fix.
    """
    from ..security.scanner import SecurityScanner

    scanner = SecurityScanner()
    if content is not None:
        report = scanner.scan_content(content, file)
    else:
        try:
            from pathlib import Path
            file_content = Path(file).read_text(encoding="utf-8")
            report = scanner.scan_content(file_content, file)
        except FileNotFoundError:
            return {"error": f"File '{file}' not found"}
    return report.to_dict()


@mcp.tool()
async def scan_diff(original: str, proposed: str, file: str = "") -> dict[str, Any]:
    """Security-diff: only report issues introduced by the change, not pre-existing ones.

    This is the primary tool for the Security Gate — call before any file write.
    Returns: status (PASS/WARN/BLOCK), new_issues[] with line, severity, fix.
    """
    from ..security.scanner import SecurityScanner

    scanner = SecurityScanner()
    report = scanner.scan_diff(original, proposed, file)
    return report.to_dict()


@mcp.tool()
async def check_secret_exposure(content: str) -> dict[str, Any]:
    """Scan content specifically for hardcoded secrets, tokens, and API keys.

    Uses entropy analysis + pattern matching on the secrets detector only.
    Returns: status, secrets_found[] with line and description.
    """
    from ..security.scanner import SecurityScanner

    scanner = SecurityScanner()
    report = scanner.scan_secrets_only(content)
    return {
        "status": report.status,
        "secrets_found": [i.to_dict() for i in report.issues],
        "count": len(report.issues),
    }


@mcp.tool()
async def check_dependencies_cve(requirements: str) -> dict[str, Any]:
    """Check a requirements.txt blob for packages with known CVEs via the OSV API.

    requirements: raw text of requirements.txt (one package per line).
    Returns: vulnerable[] list with package, severity, cve_ids, summary.
    A CRITICAL or HIGH severity finding should be treated as a BLOCK.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from ..security.cve import check_requirements

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        results = await loop.run_in_executor(pool, check_requirements, requirements)

    vulnerable = [
        {
            "package": r.package,
            "version": r.version,
            "severity": r.severity,
            "cve_ids": r.cve_ids,
            "summary": r.summary,
        }
        for r in results
    ]
    status = "PASS"
    for r in results:
        if r.severity == "CRITICAL":
            status = "BLOCK"
            break
        if r.severity == "HIGH" and status != "BLOCK":
            status = "WARN"
    return {"status": status, "vulnerable": vulnerable, "count": len(vulnerable)}


# ── Session overlay ───────────────────────────────────────────────────────────


@mcp.tool()
async def record_read(session_id: str, file: str, symbol: str) -> dict[str, Any]:
    """Tell CodePrism the agent has read this symbol in this session.

    Allows get_session_context to return what has already been fetched,
    preventing redundant re-reads across long agent chains.
    """
    await _get_session().record_read(session_id, file, symbol)
    return {"recorded": True, "session_id": session_id, "file": file, "symbol": symbol}


@mcp.tool()
async def record_write(
    session_id: str,
    file: str,
    content_before: str,
    content_after: str,
) -> dict[str, Any]:
    """Log a file write: run security scan, flush to disk, sync the graph.

    Returns status (PASS/WARN/BLOCK) + graph_update. A BLOCK means the write
    introduced a critical security issue — surface this to the user.
    """
    return await _get_session().record_write(session_id, file, content_before, content_after)


@mcp.tool()
async def get_session_context(session_id: str) -> dict[str, Any]:
    """What has the agent read and written in this session?

    Returns a compact summary for inclusion in the agent's context window
    instead of re-fetching individual symbols.
    """
    ctx = await _get_session().get_context(session_id)
    return {
        "session_id": ctx.session_id,
        "total_events": ctx.total_events,
        "read_count": ctx.read_count,
        "write_count": ctx.write_count,
        "undo_count": ctx.undo_count,
        "files_read": ctx.files_read,
        "files_written": ctx.files_written,
        "summary": ctx.summary,
    }


@mcp.tool()
async def undo_write(session_id: str, steps: int = 1) -> dict[str, Any]:
    """Restore the last N written files from the session journal.

    Reverses agent-authored writes in reverse chronological order.
    The graph is re-synced for each restored file.
    """
    result = await _get_session().undo_write(session_id, steps)
    return {
        "files_restored": result.files_restored,
        "steps_undone": result.steps_undone,
    }
