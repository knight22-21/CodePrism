"""Visualization contracts using a real index and isolated output paths."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeprism.cli import app
from codeprism.core.models import NodeKind, SymbolRecord
from codeprism.core.paths import get_db_path
from codeprism.core.storage import StorageManager

runner = CliRunner()


@pytest.fixture
def visual_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Index two related functions without writing to the user's data directory."""
    monkeypatch.setattr("codeprism.core.paths.get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text(
        "def first():\n    return 1\n\ndef second():\n    return first()\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["index", str(project), "--languages", "python"])
    assert result.exit_code == 0, result.output
    return project


def test_visualize_embeds_the_indexed_graph(visual_project: Path, tmp_path: Path) -> None:
    """Write valid graph JSON with the indexed names and reported counts."""
    output = tmp_path / "view.html"
    result = runner.invoke(app, ["visualize", str(visual_project), "--out", str(output)])
    assert result.exit_code == 0, result.output
    html = output.read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    match = re.search(r"var RAW=(.*);", html)
    assert match is not None
    graph = json.loads(match.group(1))
    assert len(graph["nodes"]) == 3
    assert len(graph["links"]) == 3
    assert "3 nodes, 3 edges" in result.output
    assert {node["name"] for node in graph["nodes"]} == {
        "app.py",
        "first",
        "second",
    }
    calls = [link for link in graph["links"] if link["kind"] == "calls"]
    assert len(calls) == 1
    names = {node["id"]: node["name"] for node in graph["nodes"]}
    assert names[calls[0]["source"]] == "second"
    assert names[calls[0]["target"]] == "first"
    node_ids = {node["id"] for node in graph["nodes"]}
    assert all(link["source"] in node_ids and link["target"] in node_ids for link in graph["links"])


def test_visualize_default_filename(
    visual_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default output belongs to the caller's working directory."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["visualize", str(visual_project)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "graph.html").is_file()
    assert not (visual_project / "graph.html").exists()


def test_visualize_rejects_non_html_output(visual_project: Path, tmp_path: Path) -> None:
    """An invalid extension must not create an output file."""
    output = tmp_path / "view.json"
    result = runner.invoke(app, ["visualize", str(visual_project), "--out", str(output)])
    assert result.exit_code == 1
    assert "--out must have a .html extension" in result.output
    assert not output.exists()


def test_visualize_preserves_quoted_names(visual_project: Path, tmp_path: Path) -> None:
    """Embedding must preserve unusual names without breaking its enclosing script."""
    name = 'quoted "name" </script> café'

    async def add_symbol() -> None:
        storage = StorageManager(get_db_path(visual_project))
        await storage.initialize()
        try:
            file = await storage.get_file_by_path(str(visual_project / "app.py"))
            assert file is not None
            await storage.upsert_symbol(
                SymbolRecord.create(
                    file_path=file.path,
                    file_id=file.id,
                    name=name,
                    kind=NodeKind.VARIABLE,
                    line_start=1,
                    line_end=1,
                )
            )
        finally:
            await storage.close()

    asyncio.run(add_symbol())
    output = tmp_path / "names.html"
    result = runner.invoke(app, ["visualize", str(visual_project), "--out", str(output)])
    assert result.exit_code == 0, result.output
    html = output.read_text(encoding="utf-8")
    match = re.search(r"var RAW=(.*);", html)
    assert match is not None
    assert "</script>" not in match.group(1)
    assert name in {node["name"] for node in json.loads(match.group(1))["nodes"]}
