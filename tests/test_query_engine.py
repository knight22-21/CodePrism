"""Tests for QueryEngine — find_symbol, search, file map, deps, stats."""

import pytest

from codeprism.core.models import NodeKind


# ── find_symbol ────────────────────────────────────────────────────────────────


async def test_find_symbol_returns_record(indexed_engine):
    engine, db, proj = indexed_engine
    sym = await engine.find_symbol(str(proj / "processor.py"), "compute_checksum")
    assert sym is not None
    assert sym.name == "compute_checksum"
    assert sym.kind == NodeKind.FUNCTION


async def test_find_symbol_unknown_file(indexed_engine):
    engine, db, proj = indexed_engine
    sym = await engine.find_symbol("/does/not/exist.py", "anything")
    assert sym is None


async def test_find_symbol_unknown_name(indexed_engine):
    engine, db, proj = indexed_engine
    sym = await engine.find_symbol(str(proj / "processor.py"), "nonexistent_xyz")
    assert sym is None


async def test_find_symbol_prefers_function_over_import(indexed_engine):
    """When a name matches both an ImportNode and a Function, return the Function."""
    engine, db, proj = indexed_engine
    # compute_checksum is imported in main.py (as ImportNode) and defined in processor.py
    sym = await engine.find_symbol(str(proj / "processor.py"), "compute_checksum")
    assert sym.kind == NodeKind.FUNCTION


# ── get_callers / get_callees ──────────────────────────────────────────────────


async def test_get_callers_returns_list(indexed_engine):
    engine, db, proj = indexed_engine
    callers = await engine.get_callers(str(proj / "processor.py"), "compute_checksum")
    assert isinstance(callers, list)


async def test_get_callers_process_calls_compute_checksum(indexed_engine):
    engine, db, proj = indexed_engine
    callers = await engine.get_callers(str(proj / "processor.py"), "compute_checksum")
    names = {s.name for s in callers}
    assert "process" in names


async def test_get_callees_returns_list(indexed_engine):
    engine, db, proj = indexed_engine
    callees = await engine.get_callees(str(proj / "processor.py"), "process")
    assert isinstance(callees, list)


async def test_get_callers_unknown_symbol(indexed_engine):
    engine, db, proj = indexed_engine
    callers = await engine.get_callers(str(proj / "processor.py"), "no_such_fn")
    assert callers == []


# ── search_symbols ────────────────────────────────────────────────────────────


async def test_search_by_prefix(indexed_engine):
    engine, db, proj = indexed_engine
    results = await engine.search_symbols("compute")
    names = {m.symbol.name for m in results}
    assert "compute_checksum" in names


async def test_search_by_kind_filter(indexed_engine):
    engine, db, proj = indexed_engine
    results = await engine.search_symbols("", kind="class")
    for m in results:
        assert m.symbol.kind == NodeKind.CLASS


async def test_search_returns_file_path(indexed_engine):
    engine, db, proj = indexed_engine
    results = await engine.search_symbols("PaymentProcessor")
    assert results
    assert results[0].file_path != ""


async def test_search_no_match_returns_empty(indexed_engine):
    engine, db, proj = indexed_engine
    results = await engine.search_symbols("zzz_no_such_symbol_xyz")
    assert results == []


# ── get_file_map ──────────────────────────────────────────────────────────────


async def test_file_map_total_files(indexed_engine):
    engine, db, proj = indexed_engine
    fm = await engine.get_file_map(str(proj))
    assert fm.total_files >= 2


async def test_file_map_entries_have_role(indexed_engine):
    engine, db, proj = indexed_engine
    fm = await engine.get_file_map(str(proj))
    for entry in fm.entries:
        assert entry.role_summary != ""


async def test_file_map_symbol_count(indexed_engine):
    engine, db, proj = indexed_engine
    fm = await engine.get_file_map(str(proj))
    assert fm.total_symbols > 0


# ── get_dependencies / get_dependents ─────────────────────────────────────────


async def test_get_dependencies_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_dependencies(str(proj / "processor.py"))
    assert result is not None
    assert result.file_path == str(proj / "processor.py")


async def test_get_dependencies_external_includes_stdlib(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_dependencies(str(proj / "processor.py"))
    # processor.py imports os, hashlib — these won't be in the graph
    assert len(result.external_deps) > 0


async def test_get_dependents_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_dependents(str(proj / "processor.py"))
    assert result is not None


async def test_get_dependencies_unknown_file(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_dependencies("/no/such/file.py")
    assert result is None


# ── get_stats ─────────────────────────────────────────────────────────────────


async def test_stats_returns_dict(indexed_engine):
    engine, db, proj = indexed_engine
    stats = await engine.get_stats()
    assert "file_count" in stats
    assert "function_count" in stats
    assert "edge_count" in stats


async def test_stats_counts_positive(indexed_engine):
    engine, db, proj = indexed_engine
    stats = await engine.get_stats()
    assert stats["file_count"] >= 2
    assert stats["function_count"] >= 4
    assert stats["edge_count"] >= 1


# ── get_data_flow ─────────────────────────────────────────────────────────────


async def test_data_flow_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_data_flow(str(proj / "processor.py"), "compute_checksum")
    assert result is not None
    assert result.symbol.name == "compute_checksum"


async def test_data_flow_unknown_symbol(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_data_flow(str(proj / "processor.py"), "no_such")
    assert result is None
