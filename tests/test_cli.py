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


# ── setup ─────────────────────────────────────────────────────────────────────


def test_setup_claude_creates_settings(tmp_path):
    """setup claude writes .claude/settings.json in CWD."""
    import os
    import json

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["setup", "claude", "--project", str(tmp_path)])
        assert result.exit_code == 0, result.output
        cfg_file = tmp_path / ".claude" / "settings.json"
        assert cfg_file.exists()
        data = json.loads(cfg_file.read_text())
        assert "codeprism" in data["mcpServers"]
        assert data["mcpServers"]["codeprism"]["command"] == "codeprism"
    finally:
        os.chdir(orig)


def test_setup_claude_merges_existing_servers(tmp_path):
    """setup claude merges into an existing settings.json without overwriting."""
    import os
    import json

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        dot_claude = tmp_path / ".claude"
        dot_claude.mkdir()
        existing = {"mcpServers": {"other-tool": {"command": "other"}}}
        (dot_claude / "settings.json").write_text(json.dumps(existing))

        runner.invoke(app, ["setup", "claude", "--project", str(tmp_path)])

        data = json.loads((dot_claude / "settings.json").read_text())
        assert "other-tool" in data["mcpServers"]
        assert "codeprism" in data["mcpServers"]
    finally:
        os.chdir(orig)


def test_setup_cursor_creates_mcp_json(tmp_path):
    """setup cursor writes .cursor/mcp.json."""
    import os
    import json

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["setup", "cursor", "--project", str(tmp_path)])
        assert result.exit_code == 0, result.output
        cfg_file = tmp_path / ".cursor" / "mcp.json"
        assert cfg_file.exists()
        data = json.loads(cfg_file.read_text())
        assert "codeprism" in data["mcpServers"]
    finally:
        os.chdir(orig)


def test_setup_unknown_agent_exits_nonzero(tmp_path):
    """setup with an unsupported agent name exits non-zero."""
    result = runner.invoke(app, ["setup", "unknown-agent-xyz"])
    assert result.exit_code != 0


# ── scan ──────────────────────────────────────────────────────────────────────

SECURITY_FIXTURES = Path(__file__).parent / "fixtures" / "sample_security_issues"


def test_scan_clean_file_exits_zero(tmp_path):
    clean = SECURITY_FIXTURES / "clean_example.py"
    result = runner.invoke(app, ["scan", str(clean)])
    assert result.exit_code == 0


def test_scan_shows_pass_for_clean_file(tmp_path):
    clean = SECURITY_FIXTURES / "clean_example.py"
    result = runner.invoke(app, ["scan", str(clean)])
    assert "PASS" in result.output


def test_scan_secrets_file_exits_nonzero():
    """A BLOCK-level finding causes exit code 2."""
    result = runner.invoke(app, ["scan", str(SECURITY_FIXTURES / "secrets_example.py")])
    assert result.exit_code == 2


def test_scan_secrets_shows_block():
    result = runner.invoke(app, ["scan", str(SECURITY_FIXTURES / "secrets_example.py")])
    assert "BLOCK" in result.output


def test_scan_crypto_shows_warn():
    result = runner.invoke(app, ["scan", str(SECURITY_FIXTURES / "crypto_example.py")])
    assert "WARN" in result.output or "INFO" in result.output


def test_scan_missing_file_exits_nonzero():
    result = runner.invoke(app, ["scan", "/no/such/file_xyz123.py"])
    assert result.exit_code != 0


def test_scan_all_exits_zero(project):
    result = runner.invoke(app, ["scan", ".", "--all", "--project", str(project)])
    assert result.exit_code == 0


def test_scan_all_shows_scan_complete(project):
    result = runner.invoke(app, ["scan", ".", "--all", "--project", str(project)])
    assert "Scan complete" in result.output
