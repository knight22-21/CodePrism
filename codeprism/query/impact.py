"""Impact analysis — transitive change-surface for a symbol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..core.graph import GraphEngine
from ..core.models import FileRecord, NodeKind, SymbolRecord
from ..core.storage import StorageManager
from .context import _pick


@dataclass
class ImpactResult:
    """Transitive impact of changing a single symbol."""
    symbol: SymbolRecord
    direct_dependents: list[SymbolRecord] = field(default_factory=list)
    transitive_dependents: list[SymbolRecord] = field(default_factory=list)
    severity: str = "LOW"          # LOW | MEDIUM | HIGH | CRITICAL
    affected_test_files: list[str] = field(default_factory=list)
    public_api_affected: bool = False
    estimated_change_surface: int = 0


async def get_impact(
    graph: GraphEngine,
    storage: StorageManager,
    file_path: str,
    symbol_name: str,
) -> Optional[ImpactResult]:
    """Return the full impact analysis for changing *symbol_name* in *file_path*."""
    file = await storage.get_file_by_path(file_path)
    if not file:
        return None

    syms = await storage.get_symbols_for_file(file.id)
    sym = _pick(syms, symbol_name)
    if not sym:
        return None

    # Direct callers (symbols that call this one)
    direct_callers = graph.get_callers(sym.id)

    # Full transitive set of dependents (ancestors in the directed graph)
    transitive_ids = graph.get_transitive_dependents(sym.id)

    # Resolve to SymbolRecords where possible; cap at 100 to stay compact
    transitive_syms: list[SymbolRecord] = []
    for tid in transitive_ids:
        rec = graph.get_symbol(tid)
        if rec:
            transitive_syms.append(rec)
    transitive_syms = transitive_syms[:100]

    # Map file_id → path for test-file detection
    all_files = await storage.get_all_files()
    id_to_path = {f.id: f.path for f in all_files}

    test_files: list[str] = []
    seen_test = set()
    for rec in transitive_syms:
        fp = id_to_path.get(rec.file_id, "")
        if "test" in fp.lower() and fp not in seen_test:
            seen_test.add(fp)
            test_files.append(fp)

    n = len(transitive_ids)
    public_api = sym.is_public and len(direct_callers) > 0
    severity = _severity(n, public_api)

    return ImpactResult(
        symbol=sym,
        direct_dependents=direct_callers,
        transitive_dependents=transitive_syms,
        severity=severity,
        affected_test_files=test_files,
        public_api_affected=public_api,
        estimated_change_surface=n,
    )


def _severity(n_transitive: int, public_api: bool) -> str:
    if public_api or n_transitive > 20:
        return "CRITICAL"
    if n_transitive > 10:
        return "HIGH"
    if n_transitive > 3:
        return "MEDIUM"
    return "LOW"
