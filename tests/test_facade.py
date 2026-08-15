"""Tests for the CodePrism high-level façade (spec §7 Python library API)."""

import shutil
from pathlib import Path

import pytest

from codeprism import CodePrism

PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"


@pytest.fixture
async def prism(tmp_path: Path):
    """Indexed CodePrism instance for the sample project."""
    proj = tmp_path / "project"
    shutil.copytree(PYTHON_FIXTURE, proj)
    async with CodePrism(str(proj)) as p:
        await p.index()
        yield p, proj


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def test_prism_initializes(prism):
    p, _ = prism
    assert p.engine is not None


async def test_prism_get_context(prism):
    p, proj = prism
    result = await p.get_context(str(proj / "processor.py"), "compute_checksum")
    assert result is not None
    assert result.symbol.name == "compute_checksum"


async def test_prism_get_impact(prism):
    p, proj = prism
    result = await p.get_impact(str(proj / "processor.py"), "compute_checksum")
    assert result is not None
    assert result.severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


async def test_prism_get_module_summary(prism):
    p, proj = prism
    result = await p.get_module_summary(str(proj / "processor.py"))
    assert result is not None
    assert result.purpose != ""


# ── Session API (spec §7) ─────────────────────────────────────────────────────


async def test_session_record_read(prism):
    p, proj = prism
    session = p.session("sess-facade-001")
    fp = str(proj / "processor.py")
    await session.record_read(fp, "compute_checksum")

    ctx = await session.get_context()
    assert ctx.read_count == 1
    assert any("compute_checksum" in r for r in ctx.files_read)


async def test_session_record_write_returns_report(prism):
    p, proj = prism
    session = p.session("sess-facade-002")
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    report = await session.record_write(fp, before, before + "\n# facade test\n")
    assert "status" in report
    assert report["status"] == "PASS"


async def test_session_get_context_summary(prism):
    p, proj = prism
    session = p.session("sess-facade-003")
    ctx = await session.get_context()
    assert isinstance(ctx.summary, str)
    assert "sess-facade-003" in ctx.summary


async def test_session_undo(prism):
    p, proj = prism
    session = p.session("sess-facade-004")
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    marker = "\n# undo-me\n"
    await session.record_write(fp, before, before + marker)
    assert marker.strip() in Path(fp).read_text(encoding="utf-8")

    result = await session.undo(steps=1)
    assert result.steps_undone == 1
    assert marker.strip() not in Path(fp).read_text(encoding="utf-8")


async def test_session_write_with_secret_returns_block(prism):
    p, proj = prism
    session = p.session("sess-facade-005")
    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    secret_line = '\nSECRET_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234"\n'
    report = await session.record_write(fp, before, before + secret_line)
    assert report["status"] == "BLOCK"
    assert len(report["issues"]) >= 1
    # Restore
    Path(fp).write_text(before, encoding="utf-8")


async def test_multiple_sessions_isolated(prism):
    p, proj = prism
    s1 = p.session("sess-A")
    s2 = p.session("sess-B")
    fp = str(proj / "processor.py")
    await s1.record_read(fp, "compute_checksum")
    await s2.record_read(fp, "process")

    ctx1 = await s1.get_context()
    ctx2 = await s2.get_context()
    assert ctx1.read_count == 1
    assert ctx2.read_count == 1
    assert ctx1.session_id == "sess-A"
    assert ctx2.session_id == "sess-B"
