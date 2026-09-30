"""Tests for `codeprism setup` — config writing and idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from codeprism.cli import (
    _setup,
    _write_claude_config,
    _write_cursor_config,
    _write_windsurf_config,
    _write_zed_config,
)


def _server(tmp_path: Path) -> dict:
    return {"command": "codeprism", "args": ["serve", str(tmp_path)]}


# ── claude ────────────────────────────────────────────────────────────────────


def test_claude_writes_project_mcp_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    entry = cfg["mcpServers"]["codeprism"]
    assert entry["type"] == "stdio"
    assert entry["command"] == "codeprism"
    assert str(tmp_path) in entry["args"]


def test_claude_never_writes_mcp_servers_to_settings_json(tmp_path, monkeypatch):
    # Claude Code does not read MCP servers from .claude/settings.json
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)

    settings = tmp_path / ".claude" / "settings.json"
    assert not settings.exists() or "mcpServers" not in json.loads(settings.read_text())


def test_claude_pre_approves_server_in_local_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)
    _write_claude_config(_server(tmp_path), global_=False)

    local = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert local["enabledMcpjsonServers"] == ["codeprism"]


def test_claude_removes_stale_settings_json_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "mcpServers": {"codeprism": {"command": "codeprism"}},
                "permissions": {"allow": ["mcp__codeprism__get_context"]},
            }
        )
    )

    _write_claude_config(_server(tmp_path), global_=False)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "mcpServers" not in settings
    assert settings["permissions"]["allow"] == ["mcp__codeprism__get_context"]


def test_claude_writes_claude_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    assert "codeprism-instructions" in claude_md.read_text()


def test_claude_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)
    _write_claude_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert len(cfg["mcpServers"]) == 1


def test_claude_preserves_existing_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    _write_claude_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert set(cfg["mcpServers"]) == {"other", "codeprism"}


def test_claude_global_writes_user_scope_in_claude_json(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"numStartups": 7, "projects": {"/x": {}}}))
    monkeypatch.setattr(Path, "home", lambda: home)
    project = tmp_path / "proj"
    project.mkdir()

    _write_claude_config(_server(project), global_=True, project_dir=project)

    cfg = json.loads((home / ".claude.json").read_text())
    assert cfg["mcpServers"]["codeprism"]["command"] == "codeprism"
    assert cfg["numStartups"] == 7 and cfg["projects"] == {"/x": {}}  # untouched
    assert not (project / ".mcp.json").exists()


def test_invalid_json_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".mcp.json").write_text("{ not json")

    with pytest.raises(typer.Exit):
        _write_claude_config(_server(tmp_path), global_=False)
    assert (tmp_path / ".mcp.json").read_text() == "{ not json"


def test_setup_writes_into_project_dir_not_cwd(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    project = tmp_path / "proj"
    elsewhere.mkdir()
    project.mkdir()
    monkeypatch.chdir(elsewhere)

    _setup("claude", str(project), False)
    _setup("cursor", str(project), False)

    assert (project / ".mcp.json").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / ".cursor" / "mcp.json").exists()
    assert list(elsewhere.iterdir()) == []


def test_claude_md_not_duplicated_on_rerun(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)
    _write_claude_config(_server(tmp_path), global_=False)

    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.count("codeprism-instructions") == 2  # open + close marker, not duplicated block


# ── cursor ────────────────────────────────────────────────────────────────────


def test_cursor_writes_mcp_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cursor_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert "codeprism" in cfg["mcpServers"]


def test_cursor_writes_agents_md(tmp_path, monkeypatch):
    # Cursor reads AGENTS.md natively; the legacy .cursorrules is no longer created
    monkeypatch.chdir(tmp_path)
    _write_cursor_config(_server(tmp_path), global_=False)

    assert "CodePrism" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert not (tmp_path / ".cursorrules").exists()


def test_cursor_preserves_existing_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "other"}}})
    )

    _write_cursor_config(_server(tmp_path), global_=False)

    cfg = json.loads((config_dir / "mcp.json").read_text())
    assert "other" in cfg["mcpServers"]
    assert "codeprism" in cfg["mcpServers"]


# ── windsurf ──────────────────────────────────────────────────────────────────


def test_windsurf_writes_mcp_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_windsurf_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".windsurf" / "mcp_config.json").read_text())
    assert "codeprism" in cfg["mcpServers"]


# ── zed ───────────────────────────────────────────────────────────────────────


def test_zed_writes_context_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_zed_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".zed" / "settings.json").read_text())
    assert "codeprism" in cfg["context_servers"]
    assert cfg["context_servers"]["codeprism"]["command"]["path"] == "codeprism"


# ── _setup dispatch ───────────────────────────────────────────────────────────


def test_setup_unknown_agent_raises_exit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        _setup("unknown-agent", str(tmp_path), False)


def test_setup_claude_dispatches_correctly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup("claude", str(tmp_path), False)

    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert "codeprism" in cfg["mcpServers"]


def test_setup_cursor_dispatches_correctly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup("cursor", str(tmp_path), False)

    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert "codeprism" in cfg["mcpServers"]
