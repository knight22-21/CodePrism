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


def test_claude_writes_settings_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_claude_config(_server(tmp_path), global_=False)

    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert cfg["mcpServers"]["codeprism"]["command"] == "codeprism"
    assert str(tmp_path) in cfg["mcpServers"]["codeprism"]["args"]


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

    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert len(cfg["mcpServers"]) == 1


def test_claude_preserves_existing_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "other"}}})
    )

    _write_claude_config(_server(tmp_path), global_=False)

    cfg = json.loads((config_dir / "settings.json").read_text())
    assert "other" in cfg["mcpServers"]
    assert "codeprism" in cfg["mcpServers"]


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


def test_cursor_writes_cursorrules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cursor_config(_server(tmp_path), global_=False)

    cursorrules = tmp_path / ".cursorrules"
    assert cursorrules.exists()
    assert "CodePrism" in cursorrules.read_text()


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

    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "codeprism" in cfg["mcpServers"]


def test_setup_cursor_dispatches_correctly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup("cursor", str(tmp_path), False)

    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert "codeprism" in cfg["mcpServers"]
