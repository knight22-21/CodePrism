"""Re-indexing must leave storage identical to a fresh index of the same files."""

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.storage import StorageManager
from codeprism.indexer.project_indexer import ProjectIndexer

CONFIG = CodePrismConfig(languages=["python"])

HELPERS_V1 = "def old_name(x):\n    return x\n\ndef other():\n    return old_name(1)\n"
# renamed + shifted down by blank lines so every edge line number changes
HELPERS_V2 = "\n\n\ndef new_name(x):\n    return x\n\ndef other():\n    return new_name(1)\n"
CALLER = "from helpers import old_name\n\ndef run():\n    return old_name(2)\n"


async def _snapshot(storage):
    symbols = {(s.name, s.kind) for s in await storage.get_all_symbols()}
    edges = sorted(
        (e.kind, e.from_id, e.to_id, e.line_number) for e in await storage.get_all_edges()
    )
    return symbols, edges


async def _fresh_snapshot(tmp_path, project):
    fresh = StorageManager(tmp_path / "fresh.db")
    await fresh.initialize()
    try:
        await ProjectIndexer(GraphEngine(), fresh, CONFIG).index(str(project))
        return await _snapshot(fresh)
    finally:
        await fresh.close()


async def test_incremental_reindex_matches_fresh_index(storage, graph, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "helpers.py").write_text(HELPERS_V1)
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project))

    (project / "helpers.py").write_text(HELPERS_V2)
    await indexer.index(str(project))

    symbols, edges = await _snapshot(storage)
    assert ("old_name", "function") not in {(n, k.value) for n, k in symbols}
    assert (symbols, edges) == await _fresh_snapshot(tmp_path, project)


async def test_force_reindex_does_not_duplicate_edges(storage, graph, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "helpers.py").write_text(HELPERS_V1)
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project), force=True)
    before = await _snapshot(storage)

    (project / "helpers.py").write_text(HELPERS_V2)
    await indexer.index(str(project), force=True)
    (project / "helpers.py").write_text(HELPERS_V1)
    await indexer.index(str(project), force=True)

    assert await _snapshot(storage) == before


async def test_force_reindex_purges_deleted_files(storage, graph, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "helpers.py").write_text(HELPERS_V1)
    (project / "gone.py").write_text("def temp():\n    pass\n")
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project))

    (project / "gone.py").unlink()
    await indexer.index(str(project), force=True)

    paths = {f.path for f in await storage.get_all_files()}
    assert not any(p.endswith("gone.py") for p in paths)
    assert "temp" not in {s.name for s in await storage.get_all_symbols()}


async def test_no_edges_point_at_renamed_symbols(storage, graph, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "helpers.py").write_text(HELPERS_V1)
    (project / "caller.py").write_text(CALLER)
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project))

    # caller.py is unchanged, but the symbol it pointed at no longer exists
    (project / "helpers.py").write_text(HELPERS_V2)
    await indexer.index(str(project))

    valid = {s.id for s in await storage.get_all_symbols()} | {
        f.id for f in await storage.get_all_files()
    }
    for e in await storage.get_all_edges():
        assert e.from_id in valid and e.to_id in valid


async def test_in_memory_graph_is_replaced_not_accumulated(storage, graph, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "helpers.py").write_text(HELPERS_V1)
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project))
    old_ids = {s.id for s in await storage.get_all_symbols() if s.name == "old_name"}

    (project / "helpers.py").write_text(HELPERS_V2)
    await indexer.index(str(project))

    assert old_ids and not any(graph.has_node(i) for i in old_ids)
