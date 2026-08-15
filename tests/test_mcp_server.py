"""Tests for MCP tool functions — called directly, not via MCP protocol."""

import pytest
from pathlib import Path

import codeprism.mcp.server as _srv
from codeprism.mcp.server import (
    check_secret_exposure,
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
    get_session_context,
    record_read,
    record_write,
    scan_diff,
    scan_file,
    search_symbol,
    undo_write,
)


@pytest.fixture(autouse=True)
def inject_engine(indexed_engine):
    """Bypass the lifespan and inject the test engine + session manager."""
    from codeprism.indexer.incremental_updater import IncrementalUpdater
    from codeprism.mcp.session import SessionManager

    engine, db, proj = indexed_engine
    _srv.init_engine(engine)
    updater = IncrementalUpdater(engine._graph, engine._storage)
    _srv.init_session_manager(SessionManager(engine._storage, updater))
    yield
    _srv._engine = None
    _srv._session_manager = None


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


# ── record_read ───────────────────────────────────────────────────────────────


async def test_mcp_record_read_returns_recorded(indexed_engine):
    _, _, proj = indexed_engine
    result = await record_read("sess-1", str(proj / "processor.py"), "compute_checksum")
    assert result["recorded"] is True
    assert result["session_id"] == "sess-1"


async def test_mcp_record_read_persists(indexed_engine):
    engine, db, proj = indexed_engine
    fp = str(proj / "processor.py")
    await record_read("sess-persist", fp, "process")

    events = await db.get_session_events("sess-persist")
    assert len(events) == 1
    assert events[0].symbol_name == "process"


# ── record_write ──────────────────────────────────────────────────────────────


async def test_mcp_record_write_returns_pass(indexed_engine):
    _, _, proj = indexed_engine
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    result = await record_write("sess-w", fp, before, before)
    assert result["status"] == "PASS"
    assert "graph_update" in result


async def test_mcp_record_write_flushes_disk(indexed_engine):
    _, _, proj = indexed_engine
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    marker = "\n# mcp-write-test\n"
    await record_write("sess-disk", fp, before, before + marker)
    assert marker.strip() in Path(fp).read_text(encoding="utf-8")
    # Cleanup
    Path(fp).write_text(before, encoding="utf-8")


# ── get_session_context ───────────────────────────────────────────────────────


async def test_mcp_session_context_empty(indexed_engine):
    result = await get_session_context("empty-sess-999")
    assert result["total_events"] == 0
    assert result["read_count"] == 0
    assert result["write_count"] == 0
    assert isinstance(result["summary"], str)


async def test_mcp_session_context_after_read(indexed_engine):
    _, _, proj = indexed_engine
    fp = str(proj / "processor.py")
    await record_read("sess-ctx", fp, "compute_checksum")
    result = await get_session_context("sess-ctx")
    assert result["read_count"] == 1
    assert any("compute_checksum" in r for r in result["files_read"])


async def test_mcp_session_context_has_summary(indexed_engine):
    result = await get_session_context("any-sess")
    assert "summary" in result
    assert len(result["summary"]) > 0


# ── undo_write ────────────────────────────────────────────────────────────────


async def test_mcp_undo_write_no_writes(indexed_engine):
    result = await undo_write("no-writes-sess", steps=1)
    assert result["steps_undone"] == 0
    assert result["files_restored"] == []


async def test_mcp_undo_write_restores_file(indexed_engine):
    _, _, proj = indexed_engine
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    marker = "\n# undo-test-marker\n"
    await record_write("sess-undo", fp, before, before + marker)
    assert marker.strip() in Path(fp).read_text(encoding="utf-8")

    result = await undo_write("sess-undo", steps=1)
    assert result["steps_undone"] == 1
    assert fp in result["files_restored"]
    assert marker.strip() not in Path(fp).read_text(encoding="utf-8")


async def test_mcp_undo_write_returns_file_list(indexed_engine):
    _, _, proj = indexed_engine
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    await record_write("sess-list", fp, before, before)
    result = await undo_write("sess-list", steps=1)
    assert isinstance(result["files_restored"], list)


# ── scan_file ─────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures" / "sample_security_issues"


async def test_mcp_scan_file_clean(indexed_engine):
    _, _, proj = indexed_engine
    result = await scan_file(str(FIXTURES / "clean_example.py"))
    assert result["status"] == "PASS"
    assert result["issues"] == []


async def test_mcp_scan_file_with_content_secrets():
    result = await scan_file("fake.py", content='password = "hunter2"\n')
    assert result["status"] == "BLOCK"
    assert len(result["issues"]) >= 1


async def test_mcp_scan_file_not_found():
    result = await scan_file("/no/such/file_xyz.py")
    assert "error" in result


async def test_mcp_scan_file_has_issues_list():
    result = await scan_file(str(FIXTURES / "secrets_example.py"))
    assert "issues" in result
    assert isinstance(result["issues"], list)


# ── scan_diff ─────────────────────────────────────────────────────────────────


async def test_mcp_scan_diff_no_change_is_pass():
    clean = (FIXTURES / "clean_example.py").read_text(encoding="utf-8")
    result = await scan_diff(clean, clean)
    assert result["status"] == "PASS"


async def test_mcp_scan_diff_new_secret_is_block():
    clean = (FIXTURES / "clean_example.py").read_text(encoding="utf-8")
    proposed = clean + '\napi_key = "sk-secretkey123456789012345678"\n'
    result = await scan_diff(clean, proposed)
    assert result["status"] == "BLOCK"


async def test_mcp_scan_diff_preexisting_not_reflagged():
    content = 'password = "old_pass"\n'
    proposed = content + "\n# comment\n"
    result = await scan_diff(content, proposed)
    assert result["status"] == "PASS"


# ── check_secret_exposure ─────────────────────────────────────────────────────


async def test_mcp_check_secret_clean():
    clean = (FIXTURES / "clean_example.py").read_text(encoding="utf-8")
    result = await check_secret_exposure(clean)
    assert result["status"] == "PASS"
    assert result["count"] == 0


async def test_mcp_check_secret_finds_secret():
    result = await check_secret_exposure('api_key = "sk-supersecretkey12345678901234"\n')
    assert result["status"] == "BLOCK"
    assert result["count"] >= 1


async def test_mcp_check_secret_has_secrets_found_key():
    result = await check_secret_exposure("x = 1\n")
    assert "secrets_found" in result
    assert isinstance(result["secrets_found"], list)
