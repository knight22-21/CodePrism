"""Process-pool parsing must produce exactly what the in-process path produces."""

import shutil
from pathlib import Path

import codeprism.indexer.project_indexer as pi
from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.storage import StorageManager
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.parser.registry import ParserRegistry

FIXTURES = Path(__file__).parent / "fixtures"


async def _snapshot(storage):
    return (
        sorted((f.path, f.checksum) for f in await storage.get_all_files()),
        sorted((s.id, s.name, s.kind, s.line_start) for s in await storage.get_all_symbols()),
        sorted((e.id, e.kind, e.from_id, e.to_id) for e in await storage.get_all_edges()),
    )


async def _index(db_path, project, config, force=False):
    storage = StorageManager(db_path)
    await storage.initialize()
    try:
        result = await ProjectIndexer(GraphEngine(), storage, config).index(str(project), force)
        return result, await _snapshot(storage)
    finally:
        await storage.close()


def _project(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES, project)
    return project


async def test_process_pool_matches_threads(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(pi, "_POOL_MIN_FILES", 1)

    async def no_threads(*args, **kwargs):
        raise AssertionError("pooled run fell back to the thread path")

    with monkeypatch.context() as m:
        m.setattr(ProjectIndexer, "_parse_in_threads", no_threads)
        pooled, pooled_snap = await _index(
            tmp_path / "p.db", project, CodePrismConfig(parse_workers=2)
        )
    threaded, threaded_snap = await _index(
        tmp_path / "t.db", project, CodePrismConfig(parse_workers=1)
    )

    assert pooled.errors == threaded.errors == []
    assert pooled_snap == threaded_snap
    assert pooled_snap[1], "fixtures should produce symbols"


async def test_process_pool_skips_unchanged_files(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(pi, "_POOL_MIN_FILES", 1)
    config = CodePrismConfig(parse_workers=2)
    storage = StorageManager(tmp_path / "s.db")
    await storage.initialize()
    try:
        indexer = ProjectIndexer(GraphEngine(), storage, config)
        first = await indexer.index(str(project))
        second = await indexer.index(str(project))
        assert first.files_skipped == 0
        assert second.files_skipped == second.file_count > 0
    finally:
        await storage.close()


def test_pool_is_not_used_for_small_projects_or_custom_registries():
    # library default is in-process, even for huge projects
    assert not ProjectIndexer(None, None)._use_process_pool(10_000)
    auto = ProjectIndexer(None, None, CodePrismConfig(parse_workers=0))
    assert not auto._use_process_pool(pi._POOL_MIN_FILES - 1)
    assert ProjectIndexer(None, None, CodePrismConfig(parse_workers=4))._use_process_pool(10_000)
    custom = ProjectIndexer(None, None, CodePrismConfig(parse_workers=4), ParserRegistry())
    assert not custom._use_process_pool(10_000)
    single = ProjectIndexer(None, None, CodePrismConfig(parse_workers=1))
    assert not single._use_process_pool(10_000)


async def test_broken_pool_falls_back_to_threads(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(pi, "_POOL_MIN_FILES", 1)

    class Broken:
        def __init__(self, *a, **k):
            raise OSError("process spawning not permitted")

    monkeypatch.setattr(pi, "ProcessPoolExecutor", Broken)
    result, snap = await _index(tmp_path / "b.db", project, CodePrismConfig(parse_workers=2))
    _, expected = await _index(tmp_path / "e.db", project, CodePrismConfig(parse_workers=1))
    assert result.errors == []
    assert snap == expected
