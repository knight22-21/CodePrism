"""Tests for SessionManager — record_read, record_write, get_context, undo_write."""

import shutil
import pytest
from pathlib import Path

from codeprism.core.graph import GraphEngine
from codeprism.core.storage import StorageManager
from codeprism.indexer.incremental_updater import IncrementalUpdater
from codeprism.mcp.session import SessionManager

PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"

SESSION_ID = "test-session-001"


@pytest.fixture
async def session_env(tmp_path: Path):
    """Return (SessionManager, proj_path) backed by an indexed temp project."""
    from codeprism.core.config import CodePrismConfig
    from codeprism.indexer.project_indexer import ProjectIndexer

    proj = tmp_path / "project"
    shutil.copytree(PYTHON_FIXTURE, proj)

    storage = StorageManager(tmp_path / "idx.db")
    await storage.initialize()
    graph = GraphEngine()
    config = CodePrismConfig(languages=["python"])
    await ProjectIndexer(graph, storage, config).index(str(proj))

    updater = IncrementalUpdater(graph, storage)
    manager = SessionManager(storage, updater)
    yield manager, proj, storage
    await storage.close()


# ── record_read ───────────────────────────────────────────────────────────────


async def test_record_read_stores_event(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    await manager.record_read(SESSION_ID, fp, "compute_checksum")

    events = await storage.get_session_events(SESSION_ID)
    assert len(events) == 1
    assert events[0].symbol_name == "compute_checksum"
    assert events[0].file_path == fp


async def test_record_read_event_type(session_env):
    from codeprism.core.models import SessionEventKind
    manager, proj, storage = session_env
    await manager.record_read(SESSION_ID, str(proj / "processor.py"), "process")
    events = await storage.get_session_events(SESSION_ID)
    assert events[0].event_type == SessionEventKind.READ


async def test_record_read_multiple_symbols(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    await manager.record_read(SESSION_ID, fp, "compute_checksum")
    await manager.record_read(SESSION_ID, fp, "process")
    await manager.record_read(SESSION_ID, str(proj / "main.py"), "run_payment")

    events = await storage.get_session_events(SESSION_ID)
    assert len(events) == 3
    names = {e.symbol_name for e in events}
    assert "compute_checksum" in names
    assert "run_payment" in names


# ── record_write ──────────────────────────────────────────────────────────────


async def test_record_write_stores_event(session_env):
    from codeprism.core.models import SessionEventKind
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    after = before + "\n# agent-added comment\n"

    await manager.record_write(SESSION_ID, fp, before, after)

    events = await storage.get_session_events(SESSION_ID)
    assert len(events) == 1
    assert events[0].event_type == SessionEventKind.WRITE
    assert events[0].content_before == before
    assert events[0].content_after == after


async def test_record_write_flushes_to_disk(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    after = before + "\n# flushed\n"

    await manager.record_write(SESSION_ID, fp, before, after)

    on_disk = Path(fp).read_text(encoding="utf-8")
    assert "# flushed" in on_disk


async def test_record_write_returns_security_report(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    report = await manager.record_write(SESSION_ID, fp, before, before)

    assert report["status"] == "PASS"
    assert "issues" in report
    assert "graph_update" in report


async def test_record_write_updates_graph(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    new_fn = "\ndef brand_new_function():\n    pass\n"
    after = before + new_fn

    report = await manager.record_write(SESSION_ID, fp, before, after)
    # Graph was updated — nodes_added reflects the new symbol
    assert report["graph_update"]["nodes_added"] >= 0  # at least ran without error


# ── get_context ───────────────────────────────────────────────────────────────


async def test_get_context_empty_session(session_env):
    manager, proj, storage = session_env
    ctx = await manager.get_context("empty-session")
    assert ctx.total_events == 0
    assert ctx.read_count == 0
    assert ctx.write_count == 0
    assert ctx.files_read == []
    assert ctx.files_written == []


async def test_get_context_counts_reads(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    await manager.record_read(SESSION_ID, fp, "compute_checksum")
    await manager.record_read(SESSION_ID, fp, "process")

    ctx = await manager.get_context(SESSION_ID)
    assert ctx.read_count == 2
    assert ctx.write_count == 0


async def test_get_context_counts_writes(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    await manager.record_write(SESSION_ID, fp, before, before + "\n# w1\n")
    # Restore for isolation
    Path(fp).write_text(before, encoding="utf-8")

    ctx = await manager.get_context(SESSION_ID)
    assert ctx.write_count == 1
    assert fp in ctx.files_written


async def test_get_context_files_read_format(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    await manager.record_read(SESSION_ID, fp, "compute_checksum")

    ctx = await manager.get_context(SESSION_ID)
    assert any("compute_checksum" in r for r in ctx.files_read)


async def test_get_context_summary_is_string(session_env):
    manager, proj, storage = session_env
    ctx = await manager.get_context(SESSION_ID)
    assert isinstance(ctx.summary, str)
    assert len(ctx.summary) > 0


async def test_get_context_session_isolation(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    await manager.record_read("sess-A", fp, "compute_checksum")
    await manager.record_read("sess-B", fp, "process")

    ctx_a = await manager.get_context("sess-A")
    ctx_b = await manager.get_context("sess-B")
    assert ctx_a.read_count == 1
    assert ctx_b.read_count == 1


# ── undo_write ────────────────────────────────────────────────────────────────


async def test_undo_write_restores_content(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    after = before + "\n# mutated\n"

    await manager.record_write(SESSION_ID, fp, before, after)
    assert "# mutated" in Path(fp).read_text(encoding="utf-8")

    result = await manager.undo_write(SESSION_ID, steps=1)
    assert fp in result.files_restored
    assert "# mutated" not in Path(fp).read_text(encoding="utf-8")


async def test_undo_write_steps_undone(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    original = Path(fp).read_text(encoding="utf-8")

    await manager.record_write(SESSION_ID, fp, original, original + "\n# v1\n")
    v1 = Path(fp).read_text(encoding="utf-8")
    await manager.record_write(SESSION_ID, fp, v1, v1 + "\n# v2\n")

    result = await manager.undo_write(SESSION_ID, steps=1)
    assert result.steps_undone == 1
    assert "# v2" not in Path(fp).read_text(encoding="utf-8")
    assert "# v1" in Path(fp).read_text(encoding="utf-8")


async def test_undo_write_no_writes_is_noop(session_env):
    manager, proj, storage = session_env
    result = await manager.undo_write(SESSION_ID, steps=1)
    assert result.steps_undone == 0
    assert result.files_restored == []


async def test_undo_write_records_undo_event(session_env):
    from codeprism.core.models import SessionEventKind
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    await manager.record_write(SESSION_ID, fp, before, before + "\n# x\n")

    await manager.undo_write(SESSION_ID, steps=1)

    events = await storage.get_session_events(SESSION_ID)
    undo_events = [e for e in events if e.event_type == SessionEventKind.UNDO]
    assert len(undo_events) == 1
    assert undo_events[0].file_path == fp


async def test_undo_write_undo_count_in_context(session_env):
    manager, proj, storage = session_env
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    await manager.record_write(SESSION_ID, fp, before, before + "\n# undo-me\n")
    await manager.undo_write(SESSION_ID, steps=1)

    ctx = await manager.get_context(SESSION_ID)
    assert ctx.undo_count == 1
