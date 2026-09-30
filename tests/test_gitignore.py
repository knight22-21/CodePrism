"""The indexer and watcher skip files git ignores."""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.core.gitignore import IgnoreChecker, git_listed_files
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.indexer.watcher import _FileEventHandler

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

CONFIG = CodePrismConfig(languages=["python"])


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "vendor_copy" / "lib").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("vendor_copy/\n*.gen.py\n!keep.gen.py\n")
    (repo / "src" / "app.py").write_text("def app():\n    return 1\n")
    (repo / "src" / "schema.gen.py").write_text("def generated():\n    return 1\n")
    (repo / "src" / "keep.gen.py").write_text("def kept():\n    return 1\n")
    (repo / "vendor_copy" / "lib" / "third_party.py").write_text("def vendored():\n    return 1\n")
    return repo


def _names(files):
    return sorted(Path(f).name for f in files)


def test_ignored_files_are_skipped(tmp_path):
    repo = _repo(tmp_path)
    files = ProjectIndexer(None, None, CONFIG)._find_source_files(str(repo))
    # untracked-but-not-ignored files are included; negation (!keep.gen.py) honoured
    assert _names(files) == ["app.py", "keep.gen.py"]


def test_opt_out_indexes_everything(tmp_path):
    repo = _repo(tmp_path)
    cfg = CodePrismConfig(languages=["python"], respect_gitignore=False)
    files = ProjectIndexer(None, None, cfg)._find_source_files(str(repo))
    assert _names(files) == ["app.py", "keep.gen.py", "schema.gen.py", "third_party.py"]


def test_explicitly_indexing_an_ignored_folder_still_works(tmp_path):
    repo = _repo(tmp_path)
    files = ProjectIndexer(None, None, CONFIG)._find_source_files(str(repo / "vendor_copy"))
    assert _names(files) == ["third_party.py"]


def test_outside_git_everything_is_walked(tmp_path, monkeypatch):
    # Stop git from discovering a repository above tmp_path (e.g. a home-folder repo)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("def a():\n    return 1\n")
    (plain / ".gitignore").write_text("a.py\n")  # no repo, so this means nothing
    assert git_listed_files(plain) is None
    assert _names(ProjectIndexer(None, None, CONFIG)._find_source_files(str(plain))) == ["a.py"]


async def test_reindex_purges_files_that_became_ignored(storage, graph, tmp_path):
    repo = _repo(tmp_path)
    cfg = CodePrismConfig(languages=["python"], respect_gitignore=False)
    await ProjectIndexer(graph, storage, cfg).index(str(repo))
    assert "vendored" in {s.name for s in await storage.get_all_symbols()}

    await ProjectIndexer(graph, storage, CONFIG).index(str(repo))
    names = {s.name for s in await storage.get_all_symbols()}
    assert "vendored" not in names and "generated" not in names
    assert {"app", "kept"} <= names


def test_ignore_checker(tmp_path):
    repo = _repo(tmp_path)
    checker = IgnoreChecker(repo)
    assert checker.enabled
    assert checker.is_ignored(repo / "vendor_copy" / "lib" / "third_party.py")
    assert checker.is_ignored(repo / "src" / "schema.gen.py")
    assert not checker.is_ignored(repo / "src" / "app.py")
    assert not checker.is_ignored(repo / "src" / "keep.gen.py")
    assert IgnoreChecker(tmp_path / "nowhere").enabled is False


def test_watcher_drops_ignored_and_skip_dir_events(tmp_path):
    repo = _repo(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        handler = _FileEventHandler(
            asyncio.Queue(), loop, frozenset({".py"}), IgnoreChecker(repo).is_ignored
        )
        assert handler._accepts(str(repo / "src" / "app.py"))
        assert not handler._accepts(str(repo / "vendor_copy" / "lib" / "third_party.py"))
        assert not handler._accepts(str(repo / "node_modules" / "x.py"))
        assert not handler._accepts(str(repo / "src" / "notes.txt"))
    finally:
        loop.close()
