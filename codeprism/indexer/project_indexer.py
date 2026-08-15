"""Full-project indexer: parallel parse, batch persist, cross-file resolution."""

from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.config import CodePrismConfig
from ..core.graph import GraphEngine
from ..core.models import EdgeRecord, NodeKind
from ..core.storage import StorageManager
from ..parser.base import UnresolvedRef
from ..parser.registry import ParserRegistry

_DEFAULT_IGNORE = frozenset({
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "vendor", "bower_components",
    ".venv", "venv", "env",
    "dist", "build", "out", ".next", ".nuxt",
    ".tox", ".eggs",
})

_LANGUAGE_EXTENSIONS: dict[str, frozenset[str]] = {
    "python":     frozenset({".py", ".pyi"}),
    "javascript": frozenset({".js", ".jsx", ".mjs"}),
    "typescript": frozenset({".ts", ".tsx", ".mts"}),
    "go":         frozenset({".go"}),
}


@dataclass
class IndexResult:
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


class ProjectIndexer:
    """Scans a project directory, parses every source file, and builds the graph."""

    def __init__(
        self,
        graph: GraphEngine,
        storage: StorageManager,
        config: Optional[CodePrismConfig] = None,
        registry: Optional[ParserRegistry] = None,
    ) -> None:
        self._graph = graph
        self._storage = storage
        self._config = config or CodePrismConfig()
        self._registry = registry or ParserRegistry()

    # ── Public entry ─────────────────────────────────────────────────────────

    async def index(self, project_path: str) -> IndexResult:
        start = time.time()
        errors: list[str] = []

        source_files = self._find_source_files(project_path)
        if not source_files:
            return IndexResult(duration_seconds=time.time() - start)

        # Parse all files concurrently; tree-sitter is CPU-bound → thread pool
        sem = asyncio.Semaphore(8)

        async def parse_one(fp: str):
            async with sem:
                try:
                    content = await asyncio.to_thread(
                        Path(fp).read_text, encoding="utf-8", errors="replace"
                    )
                    parser = self._registry.get(fp)
                    return await asyncio.to_thread(parser.parse, fp, content)
                except Exception as exc:
                    errors.append(f"{fp}: {exc}")
                    return None

        parse_results = [
            r for r in await asyncio.gather(*[parse_one(fp) for fp in source_files])
            if r is not None
        ]

        # Batch persist: files → symbols → edges (intra-file)
        for pr in parse_results:
            await self._storage.upsert_file(pr.file)

        all_symbols = [sym for pr in parse_results for sym in pr.symbols]
        all_edges   = [edge for pr in parse_results for edge in pr.edges]

        if all_symbols:
            await self._storage.upsert_symbols_batch(all_symbols)
        if all_edges:
            await self._storage.upsert_edges_batch(all_edges)

        # Cross-file reference resolution
        all_unresolved: list[UnresolvedRef] = [
            ref for pr in parse_results for ref in pr.unresolved_refs
        ]
        if all_unresolved:
            resolved = await self._resolve_cross_file(all_unresolved)
            if resolved:
                await self._storage.upsert_edges_batch(resolved)

        # Populate in-memory graph from the now-complete storage
        await self._graph.load_from_storage(self._storage)

        stats = await self._storage.get_stats()
        return IndexResult(
            file_count=stats["file_count"],
            symbol_count=(
                stats["function_count"] + stats["class_count"]
                + stats["variable_count"] + stats["import_count"]
            ),
            edge_count=stats["edge_count"],
            duration_seconds=time.time() - start,
            errors=errors,
        )

    # ── Cross-file resolution ─────────────────────────────────────────────────

    async def _resolve_cross_file(self, unresolved: list[UnresolvedRef]) -> list[EdgeRecord]:
        all_symbols = await self._storage.get_all_symbols()

        # Build name → id map; prefer non-import symbols on collision so that
        # direct function calls point at the actual definition, not the import stub.
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

    # ── File discovery ────────────────────────────────────────────────────────

    def _find_source_files(self, project_path: str) -> list[str]:
        root = Path(project_path)

        # Which extensions to index (based on config.languages)
        exts: frozenset[str] = frozenset().union(*(
            _LANGUAGE_EXTENSIONS.get(lang, frozenset())
            for lang in self._config.languages
        )) or frozenset().union(*_LANGUAGE_EXTENSIONS.values())

        ignore_patterns = self._config.security.ignore_paths
        files: list[str] = []

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = set(path.relative_to(root).parts)
            if rel_parts & _DEFAULT_IGNORE:
                continue
            if path.suffix.lower() not in exts:
                continue
            if any(fnmatch.fnmatch(str(path), pat) for pat in ignore_patterns):
                continue
            files.append(str(path))

        return files
