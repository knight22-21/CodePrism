"""A path matching several indexed files is reported as ambiguous, with candidates."""

import pytest

import codeprism.mcp.server as srv
from codeprism.core.config import CodePrismConfig
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.query.engine import QueryEngine


@pytest.fixture
async def served(storage, graph, tmp_path):
    proj = tmp_path / "proj"
    for sub in ("api", "core"):
        (proj / sub).mkdir(parents=True)
        (proj / sub / "utils.py").write_text(
            f"def helper():\n    return 1\n\ndef {sub}_only():\n    return helper()\n"
        )
    await ProjectIndexer(graph, storage, CodePrismConfig(languages=["python"])).index(str(proj))
    srv.init_engine(QueryEngine(graph, storage))
    srv.configure(str(proj), auto_index=False)
    yield proj
    srv._engine = None
    srv.configure(".", auto_index=False)


async def test_ambiguous_name_lists_candidates(served):
    result = await srv.get_callers("utils.py", "helper")
    assert "ambiguous" in result["error"]
    assert result["candidates"] == ["api/utils.py", "core/utils.py"]
    assert "api/utils.py" in result["hint"]


@pytest.mark.parametrize(
    "call",
    [
        lambda f: srv.get_callees(f, "helper"),
        lambda f: srv.get_context(f, "helper"),
        lambda f: srv.get_module_summary(f),
        lambda f: srv.get_impact(f, "helper"),
        lambda f: srv.get_data_flow(f, "helper"),
        lambda f: srv.get_dependencies(f),
        lambda f: srv.get_dependents(f),
    ],
)
async def test_every_file_tool_reports_ambiguity(served, call):
    result = await call("utils.py")
    assert "ambiguous" in result["error"] and len(result["candidates"]) == 2


async def test_longer_path_disambiguates(served):
    result = await srv.get_callers("api/utils.py", "helper")
    assert "error" not in result
    assert [c["name"] for c in result["callers"]] == ["api_only"]


async def test_missing_file_is_still_not_indexed(served):
    result = await srv.get_module_summary("nope/utils2.py")
    assert "not indexed" in result["error"] and "candidates" not in result


async def test_storage_returns_all_candidates(served, storage):
    assert len(await storage.find_files_by_path("utils.py")) == 2
    assert await storage.get_file_by_path("utils.py") is None
    assert len(await storage.find_files_by_path("core/utils.py")) == 1
