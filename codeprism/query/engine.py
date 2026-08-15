"""QueryEngine — single entry point for all graph queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.graph import GraphEngine
from ..core.models import EdgeKind, FileRecord, NodeKind, SymbolRecord
from ..core.storage import StorageManager
from . import context as _ctx_mod
from . import impact as _imp_mod
from . import summary as _sum_mod
from .context import ContextResult
from .impact import ImpactResult
from .summary import ModuleSummary


# ── Additional result types ───────────────────────────────────────────────────


@dataclass
class SearchMatch:
    symbol: SymbolRecord
    file_path: str
    score: float = 1.0
    docstring_excerpt: Optional[str] = None


@dataclass
class FileMapEntry:
    path: str
    language: str
    line_count: int
    symbol_count: int
    class_count: int
    function_count: int
    role_summary: str


@dataclass
class FileMap:
    project_path: str
    entries: list[FileMapEntry] = field(default_factory=list)
    total_files: int = 0
    total_symbols: int = 0


@dataclass
class DependencyResult:
    file_path: str
    internal_deps: list[str] = field(default_factory=list)
    external_deps: list[str] = field(default_factory=list)
    circular_deps: list[str] = field(default_factory=list)


@dataclass
class DependentResult:
    file_path: str
    dependents: list[str] = field(default_factory=list)


@dataclass
class DataFlowResult:
    symbol: SymbolRecord
    sources: list[SymbolRecord] = field(default_factory=list)
    sinks: list[SymbolRecord] = field(default_factory=list)
    intermediate_nodes: list[SymbolRecord] = field(default_factory=list)
    flow_paths: list[list[str]] = field(default_factory=list)


# ── Engine ────────────────────────────────────────────────────────────────────


class QueryEngine:
    """Facade over GraphEngine + StorageManager for high-level queries."""

    def __init__(self, graph: GraphEngine, storage: StorageManager) -> None:
        self._graph = graph
        self._storage = storage

    # ── Delegation to sub-modules ─────────────────────────────────────────────

    async def get_context(
        self, file_path: str, symbol_name: str, depth: int = 2
    ) -> Optional[ContextResult]:
        return await _ctx_mod.get_context(
            self._graph, self._storage, file_path, symbol_name, depth
        )

    async def get_impact(
        self, file_path: str, symbol_name: str
    ) -> Optional[ImpactResult]:
        return await _imp_mod.get_impact(
            self._graph, self._storage, file_path, symbol_name
        )

    async def get_module_summary(self, file_path: str) -> Optional[ModuleSummary]:
        return await _sum_mod.get_module_summary(
            self._graph, self._storage, file_path
        )

    # ── Symbol lookup ─────────────────────────────────────────────────────────

    async def find_symbol(self, file_path: str, name: str) -> Optional[SymbolRecord]:
        file = await self._storage.get_file_by_path(file_path)
        if not file:
            return None
        syms = await self._storage.get_symbols_for_file(file.id)
        return _ctx_mod._pick(syms, name)

    async def get_file(self, file_path: str) -> Optional[FileRecord]:
        return await self._storage.get_file_by_path(file_path)

    # ── Callers / callees ─────────────────────────────────────────────────────

    async def get_callers(self, file_path: str, symbol_name: str) -> list[SymbolRecord]:
        sym = await self.find_symbol(file_path, symbol_name)
        if not sym:
            return []
        return self._graph.get_callers(sym.id)

    async def get_callees(self, file_path: str, symbol_name: str) -> list[SymbolRecord]:
        sym = await self.find_symbol(file_path, symbol_name)
        if not sym:
            return []
        return self._graph.get_callees(sym.id)

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_symbols(
        self, query: str, kind: Optional[str] = None
    ) -> list[SearchMatch]:
        raw = await self._storage.search_symbols(query, kind)
        all_files = await self._storage.get_all_files()
        id_to_path = {f.id: f.path for f in all_files}

        results: list[SearchMatch] = []
        for sym in raw:
            excerpt = sym.docstring[:120] if sym.docstring else None
            results.append(SearchMatch(
                symbol=sym,
                file_path=id_to_path.get(sym.file_id, ""),
                score=1.0,
                docstring_excerpt=excerpt,
            ))
        return results

    # ── File map ──────────────────────────────────────────────────────────────

    async def get_file_map(self, project_path: str = "") -> FileMap:
        all_files = await self._storage.get_all_files()
        all_syms = await self._storage.get_all_symbols()

        # Build per-file symbol counts
        file_syms: dict[str, list[SymbolRecord]] = {f.id: [] for f in all_files}
        for sym in all_syms:
            if sym.file_id in file_syms:
                file_syms[sym.file_id].append(sym)

        entries: list[FileMapEntry] = []
        for f in sorted(all_files, key=lambda x: x.path):
            syms = file_syms[f.id]
            n_class = sum(1 for s in syms if s.kind == NodeKind.CLASS)
            n_func  = sum(1 for s in syms if s.kind == NodeKind.FUNCTION)
            stem = Path(f.path).name
            role = f"{stem}: "
            parts = []
            if n_class:
                parts.append(f"{n_class} class{'es' if n_class > 1 else ''}")
            if n_func:
                parts.append(f"{n_func} function{'s' if n_func > 1 else ''}")
            role += ", ".join(parts) if parts else "source file"
            entries.append(FileMapEntry(
                path=f.path,
                language=f.language or "",
                line_count=f.line_count or 0,
                symbol_count=len(syms),
                class_count=n_class,
                function_count=n_func,
                role_summary=role,
            ))

        return FileMap(
            project_path=project_path,
            entries=entries,
            total_files=len(all_files),
            total_symbols=len(all_syms),
        )

    # ── Dependencies ──────────────────────────────────────────────────────────

    async def get_dependencies(self, file_path: str) -> Optional[DependencyResult]:
        file = await self._storage.get_file_by_path(file_path)
        if not file:
            return None

        syms = await self._storage.get_symbols_for_file(file.id)
        import_syms = [s for s in syms if s.kind == NodeKind.IMPORT]

        # Anything with a matching non-import symbol in the graph = internal
        all_syms = await self._storage.get_all_symbols()
        known_names = {
            s.name for s in all_syms
            if s.kind != NodeKind.IMPORT and s.file_id != file.id
        }

        internal: list[str] = []
        external: list[str] = []
        for imp in import_syms:
            if imp.name in known_names:
                internal.append(imp.name)
            else:
                external.append(imp.name)

        return DependencyResult(
            file_path=file_path,
            internal_deps=internal,
            external_deps=external,
            circular_deps=[],  # TODO: nx cycle detection in Phase 5+
        )

    async def get_dependents(self, file_path: str) -> Optional[DependentResult]:
        file = await self._storage.get_file_by_path(file_path)
        if not file:
            return None

        syms = await self._storage.get_symbols_for_file(file.id)
        all_files = await self._storage.get_all_files()
        id_to_path = {f.id: f.path for f in all_files}

        dependent_paths: set[str] = set()
        for sym in syms:
            trans = self._graph.get_transitive_dependents(sym.id)
            for tid in trans:
                rec = self._graph.get_symbol(tid)
                if rec:
                    fp = id_to_path.get(rec.file_id, "")
                    if fp and fp != file_path:
                        dependent_paths.add(fp)

        return DependentResult(file_path=file_path, dependents=sorted(dependent_paths))

    # ── Data flow ─────────────────────────────────────────────────────────────

    async def get_data_flow(
        self, file_path: str, symbol_name: str
    ) -> Optional[DataFlowResult]:
        sym = await self.find_symbol(file_path, symbol_name)
        if not sym:
            return None

        # sources = things that flow INTO this symbol (callers + symbols that define it)
        sources = self._graph.get_callers(sym.id)

        # sinks = things this symbol produces / calls
        sinks = self._graph.get_callees(sym.id)

        # Approximate flow paths (direct 1-hop paths only for now)
        paths: list[list[str]] = []
        for src in sources[:5]:
            paths.append([src.name, sym.name])
        for sink in sinks[:5]:
            paths.append([sym.name, sink.name])

        return DataFlowResult(
            symbol=sym,
            sources=sources[:20],
            sinks=sinks[:20],
            intermediate_nodes=[],
            flow_paths=paths,
        )

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        return await self._storage.get_stats()
