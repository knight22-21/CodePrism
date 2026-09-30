"""Supported languages and their file extensions — the single source of truth.

Used by the indexer (which files to parse), the watcher (which changes to react
to), and the config defaults. ``ParserRegistry`` must map every extension listed
here to a real parser; ``tests/test_languages.py`` enforces that.
"""

from __future__ import annotations

from collections.abc import Iterable

LANGUAGE_EXTENSIONS: dict[str, frozenset[str]] = {
    "python": frozenset({".py", ".pyi"}),
    "javascript": frozenset({".js", ".jsx", ".mjs"}),
    "typescript": frozenset({".ts", ".tsx", ".mts"}),
    "go": frozenset({".go"}),
    "rust": frozenset({".rs"}),
    "java": frozenset({".java"}),
    "c": frozenset({".c", ".h"}),
    "cpp": frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh"}),
    "ruby": frozenset({".rb", ".rake", ".gemspec"}),
    "php": frozenset({".php", ".php5", ".phtml"}),
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(LANGUAGE_EXTENSIONS)

ALL_EXTENSIONS: frozenset[str] = frozenset().union(*LANGUAGE_EXTENSIONS.values())

_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "rs": "rust",
    "c++": "cpp",
    "cxx": "cpp",
    "rb": "ruby",
}


def normalize_language(name: str) -> str:
    key = name.strip().lower()
    return _ALIASES.get(key, key)


def extensions_for(languages: Iterable[str]) -> frozenset[str]:
    """Extensions for *languages*; unknown names are ignored.

    Returns every supported extension when nothing known was requested, so a
    typo in the config never silently indexes zero files.
    """
    exts = frozenset().union(
        *(LANGUAGE_EXTENSIONS.get(normalize_language(lang), frozenset()) for lang in languages)
    )
    return exts or ALL_EXTENSIONS
