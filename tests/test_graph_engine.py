"""Tests for GraphEngine (in-memory NetworkX wrapper)."""

import pytest
from codeprism.core.graph import GraphEngine
from codeprism.core.models import EdgeKind, NodeKind
from tests.conftest import make_edge, make_file, make_symbol


# ── Basic mutation ────────────────────────────────────────────────────────────

def test_add_file_and_get():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    assert g.has_node(f.id)
    assert g.get_file(f.id) is not None
    assert g.get_file(f.id).path == "/project/main.py"


def test_add_symbol_and_get():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("process_payment", file=f)
    g.add_symbol(sym)
    assert g.has_node(sym.id)
    assert g.get_symbol(sym.id).name == "process_payment"


def test_remove_symbol_removes_node():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("foo", file=f)
    g.add_symbol(sym)
    g.remove_symbol(sym.id)
    assert not g.has_node(sym.id)
    assert g.get_symbol(sym.id) is None


def test_remove_file_removes_node_and_incident_edges():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("bar", file=f)
    g.add_symbol(sym)
    g.add_edge(make_edge(sym, sym))  # self-loop for simplicity
    g.remove_file(f.id)
    assert not g.has_node(f.id)


def test_remove_edge_by_id():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a = make_symbol("a", file=f)
    b = make_symbol("b", file=f)
    g.add_symbol(a)
    g.add_symbol(b)
    e = make_edge(a, b)
    g.add_edge(e)
    assert len(g.get_edges_from(a.id)) == 1
    g.remove_edge_by_id(e.id)
    assert len(g.get_edges_from(a.id)) == 0


# ── Caller / callee ───────────────────────────────────────────────────────────

def test_callers_and_callees():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    main = make_symbol("main", file=f)
    process = make_symbol("process_payment", file=f)
    validate = make_symbol("validate_card", file=f)
    for s in (main, process, validate):
        g.add_symbol(s)
    g.add_edge(make_edge(main, process))
    g.add_edge(make_edge(main, validate))

    callers_of_process = g.get_callers(process.id)
    assert len(callers_of_process) == 1
    assert callers_of_process[0].name == "main"

    callees_of_main = g.get_callees(main.id)
    names = {s.name for s in callees_of_main}
    assert "process_payment" in names
    assert "validate_card" in names


def test_get_callers_empty_when_none():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("orphan", file=f)
    g.add_symbol(sym)
    assert g.get_callers(sym.id) == []


def test_callers_only_includes_calls_edges():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    parent = make_symbol("Parent", kind=NodeKind.CLASS, file=f)
    child = make_symbol("Child", kind=NodeKind.CLASS, file=f)
    func = make_symbol("method", kind=NodeKind.FUNCTION, file=f)
    for s in (parent, child, func):
        g.add_symbol(s)
    g.add_edge(make_edge(child, parent, kind=EdgeKind.INHERITS))
    g.add_edge(make_edge(func, parent, kind=EdgeKind.CALLS))

    # Only CALLS edges contribute to callers
    callers = g.get_callers(parent.id)
    assert len(callers) == 1
    assert callers[0].name == "method"


# ── Neighbourhood traversal ───────────────────────────────────────────────────

def test_get_neighbors_depth_1():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a, b, c = make_symbol("a", file=f), make_symbol("b", file=f), make_symbol("c", file=f)
    for s in (a, b, c):
        g.add_symbol(s)
    g.add_edge(make_edge(a, b))
    g.add_edge(make_edge(b, c))

    neighbors = g.get_neighbors(a.id, depth=1)
    assert b.id in neighbors
    assert c.id not in neighbors  # two hops away


def test_get_neighbors_depth_2():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a, b, c = make_symbol("a", file=f), make_symbol("b", file=f), make_symbol("c", file=f)
    for s in (a, b, c):
        g.add_symbol(s)
    g.add_edge(make_edge(a, b))
    g.add_edge(make_edge(b, c))

    neighbors = g.get_neighbors(a.id, depth=2)
    assert b.id in neighbors
    assert c.id in neighbors


def test_get_neighbors_isolated_node():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    iso = make_symbol("isolated", file=f)
    g.add_symbol(iso)
    assert g.get_neighbors(iso.id) == set()


# ── Transitive analysis ───────────────────────────────────────────────────────

def test_transitive_dependents():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    root = make_symbol("root", file=f)
    mid = make_symbol("mid", file=f)
    leaf = make_symbol("leaf", file=f)
    for s in (root, mid, leaf):
        g.add_symbol(s)
    # mid depends on root, leaf depends on mid
    g.add_edge(make_edge(mid, root))
    g.add_edge(make_edge(leaf, mid))

    dependents = g.get_transitive_dependents(root.id)
    assert mid.id in dependents
    assert leaf.id in dependents
    assert root.id not in dependents


def test_transitive_dependencies():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    root = make_symbol("root", file=f)
    mid = make_symbol("mid", file=f)
    leaf = make_symbol("leaf", file=f)
    for s in (root, mid, leaf):
        g.add_symbol(s)
    g.add_edge(make_edge(mid, root))
    g.add_edge(make_edge(leaf, mid))

    deps = g.get_transitive_dependencies(leaf.id)
    assert mid.id in deps
    assert root.id in deps


# ── Subgraph ──────────────────────────────────────────────────────────────────

def test_get_subgraph_contains_center():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    center = make_symbol("center", file=f)
    g.add_symbol(center)
    sg = g.get_subgraph(center.id, depth=1)
    assert center.id in sg.nodes


def test_get_subgraph_respects_depth():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a, b, c, d = [make_symbol(n, file=f) for n in ("a", "b", "c", "d")]
    for s in (a, b, c, d):
        g.add_symbol(s)
    g.add_edge(make_edge(a, b))
    g.add_edge(make_edge(b, c))
    g.add_edge(make_edge(c, d))

    sg1 = g.get_subgraph(a.id, depth=1)
    assert b.id in sg1.nodes
    assert d.id not in sg1.nodes

    sg2 = g.get_subgraph(a.id, depth=2)
    assert c.id in sg2.nodes
    assert d.id not in sg2.nodes


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_counts():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    g.add_symbol(make_symbol("Foo", kind=NodeKind.CLASS, file=f))
    g.add_symbol(make_symbol("Bar", kind=NodeKind.CLASS, file=f))
    g.add_symbol(make_symbol("baz", kind=NodeKind.FUNCTION, file=f))
    g.add_symbol(make_symbol("qux", kind=NodeKind.FUNCTION, file=f))
    g.add_symbol(make_symbol("MY_CONST", kind=NodeKind.VARIABLE, file=f))

    stats = g.get_stats()
    assert stats.file_count == 1
    assert stats.class_count == 2
    assert stats.function_count == 2
    assert stats.variable_count == 1
    assert "python" in stats.languages


def test_stats_edge_count():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a, b, c = [make_symbol(n, file=f) for n in ("a", "b", "c")]
    for s in (a, b, c):
        g.add_symbol(s)
    g.add_edge(make_edge(a, b))
    g.add_edge(make_edge(b, c))
    assert g.get_stats().edge_count == 2


# ── Load from storage ─────────────────────────────────────────────────────────

async def test_load_from_storage(storage):
    f = make_file()
    await storage.upsert_file(f)
    sym = make_symbol("loaded_fn", file=f)
    await storage.upsert_symbol(sym)
    caller = make_symbol("caller_fn", file=f)
    await storage.upsert_symbol(caller)
    await storage.upsert_edge(make_edge(caller, sym))

    g = GraphEngine()
    await g.load_from_storage(storage)

    assert g.has_node(f.id)
    assert g.has_node(sym.id)
    assert g.has_node(caller.id)
    callers = g.get_callers(sym.id)
    assert len(callers) == 1
    assert callers[0].name == "caller_fn"


# ── Serialization ─────────────────────────────────────────────────────────────

def test_to_json_structure():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("foo", file=f)
    g.add_symbol(sym)
    g.add_edge(make_edge(sym, sym))  # self-loop

    data = g.to_json()
    assert "nodes" in data
    assert "edges" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert f.id in node_ids
    assert sym.id in node_ids


def test_to_graphviz_is_valid_dot():
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    sym = make_symbol("my_func", file=f)
    g.add_symbol(sym)
    dot = g.to_graphviz()
    assert "digraph" in dot
    assert "my_func" in dot
