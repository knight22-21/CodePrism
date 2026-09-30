"""Process-pool worker for ProjectIndexer: read, checksum and parse a batch of files.

Parsing is CPU-bound Python (tree-sitter walk + record building), so threads are
serialized by the GIL. Each worker process builds its own ParserRegistry once —
tree-sitter parsers cannot be pickled — and returns picklable ParseResults.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..parser.base import ParseResult
from ..parser.registry import ParserRegistry

# One registry per worker process, created lazily on first use
_registry: ParserRegistry | None = None

# (file_path, stored_checksum_or_None, force)
Job = tuple[str, str | None, bool]
# ("ok", path, ParseResult) | ("skip", path, None) | ("error", path, message)
Outcome = tuple[str, str, ParseResult | str | None]


def parse_batch(jobs: list[Job]) -> list[Outcome]:
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    out: list[Outcome] = []
    for fp, stored_checksum, force in jobs:
        try:
            content = Path(fp).read_text(encoding="utf-8", errors="replace")
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if not force and stored_checksum == checksum:
                out.append(("skip", fp, None))
                continue
            out.append(("ok", fp, _registry.get(fp).parse(fp, content)))
        except Exception as exc:  # one bad file must not fail the batch
            out.append(("error", fp, f"{fp}: {exc}"))
    return out
