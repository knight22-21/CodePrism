"""ParserRegistry — maps file extensions to parser instances (lazy init)."""

from __future__ import annotations

from pathlib import Path

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
        if ext == ".rs":
            return self._try_build("rust", ext)
        if ext == ".java":
            return self._try_build("java", ext)
        if ext in (".c", ".h"):
            return self._try_build("c", ext)
        if ext in (".cpp", ".cc", ".cxx", ".hpp", ".hh"):
            return self._try_build("cpp", ext)
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
            if lang == "rust":
                from .rust_parser import RustParser

                return RustParser()
            if lang == "java":
                from .java_parser import JavaParser

                return JavaParser()
            if lang == "c":
                from .c_parser import CParser

                return CParser()
            if lang == "cpp":
                from .c_parser import CppParser

                return CppParser()
        except ImportError:
            pass
        return self._generic

    def register(self, extension: str, parser: BaseParser) -> None:
        """Register a custom parser for a file extension."""
        self._cache[extension.lower()] = parser

    def supported_extensions(self) -> list[str]:
        """All extensions with a non-generic parser (discovered lazily)."""
        known = [
            ".py",
            ".pyi",
            ".js",
            ".jsx",
            ".mjs",
            ".ts",
            ".tsx",
            ".mts",
            ".go",
            ".rs",
            ".java",
            ".c",
            ".h",
            ".cpp",
            ".cc",
            ".cxx",
            ".hpp",
            ".hh",
        ]
        return [e for e in known if not isinstance(self.get(f"file{e}"), GenericParser)]


# Module-level default registry
_default_registry: ParserRegistry | None = None


def get_registry() -> ParserRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ParserRegistry()
    return _default_registry
