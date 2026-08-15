"""Base parser interface and shared result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.models import EdgeKind, EdgeRecord, FileRecord, SymbolRecord


@dataclass
class UnresolvedRef:
    """A cross-file call/inherits/imports that cannot be resolved from one file alone."""
    from_id: str
    ref_name: str      # name of the target symbol or module
    kind: EdgeKind
    file_path: str
    line_number: Optional[int] = None


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
