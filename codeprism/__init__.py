"""CodePrism — persistent knowledge graph for AI coding agents."""

from __future__ import annotations

from typing import Optional

from .core import (
    CodePrismConfig,
    EdgeKind,
    EdgeRecord,
    FileRecord,
    GraphEngine,
    GraphStats,
    NodeKind,
    SecurityIssue,
    SessionEvent,
    Severity,
    StorageManager,
    SymbolRecord,
)
from .query.context import ContextResult
from .query.engine import QueryEngine
from .query.impact import ImpactResult
from .query.summary import ModuleSummary

__version__ = "0.1.0"


class CodePrism:
    """High-level façade: one object for indexing, querying, and watching a project.

    Usage::

        async with CodePrism("/path/to/project") as prism:
            await prism.index()
            ctx = await prism.get_context("payments/processor.py", "process_payment")
            impact = await prism.get_impact("payments/processor.py", "process_payment")
    """

    def __init__(
        self,
        project_path: str,
        config: Optional[CodePrismConfig] = None,
    ) -> None:
        self.project_path = project_path
        self.config = config or CodePrismConfig()
        self._storage: Optional[StorageManager] = None
        self._graph: Optional[GraphEngine] = None
        self._engine: Optional[QueryEngine] = None

    # ── Async context-manager protocol ───────────────────────────────────────

    async def __aenter__(self) -> "CodePrism":
        await self.initialize()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        from .core.paths import get_db_path
        db_path = get_db_path(self.project_path)
        self._storage = StorageManager(db_path)
        await self._storage.initialize()
        self._graph = GraphEngine()
        await self._graph.load_from_storage(self._storage)
        self._engine = QueryEngine(self._graph, self._storage)

    async def close(self) -> None:
        if self._storage:
            await self._storage.close()
            self._storage = None
            self._engine = None

    # ── Indexing ──────────────────────────────────────────────────────────────

    async def index(self):
        """Build or rebuild the full knowledge graph."""
        from .indexer.project_indexer import ProjectIndexer
        assert self._graph and self._storage
        indexer = ProjectIndexer(self._graph, self._storage, self.config)
        return await indexer.index(self.project_path)

    # ── Queries ───────────────────────────────────────────────────────────────

    @property
    def engine(self) -> QueryEngine:
        if self._engine is None:
            raise RuntimeError("CodePrism not initialized — use `async with CodePrism(...)`")
        return self._engine

    async def get_context(
        self, file: str, symbol: str, depth: int = 2
    ) -> Optional[ContextResult]:
        return await self.engine.get_context(file, symbol, depth)

    async def get_impact(
        self, file: str, symbol: str
    ) -> Optional[ImpactResult]:
        return await self.engine.get_impact(file, symbol)

    async def get_module_summary(self, file: str) -> Optional[ModuleSummary]:
        return await self.engine.get_module_summary(file)


__all__ = [
    "__version__",
    "CodePrism",
    "CodePrismConfig",
    "QueryEngine",
    "ContextResult",
    "ImpactResult",
    "ModuleSummary",
    "GraphEngine",
    "StorageManager",
    "NodeKind",
    "EdgeKind",
    "Severity",
    "FileRecord",
    "SymbolRecord",
    "EdgeRecord",
    "SecurityIssue",
    "SessionEvent",
    "GraphStats",
]
