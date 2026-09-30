"""`codeprism setup`: AGENTS.md is the shared guide; each agent gets the file it reads."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import typer

from codeprism.cli import _setup, _upsert_codex_server


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(tmp_path)
    return proj


def _agents_md(project: Path) -> str:
    return (project / "AGENTS.md").read_text(encoding="utf-8")


# ── AGENTS.md is the source of truth ─────────────────────────────────────────


@pytest.mark.parametrize("agent", ["claude", "codex", "cursor", "windsurf", "zed"])
def test_every_agent_gets_the_full_guide_in_agents_md(project, agent):
    _setup(agent, str(project), False)
    text = _agents_md(project)
    assert "get_context(file, symbol, depth=2)" in text
    assert text.count("<!-- codeprism-instructions -->") == 1


def test_claude_md_is_a_thin_import_of_agents_md(project):
    _setup("claude", str(project), False)
    claude = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "\n@AGENTS.md\n" in claude
    assert "get_context(file, symbol" not in claude  # no duplicated guide


def test_old_full_claude_md_block_is_replaced_and_user_content_kept(project):
    (project / "CLAUDE.md").write_text(
        "# My project\n\nRun `make test`.\n\n"
        "<!-- codeprism-instructions -->\n## CodePrism — old full guide\n"
        "get_context(file, symbol, depth=2)\n<!-- /codeprism-instructions -->\n",
        encoding="utf-8",
    )
    _setup("claude", str(project), False)
    claude = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Run `make test`." in claude
    assert "old full guide" not in claude
    assert "@AGENTS.md" in claude


def test_existing_agents_md_import_is_not_duplicated(project):
    (project / "CLAUDE.md").write_text("@AGENTS.md\n\n# Claude-only notes\n", encoding="utf-8")
    _setup("claude", str(project), False)
    _setup("claude", str(project), False)
    claude = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.count("@AGENTS.md") == 1


def test_setup_is_idempotent_for_agents_md(project):
    for _ in range(3):
        _setup("claude", str(project), False)
        _setup("cursor", str(project), False)
    assert _agents_md(project).count("<!-- codeprism-instructions -->") == 1


def test_user_content_in_agents_md_is_preserved(project):
    (project / "AGENTS.md").write_text("# Build\n\nUse uv.\n", encoding="utf-8")
    _setup("codex", str(project), False)
    text = _agents_md(project)
    assert text.startswith("# Build\n\nUse uv.")
    assert "get_context(file, symbol, depth=2)" in text


@pytest.mark.parametrize("agent", ["cursor", "windsurf", "zed", "continue"])
def test_non_claude_agents_do_not_get_a_claude_md(project, agent):
    _setup(agent, str(project), False)
    assert not (project / "CLAUDE.md").exists()


def test_cursor_no_longer_creates_legacy_cursorrules(project):
    _setup("cursor", str(project), False)
    assert not (project / ".cursorrules").exists()


def test_continue_gets_an_always_apply_rule(project):
    _setup("continue", str(project), False)
    rule = (project / ".continue" / "rules" / "codeprism.md").read_text(encoding="utf-8")
    assert rule.startswith("---\nname: CodePrism knowledge graph\nalwaysApply: true\n---\n")
    assert "get_context(file, symbol, depth=2)" in rule
    assert "<!-- codeprism-instructions -->" not in rule


# ── Codex ────────────────────────────────────────────────────────────────────


def _codex_cfg(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_codex_project_config(project):
    _setup("codex", str(project), False)
    cfg = _codex_cfg(project / ".codex" / "config.toml")
    assert cfg["mcp_servers"]["codeprism"] == {
        "command": "codeprism",
        "args": ["serve", str(project.resolve())],
    }


def test_codex_global_config(project):
    _setup("codex", str(project), True)
    cfg = _codex_cfg(Path.home() / ".codex" / "config.toml")
    assert cfg["mcp_servers"]["codeprism"]["command"] == "codeprism"
    assert not (project / ".codex").exists()
    assert (project / "AGENTS.md").exists()


def test_codex_keeps_other_settings_and_comments(project):
    cfg_file = project / ".codex" / "config.toml"
    cfg_file.parent.mkdir()
    cfg_file.write_text(
        '# my codex settings\nmodel = "gpt-5"\n\n'
        '[mcp_servers.context7]\ncommand = "npx"\nargs = ["-y", "@upstash/context7-mcp"]\n',
        encoding="utf-8",
    )
    _setup("codex", str(project), False)
    text = cfg_file.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    assert "# my codex settings" in text
    assert cfg["model"] == "gpt-5"
    assert set(cfg["mcp_servers"]) == {"context7", "codeprism"}


def test_codex_replaces_existing_entry_including_subtables(project):
    cfg_file = project / ".codex" / "config.toml"
    cfg_file.parent.mkdir()
    cfg_file.write_text(
        '[mcp_servers.codeprism]\ncommand = "old"\nargs = []\n\n'
        '[mcp_servers.codeprism.env]\nX = "1"\n\n[profiles.fast]\nmodel = "o4-mini"\n',
        encoding="utf-8",
    )
    _setup("codex", str(project), False)
    _setup("codex", str(project), False)
    text = cfg_file.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    assert cfg["mcp_servers"]["codeprism"]["command"] == "codeprism"
    assert "env" not in cfg["mcp_servers"]["codeprism"]
    assert cfg["profiles"]["fast"]["model"] == "o4-mini"
    assert text.count("[mcp_servers.codeprism]") == 1


def test_codex_windows_paths_round_trip():
    entry = {"command": "codeprism", "args": ["serve", r"C:\Users\me\My Repo"]}
    cfg = tomllib.loads(_upsert_codex_server("", entry))
    assert cfg["mcp_servers"]["codeprism"]["args"] == ["serve", r"C:\Users\me\My Repo"]


def test_codex_invalid_toml_is_left_untouched(project):
    cfg_file = project / ".codex" / "config.toml"
    cfg_file.parent.mkdir()
    cfg_file.write_text("model = \n[[[broken", encoding="utf-8")
    with pytest.raises(typer.Exit):
        _setup("codex", str(project), False)
    assert cfg_file.read_text(encoding="utf-8") == "model = \n[[[broken"


def test_codex_dotted_key_conflict_is_refused_not_mangled():
    # A top-level dotted key defining the same table can't be safely rewritten
    text = 'mcp_servers.codeprism.command = "old"\n'
    with pytest.raises((ValueError, tomllib.TOMLDecodeError)):
        _upsert_codex_server(text, {"command": "codeprism", "args": ["serve", "x"]})


def test_claude_setup_still_writes_mcp_json(project):
    _setup("claude", str(project), False)
    assert "codeprism" in json.loads((project / ".mcp.json").read_text())["mcpServers"]
