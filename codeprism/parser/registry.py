"""ParserRegistry — maps file extensions to parser instances (lazy init)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BaseParser
from .generic_parser import GenericParser


class ParserRegistry:
    """Returns the right parser for a given file path.

    Parsers are instantiated lazily so an unavailable grammar (e.g.
    tree-sitter-go) only raises when that language is actually needed.
    """

    def __init__(self) -> None:
        self._cache: dict[str, BaseParser] = {}
        self._generic = GenericParser()

    def get(self, file_path: str) -> BaseParser:
        """Return the parser for *file_path*, falling back to GenericParser."""
        ext = Path(file_path).suffix.lower()
        if ext in self._cache:
            return self._cache[ext]

        parser = self._build(ext)
        self._cache[ext] = parser
        return parser

    def _build(self, ext: str) -> BaseParser:
        if ext in (".py", ".pyi"):
            return self._try_build("python", ext)
        if ext in (".js", ".jsx", ".mjs", ".ts", ".tsx", ".mts"):
            return self._try_build("javascript", ext)
        if ext == ".go":
            return self._try_build("go", ext)
        return self._generic

    def _try_build(self, lang: str, ext: str) -> BaseParser:
        try:
            if lang == "python":
                from .python_parser import PythonParser
                return PythonParser()
            if lang == "javascript":
                from .javascript_parser import JavaScriptParser
                return JavaScriptParser()
            if lang == "go":
                from .go_parser import GoParser
                return GoParser()
        except ImportError:
            pass
        return self._generic

    def register(self, extension: str, parser: BaseParser) -> None:
        """Register a custom parser for a file extension."""
        self._cache[extension.lower()] = parser

    def supported_extensions(self) -> list[str]:
        """All extensions with a non-generic parser (discovered lazily)."""
        known = [".py", ".pyi", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".mts", ".go"]
        return [e for e in known if not isinstance(self.get(f"file{e}"), GenericParser)]


# Module-level default registry
_default_registry: Optional[ParserRegistry] = None


def get_registry() -> ParserRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ParserRegistry()
    return _default_registry
