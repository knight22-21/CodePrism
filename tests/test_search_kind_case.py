"""search_symbol's kind filter is case-insensitive (issue #18, PR #19)."""

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.query.engine import QueryEngine

SOURCE = "def process_payment():\n    pass\n\nclass PaymentService:\n    pass\n"


@pytest.fixture
async def engine(storage, graph, tmp_path):
    (tmp_path / "pay.py").write_text(SOURCE)
    await ProjectIndexer(graph, storage, CodePrismConfig(languages=["python"])).index(str(tmp_path))
    return QueryEngine(graph, storage)


@pytest.mark.parametrize("kind", ["function", "Function", "FUNCTION"])
async def test_function_kind_any_case(engine, kind):
    names = [m.symbol.name for m in await engine.search_symbols("pay", kind=kind)]
    assert names == ["process_payment"]


@pytest.mark.parametrize("kind", ["class", "Class", "CLASS"])
async def test_class_kind_any_case(engine, kind):
    names = [m.symbol.name for m in await engine.search_symbols("pay", kind=kind)]
    assert names == ["PaymentService"]


async def test_storage_find_symbols_kind_any_case(engine, storage):
    assert [s.name for s in await storage.find_symbols("PaymentService", kind="Class")] == [
        "PaymentService"
    ]


@pytest.mark.parametrize("kind", ["method", "banana", "", "file"])
async def test_unknown_kind_reports_valid_choices(engine, kind):
    with pytest.raises(ValueError, match="Unknown kind") as error:
        await engine.search_symbols("pay", kind=kind)
    assert repr(kind) in str(error.value)
    assert "Valid kinds: class, function, import, module, type, variable" in str(error.value)


@pytest.mark.parametrize("kind", ["class", "function", "import", "module", "type", "variable"])
async def test_all_symbol_kinds_accept_uppercase(engine, kind):
    assert await engine.search_symbols("", kind=kind.upper()) == await engine.search_symbols(
        "", kind=kind
    )


async def test_invalid_kind_is_rejected_before_semantic_search(engine):
    from unittest.mock import Mock

    engine._embedder = Mock()
    engine._embed_store = Mock()
    with pytest.raises(ValueError, match="Unknown kind"):
        await engine.search_symbols("pay", kind="method")
    engine._embedder.encode_one.assert_not_called()
    engine._embed_store.search.assert_not_called()
