"""Single-file updates must not do whole-repo work (full symbol load, full edge scan)."""

from pathlib import Path

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.models import NodeKind
from codeprism.indexer.incremental_updater import IncrementalUpdater
from codeprism.indexer.project_indexer import ProjectIndexer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"

FILES = {
    # 'shared' is defined in two files and imported in a third: exercises the
    # import-stub vs definition tie-break and the "later row wins" rule
    "a.py": "def shared():\n    return 1\n\ndef only_a():\n    return shared()\n",
    "b.py": "def shared():\n    return 2\n",
    "c.py": "from a import shared, only_a\n\ndef use():\n    return shared() + only_a()\n",
}


def _old_resolution(symbols, names):
    """The previous algorithm: scan every symbol in storage order."""
    name_to_id = {}
    for sym in symbols:
        if sym.name not in name_to_id or sym.kind != NodeKind.IMPORT:
            name_to_id[sym.name] = sym.id
    return {n: i for n, i in name_to_id.items() if n in names}


async def _index(storage, graph, root):
    await ProjectIndexer(graph, storage, CodePrismConfig(languages=["python"])).index(str(root))


async def test_targeted_lookup_matches_full_scan(storage, graph, tmp_path):
    for name, content in FILES.items():
        (tmp_path / name).write_text(content)
    await _index(storage, graph, tmp_path)

    symbols = await storage.get_all_symbols()
    names = {s.name for s in symbols} | {"does_not_exist"}
    assert await storage.resolve_symbol_names(names) == _old_resolution(symbols, names)


async def test_targeted_lookup_matches_full_scan_on_fixture(storage, graph):
    await _index(storage, graph, FIXTURE)
    symbols = await storage.get_all_symbols()
    names = {s.name for s in symbols}
    assert await storage.resolve_symbol_names(names) == _old_resolution(symbols, names)


async def test_resolution_handles_more_names_than_one_sql_chunk(storage):
    assert await storage.resolve_symbol_names({f"n{i}" for i in range(2500)}) == {}


async def test_update_file_never_loads_every_symbol(storage, graph, tmp_path, monkeypatch):
    for name, content in FILES.items():
        (tmp_path / name).write_text(content)
    await _index(storage, graph, tmp_path)

    async def forbidden():
        raise AssertionError("update_file must not load the whole symbols table")

    monkeypatch.setattr(storage, "get_all_symbols", forbidden)
    (tmp_path / "c.py").write_text(FILES["c.py"] + "\ndef extra():\n    return use()\n")
    result = await IncrementalUpdater(graph, storage).update_file(str(tmp_path / "c.py"))
    assert result.nodes_added > 0


async def test_remove_edges_for_file_removes_exactly_that_files_edges(storage, graph, tmp_path):
    for name, content in FILES.items():
        (tmp_path / name).write_text(content)
    await _index(storage, graph, tmp_path)

    target = str(tmp_path / "a.py")
    keep = {
        (u, v, k)
        for u, v, k, d in graph._g.edges(keys=True, data=True)
        if d["record"].file_path != target
    }
    graph.remove_edges_for_file(target)
    assert {(u, v, k) for u, v, k in graph._g.edges(keys=True)} == keep


async def test_edge_index_tolerates_edges_dropped_by_node_removal(storage, tmp_path):
    for name, content in FILES.items():
        (tmp_path / name).write_text(content)
    graph = GraphEngine()
    await _index(storage, graph, tmp_path)

    only_a = next(s for s in await storage.get_all_symbols() if s.name == "only_a")
    graph.remove_symbol(only_a.id)  # implicitly drops edges; index keeps stale keys
    graph.remove_edges_for_file(str(tmp_path / "c.py"))  # must not raise
    some_edge = next(iter(graph._edge_ends))
    graph.remove_edge_by_id(some_edge)
    assert some_edge not in {k for _, _, k in graph._g.edges(keys=True)}
