"""Tests for IncrementalUpdater — checksum gating, graph surgery, persistence."""

from pathlib import Path

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.core.models import NodeKind
from codeprism.indexer.incremental_updater import IncrementalUpdater
from codeprism.indexer.project_indexer import ProjectIndexer


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _bootstrap(storage, graph, tmp_path, content: str, filename: str = "f.py"):
    """Write a file, index the directory, return an IncrementalUpdater."""
    f = tmp_path / filename
    f.write_text(content)
    config = CodePrismConfig(languages=["python"])
    await ProjectIndexer(graph, storage, config).index(str(tmp_path))
    return IncrementalUpdater(graph, storage)


# ── Checksum gating ────────────────────────────────────────────────────────────


async def test_unchanged_file_is_skipped(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\n")
    result = await updater.update_file(str(tmp_path / "f.py"))
    assert result.skipped is True


async def test_changed_file_is_not_skipped(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\n")
    (tmp_path / "f.py").write_text("def foo(): return 1\n")
    result = await updater.update_file(str(tmp_path / "f.py"))
    assert result.skipped is False


# ── Symbol additions ───────────────────────────────────────────────────────────


async def test_new_symbol_appears_in_storage(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\n")
    (tmp_path / "f.py").write_text("def foo(): pass\ndef bar(): pass\n")
    await updater.update_file(str(tmp_path / "f.py"))
    names = {s.name for s in await storage.get_all_symbols()}
    assert "bar" in names


async def test_new_symbol_appears_in_graph(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\n")
    (tmp_path / "f.py").write_text("def foo(): pass\ndef bar(): pass\n")
    await updater.update_file(str(tmp_path / "f.py"))
    syms = await storage.get_all_symbols()
    bar = next(s for s in syms if s.name == "bar")
    assert graph.has_node(bar.id)


async def test_nodes_added_count_reflects_new_symbols(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\n")
    (tmp_path / "f.py").write_text("def foo(): pass\ndef bar(): pass\n")
    result = await updater.update_file(str(tmp_path / "f.py"))
    assert result.nodes_added > 0


# ── Symbol removals ────────────────────────────────────────────────────────────


async def test_removed_symbol_absent_from_storage(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\ndef bar(): pass\n")
    # Remove bar from the file
    (tmp_path / "f.py").write_text("def foo(): pass\n")
    await updater.update_file(str(tmp_path / "f.py"))
    names = {s.name for s in await storage.get_all_symbols()}
    assert "bar" not in names


async def test_removed_symbol_absent_from_graph(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\ndef bar(): pass\n")
    syms = await storage.get_all_symbols()
    bar_id = next(s.id for s in syms if s.name == "bar")
    (tmp_path / "f.py").write_text("def foo(): pass\n")
    await updater.update_file(str(tmp_path / "f.py"))
    assert not graph.has_node(bar_id)


async def test_nodes_removed_count_reflects_deletions(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def foo(): pass\ndef bar(): pass\n")
    (tmp_path / "f.py").write_text("def foo(): pass\n")
    result = await updater.update_file(str(tmp_path / "f.py"))
    assert result.nodes_removed > 0


# ── New (un-indexed) file ──────────────────────────────────────────────────────


async def test_update_previously_unseen_file(storage, graph, tmp_path):
    updater = IncrementalUpdater(graph, storage)
    new_file = tmp_path / "brand_new.py"
    new_file.write_text("def brand_new(): pass\n")
    result = await updater.update_file(str(new_file))
    assert result.skipped is False
    names = {s.name for s in await storage.get_all_symbols()}
    assert "brand_new" in names


# ── File deletion ──────────────────────────────────────────────────────────────


async def test_deleted_file_symbols_removed_from_storage(storage, graph, tmp_path):
    updater = await _bootstrap(storage, graph, tmp_path, "def delete_me(): pass\n")
    sym_id = next(s.id for s in await storage.get_all_symbols() if s.name == "delete_me")
    (tmp_path / "f.py").unlink()
    await updater.update_file(str(tmp_path / "f.py"))
    assert not graph.has_node(sym_id)
    assert not any(s.name == "delete_me" for s in await storage.get_all_symbols())


# ── Multi-file isolation ───────────────────────────────────────────────────────


async def test_update_does_not_affect_other_files(storage, graph, tmp_path):
    """Symbols from un-touched files must survive an update to another file."""
    (tmp_path / "a.py").write_text("def func_a(): pass\n")
    (tmp_path / "b.py").write_text("def func_b(): pass\n")
    config = CodePrismConfig(languages=["python"])
    await ProjectIndexer(graph, storage, config).index(str(tmp_path))

    updater = IncrementalUpdater(graph, storage)
    (tmp_path / "a.py").write_text("def func_a_v2(): pass\n")
    await updater.update_file(str(tmp_path / "a.py"))

    names = {s.name for s in await storage.get_all_symbols() if s.kind == NodeKind.FUNCTION}
    assert "func_b" in names
    assert "func_a_v2" in names
    assert "func_a" not in names


# ── Edges ─────────────────────────────────────────────────────────────────────


async def test_edges_updated_after_change(storage, graph, tmp_path):
    src = "def caller(): callee()\ndef callee(): pass\n"
    updater = await _bootstrap(storage, graph, tmp_path, src)
    new_src = "def caller(): callee()\ndef callee(): return 1\n"
    (tmp_path / "f.py").write_text(new_src)
    result = await updater.update_file(str(tmp_path / "f.py"))
    assert result.edges_updated > 0


async def test_intrafile_call_edge_preserved_after_update(storage, graph, tmp_path):
    """A call edge within a file must survive an update that doesn't remove it."""
    from codeprism.core.models import EdgeKind

    src = "def caller(): callee()\ndef callee(): pass\n"
    updater = await _bootstrap(storage, graph, tmp_path, src)
    # Modify callee body but keep the call
    (tmp_path / "f.py").write_text("def caller(): callee()\ndef callee(): return 42\n")
    await updater.update_file(str(tmp_path / "f.py"))

    syms = await storage.get_all_symbols()
    caller_id = next(s.id for s in syms if s.name == "caller")
    callee_id = next(s.id for s in syms if s.name == "callee")
    calls = graph.get_edges_from(caller_id, kind=EdgeKind.CALLS)
    assert any(e.to_id == callee_id for e in calls)
