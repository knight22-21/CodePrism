"""Incremental file updater: checksum-diff, graph surgery, cross-file re-resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.graph import GraphEngine
from ..core.models import EdgeRecord, NodeKind
from ..core.storage import StorageManager
from ..parser.base import UnresolvedRef
from ..parser.registry import ParserRegistry


@dataclass
class UpdateResult:
    nodes_added: int = 0
    nodes_removed: int = 0
    edges_updated: int = 0
    skipped: bool = False


class IncrementalUpdater:
    """Handles a single-file change: parse → diff → update storage + graph."""

    def __init__(
        self,
        graph: GraphEngine,
        storage: StorageManager,
        registry: Optional[ParserRegistry] = None,
    ) -> None:
        self._graph = graph
        self._storage = storage
        self._registry = registry or ParserRegistry()

    async def update_file(self, file_path: str) -> UpdateResult:
        path = Path(file_path)

        # File deleted — remove all its data
        if not path.exists():
            return await self._remove_file(file_path)

        # 1. Read content and short-circuit if unchanged
        content = path.read_text(encoding="utf-8", errors="replace")
        new_checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

        existing = await self._storage.get_file_by_path(file_path)
        if existing and existing.checksum == new_checksum:
            return UpdateResult(skipped=True)

        # 2. Load old symbols so we know what to remove from the graph
        old_symbols = []
        if existing:
            old_symbols = await self._storage.get_symbols_for_file(existing.id)

        # 3. Parse the new content
        parser = self._registry.get(file_path)
        parse_result = parser.parse(file_path, content)

        # 4. Remove old edges (graph + storage) before touching symbols
        self._graph.remove_edges_for_file(file_path)
        await self._storage.delete_edges_for_file(file_path)

        # 5. Remove old symbols from graph + storage
        for sym in old_symbols:
            self._graph.remove_symbol(sym.id)
        if existing:
            await self._storage.delete_symbols_for_file(existing.id)

        # 6. Persist new records
        await self._storage.upsert_file(parse_result.file)
        if parse_result.symbols:
            await self._storage.upsert_symbols_batch(parse_result.symbols)
        if parse_result.edges:
            await self._storage.upsert_edges_batch(parse_result.edges)

        # 7. Update in-memory graph
        self._graph.add_file(parse_result.file)
        for sym in parse_result.symbols:
            self._graph.add_symbol(sym)
        for edge in parse_result.edges:
            self._graph.add_edge(edge)

        # 8. Resolve cross-file refs against the current global symbol table
        resolved_edges: list[EdgeRecord] = []
        if parse_result.unresolved_refs:
            resolved_edges = await self._resolve_refs(parse_result.unresolved_refs)
            if resolved_edges:
                await self._storage.upsert_edges_batch(resolved_edges)
                for edge in resolved_edges:
                    self._graph.add_edge(edge)

        return UpdateResult(
            nodes_added=len(parse_result.symbols),
            nodes_removed=len(old_symbols),
            edges_updated=len(parse_result.edges) + len(resolved_edges),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _remove_file(self, file_path: str) -> UpdateResult:
        existing = await self._storage.get_file_by_path(file_path)
        if not existing:
            return UpdateResult(skipped=True)

        old_symbols = await self._storage.get_symbols_for_file(existing.id)
        self._graph.remove_edges_for_file(file_path)
        await self._storage.delete_edges_for_file(file_path)
        for sym in old_symbols:
            self._graph.remove_symbol(sym.id)
        await self._storage.delete_symbols_for_file(existing.id)
        self._graph.remove_file(existing.id)
        await self._storage.delete_file(existing.id)

        return UpdateResult(nodes_removed=len(old_symbols))

    async def _resolve_refs(self, unresolved: list[UnresolvedRef]) -> list[EdgeRecord]:
        all_symbols = await self._storage.get_all_symbols()

        name_to_id: dict[str, str] = {}
        for sym in all_symbols:
            if sym.name not in name_to_id or sym.kind != NodeKind.IMPORT:
                name_to_id[sym.name] = sym.id

        resolved: list[EdgeRecord] = []
        for ref in unresolved:
            target_id = name_to_id.get(ref.ref_name)
            if target_id and target_id != ref.from_id:
                resolved.append(EdgeRecord.create(
                    kind=ref.kind,
                    from_id=ref.from_id,
                    to_id=target_id,
                    file_path=ref.file_path,
                    line_number=ref.line_number,
                ))
        return resolved
