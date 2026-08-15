"""Integration tests for ProjectIndexer."""

import shutil
from pathlib import Path

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.core.models import EdgeKind, NodeKind
from codeprism.indexer.project_indexer import ProjectIndexer

PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def py_project(tmp_path):
    """Copy sample Python fixtures into a temp directory."""
    shutil.copytree(PYTHON_FIXTURE, tmp_path / "project")
    return tmp_path / "project"


@pytest.fixture
async def py_indexer(storage, graph, py_project):
    config = CodePrismConfig(languages=["python"])
    return ProjectIndexer(graph, storage, config)


@pytest.fixture
async def indexed(storage, graph, py_project, py_indexer):
    result = await py_indexer.index(str(py_project))
    return result


# ── Basic correctness ──────────────────────────────────────────────────────────


async def test_index_succeeds(indexed):
    assert indexed.success
    assert not indexed.errors


async def test_index_finds_both_files(indexed):
    # processor.py + main.py
    assert indexed.file_count >= 2


async def test_index_duration_is_positive(indexed):
    assert indexed.duration_seconds > 0


async def test_index_symbol_count_positive(indexed):
    assert indexed.symbol_count > 0


async def test_index_edge_count_positive(indexed):
    assert indexed.edge_count > 0


# ── Symbol presence ────────────────────────────────────────────────────────────


async def test_finds_class_from_processor(storage, indexed):
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "PaymentProcessor" in names


async def test_finds_function_from_processor(storage, indexed):
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "compute_checksum" in names


async def test_finds_function_from_main(storage, indexed):
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "run_payment" in names


async def test_finds_methods_on_class(storage, indexed):
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "process" in names
    assert "_validate" in names


# ── Graph integrity ────────────────────────────────────────────────────────────


async def test_graph_has_file_nodes(graph, indexed):
    stats = graph.get_stats()
    assert stats.file_count >= 2


async def test_graph_has_function_nodes(graph, indexed):
    stats = graph.get_stats()
    assert stats.function_count >= 4


async def test_graph_has_class_nodes(graph, indexed):
    stats = graph.get_stats()
    assert stats.class_count >= 1


# ── Cross-file resolution ──────────────────────────────────────────────────────


async def test_cross_file_call_resolved(storage, graph, indexed):
    """run_payment() in main.py should have a CALLS edge to compute_checksum."""
    all_syms = await storage.get_all_symbols()

    run_payment = next(
        (s for s in all_syms if s.name == "run_payment"), None
    )
    assert run_payment is not None, "run_payment not found in symbols"

    calls = graph.get_edges_from(run_payment.id, kind=EdgeKind.CALLS)
    assert calls, "run_payment should have outgoing CALLS edges"

    # The call to compute_checksum may resolve to the ImportNode (named
    # "compute_checksum") or the actual function — either is acceptable.
    target_ids = {e.to_id for e in calls}
    targets = [s for s in all_syms if s.id in target_ids]
    target_names = {s.name for s in targets}
    assert "compute_checksum" in target_names, (
        f"compute_checksum not in call targets: {target_names}"
    )


async def test_intrafile_call_within_processor(storage, graph, indexed):
    """process() in processor.py calls compute_checksum (same file)."""
    all_syms = await storage.get_all_symbols()

    process_sym = next(
        (s for s in all_syms if s.name == "process" and s.kind == NodeKind.FUNCTION), None
    )
    checksum_sym = next(
        (s for s in all_syms if s.name == "compute_checksum" and s.kind == NodeKind.FUNCTION), None
    )
    assert process_sym and checksum_sym

    calls = graph.get_edges_from(process_sym.id, kind=EdgeKind.CALLS)
    callee_ids = {e.to_id for e in calls}
    assert checksum_sym.id in callee_ids


# ── Exclusion and filtering ────────────────────────────────────────────────────


async def test_pycache_excluded(storage, graph, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("def hello(): pass\n")
    cache = proj / "__pycache__"
    cache.mkdir()
    (cache / "app.cpython-312.pyc").write_bytes(b"\x00\x00")

    config = CodePrismConfig(languages=["python"])
    indexer = ProjectIndexer(graph, storage, config)
    await indexer.index(str(proj))

    all_files = await storage.get_all_files()
    paths = {f.path for f in all_files}
    assert not any("__pycache__" in p for p in paths)


async def test_index_empty_directory(storage, graph, tmp_path):
    proj = tmp_path / "empty"
    proj.mkdir()
    config = CodePrismConfig(languages=["python"])
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(str(proj))
    assert result.file_count == 0
    assert result.success


async def test_index_single_js_file(storage, graph, tmp_path):
    proj = tmp_path / "js"
    proj.mkdir()
    (proj / "index.js").write_text(
        "class Greeter { greet(name) { return 'hi ' + name; } }\n"
        "function run() { return new Greeter(); }\n"
    )
    config = CodePrismConfig(languages=["javascript"])
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(str(proj))

    assert result.file_count == 1
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "Greeter" in names
    assert "run" in names


async def test_language_filter_skips_wrong_extension(storage, graph, tmp_path):
    """Indexing with languages=['python'] should not pick up .js files."""
    proj = tmp_path / "mixed"
    proj.mkdir()
    (proj / "app.py").write_text("def hello(): pass\n")
    (proj / "utils.js").write_text("function helper() {}\n")

    config = CodePrismConfig(languages=["python"])
    indexer = ProjectIndexer(graph, storage, config)
    await indexer.index(str(proj))

    all_files = await storage.get_all_files()
    assert all(f.language == "python" for f in all_files)


async def test_idempotent_reindex(storage, graph, py_project, py_indexer):
    """Indexing the same project twice must not duplicate symbols."""
    r1 = await py_indexer.index(str(py_project))
    r2 = await py_indexer.index(str(py_project))
    # Symbol count must be the same after a re-index
    assert r1.symbol_count == r2.symbol_count
    assert r1.file_count == r2.file_count
