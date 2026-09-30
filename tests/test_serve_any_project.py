"""`codeprism serve` without a path serves the enclosing project and indexes it itself."""

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import codeprism.core.paths as paths
import codeprism.mcp.server as server
from codeprism.cli import _setup, app
from codeprism.core.paths import find_project_root


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", lambda: h)
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path / "data")
    return h


def _repo(parent: Path, name="repo") -> Path:
    repo = parent / name
    (repo / ".git").mkdir(parents=True)
    (repo / "pkg").mkdir()
    (repo / "pkg" / "core.py").write_text("def compute():\n    return 1\n")
    return repo


# ── project-root discovery ───────────────────────────────────────────────────


def test_root_found_from_subdirectory(home):
    repo = _repo(home / "code")
    assert find_project_root(repo / "pkg") == repo.resolve()


def test_codeprism_toml_marks_a_project(home):
    proj = home / "code" / "proj"
    proj.mkdir(parents=True)
    (proj / ".codeprism.toml").write_text("[codeprism]\n")
    assert find_project_root(proj) == proj.resolve()


def test_git_worktree_file_marks_a_project(home):
    wt = home / "code" / "wt"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere\n")
    assert find_project_root(wt) == wt.resolve()


def test_home_directory_is_never_a_project(home):
    (home / ".git").mkdir()  # e.g. a dotfiles repo in ~
    (home / "notes").mkdir()
    assert find_project_root(home) is None
    assert find_project_root(home / "notes") is None


# ── serve argument resolution ────────────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        server, "configure", lambda p, auto_index=False: calls.update(p=p, auto=auto_index)
    )
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: None)
    return calls


def test_serve_without_path_uses_enclosing_project(home, captured, monkeypatch):
    repo = _repo(home / "code")
    monkeypatch.chdir(repo / "pkg")
    assert CliRunner().invoke(app, ["serve"]).exit_code == 0
    assert captured == {"p": str(repo.resolve()), "auto": True}


def test_serve_outside_a_project_never_auto_indexes(home, captured, monkeypatch):
    monkeypatch.chdir(home)
    assert CliRunner().invoke(app, ["serve"]).exit_code == 0
    assert captured["auto"] is False


def test_serve_explicit_path_and_opt_out(home, captured, tmp_path):
    assert CliRunner().invoke(app, ["serve", str(tmp_path), "--no-auto-index"]).exit_code == 0
    assert captured == {"p": str(tmp_path), "auto": False}


# ── background indexing at startup ───────────────────────────────────────────


async def test_server_indexes_project_in_background(home):
    repo = _repo(home / "code")
    server.configure(str(repo), auto_index=True)
    try:
        async with server._lifespan(server.mcp):
            for _ in range(200):
                if server._index_status != "indexing":
                    break
                await asyncio.sleep(0.05)
            stats = await server.get_graph_stats()
            assert stats["index_status"] == "ready"
            assert stats["file_count"] == 1
            assert stats["function_count"] >= 1
    finally:
        server.configure(".", auto_index=False)


async def test_server_without_auto_index_leaves_index_alone(home):
    repo = _repo(home / "code")
    server.configure(str(repo), auto_index=False)
    try:
        async with server._lifespan(server.mcp):
            await asyncio.sleep(0.2)
            stats = await server.get_graph_stats()
            assert stats["index_status"] == "off"
            assert stats["file_count"] == 0
    finally:
        server.configure(".", auto_index=False)


# ── global setup writes a path-less command ─────────────────────────────────


def test_global_claude_setup_serves_every_project(home, tmp_path):
    proj = _repo(tmp_path)
    _setup("claude", str(proj), True)
    entry = json.loads((home / ".claude.json").read_text())["mcpServers"]["codeprism"]
    assert entry["args"] == ["serve"]
    assert (proj / "AGENTS.md").exists()


def test_global_codex_setup_serves_every_project(home, tmp_path):
    import tomllib

    proj = _repo(tmp_path)
    _setup("codex", str(proj), True)
    cfg = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["mcp_servers"]["codeprism"]["args"] == ["serve"]


def test_project_scope_setup_still_pins_the_project(home, tmp_path):
    proj = _repo(tmp_path)
    _setup("claude", str(proj), False)
    entry = json.loads((proj / ".mcp.json").read_text())["mcpServers"]["codeprism"]
    assert entry["args"] == ["serve", str(proj.resolve())]
