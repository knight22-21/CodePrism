"""GraphEngine — in-memory NetworkX graph, synchronized with SQLite storage."""

from __future__ import annotations

from typing import Optional

import networkx as nx

from .models import (
    EdgeKind,
    EdgeRecord,
    FileRecord,
    GraphStats,
    NodeKind,
    SymbolRecord,
)
from .storage import StorageManager


class GraphEngine:
    """MultiDiGraph wrapper providing all graph traversal operations.

    Nodes are keyed by their string ID (file.id or symbol.id).
    Each node carries ``kind`` and ``record`` attributes.
    Edges are keyed by edge.id and carry ``kind`` and ``record`` attributes.
    """

    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()

    # ── Population ────────────────────────────────────────────────────────────

    async def load_from_storage(self, storage: StorageManager) -> None:
        """Populate the in-memory graph from persistent storage."""
        for file in await storage.get_all_files():
            self._add_file_node(file)
        for symbol in await storage.get_all_symbols():
            self._add_symbol_node(symbol)
        for edge in await storage.get_all_edges():
            self._add_edge_record(edge)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_file(self, file: FileRecord) -> None:
        self._add_file_node(file)

    def add_symbol(self, symbol: SymbolRecord) -> None:
        self._add_symbol_node(symbol)

    def add_edge(self, edge: EdgeRecord) -> None:
        self._add_edge_record(edge)

    def remove_file(self, file_id: str) -> None:
        if self._g.has_node(file_id):
            self._g.remove_node(file_id)

    def remove_symbol(self, symbol_id: str) -> None:
        if self._g.has_node(symbol_id):
            self._g.remove_node(symbol_id)

    def remove_edge_by_id(self, edge_id: str) -> None:
        for u, v, key in list(self._g.edges(keys=True)):
            if key == edge_id:
                self._g.remove_edge(u, v, key=key)
                return

    def remove_edges_for_file(self, file_path: str) -> None:
        to_remove = [
            (u, v, key)
            for u, v, key, data in self._g.edges(keys=True, data=True)
            if data.get("record") and data["record"].file_path == file_path
        ]
        for u, v, key in to_remove:
            self._g.remove_edge(u, v, key=key)

    # ── Node lookup ───────────────────────────────────────────────────────────

    def has_node(self, node_id: str) -> bool:
        return self._g.has_node(node_id)

    def get_symbol(self, symbol_id: str) -> Optional[SymbolRecord]:
        if not self._g.has_node(symbol_id):
            return None
        record = self._g.nodes[symbol_id].get("record")
        return record if isinstance(record, SymbolRecord) else None

    def get_file(self, file_id: str) -> Optional[FileRecord]:
        if not self._g.has_node(file_id):
            return None
        record = self._g.nodes[file_id].get("record")
        return record if isinstance(record, FileRecord) else None

    # ── Caller / callee traversal ─────────────────────────────────────────────

    def get_callers(self, symbol_id: str) -> list[SymbolRecord]:
        """Symbols that directly call this symbol (in-edges with kind=CALLS)."""
        seen: set[str] = set()
        result: list[SymbolRecord] = []
        for u, _v, data in self._g.in_edges(symbol_id, data=True):
            if data.get("kind") == EdgeKind.CALLS and u not in seen:
                seen.add(u)
                rec = self.get_symbol(u)
                if rec:
                    result.append(rec)
        return result

    def get_callees(self, symbol_id: str) -> list[SymbolRecord]:
        """Symbols directly called by this symbol (out-edges with kind=CALLS)."""
        seen: set[str] = set()
        result: list[SymbolRecord] = []
        for _u, v, data in self._g.out_edges(symbol_id, data=True):
            if data.get("kind") == EdgeKind.CALLS and v not in seen:
                seen.add(v)
                rec = self.get_symbol(v)
                if rec:
                    result.append(rec)
        return result

    # ── Generic edge access ───────────────────────────────────────────────────

    def get_edges_from(self, node_id: str, kind: Optional[EdgeKind] = None) -> list[EdgeRecord]:
        edges = []
        for _u, _v, data in self._g.out_edges(node_id, data=True):
            rec: Optional[EdgeRecord] = data.get("record")
            if rec and (kind is None or rec.kind == kind):
                edges.append(rec)
        return edges

    def get_edges_to(self, node_id: str, kind: Optional[EdgeKind] = None) -> list[EdgeRecord]:
        edges = []
        for _u, _v, data in self._g.in_edges(node_id, data=True):
            rec: Optional[EdgeRecord] = data.get("record")
            if rec and (kind is None or rec.kind == kind):
                edges.append(rec)
        return edges

    # ── Neighbourhood traversal ───────────────────────────────────────────────

    def get_neighbors(self, node_id: str, depth: int = 1) -> set[str]:
        """BFS over all edge types, returning node IDs within *depth* hops."""
        if not self._g.has_node(node_id):
            return set()
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for n in frontier:
                next_frontier.update(self._g.predecessors(n))
                next_frontier.update(self._g.successors(n))
            next_frontier -= visited
            visited.update(next_frontier)
            frontier = next_frontier
        return visited - {node_id}

    def get_transitive_dependents(self, node_id: str) -> set[str]:
        """All nodes that (transitively) depend on this node.

        An ancestor in graph terms: nodes that can reach *node_id* by following
        directed edges, i.e. the "upward" callers/importers chain.
        """
        if not self._g.has_node(node_id):
            return set()
        return nx.ancestors(self._g, node_id)

    def get_transitive_dependencies(self, node_id: str) -> set[str]:
        """All nodes this node (transitively) depends on (descendants)."""
        if not self._g.has_node(node_id):
            return set()
        return nx.descendants(self._g, node_id)

    def get_subgraph(self, center_id: str, depth: int = 2) -> nx.MultiDiGraph:
        nodes = self.get_neighbors(center_id, depth) | {center_id}
        return self._g.subgraph(nodes).copy()

    def find_all_paths(self, from_id: str, to_id: str, cutoff: int = 6) -> list[list[str]]:
        try:
            return list(nx.all_simple_paths(self._g, from_id, to_id, cutoff=cutoff))
        except (nx.NodeNotFound, nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    # ── Stats ─────────────────────────────────────────────────────────────────

    def node_count(self) -> int:
        return self._g.number_of_nodes()

    def edge_count(self) -> int:
        return self._g.number_of_edges()

    def get_stats(self) -> GraphStats:
        kind_counts: dict[NodeKind, int] = {k: 0 for k in NodeKind}
        languages: set[str] = set()
        indexed_ats: list[float] = []

        for _node_id, data in self._g.nodes(data=True):
            kind = data.get("kind")
            if kind in kind_counts:
                kind_counts[kind] += 1
            rec = data.get("record")
            if isinstance(rec, FileRecord):
                if rec.language:
                    languages.add(rec.language)
                if rec.indexed_at:
                    indexed_ats.append(rec.indexed_at)

        return GraphStats(
            file_count=kind_counts[NodeKind.FILE],
            class_count=kind_counts[NodeKind.CLASS],
            function_count=kind_counts[NodeKind.FUNCTION],
            variable_count=kind_counts[NodeKind.VARIABLE],
            import_count=kind_counts[NodeKind.IMPORT],
            edge_count=self._g.number_of_edges(),
            languages=sorted(languages),
            last_indexed_at=max(indexed_ats) if indexed_ats else None,
        )

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_json(self) -> dict[str, object]:
        """D3.js / Cytoscape.js compatible JSON."""
        nodes = []
        for node_id, data in self._g.nodes(data=True):
            rec = data.get("record")
            entry: dict[str, object] = {
                "id": node_id,
                "kind": str(data.get("kind", "unknown")),
            }
            if isinstance(rec, FileRecord):
                entry["name"] = rec.path.split("/")[-1]
                entry["path"] = rec.path
            elif isinstance(rec, SymbolRecord):
                entry["name"] = rec.name
                entry["file_id"] = rec.file_id
                entry["line_start"] = rec.line_start
            nodes.append(entry)

        edges = []
        for u, v, data in self._g.edges(data=True):
            rec = data.get("record")
            entry = {
                "source": u,
                "target": v,
                "kind": str(data.get("kind", "unknown")),
            }
            if isinstance(rec, EdgeRecord):
                entry["id"] = rec.id
                entry["line_number"] = rec.line_number
                entry["weight"] = rec.weight
            edges.append(entry)

        return {"nodes": nodes, "edges": edges}

    def to_graphviz(self) -> str:
        """Generate DOT format for graphviz rendering."""
        lines = ['digraph CodePrism {', '  rankdir=LR;', '  node [shape=box];']
        for node_id, data in self._g.nodes(data=True):
            rec = data.get("record")
            if isinstance(rec, FileRecord):
                label = rec.path.split("/")[-1]
            elif isinstance(rec, SymbolRecord):
                label = rec.name
            else:
                label = node_id[:8]
            kind = str(data.get("kind", ""))
            lines.append(f'  "{node_id}" [label="{label}" tooltip="{kind}"];')

        for u, v, data in self._g.edges(data=True):
            kind = str(data.get("kind", ""))
            lines.append(f'  "{u}" -> "{v}" [label="{kind}"];')

        lines.append("}")
        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _add_file_node(self, file: FileRecord) -> None:
        self._g.add_node(file.id, kind=NodeKind.FILE, record=file)

    def _add_symbol_node(self, symbol: SymbolRecord) -> None:
        self._g.add_node(symbol.id, kind=symbol.kind, record=symbol)

    def _add_edge_record(self, edge: EdgeRecord) -> None:
        self._g.add_edge(
            edge.from_id,
            edge.to_id,
            key=edge.id,
            kind=edge.kind,
            record=edge,
        )
