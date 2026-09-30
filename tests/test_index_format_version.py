"""An index written by an older format is rebuilt instead of trusted by checksum."""

import codeprism.core.storage as storage_mod
from codeprism.core.config import CodePrismConfig
from codeprism.core.storage import INDEX_FORMAT_VERSION
from codeprism.indexer.project_indexer import ProjectIndexer

CONFIG = CodePrismConfig(languages=["python"])


def _project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a():\n    return 1\n")
    (project / "b.py").write_text("def b():\n    return a()\n")
    return project


async def test_fresh_index_is_stamped_with_current_format(storage, graph, tmp_path):
    result = await ProjectIndexer(graph, storage, CONFIG).index(str(_project(tmp_path)))
    assert result.format_upgraded is False
    assert await storage.get_index_format_version() == INDEX_FORMAT_VERSION
    assert await storage.index_is_outdated() is False


async def test_empty_database_is_not_outdated(storage):
    assert await storage.get_index_format_version() == 0
    assert await storage.index_is_outdated() is False


async def test_legacy_index_is_fully_reparsed_once(storage, graph, tmp_path):
    project = _project(tmp_path)
    indexer = ProjectIndexer(graph, storage, CONFIG)
    await indexer.index(str(project))
    await storage.set_index_format_version(0)  # simulate a pre-versioning index

    upgraded = await indexer.index(str(project))
    assert upgraded.format_upgraded is True
    assert upgraded.files_skipped == 0  # checksums matched, but everything re-parsed
    assert await storage.get_index_format_version() == INDEX_FORMAT_VERSION

    again = await indexer.index(str(project))
    assert again.format_upgraded is False
    assert again.files_skipped == again.file_count == 2


async def test_format_bump_marks_existing_index_outdated(storage, graph, tmp_path, monkeypatch):
    await ProjectIndexer(graph, storage, CONFIG).index(str(_project(tmp_path)))
    monkeypatch.setattr(storage_mod, "INDEX_FORMAT_VERSION", INDEX_FORMAT_VERSION + 1)
    assert await storage.index_is_outdated() is True


async def test_version_survives_reopening_the_database(tmp_path, graph):
    db = tmp_path / "persist.db"
    first = storage_mod.StorageManager(db)
    await first.initialize()
    await ProjectIndexer(graph, first, CONFIG).index(str(_project(tmp_path)))
    await first.close()

    reopened = storage_mod.StorageManager(db)
    await reopened.initialize()
    try:
        assert await reopened.get_index_format_version() == INDEX_FORMAT_VERSION
    finally:
        await reopened.close()
