"""Watchdog-based file watcher with debounce, bridged to asyncio."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..core.gitignore import IgnoreChecker
from ..core.languages import ALL_EXTENSIONS
from .incremental_updater import IncrementalUpdater, UpdateResult

_WATCH_EXTENSIONS = ALL_EXTENSIONS


def _default_skip_dirs() -> frozenset[str]:
    from .project_indexer import _DEFAULT_IGNORE

    return _DEFAULT_IGNORE


_SKIP_DIRS = _default_skip_dirs()

UpdateCallback = Callable[[str, UpdateResult], None]


class _FileEventHandler(FileSystemEventHandler):
    """Watchdog handler that pushes file paths onto an asyncio queue."""

    def __init__(
        self,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        extensions: frozenset[str],
        ignored: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._extensions = extensions
        self._ignored = ignored or (lambda _p: False)

    def _accepts(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in self._extensions:
            return False
        if set(p.parts) & _SKIP_DIRS:
            return False
        return not self._ignored(path)

    def _push(self, path: str) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._accepts(str(event.src_path)):
            self._push(str(event.src_path))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._accepts(str(event.src_path)):
            self._push(str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src, dst = str(event.src_path), str(event.dest_path)
            if self._accepts(src):
                self._push(src)
            if self._accepts(dst):
                self._push(dst)

    def on_deleted(self, event: FileSystemEvent) -> None:
        # A deleted file can't be checked against .gitignore reliably; only the
        # extension/dir filters apply, and removing an unindexed path is a no-op.
        if not event.is_directory:
            p = Path(str(event.src_path))
            if p.suffix.lower() in self._extensions and not (set(p.parts) & _SKIP_DIRS):
                self._push(str(event.src_path))


class ProjectWatcher:
    """Watches a project directory and feeds changes into an IncrementalUpdater.

    Debounces rapid save storms (e.g. formatter writes) so each file is
    processed once after it has been stable for *debounce_ms* milliseconds.

    Usage::

        async with asyncio.TaskGroup() as tg:
            tg.create_task(watcher.run("/path/to/project"))
    """

    def __init__(
        self,
        updater: IncrementalUpdater,
        debounce_ms: int = 500,
        on_update: UpdateCallback | None = None,
        respect_gitignore: bool = True,
    ) -> None:
        self._updater = updater
        self._debounce_ms = debounce_ms
        self._on_update = on_update
        self._respect_gitignore = respect_gitignore
        self._observer: Observer | None = None

    async def run(self, project_path: str) -> None:
        """Watch *project_path* forever; cancel the coroutine to stop."""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        checker = IgnoreChecker(project_path) if self._respect_gitignore else None
        handler = _FileEventHandler(
            queue, loop, _WATCH_EXTENSIONS, checker.is_ignored if checker else None
        )
        observer = Observer()
        observer.schedule(handler, project_path, recursive=True)
        observer.start()
        self._observer = observer

        debounce = self._debounce_ms / 1000.0
        poll_interval = debounce / 4.0

        try:
            pending: dict[str, float] = {}
            while True:
                # Drain the queue without blocking
                try:
                    while True:
                        path = queue.get_nowait()
                        pending[path] = loop.time()
                except asyncio.QueueEmpty:
                    pass

                # Flush events that have been stable for debounce_ms
                now = loop.time()
                ready = [p for p, t in list(pending.items()) if now - t >= debounce]
                for path in ready:
                    del pending[path]
                    try:
                        result = await self._updater.update_file(path)
                        if self._on_update and not result.skipped:
                            self._on_update(path, result)
                    except Exception:
                        pass  # individual file errors must not crash the watcher

                await asyncio.sleep(poll_interval)
        finally:
            observer.stop()
            observer.join()
            self._observer = None

    def stop(self) -> None:
        """Synchronously stop the watchdog observer (call from outside the loop)."""
        if self._observer:
            self._observer.stop()
