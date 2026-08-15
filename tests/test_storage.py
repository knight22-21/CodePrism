"""Tests for StorageManager (SQLite persistence layer)."""

import pytest
from codeprism.core.models import EdgeKind, EdgeRecord, FileRecord, NodeKind, SymbolRecord
from tests.conftest import make_edge, make_file, make_symbol


# ── File CRUD ─────────────────────────────────────────────────────────────────

async def test_upsert_and_get_file_by_path(storage):
    f = make_file("/project/main.py")
    await storage.upsert_file(f)
    fetched = await storage.get_file_by_path("/project/main.py")
    assert fetched is not None
    assert fetched.id == f.id
    assert fetched.language == "python"
    assert fetched.line_count == 100


async def test_upsert_file_is_idempotent(storage):
    f = make_file("/project/main.py")
    await storage.upsert_file(f)
    f2 = FileRecord.create(path="/project/main.py", language="python", line_count=200)
    await storage.upsert_file(f2)
    fetched = await storage.get_file_by_path("/project/main.py")
    assert fetched is not None
    assert fetched.line_count == 200


async def test_get_file_missing_returns_none(storage):
    result = await storage.get_file_by_path("/nonexistent.py")
    assert result is None


async def test_get_all_files(storage):
    for path in ("/a.py", "/b.py", "/c.py"):
        await storage.upsert_file(make_file(path))
    files = await storage.get_all_files()
    assert len(files) == 3


async def test_delete_file(storage):
    f = make_file()
    await storage.upsert_file(f)
    await storage.delete_file(f.id)
    assert await storage.get_file_by_id(f.id) is None


# ── Symbol CRUD ───────────────────────────────────────────────────────────────

async def test_upsert_and_get_symbol(storage):
    f = make_file()
    await storage.upsert_file(f)
    sym = make_symbol("process_payment", file=f)
    await storage.upsert_symbol(sym)

    symbols = await storage.get_symbols_for_file(f.id)
    assert len(symbols) == 1
    assert symbols[0].name == "process_payment"
    assert symbols[0].kind == NodeKind.FUNCTION


async def test_upsert_symbols_batch(storage):
    f = make_file()
    await storage.upsert_file(f)
    syms = [make_symbol(name, file=f) for name in ("a", "b", "c", "d", "e")]
    await storage.upsert_symbols_batch(syms)
    stored = await storage.get_symbols_for_file(f.id)
    assert len(stored) == 5


async def test_delete_symbols_for_file(storage):
    f = make_file()
    await storage.upsert_file(f)
    for name in ("foo", "bar", "baz"):
        await storage.upsert_symbol(make_symbol(name, file=f))
    await storage.delete_symbols_for_file(f.id)
    assert await storage.get_symbols_for_file(f.id) == []


async def test_find_symbols_by_name(storage):
    f = make_file()
    await storage.upsert_file(f)
    await storage.upsert_symbol(make_symbol("process_payment", kind=NodeKind.FUNCTION, file=f))
    await storage.upsert_symbol(make_symbol("ProcessPayment", kind=NodeKind.CLASS, file=f))

    exact = await storage.find_symbols("process_payment")
    assert len(exact) == 1
    assert exact[0].kind == NodeKind.FUNCTION

    by_kind = await storage.find_symbols("ProcessPayment", kind="class")
    assert len(by_kind) == 1


async def test_search_symbols_prefix(storage):
    f = make_file()
    await storage.upsert_file(f)
    for name in ("process_payment", "process_refund", "validate_card"):
        await storage.upsert_symbol(make_symbol(name, file=f))
    results = await storage.search_symbols("process_")
    names = {r.name for r in results}
    assert "process_payment" in names
    assert "process_refund" in names
    assert "validate_card" not in names


async def test_get_symbol_by_id(storage):
    f = make_file()
    await storage.upsert_file(f)
    sym = make_symbol("foo", file=f)
    await storage.upsert_symbol(sym)
    fetched = await storage.get_symbol_by_id(sym.id)
    assert fetched is not None
    assert fetched.name == "foo"


# ── Edge CRUD ─────────────────────────────────────────────────────────────────

async def test_upsert_and_get_edges(storage):
    f = make_file()
    await storage.upsert_file(f)
    caller = make_symbol("main", file=f)
    callee = make_symbol("process_payment", file=f)
    await storage.upsert_symbol(caller)
    await storage.upsert_symbol(callee)

    edge = make_edge(caller, callee)
    await storage.upsert_edge(edge)

    edges_from = await storage.get_edges_from(caller.id)
    assert len(edges_from) == 1
    assert edges_from[0].kind == EdgeKind.CALLS

    edges_to = await storage.get_edges_to(callee.id)
    assert len(edges_to) == 1
    assert edges_to[0].from_id == caller.id


async def test_upsert_edges_batch(storage):
    f = make_file()
    await storage.upsert_file(f)
    root = make_symbol("root", file=f)
    await storage.upsert_symbol(root)
    leaves = [make_symbol(f"leaf_{i}", file=f) for i in range(5)]
    for leaf in leaves:
        await storage.upsert_symbol(leaf)
    edges = [make_edge(root, leaf) for leaf in leaves]
    await storage.upsert_edges_batch(edges)
    stored = await storage.get_edges_from(root.id)
    assert len(stored) == 5


async def test_get_edges_by_kind_filter(storage):
    f = make_file()
    await storage.upsert_file(f)
    a = make_symbol("A", kind=NodeKind.CLASS, file=f)
    b = make_symbol("B", kind=NodeKind.CLASS, file=f)
    await storage.upsert_symbol(a)
    await storage.upsert_symbol(b)
    await storage.upsert_edge(make_edge(a, b, kind=EdgeKind.INHERITS))
    await storage.upsert_edge(make_edge(a, b, kind=EdgeKind.CALLS, line=10))

    inherits = await storage.get_edges_from(a.id, kind="inherits")
    assert len(inherits) == 1
    assert inherits[0].kind == EdgeKind.INHERITS


async def test_delete_edges_for_file(storage):
    f = make_file()
    await storage.upsert_file(f)
    a = make_symbol("a", file=f)
    b = make_symbol("b", file=f)
    await storage.upsert_symbol(a)
    await storage.upsert_symbol(b)
    await storage.upsert_edge(make_edge(a, b, file_path=f.path))
    await storage.delete_edges_for_file(f.path)
    assert await storage.get_edges_for_file(f.path) == []


# ── Stats ─────────────────────────────────────────────────────────────────────

async def test_stats(storage):
    f = make_file("/project/main.py", language="python")
    await storage.upsert_file(f)
    await storage.upsert_symbol(make_symbol("Foo", kind=NodeKind.CLASS, file=f))
    await storage.upsert_symbol(make_symbol("Bar", kind=NodeKind.CLASS, file=f))
    await storage.upsert_symbol(make_symbol("baz", kind=NodeKind.FUNCTION, file=f))

    stats = await storage.get_stats()
    assert stats["file_count"] == 1
    assert stats["class_count"] == 2
    assert stats["function_count"] == 1
    assert "python" in stats["languages"]
