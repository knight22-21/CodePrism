"""Pydantic models for all graph nodes, edges, and result types."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeKind(str, Enum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"
    IMPORT = "import"
    TYPE = "type"


class EdgeKind(str, Enum):
    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    USES = "uses"
    DEFINES = "defines"
    DATA_FLOWS = "data_flows"
    EXPORTS = "exports"
    TESTS = "tests"
    REFERENCES = "references"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    BLOCK = "BLOCK"


class SessionEventKind(str, Enum):
    READ = "read"
    WRITE = "write"
    UNDO = "undo"


# ─── ID helpers ───────────────────────────────────────────────────────────────

def make_file_id(path: str) -> str:
    return hashlib.sha256(f"file:{path}".encode()).hexdigest()


def make_symbol_id(file_path: str, name: str, kind: str) -> str:
    return hashlib.sha256(f"{file_path}:{name}:{kind}".encode()).hexdigest()


def make_edge_id(from_id: str, to_id: str, kind: str, line: int | None = None) -> str:
    return hashlib.sha256(f"{from_id}:{to_id}:{kind}:{line}".encode()).hexdigest()


# ─── Storage-mapped models ────────────────────────────────────────────────────

class FileRecord(BaseModel):
    """Maps to the `files` table. One record per indexed source file."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    language: str | None = None
    size_bytes: int = 0
    last_modified: float = 0.0
    checksum: str = ""
    line_count: int = 0
    indexed_at: float = 0.0

    @classmethod
    def create(cls, path: str, **kwargs: Any) -> FileRecord:
        return cls(id=make_file_id(path), path=path, **kwargs)


class SymbolRecord(BaseModel):
    """Maps to the `symbols` table. Covers all symbol kinds (function/class/variable/import/type)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    file_id: str
    name: str
    kind: NodeKind
    line_start: int | None = None
    line_end: int | None = None
    signature: str | None = None
    docstring: str | None = None
    is_async: bool = False
    is_public: bool = True
    complexity_score: float = 0.0
    # In-memory only — not persisted to SQLite
    extra: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def create(
        cls,
        file_path: str,
        file_id: str,
        name: str,
        kind: NodeKind,
        **kwargs: Any,
    ) -> SymbolRecord:
        symbol_id = make_symbol_id(file_path, name, kind.value)
        return cls(id=symbol_id, file_id=file_id, name=name, kind=kind, **kwargs)


class EdgeRecord(BaseModel):
    """Maps to the `edges` table."""

    model_config = ConfigDict(extra="ignore")

    id: str
    kind: EdgeKind
    from_id: str  # references files.id or symbols.id
    to_id: str    # same
    file_path: str
    line_number: int | None = None
    weight: float = 1.0
    is_conditional: bool = False

    @classmethod
    def create(
        cls,
        kind: EdgeKind,
        from_id: str,
        to_id: str,
        file_path: str,
        line_number: int | None = None,
        **kwargs: Any,
    ) -> EdgeRecord:
        edge_id = make_edge_id(from_id, to_id, kind.value, line_number)
        return cls(
            id=edge_id,
            kind=kind,
            from_id=from_id,
            to_id=to_id,
            file_path=file_path,
            line_number=line_number,
            **kwargs,
        )


class SecurityIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    file_id: str
    symbol_id: str | None = None
    detector: str
    severity: Severity
    category: str | None = None
    line_number: int | None = None
    description: str
    fix_suggestion: str | None = None
    detected_at: float = 0.0
    resolved: bool = False


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    session_id: str
    event_type: SessionEventKind
    file_path: str | None = None
    symbol_name: str | None = None
    content_before: str | None = None
    content_after: str | None = None
    security_report: str | None = None  # JSON blob
    created_at: float = 0.0


# ─── Query result models ──────────────────────────────────────────────────────

class GraphStats(BaseModel):
    file_count: int = 0
    class_count: int = 0
    function_count: int = 0
    variable_count: int = 0
    import_count: int = 0
    edge_count: int = 0
    languages: list[str] = Field(default_factory=list)
    last_indexed_at: float | None = None
