"""Session overlay — track agent reads/writes, enable undo, and compact context."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import SessionEvent, SessionEventKind
from ..core.storage import StorageManager
from ..indexer.incremental_updater import IncrementalUpdater


@dataclass
class SessionContext:
    """Compact session summary suitable for inclusion in an agent's context window."""

    session_id: str
    total_events: int = 0
    read_count: int = 0
    write_count: int = 0
    undo_count: int = 0
    files_read: list[str] = field(default_factory=list)   # "path::symbol"
    files_written: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class UndoResult:
    files_restored: list[str] = field(default_factory=list)
    steps_undone: int = 0


class SessionManager:
    """
    Records what an agent has read and written within a named session.

    Responsibilities:
    - Persist READ/WRITE/UNDO events to the session_events table
    - On WRITE: run security scan, flush new content to disk, propagate into graph
    - On UNDO: restore content_before from the journal and re-sync the graph
    - Expose a compact SessionContext for token-efficient context-window inclusion
    """

    def __init__(self, storage: StorageManager, updater: IncrementalUpdater) -> None:
        self._storage = storage
        self._updater = updater

    # ── Public API ────────────────────────────────────────────────────────────

    async def record_read(
        self,
        session_id: str,
        file_path: str,
        symbol_name: str,
    ) -> None:
        """Record that the agent read a symbol — prevents redundant re-fetches."""
        await self._storage.insert_session_event(
            SessionEvent(
                id=uuid.uuid4().hex,
                session_id=session_id,
                event_type=SessionEventKind.READ,
                file_path=file_path,
                symbol_name=symbol_name,
                created_at=time.time(),
            )
        )

    async def record_write(
        self,
        session_id: str,
        file_path: str,
        content_before: str,
        content_after: str,
    ) -> dict:
        """
        Log a file write, run the security scanner, flush to disk, and sync the graph.

        Returns a dict with status (PASS/WARN/BLOCK), issues[], and graph_update.
        A BLOCK status means the write contains a critical security issue — the
        caller should surface this to the user before proceeding.
        """
        from ..security.scanner import SecurityScanner

        scanner = SecurityScanner()
        report = scanner.scan_diff(content_before, content_after, file_path)

        await self._storage.insert_session_event(
            SessionEvent(
                id=uuid.uuid4().hex,
                session_id=session_id,
                event_type=SessionEventKind.WRITE,
                file_path=file_path,
                content_before=content_before,
                content_after=content_after,
                security_report=json.dumps(report.to_dict()),
                created_at=time.time(),
            )
        )

        if report.status != "BLOCK":
            # Only flush to disk when the security gate passes or warns.
            Path(file_path).write_text(content_after, encoding="utf-8")
            update = await self._updater.update_file(file_path)
            graph_update = {
                "nodes_added": update.nodes_added,
                "nodes_removed": update.nodes_removed,
                "edges_updated": update.edges_updated,
            }
        else:
            graph_update = {"nodes_added": 0, "nodes_removed": 0, "edges_updated": 0}

        return {**report.to_dict(), "graph_update": graph_update}

    async def get_context(self, session_id: str) -> SessionContext:
        """Return a compact summary of all reads and writes in this session."""
        events = await self._storage.get_session_events(session_id)

        reads = [e for e in events if e.event_type == SessionEventKind.READ]
        writes = [e for e in events if e.event_type == SessionEventKind.WRITE]
        undos = [e for e in events if e.event_type == SessionEventKind.UNDO]

        files_read = [
            f"{e.file_path}::{e.symbol_name}" if e.symbol_name else str(e.file_path)
            for e in reads
        ]
        files_written = list({e.file_path for e in writes if e.file_path})
        unique_read_files = len({e.file_path for e in reads if e.file_path})

        summary = (
            f"Session '{session_id}': "
            f"{len(reads)} read(s) across {unique_read_files} file(s), "
            f"{len(writes)} write(s) to {len(files_written)} file(s), "
            f"{len(undos)} undo(s)."
        )

        return SessionContext(
            session_id=session_id,
            total_events=len(events),
            read_count=len(reads),
            write_count=len(writes),
            undo_count=len(undos),
            files_read=files_read,
            files_written=files_written,
            summary=summary,
        )

    async def undo_write(self, session_id: str, steps: int = 1) -> UndoResult:
        """
        Restore the last N written files from the session journal.

        Files are restored in reverse chronological write order.
        Skips entries with missing content_before (e.g., initial creates).
        """
        events = await self._storage.get_session_events(session_id)
        write_events = [
            e for e in reversed(events)
            if e.event_type == SessionEventKind.WRITE
        ]
        to_undo = write_events[:steps]

        files_restored: list[str] = []
        for event in to_undo:
            if event.file_path is None or event.content_before is None:
                continue
            Path(event.file_path).write_text(event.content_before, encoding="utf-8")
            await self._updater.update_file(event.file_path)
            files_restored.append(event.file_path)

            await self._storage.insert_session_event(
                SessionEvent(
                    id=uuid.uuid4().hex,
                    session_id=session_id,
                    event_type=SessionEventKind.UNDO,
                    file_path=event.file_path,
                    created_at=time.time(),
                )
            )

        return UndoResult(files_restored=files_restored, steps_undone=len(files_restored))


class Session:
    """
    Session-id–bound wrapper around SessionManager.

    Obtained via ``prism.session("session-id")`` — matches the Python library
    API from spec §7.  All calls forward to the underlying SessionManager
    with the bound session_id so callers never have to pass it explicitly.
    """

    def __init__(self, session_id: str, manager: SessionManager) -> None:
        self.session_id = session_id
        self._manager = manager

    async def record_read(self, file: str, symbol: str) -> None:
        await self._manager.record_read(self.session_id, file, symbol)

    async def record_write(
        self, file: str, content_before: str, content_after: str
    ) -> dict:
        return await self._manager.record_write(
            self.session_id, file, content_before, content_after
        )

    async def get_context(self) -> SessionContext:
        return await self._manager.get_context(self.session_id)

    async def undo(self, steps: int = 1) -> UndoResult:
        return await self._manager.undo_write(self.session_id, steps)
