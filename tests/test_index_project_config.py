"""CLI and MCP indexing share project configuration and explicit overrides."""

import asyncio
import os
import shutil
import sqlite3
import subprocess
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from typer.testing import CliRunner

import codeprism.core.paths as paths
import codeprism.mcp.server as server
from codeprism.cli import app
from codeprism.core.config import CodePrismConfig
from codeprism.indexer.project_indexer import ProjectIndexer

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(params=["cli", "mcp"])
def entry_point(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
async def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    """Create an isolated Git project and keep all index data under tmp_path."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(server, "_engine", None)
    root = tmp_path / "project"
    (root / "vendor_gen").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("cache.py\n", encoding="utf-8")
    (root / "app.py").write_text("def main(): pass\n", encoding="utf-8")
    (root / "app.js").write_text("function main() {}\n", encoding="utf-8")
    (root / "cache.py").write_text("def cached(): pass\n", encoding="utf-8")
    (root / "vendor_gen" / "big.py").write_text("def generated(): pass\n", encoding="utf-8")
    (root / "vendor_gen" / "big.js").write_text("function generated() {}\n", encoding="utf-8")
    try:
        yield root
    finally:
        if server._engine is not None:
            await server._engine._storage.close()


async def _run_index(
    entry_point: str,
    project: Path,
    *,
    languages: list[str] | None = None,
    embeddings: bool | None = None,
) -> None:
    if entry_point == "cli":
        arguments = ["index", str(project)]
        if languages is not None:
            arguments += ["--languages", ",".join(languages)]
        if embeddings is not None:
            arguments.append("--embeddings" if embeddings else "--no-embeddings")
        result = await asyncio.to_thread(CliRunner().invoke, app, arguments)
        assert result.exit_code == 0, (result.output, result.exception)
    else:
        tool_arguments: dict[str, Any] = {}
        if languages is not None:
            tool_arguments["languages"] = languages
        if embeddings is not None:
            tool_arguments["embeddings"] = embeddings
        tool_result = await server.index_project(str(project), **tool_arguments)
        assert tool_result["success"], tool_result["errors"]


def _stored_paths(project: Path) -> set[str]:
    with closing(sqlite3.connect(paths.get_db_path(project))) as database:
        return {
            Path(row[0]).relative_to(project).as_posix()
            for row in database.execute("SELECT path FROM files")
        }


@pytest.mark.parametrize("respect_gitignore", [True, False])
async def test_project_filters_apply_to_each_entry_point(
    entry_point: str, project: Path, respect_gitignore: bool
) -> None:
    (project / ".codeprism.toml").write_text(
        '[codeprism]\nlanguages = ["python"]\n'
        f"respect_gitignore = {str(respect_gitignore).lower()}\n"
        '[codeprism.security]\nignore_paths = ["*/vendor_gen/*"]\n',
        encoding="utf-8",
    )

    await _run_index(entry_point, project)

    expected = {"app.py"} if respect_gitignore else {"app.py", "cache.py"}
    assert _stored_paths(project) == expected


async def test_explicit_languages_override_only_languages(entry_point: str, project: Path) -> None:
    (project / ".codeprism.toml").write_text(
        '[codeprism]\nlanguages = ["python"]\n'
        '[codeprism.security]\nignore_paths = ["*/vendor_gen/*"]\n',
        encoding="utf-8",
    )

    await _run_index(entry_point, project, languages=["javascript"])

    assert _stored_paths(project) == {"app.js"}


@pytest.mark.parametrize(
    ("configured", "override", "expected"),
    [(True, None, True), (True, False, False), (False, True, True), (False, None, False)],
)
async def test_embeddings_inherit_config_and_allow_explicit_override(
    entry_point: str,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
    override: bool | None,
    expected: bool,
) -> None:
    (project / ".codeprism.toml").write_text(
        f"[codeprism]\nenable_embeddings = {str(configured).lower()}\n"
        'languages = ["python"]\n'
        '[codeprism.embeddings]\nmodel = "configured-model"\ndevice = "configured-device"\n',
        encoding="utf-8",
    )
    calls: list[CodePrismConfig] = []

    async def record_embedding_config(
        indexer: ProjectIndexer, project_path: str, symbols: list[Any]
    ) -> None:
        # Configuration is the contract here; optional model downloads stay out of this test.
        calls.append(indexer._config)

    monkeypatch.setattr(ProjectIndexer, "_build_embeddings", record_embedding_config)

    await _run_index(entry_point, project, embeddings=override)

    assert bool(calls) is expected
    if expected:
        assert calls[0].embeddings.model == "configured-model"
        assert calls[0].embeddings.device == "configured-device"
    assert _stored_paths(project) == {"app.py", "vendor_gen/big.py"}


async def test_without_config_keeps_indexing_defaults(entry_point: str, project: Path) -> None:
    await _run_index(entry_point, project)

    assert _stored_paths(project) == {
        "app.py",
        "app.js",
        "vendor_gen/big.py",
        "vendor_gen/big.js",
    }


async def test_entry_points_keep_automatic_workers(
    entry_point: str, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / ".codeprism.toml").write_text("[codeprism]\nparse_workers = 9\n", encoding="utf-8")
    workers: list[int] = []
    original_index = ProjectIndexer.index

    async def capture_workers(indexer: ProjectIndexer, path: str, force: bool = False) -> Any:
        workers.append(indexer._config.parse_workers)
        return await original_index(indexer, path, force=force)

    monkeypatch.setattr(ProjectIndexer, "index", capture_workers)

    await _run_index(entry_point, project)

    assert workers == [0]
    assert CodePrismConfig().parse_workers == 1


@pytest.mark.parametrize("workers", [1, 3])
async def test_explicit_cli_workers_win(
    project: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    (project / ".codeprism.toml").write_text("[codeprism]\nparse_workers = 9\n", encoding="utf-8")
    observed: list[int] = []
    original_index = ProjectIndexer.index

    async def capture_workers(indexer: ProjectIndexer, path: str, force: bool = False) -> Any:
        observed.append(indexer._config.parse_workers)
        return await original_index(indexer, path, force=force)

    monkeypatch.setattr(ProjectIndexer, "index", capture_workers)
    result = await asyncio.to_thread(
        CliRunner().invoke, app, ["index", str(project), "--workers", str(workers)]
    )

    assert result.exit_code == 0, result.output
    assert observed == [workers]


async def test_invalid_config_fails_before_creating_index(entry_point: str, project: Path) -> None:
    (project / ".codeprism.toml").write_text(
        "[codeprism]\nrespect_gitignore = []\n", encoding="utf-8"
    )
    if entry_point == "cli":
        result = await asyncio.to_thread(CliRunner().invoke, app, ["index", str(project)])
        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)
        assert "respect_gitignore" in str(result.exception)
    else:
        with pytest.raises(ValueError, match="respect_gitignore"):
            await server.index_project(str(project))

    assert not paths.get_db_path(project).exists()


async def test_mcp_protocol_preserves_omitted_and_false_embeddings(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / ".codeprism.toml").write_text(
        '[codeprism]\nlanguages = ["python"]\nenable_embeddings = true\n'
        '[codeprism.security]\nignore_paths = ["*/vendor_gen/*"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_project_path", str(project))
    monkeypatch.setattr(server, "_auto_index", False)
    calls: list[bool] = []

    async def record_embeddings(
        indexer: ProjectIndexer, project_path: str, symbols: list[Any]
    ) -> None:
        calls.append(indexer._config.enable_embeddings)

    monkeypatch.setattr(ProjectIndexer, "_build_embeddings", record_embeddings)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools if tool.name == "index_project")
        schema = getattr(tool, "input_schema", None)
        if schema is None:  # MCP SDK v1 uses the original camelCase field.
            schema = tool.inputSchema
        assert schema["properties"]["embeddings"]["default"] is None
        try:
            inherited = await client.call_tool("index_project", {"path": str(project)})
            assert inherited.data["success"]
            assert inherited.data["file_count"] == 1
            assert calls == [True]

            disabled = await client.call_tool(
                "index_project", {"path": str(project), "embeddings": False}
            )
            assert disabled.data["success"]
            assert _stored_paths(project) == {"app.py"}
            assert calls == [True]
        finally:
            # index_project replaces the lifespan engine; close its storage explicitly.
            if server._engine is not None:
                await server._engine._storage.close()
