"""File-event filtering and real watcher updates with bounded waits."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
)

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.storage import StorageManager
from codeprism.indexer.incremental_updater import IncrementalUpdater, UpdateResult
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.indexer.watcher import ProjectWatcher, _FileEventHandler


def _handler(queue: asyncio.Queue[str]) -> _FileEventHandler:
    return _FileEventHandler(queue, asyncio.get_running_loop(), frozenset({".py"}))


async def _wait_for(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


@asynccontextmanager
async def _watching(
    updater: IncrementalUpdater,
    project: Path,
    updates: dict[str, UpdateResult],
    *,
    respect_gitignore: bool = False,
) -> AsyncIterator[tuple[ProjectWatcher, asyncio.Task[None]]]:
    watcher = ProjectWatcher(
        updater,
        debounce_ms=40,
        on_update=lambda path, result: updates.__setitem__(path, result),
        respect_gitignore=respect_gitignore,
    )
    task = asyncio.create_task(watcher.run(str(project)))
    observer = None
    try:
        await _wait_for(lambda: watcher._observer is not None or task.done())
        if task.done():
            await task
        observer = watcher._observer
        assert observer is not None and observer.is_alive()
        yield watcher, task
    finally:
        # run() owns observer.join(); always cancel it, including on assertion failures.
        task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert watcher._observer is None
        if observer is not None:
            assert not observer.is_alive()


@pytest.mark.parametrize(
    ("path", "accepted"),
    [
        ("src/app.py", True),
        ("src/APP.PY", True),
        ("src/node_modules_copy.py", True),
        ("src/notes.txt", False),
        ("src/no_extension", False),
        (".git/hooks/check.py", False),
        ("node_modules/package/app.py", False),
        ("src/__pycache__/app.py", False),
    ],
)
async def test_accepts_supported_paths_outside_skipped_directories(
    tmp_path: Path, path: str, accepted: bool
) -> None:
    """Path filtering is case-insensitive and checks whole directory components."""
    assert _handler(asyncio.Queue())._accepts(str(tmp_path / path)) is accepted


@pytest.mark.parametrize("event_type", [FileCreatedEvent, FileModifiedEvent, FileDeletedEvent])
async def test_file_events_enqueue_only_supported_paths(event_type: type[FileSystemEvent]) -> None:
    """Each file event crosses the asyncio bridge after extension/directory filtering."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    handler = _handler(queue)
    for path in ("/project/a.txt", "/project/.git/a.py", "/project/a.py"):
        handler.dispatch(event_type(path))
    assert await asyncio.wait_for(queue.get(), timeout=1) == "/project/a.py"
    assert queue.empty()


@pytest.mark.parametrize(
    "event",
    [
        DirCreatedEvent("/project/a.py"),
        DirModifiedEvent("/project/a.py"),
        DirDeletedEvent("/project/a.py"),
        DirMovedEvent("/project/a.py", "/project/b.py"),
    ],
)
async def test_directory_events_are_not_enqueued(event: FileSystemEvent) -> None:
    """Directories with source-looking names must not be sent to the updater."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    _handler(queue).dispatch(event)
    await asyncio.sleep(0)  # Let any incorrectly scheduled queue writes run before asserting.
    assert queue.empty()


async def test_moves_filter_source_and_destination_independently() -> None:
    """Renames into or out of supported extensions still update the supported side."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    handler = _handler(queue)
    handler.on_moved(FileMovedEvent("/project/a.py", "/project/a.txt"))
    handler.on_moved(FileMovedEvent("/project/b.txt", "/project/b.py"))
    handler.on_moved(FileMovedEvent("/project/c.py", "/project/d.py"))
    paths = [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(4)]
    assert paths == ["/project/a.py", "/project/b.py", "/project/c.py", "/project/d.py"]
    assert queue.empty()


async def test_ignored_files_are_filtered_except_for_deletion() -> None:
    """Deletion still removes stale records even when the ignore checker rejects a path."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    handler = _FileEventHandler(
        queue, asyncio.get_running_loop(), frozenset({".py"}), ignored=lambda path: True
    )
    path = "/project/generated.py"
    assert not handler._accepts(path)
    handler.on_created(FileCreatedEvent(path))
    handler.on_modified(FileModifiedEvent(path))
    handler.on_deleted(FileDeletedEvent(path))
    assert await asyncio.wait_for(queue.get(), timeout=1) == path
    assert queue.empty()


async def test_create_modify_delete_update_storage_and_graph(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> None:
    """Real filesystem events add, replace and remove the file's indexed symbols."""
    path = tmp_path / "app.py"
    updates: dict[str, UpdateResult] = {}
    async with _watching(IncrementalUpdater(graph, storage), tmp_path, updates):
        path.write_text("def original(): pass\n", encoding="utf-8")
        await _wait_for(lambda: str(path) in updates)
        original = next(s for s in await storage.get_all_symbols() if s.name == "original")
        assert graph.has_node(original.id)

        updates.clear()
        path.write_text("def replacement(): pass\n", encoding="utf-8")
        await _wait_for(lambda: str(path) in updates)
        symbols = await storage.get_all_symbols()
        assert {s.name for s in symbols} == {"replacement"}
        replacement = symbols[0]
        assert graph.has_node(replacement.id)
        assert not graph.has_node(original.id)

        updates.clear()
        path.unlink()
        await _wait_for(lambda: str(path) in updates)
        assert await storage.get_all_symbols() == []
        assert await storage.get_file_by_path(str(path)) is None
        assert not graph.has_node(replacement.id)


async def test_move_updates_both_paths(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> None:
    """A real rename removes the old file record and indexes symbols at the new path."""
    source, destination = tmp_path / "before.py", tmp_path / "after.py"
    source.write_text("def moved(): pass\n", encoding="utf-8")
    config = CodePrismConfig(languages=["python"], respect_gitignore=False)
    await ProjectIndexer(graph, storage, config).index(str(tmp_path))
    original = next(s for s in await storage.get_all_symbols() if s.name == "moved")
    updates: dict[str, UpdateResult] = {}
    async with _watching(IncrementalUpdater(graph, storage), tmp_path, updates):
        source.rename(destination)
        await _wait_for(lambda: {str(source), str(destination)} <= updates.keys())
        assert await storage.get_file_by_path(str(source)) is None
        moved_file = await storage.get_file_by_path(str(destination))
        assert moved_file is not None
        symbols = await storage.get_all_symbols()
        assert [(s.name, s.file_id) for s in symbols] == [("moved", moved_file.id)]
        assert graph.has_node(symbols[0].id)
        assert not graph.has_node(original.id)


async def test_unsupported_files_and_skipped_directories_are_not_indexed(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> None:
    """An accepted sentinel confirms the real watcher processes a batch of new files."""
    for directory in (".git", "node_modules", "__pycache__"):
        (tmp_path / directory).mkdir()
    ignored = [tmp_path / "notes.txt"] + [
        tmp_path / directory / "ignored.py" for directory in (".git", "node_modules", "__pycache__")
    ]
    updates: dict[str, UpdateResult] = {}
    async with _watching(IncrementalUpdater(graph, storage), tmp_path, updates):
        for path in ignored:
            path.write_text("def ignored(): pass\n", encoding="utf-8")
        sentinel = tmp_path / "sentinel.py"
        sentinel.write_text("def sentinel(): pass\n", encoding="utf-8")
        await _wait_for(lambda: str(sentinel) in updates)
        assert not set(map(str, ignored)) & updates.keys()
        assert {s.name for s in await storage.get_all_symbols()} == {"sentinel"}
        for path in ignored:
            assert await storage.get_file_by_path(str(path)) is None


async def test_stop_stops_observer_and_cancellation_finishes_run(
    storage: StorageManager, graph: GraphEngine, tmp_path: Path
) -> None:
    """stop() stops event delivery; cancelling run() joins and clears its observer."""
    updates: dict[str, UpdateResult] = {}
    async with _watching(
        IncrementalUpdater(graph, storage), tmp_path, updates, respect_gitignore=True
    ) as (watcher, task):
        observer = watcher._observer
        assert observer is not None
        watcher.stop()
        await _wait_for(lambda: not observer.is_alive())
    assert task.done()
    watcher.stop()
