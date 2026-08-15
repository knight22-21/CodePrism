"""Context assembly — builds the minimal LLM context packet for a symbol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..core.graph import GraphEngine
from ..core.models import FileRecord, NodeKind, SymbolRecord
from ..core.storage import StorageManager


@dataclass
class ContextResult:
    """Structured context packet for a single symbol."""
    symbol: SymbolRecord
    file: FileRecord
    direct_callers: list[SymbolRecord] = field(default_factory=list)
    direct_callees: list[SymbolRecord] = field(default_factory=list)
    related_types: list[SymbolRecord] = field(default_factory=list)
    relevant_variables: list[SymbolRecord] = field(default_factory=list)
    estimated_token_count: int = 0


async def get_context(
    graph: GraphEngine,
    storage: StorageManager,
    file_path: str,
    symbol_name: str,
    depth: int = 2,
) -> Optional[ContextResult]:
    """Assemble the minimal structured context for *symbol_name* in *file_path*.

    depth=1 — symbol + direct callers/callees
    depth=2 — + their direct neighbours (recommended)
    depth=3 — full transitive neighbourhood (expensive for large graphs)
    """
    file = await storage.get_file_by_path(file_path)
    if not file:
        return None

    syms = await storage.get_symbols_for_file(file.id)
    sym = _pick(syms, symbol_name)
    if not sym:
        return None

    callers = graph.get_callers(sym.id)
    callees = graph.get_callees(sym.id)

    # Neighbourhood at *depth* — limit to symbol nodes only
    neighbor_ids = graph.get_neighbors(sym.id, depth)
    neighbor_syms = [graph.get_symbol(nid) for nid in neighbor_ids]
    neighbor_syms = [s for s in neighbor_syms if s is not None]

    related_types = [s for s in neighbor_syms if s.kind == NodeKind.TYPE]
    relevant_vars  = [s for s in neighbor_syms if s.kind == NodeKind.VARIABLE]

    # Rough token estimate: ~200 base + ~50 per returned symbol
    unique_count = 1 + len({s.id for s in callers + callees})
    token_est = 200 + 50 * unique_count

    return ContextResult(
        symbol=sym,
        file=file,
        direct_callers=callers[:20],
        direct_callees=callees[:20],
        related_types=related_types[:10],
        relevant_variables=relevant_vars[:10],
        estimated_token_count=token_est,
    )


def _pick(syms: list[SymbolRecord], name: str) -> Optional[SymbolRecord]:
    matches = [s for s in syms if s.name == name]
    if not matches:
        return None
    preferred = [s for s in matches if s.kind in (NodeKind.FUNCTION, NodeKind.CLASS)]
    return preferred[0] if preferred else matches[0]
