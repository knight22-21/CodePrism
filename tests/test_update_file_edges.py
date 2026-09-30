"""update_file must keep other files' edges into the changed file intact."""

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.models import NodeKind
from codeprism.indexer.incremental_updater import IncrementalUpdater
from codeprism.indexer.project_indexer import ProjectIndexer

HELPERS = "def helper(x):\n    return x\n"
HELPERS_SHIFTED = "\n\ndef added():\n    return 0\n\ndef helper(x):\n    return x + 1\n"
HELPERS_RENAMED = "def helper_v2(x):\n    return x\n"
HELPERS_AS_CLASS = "class helper:\n    pass\n"
CALLER = "from helpers import helper\n\ndef run():\n    return helper(2)\n"


async def _setup(storage, graph, tmp_path):
    (tmp_path / "helpers.py").write_text(HELPERS)
    (tmp_path / "caller.py").write_text(CALLER)
    await ProjectIndexer(graph, storage, CodePrismConfig(languages=["python"])).index(str(tmp_path))
    return IncrementalUpdater(graph, storage)


async def _symbol(storage, name, kind=NodeKind.FUNCTION):
    return next(s for s in await storage.get_all_symbols() if s.name == name and s.kind == kind)


def _edge_keys(g: GraphEngine):
    return {(u, v, k) for u, v, k in g._g.edges(keys=True)}


async def _assert_memory_matches_storage(storage, graph):
    reloaded = GraphEngine()
    await reloaded.load_from_storage(storage)
    assert _edge_keys(graph) == _edge_keys(reloaded)
    assert set(graph._g.nodes) == set(reloaded._g.nodes)


async def test_cross_file_caller_survives_edit_of_callee_file(storage, graph, tmp_path):
    updater = await _setup(storage, graph, tmp_path)
    helper = await _symbol(storage, "helper")
    assert [c.name for c in graph.get_callers(helper.id)] == ["run"]

    (tmp_path / "helpers.py").write_text(HELPERS_SHIFTED)
    await updater.update_file(str(tmp_path / "helpers.py"))

    assert [c.name for c in graph.get_callers(helper.id)] == ["run"]
    await _assert_memory_matches_storage(storage, graph)


async def test_renamed_target_leaves_no_ghost_edges(storage, graph, tmp_path):
    updater = await _setup(storage, graph, tmp_path)
    old_id = (await _symbol(storage, "helper")).id

    (tmp_path / "helpers.py").write_text(HELPERS_RENAMED)
    await updater.update_file(str(tmp_path / "helpers.py"))

    assert not graph.has_node(old_id)
    assert all(e.to_id != old_id for e in await storage.get_all_edges())
    await _assert_memory_matches_storage(storage, graph)


async def test_same_name_new_kind_is_repointed(storage, graph, tmp_path):
    updater = await _setup(storage, graph, tmp_path)

    (tmp_path / "helpers.py").write_text(HELPERS_AS_CLASS)
    await updater.update_file(str(tmp_path / "helpers.py"))

    cls = await _symbol(storage, "helper", NodeKind.CLASS)
    assert [c.name for c in graph.get_callers(cls.id)] == ["run"]
    await _assert_memory_matches_storage(storage, graph)


async def test_deleting_callee_file_removes_inbound_edges_from_storage(storage, graph, tmp_path):
    updater = await _setup(storage, graph, tmp_path)
    old_id = (await _symbol(storage, "helper")).id

    (tmp_path / "helpers.py").unlink()
    await updater.update_file(str(tmp_path / "helpers.py"))

    assert all(e.to_id != old_id for e in await storage.get_all_edges())
    await _assert_memory_matches_storage(storage, graph)
