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
