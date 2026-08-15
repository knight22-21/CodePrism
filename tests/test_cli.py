"""CLI tests using Typer's CliRunner (sync, subprocess-free)."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeprism.cli import app

PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Copy the sample project to a fresh temp dir and index it."""
    proj = tmp_path / "project"
    shutil.copytree(PYTHON_FIXTURE, proj)
    # Index via CLI
    result = runner.invoke(app, ["index", str(proj), "--languages", "python"])
    assert result.exit_code == 0, result.output
    return proj


# ── index ─────────────────────────────────────────────────────────────────────


def test_index_exits_zero(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("def hello(): pass\n")
    result = runner.invoke(app, ["index", str(proj), "--languages", "python"])
    assert result.exit_code == 0


def test_index_reports_file_count(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("def hello(): pass\n")
    result = runner.invoke(app, ["index", str(proj), "--languages", "python"])
    assert "file" in result.output.lower() or "Done" in result.output


def test_index_fixture_project(project):
    # project is already indexed in the fixture; re-running should succeed
    result = runner.invoke(app, ["index", str(project), "--languages", "python"])
    assert result.exit_code == 0


# ── stats ─────────────────────────────────────────────────────────────────────


def test_stats_exits_zero(project):
    result = runner.invoke(app, ["stats", "--project", str(project)])
    assert result.exit_code == 0


def test_stats_shows_file_count(project):
    result = runner.invoke(app, ["stats", "--project", str(project)])
    assert "Files" in result.output or "file" in result.output.lower()


def test_stats_verbose(project):
    result = runner.invoke(app, ["stats", "--verbose", "--project", str(project)])
    assert result.exit_code == 0


# ── search ────────────────────────────────────────────────────────────────────


def test_search_finds_symbol(project):
    result = runner.invoke(
        app, ["search", "compute", "--project", str(project)]
    )
    assert result.exit_code == 0
    assert "compute_checksum" in result.output


def test_search_no_match(project):
    result = runner.invoke(
        app, ["search", "zzz_no_match_xyz", "--project", str(project)]
    )
    assert result.exit_code == 0
    assert "No matches" in result.output


def test_search_kind_filter(project):
    result = runner.invoke(
        app, ["search", "", "--kind", "class", "--project", str(project)]
    )
    assert result.exit_code == 0


# ── context ───────────────────────────────────────────────────────────────────


def test_context_found(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["context", f"{proc}::compute_checksum", "--project", str(project)]
    )
    assert result.exit_code == 0
    assert "compute_checksum" in result.output


def test_context_missing_symbol(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["context", f"{proc}::no_such_fn", "--project", str(project)]
    )
    assert result.exit_code != 0 or "Not found" in result.output


def test_context_bad_format(project):
    result = runner.invoke(
        app, ["context", "no_double_colon_here", "--project", str(project)]
    )
    # Should show error
    assert result.exit_code != 0 or "Error" in result.output


# ── impact ────────────────────────────────────────────────────────────────────


def test_impact_found(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["impact", f"{proc}::compute_checksum", "--project", str(project)]
    )
    assert result.exit_code == 0
    assert "severity" in result.output.lower() or "Impact" in result.output


def test_impact_missing(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["impact", f"{proc}::no_fn_xyz", "--project", str(project)]
    )
    assert result.exit_code != 0 or "Not found" in result.output


# ── summary ───────────────────────────────────────────────────────────────────


def test_summary_found(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["summary", proc, "--project", str(project)]
    )
    assert result.exit_code == 0
    assert "processor" in result.output.lower()


def test_summary_missing(project):
    result = runner.invoke(
        app, ["summary", "/no/such/file.py", "--project", str(project)]
    )
    assert result.exit_code != 0 or "Not found" in result.output


# ── callers ───────────────────────────────────────────────────────────────────


def test_callers_found(project):
    proc = str(project / "processor.py")
    result = runner.invoke(
        app, ["callers", f"{proc}::compute_checksum", "--project", str(project)]
    )
    assert result.exit_code == 0
