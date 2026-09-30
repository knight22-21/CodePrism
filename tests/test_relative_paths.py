"""Tools accept project-relative paths; stored paths are always absolute."""

import os
from pathlib import Path

import pytest

import codeprism.mcp.server as srv
from codeprism.core.config import CodePrismConfig
from codeprism.indexer.incremental_updater import IncrementalUpdater
from codeprism.indexer.project_indexer import ProjectIndexer

CONFIG = CodePrismConfig(languages=["python"])


# ── storage lookup ───────────────────────────────────────────────────────────


@pytest.fixture
async def two_utils(storage, graph, tmp_path):
    proj = tmp_path / "proj"
    for sub in ("api", "core"):
        (proj / sub).mkdir(parents=True)
        (proj / sub / "utils.py").write_text(f"def {sub}_util():\n    return 1\n")
    (proj / "core" / "engine.py").write_text("def run():\n    return 1\n")
    await ProjectIndexer(graph, storage, CONFIG).index(str(proj))
    return proj


@pytest.mark.parametrize(
    "query", ["core/engine.py", "core\\engine.py", "./core/engine.py", "proj/core/engine.py"]
)
async def test_relative_forms_resolve(storage, two_utils, query):
    rec = await storage.get_file_by_path(query)
    assert rec is not None and rec.path == str((two_utils / "core" / "engine.py").resolve())


async def test_exact_absolute_still_resolves(storage, two_utils):
    target = str((two_utils / "api" / "utils.py").resolve())
    assert (await storage.get_file_by_path(target)).path == target


async def test_ambiguous_name_is_not_guessed(storage, two_utils):
    assert await storage.get_file_by_path("utils.py") is None
    assert (await storage.get_file_by_path("api/utils.py")) is not None


async def test_unknown_or_partial_segment_does_not_match(storage, two_utils):
    assert await storage.get_file_by_path("nope/engine.py") is None
    assert await storage.get_file_by_path("ngine.py") is None  # segment-aligned only
    assert await storage.get_file_by_path("") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive")
async def test_windows_case_insensitive(storage, two_utils):
    assert await storage.get_file_by_path("CORE/Engine.PY") is not None


# ── stored paths are absolute ────────────────────────────────────────────────


async def test_index_dot_stores_absolute_paths_without_duplicates(
    storage, graph, tmp_path, monkeypatch
):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("def a():\n    return 1\n")
    monkeypatch.chdir(proj)
    await ProjectIndexer(graph, storage, CONFIG).index(".")
    await ProjectIndexer(graph, storage, CONFIG).index(str(proj))  # same project, absolute

    paths = [f.path for f in await storage.get_all_files()]
    assert paths == [str((proj / "a.py").resolve())]


async def test_update_file_with_relative_path_updates_same_record(
    storage, graph, tmp_path, monkeypatch
):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("def a():\n    return 1\n")
    await ProjectIndexer(graph, storage, CONFIG).index(str(proj))
    monkeypatch.chdir(proj)
    (proj / "a.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")

    await IncrementalUpdater(graph, storage).update_file("a.py")

    files = await storage.get_all_files()
    assert [f.path for f in files] == [str((proj / "a.py").resolve())]
    assert {"a", "b"} <= {s.name for s in await storage.get_all_symbols()}


# ── MCP tools ────────────────────────────────────────────────────────────────


@pytest.fixture
def served(indexed_engine):
    engine, _db, proj = indexed_engine
    srv.init_engine(engine)
    srv.configure(str(proj), auto_index=False)
    yield proj
    srv._engine = None
    srv.configure(".", auto_index=False)


async def test_get_callers_with_relative_path(served):
    result = await srv.get_callers("processor.py", "compute_checksum")
    assert result["count"] >= 1
    caller_files = {c["file"] for c in result["callers"]}
    assert str((served / "main.py").resolve()) in caller_files  # cross-file caller, real path


async def test_relative_path_resolves_against_project_not_cwd(served, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # server cwd is elsewhere (e.g. a subfolder)
    assert (await srv.get_callers("processor.py", "compute_checksum"))["count"] >= 1


async def test_missing_file_is_an_error_not_an_empty_list(served):
    result = await srv.get_callers("nowhere/missing.py", "x")
    assert "error" in result and "not indexed" in result["error"]
    assert "callers" not in result


async def test_missing_symbol_is_an_error(served):
    result = await srv.get_callees("processor.py", "does_not_exist")
    assert "not found" in result["error"]


async def test_other_file_tools_accept_relative_paths(served):
    summary = await srv.get_module_summary("processor.py")
    assert "error" not in summary
    ctx = await srv.get_context("processor.py", "compute_checksum")
    assert "error" not in ctx
    deps = await srv.get_dependencies("main.py")
    assert "error" not in deps


async def test_search_symbol_relative_project_path(served):
    found = await srv.search_symbol("compute", project_path=".")
    assert found["count"] >= 1
    none = await srv.search_symbol("compute", project_path="no/such/dir")
    assert none["count"] == 0


async def test_stats_path_filter_accepts_relative(served):
    stats = await srv.get_graph_stats(path=".")
    assert stats["file_count"] >= 2
    assert Path(stats["project_path"]) == served.resolve()
