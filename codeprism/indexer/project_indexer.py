"""Full-project indexer: parallel parse, batch persist, cross-file resolution."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..core.config import CodePrismConfig
from ..core.gitignore import git_listed_files
from ..core.graph import GraphEngine
from ..core.languages import extensions_for
from ..core.models import EdgeRecord, NodeKind
from ..core.storage import StorageManager
from ..parser.base import UnresolvedRef
from ..parser.registry import ParserRegistry
from . import _parse_worker

_DEFAULT_IGNORE = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "vendor",
        "bower_components",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        ".tox",
        ".eggs",
    }
)

# Below this many candidate files, process start-up costs more than it saves
_POOL_MIN_FILES = 200
_POOL_BATCH = 64
# ProcessPoolExecutor on Windows allows at most 61 workers
_MAX_WORKERS = 61


@dataclass
class IndexResult:
    file_count: int = 0
    files_skipped: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    # True when the stored index predated the current format and was rebuilt
    format_upgraded: bool = False

    @property
    def success(self) -> bool:
        return not self.errors


class ProjectIndexer:
    """Scans a project directory, parses every source file, and builds the graph."""

    def __init__(
        self,
        graph: GraphEngine,
        storage: StorageManager,
        config: CodePrismConfig | None = None,
        registry: ParserRegistry | None = None,
    ) -> None:
        self._graph = graph
        self._storage = storage
        self._config = config or CodePrismConfig()
        # Worker processes build their own default registry, so a caller-supplied
        # one (custom parsers) forces the in-process path.
        self._custom_registry = registry is not None
        self._registry = registry or ParserRegistry()

    # ── Public entry ─────────────────────────────────────────────────────────

    async def index(self, project_path: str, force: bool = False) -> IndexResult:
        """Index *project_path*.

        When *force* is False (default) files whose SHA-256 checksum matches
        the stored record are skipped — only changed, new, and deleted files
        are processed.  Pass ``force=True`` to always re-parse everything.
        """
        start = time.time()
        errors: list[str] = []

        # An index written by an older format can't be trusted file-by-file:
        # checksums match but the stored rows are stale. Re-parse everything.
        format_upgraded = not force and await self._storage.index_is_outdated()
        if format_upgraded:
            force = True

        source_files = self._find_source_files(project_path)

        # Everything currently stored, keyed by path. Needed even with force=True
        # so deleted files are purged and re-parsed files replace their old rows.
        stored = {rec.path: rec for rec in await self._storage.get_all_files()}
        # Checksums for incremental skipping (empty when force=True)
        existing: dict[str, str] = (
            {} if force else {path: rec.checksum or "" for path, rec in stored.items()}
        )

        # Remove records for files that were deleted since last index
        on_disk = set(source_files)
        removed_any = False
        for path, rec in stored.items():
            if path not in on_disk:
                await self._storage.delete_edges_for_file(path)
                await self._storage.delete_symbols_for_file(rec.id)
                await self._storage.delete_file(rec.id)
                removed_any = True

        if not source_files:
            if removed_any:
                await self._storage.delete_dangling_edges()
            await self._storage.set_index_format_version()
            await self._graph.load_from_storage(self._storage)
            return IndexResult(
                duration_seconds=time.time() - start, format_upgraded=format_upgraded
            )

        # Parse changed / new files; unchanged ones are skipped by checksum
        parse_results, skipped = None, 0
        if self._use_process_pool(len(source_files)):
            try:
                parse_results, skipped = await self._parse_in_processes(
                    source_files, existing, force, errors
                )
            except Exception:  # broken pool / spawn not permitted: fall back
                parse_results, skipped = None, 0
                errors.clear()
        if parse_results is None:
            parse_results, skipped = await self._parse_in_threads(
                source_files, existing, force, errors
            )

        # Drop the previous symbols/edges of every re-parsed file first; upserting
        # alone would leave renamed symbols and line-shifted edges behind.
        await self._storage.clear_files_contents(
            [stored[pr.file.path] for pr in parse_results if pr.file.path in stored]
        )

        # Batch persist: files → symbols → edges (intra-file)
        await self._storage.upsert_files_batch([pr.file for pr in parse_results])

        all_symbols = [sym for pr in parse_results for sym in pr.symbols]
        all_edges = [edge for pr in parse_results for edge in pr.edges]

        if all_symbols:
            await self._storage.upsert_symbols_batch(all_symbols)
        if all_edges:
            await self._storage.upsert_edges_batch(all_edges)

        # Cross-file reference resolution (only for newly parsed files)
        all_unresolved: list[UnresolvedRef] = [
            ref for pr in parse_results for ref in pr.unresolved_refs
        ]
        if all_unresolved:
            resolved = await self._resolve_cross_file(all_unresolved)
            if resolved:
                await self._storage.upsert_edges_batch(resolved)

        # Edges from unchanged files may still point at symbols that were just
        # renamed or deleted; drop them rather than loading ghost nodes.
        if removed_any or any(pr.file.path in stored for pr in parse_results):
            await self._storage.delete_dangling_edges()

        # Populate in-memory graph from the now-complete storage
        await self._graph.load_from_storage(self._storage)

        # Optionally build vector index for semantic search
        if self._config.enable_embeddings:
            await self._build_embeddings(project_path, all_symbols)

        await self._storage.set_index_format_version()

        stats = await self._storage.get_stats()
        return IndexResult(
            file_count=stats["file_count"],
            files_skipped=skipped,
            symbol_count=(
                stats["function_count"]
                + stats["class_count"]
                + stats["variable_count"]
                + stats["import_count"]
            ),
            edge_count=stats["edge_count"],
            duration_seconds=time.time() - start,
            errors=errors,
            format_upgraded=format_upgraded,
        )

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _worker_count(self) -> int:
        n = self._config.parse_workers or (os.cpu_count() or 1)
        return max(1, min(n, _MAX_WORKERS))

    def _use_process_pool(self, candidate_files: int) -> bool:
        return (
            not self._custom_registry
            and candidate_files >= _POOL_MIN_FILES
            and self._worker_count() > 1
        )

    async def _parse_in_processes(self, source_files, existing, force, errors):
        """CPU-bound parsing across worker processes (sidesteps the GIL)."""
        jobs = [(fp, existing.get(fp), force) for fp in source_files]
        batches = [jobs[i : i + _POOL_BATCH] for i in range(0, len(jobs), _POOL_BATCH)]
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=self._worker_count()) as pool:
            outcomes = await asyncio.gather(
                *[loop.run_in_executor(pool, _parse_worker.parse_batch, b) for b in batches]
            )
        results, skipped = [], 0
        for batch in outcomes:
            for status, _fp, payload in batch:
                if status == "ok":
                    results.append(payload)
                elif status == "skip":
                    skipped += 1
                else:
                    errors.append(payload)
        return results, skipped

    async def _parse_in_threads(self, source_files, existing, force, errors):
        sem = asyncio.Semaphore(8)
        skipped = 0

        async def parse_one(fp: str):
            nonlocal skipped
            async with sem:
                try:
                    content = await asyncio.to_thread(
                        Path(fp).read_text, encoding="utf-8", errors="replace"
                    )
                    new_checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    if not force and existing.get(fp) == new_checksum:
                        skipped += 1
                        return None
                    parser = self._registry.get(fp)
                    return await asyncio.to_thread(parser.parse, fp, content)
                except Exception as exc:
                    errors.append(f"{fp}: {exc}")
                    return None

        results = [
            r
            for r in await asyncio.gather(*[parse_one(fp) for fp in source_files])
            if r is not None
        ]
        return results, skipped

    # ── Cross-file resolution ─────────────────────────────────────────────────

    async def _resolve_cross_file(self, unresolved: list[UnresolvedRef]) -> list[EdgeRecord]:
        # name → id for just the referenced names; non-import symbols win on
        # collision so calls point at the definition, not the import stub.
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

    # ── Embeddings builder ────────────────────────────────────────────────────

    async def _build_embeddings(self, project_path: str, symbols: list) -> None:
        from ..core.paths import get_chroma_path

        try:
            from ..embeddings.embedder import Embedder
            from ..embeddings.store import EmbeddingStore
        except ImportError:
            return

        try:
            embedder = Embedder(
                model_name=self._config.embeddings.model,
                device=self._config.embeddings.device,
            )
            store = EmbeddingStore(str(get_chroma_path(project_path)))
        except ImportError:
            return

        all_files = await self._storage.get_all_files()
        id_to_path = {f.id: f.path for f in all_files}

        meaningful = [
            s for s in symbols if s.kind in {NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.VARIABLE}
        ]
        if not meaningful:
            return

        texts = []
        for sym in meaningful:
            parts = [sym.kind.value, sym.name]
            if sym.signature:
                parts.append(sym.signature)
            if sym.docstring:
                parts.append(sym.docstring[:200])
            texts.append(" ".join(parts))

        vectors = await asyncio.to_thread(embedder.encode, texts)

        ids = [sym.id for sym in meaningful]
        metadatas = [
            {
                "name": sym.name,
                "kind": sym.kind.value,
                "file_path": id_to_path.get(sym.file_id, ""),
                "line_start": sym.line_start or 0,
                "signature": sym.signature or "",
            }
            for sym in meaningful
        ]
        store.upsert_batch(ids, vectors, metadatas)

    # ── File discovery ────────────────────────────────────────────────────────

    def _find_source_files(self, project_path: str) -> list[str]:
        # Absolute root, so stored paths are the same whether the project was
        # indexed as "." from the CLI or by absolute path from the MCP server.
        root = Path(project_path).resolve()

        # Which extensions to index (based on config.languages)
        exts = extensions_for(self._config.languages)

        ignore_patterns = self._config.security.ignore_paths

        def keep(path: Path) -> bool:
            if path.suffix.lower() not in exts or not path.is_file():
                return False
            if set(path.relative_to(root).parts) & _DEFAULT_IGNORE:
                return False
            return not any(fnmatch.fnmatch(str(path), pat) for pat in ignore_patterns)

        walked = (
            [p for p in sorted(root.rglob("*")) if keep(p)]
            if not self._config.respect_gitignore
            else None
        )
        if walked is not None:
            return [str(p) for p in walked]

        # Ask git which files belong to the project: exact .gitignore semantics,
        # and no walk through ignored trees (node_modules, vendored checkouts).
        listed = git_listed_files(root)
        if listed:
            files = [p for p in sorted(set(listed)) if keep(p)]
            if files:
                return [str(p) for p in files]
        # Not a git repo, git unavailable, or the root itself is ignored (an
        # explicit request to index it): fall back to walking the directory.
        return [str(p) for p in sorted(root.rglob("*")) if keep(p)]
