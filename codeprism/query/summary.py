"""Module summary — file-level narrative for a single source file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.graph import GraphEngine
from ..core.models import FileRecord, NodeKind, SymbolRecord
from ..core.storage import StorageManager


@dataclass
class ModuleSummary:
    """High-level summary of a single source file."""
    file: FileRecord
    purpose: str = ""
    public_api: list[SymbolRecord] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    complexity_score: float = 0.0
    test_coverage_file: Optional[str] = None
    key_classes: list[SymbolRecord] = field(default_factory=list)


async def get_module_summary(
    graph: GraphEngine,
    storage: StorageManager,
    file_path: str,
) -> Optional[ModuleSummary]:
    """Produce a human-readable summary of the module at *file_path*."""
    file = await storage.get_file_by_path(file_path)
    if not file:
        return None

    syms = await storage.get_symbols_for_file(file.id)

    classes   = [s for s in syms if s.kind == NodeKind.CLASS]
    functions = [s for s in syms if s.kind == NodeKind.FUNCTION]
    imports   = [s for s in syms if s.kind == NodeKind.IMPORT]

    public_api = [
        s for s in syms
        if s.is_public and s.kind in (NodeKind.FUNCTION, NodeKind.CLASS)
    ]

    # Average function complexity
    complexities = [s.complexity_score for s in functions if s.complexity_score]
    avg_complexity = sum(complexities) / len(complexities) if complexities else 0.0

    # Import names as dependencies
    dep_names = [s.name for s in imports]

    # Find a corresponding test file
    stem = Path(file_path).stem
    test_file = await _find_test_file(storage, stem, file_path)

    # Key classes — up to 5, ordered by line count (proxy for richness)
    key = sorted(
        classes,
        key=lambda s: (s.line_end or 0) - (s.line_start or 0),
        reverse=True,
    )[:5]

    purpose = _generate_purpose(stem, classes, public_api)

    return ModuleSummary(
        file=file,
        purpose=purpose,
        public_api=public_api,
        dependencies=dep_names,
        complexity_score=round(avg_complexity, 2),
        test_coverage_file=test_file,
        key_classes=key,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _find_test_file(
    storage: StorageManager,
    stem: str,
    skip_path: str,
) -> Optional[str]:
    all_files = await storage.get_all_files()
    for f in all_files:
        if f.path == skip_path:
            continue
        fname = Path(f.path).name.lower()
        if f"test_{stem}" in fname or f"{stem}_test" in fname:
            return f.path
    return None


def _generate_purpose(
    stem: str,
    classes: list[SymbolRecord],
    public_api: list[SymbolRecord],
) -> str:
    parts: list[str] = []
    if classes:
        cnames = ", ".join(s.name for s in classes[:3])
        parts.append(f"defines {cnames}")
    funcs = [s for s in public_api if s.kind == NodeKind.FUNCTION]
    if funcs:
        fnames = ", ".join(s.name for s in funcs[:3])
        parts.append(f"provides {fnames}")
    body = "; ".join(parts) if parts else "source module"
    return f"Module {stem}: {body}."
