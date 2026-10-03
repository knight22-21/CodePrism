"""Ranked substring search and truthful MCP pagination (issue #38)."""

from pathlib import Path
from typing import cast

import pytest

import codeprism.mcp.server as server
from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.models import FileRecord, NodeKind, SymbolRecord
from codeprism.core.storage import StorageManager
from codeprism.embeddings.store import SearchResult
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.mcp.tools import search_matches_to_dict
from codeprism.query.engine import QueryEngine


async def _index_sources(
    root: Path, graph: GraphEngine, storage: StorageManager, sources: dict[str, str]
) -> None:
    """Index real fixture files without inheriting the surrounding Git checkout."""
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    config = CodePrismConfig(languages=["python"], respect_gitignore=False)
    await ProjectIndexer(graph, storage, config).index(str(root))


@pytest.fixture
async def search_index(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> tuple[QueryEngine, Path]:
    """Index 60 partial matches before the exact match in real SQLite storage."""
    root = tmp_path / "project"
    await _index_sources(
        root,
        graph,
        storage,
        {
            "a_helpers.py": "".join(
                f"def prerun_step_{i}():\n    return {i}\n\n" for i in range(60)
            ),
            "z_core.py": "def run():\n    return 1\n",
        },
    )
    return QueryEngine(graph, storage), root.resolve()


@pytest.fixture
def mcp_search(search_index: tuple[QueryEngine, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the real indexed query engine and served root into the MCP tool."""
    engine, root = search_index
    monkeypatch.setattr(server, "_engine", engine)
    monkeypatch.setattr(server, "_project_path", str(root))


async def test_existing_list_api_keeps_exact_match_before_limit(
    search_index: tuple[QueryEngine, Path], storage: StorageManager
) -> None:
    """The original reproduction must succeed through both existing list APIs."""
    engine, _ = search_index
    matches = await engine.search_symbols("run")
    assert isinstance(matches, list)
    assert len(matches) == 50
    assert matches[0].symbol.name == "run"
    symbols = await storage.search_symbols("run")
    assert isinstance(symbols, list)
    assert len(symbols) == 50
    assert symbols[0].name == "run"


async def test_existing_list_api_ranks_prefix_before_substrings(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> None:
    """SQL ranking precedes the cap and uses stable names within each tier."""
    await _index_sources(
        tmp_path / "rank",
        graph,
        storage,
        {
            "rank.py": "\n".join(
                f"def {name}(): pass" for name in ["prerun_z", "run_z", "prerun_a", "run_a", "run"]
            )
        },
    )
    names = [match.symbol.name for match in await QueryEngine(graph, storage).search_symbols("run")]
    assert names == ["run", "run_a", "run_z", "prerun_a", "prerun_z"]


async def test_existing_list_api_orders_tied_names_by_file(
    storage: StorageManager, graph: GraphEngine
) -> None:
    """Equal names must not depend on SQLite insertion order."""
    for path in ["/project/z.py", "/project/a.py"]:
        file = FileRecord.create(path)
        await storage.upsert_file(file)
        await storage.upsert_symbol(SymbolRecord.create(path, file.id, "run", NodeKind.FUNCTION))
    engine = QueryEngine(graph, storage)
    assert [match.file_path for match in await engine.search_symbols("run")] == [
        "/project/a.py",
        "/project/z.py",
    ]


@pytest.mark.parametrize("count,limit", [(0, 5), (4, 5), (5, 5), (6, 5), (50, 50), (51, 50)])
async def test_substring_page_reports_actual_total_and_truncation(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path, count: int, limit: int
) -> None:
    """Empty, below-limit, exact-limit and cut pages have accurate metadata."""
    await _index_sources(
        tmp_path / "boundary",
        graph,
        storage,
        {"symbols.py": "".join(f"def item_{i}(): pass\n" for i in range(count))},
    )
    page = await QueryEngine(graph, storage).search_symbols_page("item", limit=limit)
    result = search_matches_to_dict(page.matches, total=page.total)
    assert result["count"] == min(count, limit)
    assert result["total"] == count
    assert result["truncated"] is (count > limit)


@pytest.mark.parametrize("limit", [1, 50, 500])
async def test_mcp_limit_and_default_ranked_page(mcp_search: None, limit: int) -> None:
    """MCP exposes the default and both valid bound values without losing run."""
    result = await server.search_symbol("run", limit=limit)
    assert result["count"] == min(61, limit)
    assert result["total"] == 61
    assert result["truncated"] is (limit < 61)
    assert result["matches"][0]["name"] == "run"
    if limit == 50:
        assert await server.search_symbol("run") == result


async def test_mcp_filters_before_pagination_and_total(
    search_index: tuple[QueryEngine, Path], mcp_search: None
) -> None:
    """Relative project and kind filters select/count rows before the cap."""
    engine, root = search_index
    await _index_sources(
        root,
        engine._graph,
        engine._storage,
        {
            "sub%_project/target.py": "def run(): pass\ndef run_again(): pass\nclass run_type: pass\n",
            "subXXproject/other.py": "def run_other(): pass\n",
        },
    )
    result = await server.search_symbol("run", "sub%_project", "FUNCTION", limit=1)
    assert result["count"] == 1
    assert result["total"] == 2
    assert result["truncated"] is True
    assert result["matches"][0]["name"] == "run"
    assert result["matches"][0]["file_path"] == str(root / "sub%_project/target.py")
    assert (
        await server.search_symbol("run", str(root / "sub%_project"), "FUNCTION", limit=1) == result
    )
    uncut = await server.search_symbol("run", "sub%_project", "FUNCTION", limit=2)
    assert uncut["total"] == 2
    assert uncut["truncated"] is False
    empty = await server.search_symbol("run", "absent", limit=1)
    assert empty == {"count": 0, "matches": [], "total": 0, "truncated": False}


@pytest.mark.parametrize("kind", ["function", "Function", "FUNCTION"])
async def test_page_kind_filter_counts_only_selected_kind(
    search_index: tuple[QueryEngine, Path], kind: str
) -> None:
    """Case-insensitive kinds retain the complete filtered total."""
    engine, root = search_index
    await _index_sources(root, engine._graph, engine._storage, {"types.py": "class run: pass\n"})
    page = await engine.search_symbols_page("run", kind, limit=1)
    assert page.total == 61
    assert len(page.matches) == 1
    assert page.matches[0].symbol.kind == NodeKind.FUNCTION


@pytest.mark.parametrize("limit", [0, -1, 501, True, 1.5, "5", None])
async def test_invalid_limits_return_mcp_error_and_query_value_error(
    search_index: tuple[QueryEngine, Path], mcp_search: None, limit: object
) -> None:
    """Out-of-range input is rejected instead of silently clamped."""
    engine, _ = search_index
    with pytest.raises(ValueError, match="limit"):
        await engine.search_symbols_page("run", limit=cast(int, limit))
    with pytest.raises(ValueError, match="limit"):
        await engine._storage.search_symbols_page("run", limit=cast(int, limit))
    result = await server.search_symbol("run", limit=cast(int, limit))
    assert set(result) == {"error"}
    assert "1" in result["error"] and "500" in result["error"]


async def test_invalid_kind_keeps_mcp_error_contract(mcp_search: None) -> None:
    """Unknown kinds still explain accepted choices through the MCP wrapper."""
    result = await server.search_symbol("run", kind="method")
    assert "Unknown kind 'method'" in result["error"]


async def test_serializer_without_total_keeps_original_shape(
    search_index: tuple[QueryEngine, Path],
) -> None:
    """Existing serializer callers retain count/matches without invented metadata."""
    engine, _ = search_index
    matches = await engine.search_symbols("run")
    result = search_matches_to_dict(matches)
    assert set(result) == {"count", "matches"}
    assert result["count"] == len(matches)


class _Embedder:
    """Lightweight semantic encoder; no optional model is downloaded."""

    def encode_one(self, query: str) -> list[float]:
        """Return a deterministic vector for the semantic compatibility test."""
        return [1.0]


class _Store:
    """Return actual indexed symbol IDs in a fixed semantic order."""

    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.requested_top_k: int | None = None

    def search(self, vector: list[float], top_k: int) -> list[SearchResult]:
        """Mimic the existing vector store's capped nearest-neighbor API."""
        self.requested_top_k = top_k
        return self.results[:top_k]


async def test_semantic_backend_keeps_cap_order_and_original_metadata_shape(
    search_index: tuple[QueryEngine, Path], mcp_search: None
) -> None:
    """Substring limit/total must not pretend to describe the semantic result set."""
    engine, root = search_index
    symbols = await engine._storage.get_all_symbols()
    results = [
        SearchResult(symbol.id, str(root / "a_helpers.py"), symbol.name, 0.1, {"kind": "function"})
        for symbol in symbols[:30]
    ]
    store = _Store(results)
    engine.set_embeddings(_Embedder(), store)
    page = await engine.search_symbols_page("run", limit=1)
    assert store.requested_top_k == 20
    assert page.total is None
    assert len(page.matches) == 20
    assert [match.symbol.id for match in page.matches] == [
        result.symbol_id for result in results[:20]
    ]
    assert page.matches == await engine.search_symbols("run")
    response = await server.search_symbol("run", kind="FUNCTION", limit=1)
    assert set(response) == {"count", "matches"}
    assert response["count"] == 20
    assert await server.search_symbol("run", "absent", limit=1) == {"count": 0, "matches": []}
