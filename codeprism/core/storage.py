"""Async SQLite persistence layer for the knowledge graph."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite

from .models import (
    EdgeKind,
    EdgeRecord,
    FileRecord,
    NodeKind,
    SecurityIssue,
    SessionEvent,
    SessionEventKind,
    Severity,
    SymbolRecord,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS files (
    id            TEXT PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    language      TEXT,
    size_bytes    INTEGER DEFAULT 0,
    checksum      TEXT    DEFAULT '',
    last_modified REAL    DEFAULT 0,
    line_count    INTEGER DEFAULT 0,
    indexed_at    REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS symbols (
    id               TEXT PRIMARY KEY,
    file_id          TEXT NOT NULL,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL,
    line_start       INTEGER,
    line_end         INTEGER,
    signature        TEXT,
    docstring        TEXT,
    is_async         INTEGER DEFAULT 0,
    is_public        INTEGER DEFAULT 1,
    complexity_score REAL    DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS edges (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    from_id      TEXT NOT NULL,
    to_id        TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    line_number  INTEGER,
    weight       REAL    DEFAULT 1.0,
    is_conditional INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS security_issues (
    id             TEXT PRIMARY KEY,
    file_id        TEXT NOT NULL,
    symbol_id      TEXT,
    detector       TEXT NOT NULL,
    severity       TEXT NOT NULL,
    category       TEXT,
    line_number    INTEGER,
    description    TEXT,
    fix_suggestion TEXT,
    detected_at    REAL    DEFAULT 0,
    resolved       INTEGER DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS session_events (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    file_path       TEXT,
    symbol_name     TEXT,
    content_before  TEXT,
    content_after   TEXT,
    security_report TEXT,
    created_at      REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_edges_from   ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to     ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind   ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_session_session ON session_events(session_id);
"""


class StorageManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("StorageManager not initialized — call initialize() first.")
        return self._db

    # ── Files ─────────────────────────────────────────────────────────────────

    async def upsert_file(self, file: FileRecord) -> None:
        await self.db.execute(
            """
            INSERT INTO files (id, path, language, size_bytes, checksum, last_modified, line_count, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                language      = excluded.language,
                size_bytes    = excluded.size_bytes,
                checksum      = excluded.checksum,
                last_modified = excluded.last_modified,
                line_count    = excluded.line_count,
                indexed_at    = excluded.indexed_at
            """,
            (
                file.id, file.path, file.language, file.size_bytes,
                file.checksum, file.last_modified, file.line_count, file.indexed_at,
            ),
        )
        await self.db.commit()

    async def get_file_by_path(self, path: str) -> Optional[FileRecord]:
        async with self.db.execute("SELECT * FROM files WHERE path = ?", (path,)) as cur:
            row = await cur.fetchone()
        return FileRecord(**dict(row)) if row else None

    async def get_file_by_id(self, file_id: str) -> Optional[FileRecord]:
        async with self.db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            row = await cur.fetchone()
        return FileRecord(**dict(row)) if row else None

    async def get_all_files(self) -> list[FileRecord]:
        async with self.db.execute("SELECT * FROM files") as cur:
            rows = await cur.fetchall()
        return [FileRecord(**dict(r)) for r in rows]

    async def delete_file(self, file_id: str) -> None:
        await self.db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        await self.db.commit()

    # ── Symbols ───────────────────────────────────────────────────────────────

    async def upsert_symbol(self, symbol: SymbolRecord) -> None:
        await self.db.execute(
            """
            INSERT INTO symbols
                (id, file_id, name, kind, line_start, line_end, signature, docstring,
                 is_async, is_public, complexity_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                file_id          = excluded.file_id,
                name             = excluded.name,
                kind             = excluded.kind,
                line_start       = excluded.line_start,
                line_end         = excluded.line_end,
                signature        = excluded.signature,
                docstring        = excluded.docstring,
                is_async         = excluded.is_async,
                is_public        = excluded.is_public,
                complexity_score = excluded.complexity_score
            """,
            (
                symbol.id, symbol.file_id, symbol.name, symbol.kind.value,
                symbol.line_start, symbol.line_end, symbol.signature, symbol.docstring,
                int(symbol.is_async), int(symbol.is_public), symbol.complexity_score,
            ),
        )
        await self.db.commit()

    async def upsert_symbols_batch(self, symbols: list[SymbolRecord]) -> None:
        await self.db.executemany(
            """
            INSERT INTO symbols
                (id, file_id, name, kind, line_start, line_end, signature, docstring,
                 is_async, is_public, complexity_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                file_id          = excluded.file_id,
                name             = excluded.name,
                kind             = excluded.kind,
                line_start       = excluded.line_start,
                line_end         = excluded.line_end,
                signature        = excluded.signature,
                docstring        = excluded.docstring,
                is_async         = excluded.is_async,
                is_public        = excluded.is_public,
                complexity_score = excluded.complexity_score
            """,
            [
                (
                    s.id, s.file_id, s.name, s.kind.value,
                    s.line_start, s.line_end, s.signature, s.docstring,
                    int(s.is_async), int(s.is_public), s.complexity_score,
                )
                for s in symbols
            ],
        )
        await self.db.commit()

    async def get_symbols_for_file(self, file_id: str) -> list[SymbolRecord]:
        async with self.db.execute("SELECT * FROM symbols WHERE file_id = ?", (file_id,)) as cur:
            rows = await cur.fetchall()
        return [_row_to_symbol(r) for r in rows]

    async def get_symbol_by_id(self, symbol_id: str) -> Optional[SymbolRecord]:
        async with self.db.execute("SELECT * FROM symbols WHERE id = ?", (symbol_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_symbol(row) if row else None

    async def find_symbols(self, name: str, kind: Optional[str] = None) -> list[SymbolRecord]:
        if kind:
            async with self.db.execute(
                "SELECT * FROM symbols WHERE name = ? AND kind = ?", (name, kind)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute("SELECT * FROM symbols WHERE name = ?", (name,)) as cur:
                rows = await cur.fetchall()
        return [_row_to_symbol(r) for r in rows]

    async def search_symbols(self, query: str, kind: Optional[str] = None) -> list[SymbolRecord]:
        pattern = f"%{query}%"
        if kind:
            async with self.db.execute(
                "SELECT * FROM symbols WHERE name LIKE ? AND kind = ? LIMIT 50",
                (pattern, kind),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute(
                "SELECT * FROM symbols WHERE name LIKE ? LIMIT 50", (pattern,)
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_symbol(r) for r in rows]

    async def get_all_symbols(self) -> list[SymbolRecord]:
        async with self.db.execute("SELECT * FROM symbols") as cur:
            rows = await cur.fetchall()
        return [_row_to_symbol(r) for r in rows]

    async def delete_symbols_for_file(self, file_id: str) -> None:
        await self.db.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        await self.db.commit()

    # ── Edges ─────────────────────────────────────────────────────────────────

    async def upsert_edge(self, edge: EdgeRecord) -> None:
        await self.db.execute(
            """
            INSERT INTO edges (id, kind, from_id, to_id, file_path, line_number, weight, is_conditional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                weight         = excluded.weight,
                is_conditional = excluded.is_conditional
            """,
            (
                edge.id, edge.kind.value, edge.from_id, edge.to_id,
                edge.file_path, edge.line_number, edge.weight, int(edge.is_conditional),
            ),
        )
        await self.db.commit()

    async def upsert_edges_batch(self, edges: list[EdgeRecord]) -> None:
        await self.db.executemany(
            """
            INSERT INTO edges (id, kind, from_id, to_id, file_path, line_number, weight, is_conditional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                weight         = excluded.weight,
                is_conditional = excluded.is_conditional
            """,
            [
                (
                    e.id, e.kind.value, e.from_id, e.to_id,
                    e.file_path, e.line_number, e.weight, int(e.is_conditional),
                )
                for e in edges
            ],
        )
        await self.db.commit()

    async def get_edges_for_file(self, file_path: str) -> list[EdgeRecord]:
        async with self.db.execute("SELECT * FROM edges WHERE file_path = ?", (file_path,)) as cur:
            rows = await cur.fetchall()
        return [_row_to_edge(r) for r in rows]

    async def get_edges_from(self, from_id: str, kind: Optional[str] = None) -> list[EdgeRecord]:
        if kind:
            async with self.db.execute(
                "SELECT * FROM edges WHERE from_id = ? AND kind = ?", (from_id, kind)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute("SELECT * FROM edges WHERE from_id = ?", (from_id,)) as cur:
                rows = await cur.fetchall()
        return [_row_to_edge(r) for r in rows]

    async def get_edges_to(self, to_id: str, kind: Optional[str] = None) -> list[EdgeRecord]:
        if kind:
            async with self.db.execute(
                "SELECT * FROM edges WHERE to_id = ? AND kind = ?", (to_id, kind)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute("SELECT * FROM edges WHERE to_id = ?", (to_id,)) as cur:
                rows = await cur.fetchall()
        return [_row_to_edge(r) for r in rows]

    async def get_all_edges(self) -> list[EdgeRecord]:
        async with self.db.execute("SELECT * FROM edges") as cur:
            rows = await cur.fetchall()
        return [_row_to_edge(r) for r in rows]

    async def delete_edges_for_file(self, file_path: str) -> None:
        await self.db.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
        await self.db.commit()

    # ── Security issues ───────────────────────────────────────────────────────

    async def insert_security_issue(self, issue: SecurityIssue) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO security_issues
                (id, file_id, symbol_id, detector, severity, category, line_number,
                 description, fix_suggestion, detected_at, resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue.id, issue.file_id, issue.symbol_id, issue.detector,
                issue.severity.value, issue.category, issue.line_number,
                issue.description, issue.fix_suggestion, issue.detected_at, int(issue.resolved),
            ),
        )
        await self.db.commit()

    async def get_security_issues_for_file(self, file_id: str) -> list[SecurityIssue]:
        async with self.db.execute(
            "SELECT * FROM security_issues WHERE file_id = ? AND resolved = 0", (file_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_security_issue(r) for r in rows]

    # ── Session events ────────────────────────────────────────────────────────

    async def insert_session_event(self, event: SessionEvent) -> None:
        await self.db.execute(
            """
            INSERT INTO session_events
                (id, session_id, event_type, file_path, symbol_name,
                 content_before, content_after, security_report, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id, event.session_id, event.event_type.value,
                event.file_path, event.symbol_name, event.content_before,
                event.content_after, event.security_report, event.created_at,
            ),
        )
        await self.db.commit()

    async def get_session_events(self, session_id: str) -> list[SessionEvent]:
        async with self.db.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_session_event(r) for r in rows]

    # ── Aggregate stats ───────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, object]:
        async def scalar(sql: str) -> int:
            async with self.db.execute(sql) as cur:
                row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        file_count = await scalar("SELECT COUNT(*) FROM files")
        function_count = await scalar("SELECT COUNT(*) FROM symbols WHERE kind = 'function'")
        class_count = await scalar("SELECT COUNT(*) FROM symbols WHERE kind = 'class'")
        variable_count = await scalar("SELECT COUNT(*) FROM symbols WHERE kind = 'variable'")
        import_count = await scalar("SELECT COUNT(*) FROM symbols WHERE kind = 'import'")
        edge_count = await scalar("SELECT COUNT(*) FROM edges")

        async with self.db.execute(
            "SELECT DISTINCT language FROM files WHERE language IS NOT NULL"
        ) as cur:
            lang_rows = await cur.fetchall()
        languages = [r[0] for r in lang_rows]

        async with self.db.execute("SELECT MAX(indexed_at) FROM files") as cur:
            row = await cur.fetchone()
        last_indexed_at = float(row[0]) if row and row[0] is not None else None

        files_with_symbols = await scalar(
            "SELECT COUNT(DISTINCT file_id) FROM symbols"
        )
        coverage_percent = (
            round(files_with_symbols / file_count * 100, 1) if file_count else 0.0
        )

        return {
            "file_count": file_count,
            "function_count": function_count,
            "class_count": class_count,
            "variable_count": variable_count,
            "import_count": import_count,
            "edge_count": edge_count,
            "languages": languages,
            "last_indexed_at": last_indexed_at,
            "coverage_percent": coverage_percent,
        }


# ─── Row converters (module-level for reuse) ──────────────────────────────────

def _row_to_symbol(row: aiosqlite.Row) -> SymbolRecord:
    d = dict(row)
    d["kind"] = NodeKind(d["kind"])
    d["is_async"] = bool(d["is_async"])
    d["is_public"] = bool(d["is_public"])
    return SymbolRecord(**d)


def _row_to_edge(row: aiosqlite.Row) -> EdgeRecord:
    d = dict(row)
    d["kind"] = EdgeKind(d["kind"])
    d["is_conditional"] = bool(d["is_conditional"])
    return EdgeRecord(**d)


def _row_to_security_issue(row: aiosqlite.Row) -> SecurityIssue:
    d = dict(row)
    d["severity"] = Severity(d["severity"])
    d["resolved"] = bool(d["resolved"])
    return SecurityIssue(**d)


def _row_to_session_event(row: aiosqlite.Row) -> SessionEvent:
    d = dict(row)
    d["event_type"] = SessionEventKind(d["event_type"])
    return SessionEvent(**d)
