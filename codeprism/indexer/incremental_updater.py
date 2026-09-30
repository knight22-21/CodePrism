"""Incremental file updater: checksum-diff, graph surgery, cross-file re-resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

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
        registry: ParserRegistry | None = None,
    ) -> None:
        self._graph = graph
        self._storage = storage
        self._registry = registry or ParserRegistry()

    async def update_file(self, file_path: str) -> UpdateResult:
        # Stored paths are absolute; normalize so a relative path updates the
        # same record instead of creating a duplicate.
        path = Path(file_path).resolve()
        file_path = str(path)

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

        # 4. Remember edges from *other* files into this file's symbols. Removing
        #    a symbol node below also drops these from the in-memory graph.
        inbound = self._inbound_edges(file_path, old_symbols)

        # Remove old edges (graph + storage) before touching symbols
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

        # 8. Reconnect other files' edges to the new symbols
        await self._reconnect_inbound(inbound, old_symbols, parse_result.symbols)

        # 9. Resolve cross-file refs against the current global symbol table
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
        inbound = self._inbound_edges(file_path, old_symbols)
        self._graph.remove_edges_for_file(file_path)
        await self._storage.delete_edges_for_file(file_path)
        for sym in old_symbols:
            self._graph.remove_symbol(sym.id)
        await self._storage.delete_symbols_for_file(existing.id)
        self._graph.remove_file(existing.id)
        await self._storage.delete_file(existing.id)
        # Their targets are gone: drop them from storage too, or a reload
        # would resurrect them as ghost nodes.
        await self._storage.delete_edges_by_ids([e.id for e in inbound])

        return UpdateResult(nodes_removed=len(old_symbols))

    def _inbound_edges(self, file_path: str, old_symbols: list) -> list[EdgeRecord]:
        return [
            edge
            for sym in old_symbols
            for edge in self._graph.get_edges_to(sym.id)
            if edge.file_path != file_path
        ]

    async def _reconnect_inbound(
        self, inbound: list[EdgeRecord], old_symbols: list, new_symbols: list
    ) -> None:
        """Restore, re-point, or drop edges from other files into a re-parsed file.

        Symbol ids hash (path, name, kind), so an unchanged definition keeps its
        id and its edge is simply restored. A definition that changed kind but
        kept its name is re-pointed. A removed or renamed one loses the edge —
        the caller's file would have to be re-parsed to know its new target.
        """
        if not inbound:
            return
        new_ids = {s.id for s in new_symbols}
        new_by_name: dict[str, str] = {}
        for s in new_symbols:
            if s.name not in new_by_name or s.kind != NodeKind.IMPORT:
                new_by_name[s.name] = s.id
        old_name = {s.id: s.name for s in old_symbols}

        restored: list[EdgeRecord] = []
        repointed: list[EdgeRecord] = []
        stale_ids: list[str] = []
        for edge in inbound:
            if edge.to_id in new_ids:
                restored.append(edge)
                continue
            stale_ids.append(edge.id)
            target = new_by_name.get(old_name.get(edge.to_id, ""))
            if target and target != edge.from_id:
                repointed.append(
                    EdgeRecord.create(
                        kind=edge.kind,
                        from_id=edge.from_id,
                        to_id=target,
                        file_path=edge.file_path,
                        line_number=edge.line_number,
                    )
                )

        await self._storage.delete_edges_by_ids(stale_ids)
        if repointed:
            await self._storage.upsert_edges_batch(repointed)
        for edge in restored + repointed:
            self._graph.add_edge(edge)

    async def _resolve_refs(self, unresolved: list[UnresolvedRef]) -> list[EdgeRecord]:
        # Look up only the referenced names (indexed) instead of every symbol
        name_to_id = await self._storage.resolve_symbol_names({r.ref_name for r in unresolved})

        resolved: list[EdgeRecord] = []
        for ref in unresolved:
            target_id = name_to_id.get(ref.ref_name)
            if target_id and target_id != ref.from_id:
                resolved.append(
                    EdgeRecord.create(
                        kind=ref.kind,
                        from_id=ref.from_id,
                        to_id=target_id,
                        file_path=ref.file_path,
                        line_number=ref.line_number,
                    )
                )
        return resolved
