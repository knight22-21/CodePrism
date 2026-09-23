"""Base parser interface and shared result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import EdgeKind, EdgeRecord, FileRecord, NodeKind, SymbolRecord


@dataclass
class UnresolvedRef:
    """A cross-file call/inherits/imports that cannot be resolved from one file alone."""
    from_id: str
    ref_name: str      # name of the target symbol or module
    kind: EdgeKind
    file_path: str
    line_number: int | None = None


@dataclass
class ParseResult:
    """Everything a parser extracted from a single file."""
    file: FileRecord
    symbols: list[SymbolRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)
    unresolved_refs: list[UnresolvedRef] = field(default_factory=list)


class BaseParser(ABC):
    """Abstract base for all language parsers."""

    @abstractmethod
    def parse(self, file_path: str, content: str) -> ParseResult:
        """Parse source content and return extracted graph data."""
        ...

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Canonical language name (e.g. 'python', 'javascript')."""
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this parser handles (e.g. ['.py', '.pyi'])."""
        ...

    def can_parse(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in self.supported_extensions

    @staticmethod
    def resolve_intrafile_refs(result: ParseResult, name_to_id: dict[str, str]) -> None:
        """
        Resolve unresolved refs that can be satisfied within a single file's symbol table.

        CALLS refs that match an IMPORT stub are intentionally left unresolved so the
        cross-file resolver can wire them to the actual definition. Without this, a call
        like `run_payment -> compute_checksum` in main.py resolves to the import stub
        instead of the real function in processor.py, and the caller never appears in
        get_callers() results.
        """
        import_ids = {sym.id for sym in result.symbols if sym.kind == NodeKind.IMPORT}

        still: list[UnresolvedRef] = []
        for ref in result.unresolved_refs:
            target_id = name_to_id.get(ref.ref_name)
            # Leave cross-file calls for _resolve_cross_file in the indexer.
            if ref.kind == EdgeKind.CALLS and target_id in import_ids:
                still.append(ref)
                continue
            if target_id and target_id != ref.from_id:
                result.edges.append(EdgeRecord.create(
                    kind=ref.kind,
                    from_id=ref.from_id,
                    to_id=target_id,
                    file_path=ref.file_path,
                    line_number=ref.line_number,
                ))
            else:
                still.append(ref)
        result.unresolved_refs = still
