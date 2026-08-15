"""Tests for MCP tool functions — called directly, not via MCP protocol."""

import pytest

import codeprism.mcp.server as _srv
from codeprism.mcp.server import (
    get_callers,
    get_callees,
    get_context,
    get_data_flow,
    get_dependencies,
    get_dependents,
    get_file_map,
    get_graph_stats,
    get_impact,
    get_module_summary,
    search_symbol,
)


@pytest.fixture(autouse=True)
def inject_engine(indexed_engine):
    """Bypass the lifespan and inject the test engine into the MCP module global."""
    engine, db, proj = indexed_engine
    _srv.init_engine(engine)
    yield
    _srv._engine = None


# ── get_graph_stats ───────────────────────────────────────────────────────────


async def test_mcp_stats_has_keys():
    result = await get_graph_stats()
    assert "file_count" in result
    assert "function_count" in result
    assert "edge_count" in result


async def test_mcp_stats_positive(indexed_engine):
    _, _, _ = indexed_engine
    result = await get_graph_stats()
    assert result["file_count"] >= 2


# ── get_context ───────────────────────────────────────────────────────────────


async def test_mcp_context_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_context(str(proj / "processor.py"), "compute_checksum")
    assert "error" not in result
    assert result["symbol"]["name"] == "compute_checksum"


async def test_mcp_context_miss(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_context(str(proj / "processor.py"), "no_such_fn")
    assert "error" in result


async def test_mcp_context_has_token_count(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_context(str(proj / "processor.py"), "compute_checksum")
    assert result.get("estimated_token_count", 0) > 0


# ── get_module_summary ────────────────────────────────────────────────────────


async def test_mcp_summary_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_module_summary(str(proj / "processor.py"))
    assert "error" not in result
    assert result["purpose"] != ""


async def test_mcp_summary_miss(indexed_engine):
    _, _, _ = indexed_engine
    result = await get_module_summary("/no/such/file.py")
    assert "error" in result


# ── get_file_map ──────────────────────────────────────────────────────────────


async def test_mcp_file_map_has_files(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_file_map(str(proj))
    assert result["total_files"] >= 2
    assert len(result["files"]) >= 2


# ── get_impact ────────────────────────────────────────────────────────────────


async def test_mcp_impact_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_impact(str(proj / "processor.py"), "compute_checksum")
    assert "error" not in result
    assert result["severity"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


async def test_mcp_impact_miss(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_impact(str(proj / "processor.py"), "no_fn")
    assert "error" in result


# ── get_callers / get_callees ─────────────────────────────────────────────────


async def test_mcp_callers_count(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_callers(str(proj / "processor.py"), "compute_checksum")
    assert "count" in result
    assert result["count"] >= 1


async def test_mcp_callees_count(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_callees(str(proj / "processor.py"), "process")
    assert "count" in result


# ── search_symbol ─────────────────────────────────────────────────────────────


async def test_mcp_search_hit(indexed_engine):
    _, _, _ = indexed_engine
    result = await search_symbol("compute")
    assert result["count"] >= 1
    names = [m["name"] for m in result["matches"]]
    assert "compute_checksum" in names


async def test_mcp_search_no_hit(indexed_engine):
    _, _, _ = indexed_engine
    result = await search_symbol("zzz_no_match_xyz")
    assert result["count"] == 0


async def test_mcp_search_kind_filter(indexed_engine):
    _, _, _ = indexed_engine
    result = await search_symbol("", kind="class")
    for m in result["matches"]:
        assert m["kind"] == "class"


# ── get_dependencies / get_dependents ─────────────────────────────────────────


async def test_mcp_deps_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_dependencies(str(proj / "processor.py"))
    assert "error" not in result
    assert "internal_deps" in result
    assert "external_deps" in result


async def test_mcp_deps_miss(indexed_engine):
    _, _, _ = indexed_engine
    result = await get_dependencies("/no/file.py")
    assert "error" in result


async def test_mcp_dependents_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_dependents(str(proj / "processor.py"))
    assert "error" not in result
    assert "dependents" in result


# ── get_data_flow ─────────────────────────────────────────────────────────────


async def test_mcp_data_flow_hit(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_data_flow(str(proj / "processor.py"), "compute_checksum")
    assert "error" not in result
    assert "sources" in result
    assert "sinks" in result


async def test_mcp_data_flow_miss(indexed_engine):
    _, _, proj = indexed_engine
    result = await get_data_flow(str(proj / "processor.py"), "no_sym")
    assert "error" in result
