"""Generic line-counting fallback for unsupported file types."""

from __future__ import annotations

import hashlib
import os
import time

from ..core.models import FileRecord, make_file_id
from .base import BaseParser, ParseResult


class GenericParser(BaseParser):
    """Creates a FileRecord for any file type; extracts no symbols."""

    def __init__(self, language_name: str = "unknown", extensions: list[str] | None = None) -> None:
        self._language_name = language_name
        self._extensions = extensions or []

    @property
    def language_name(self) -> str:
        return self._language_name

    @property
    def supported_extensions(self) -> list[str]:
        return self._extensions

    def parse(self, file_path: str, content: str) -> ParseResult:
        source = content.encode("utf-8")
        file_id = make_file_id(file_path)

        try:
            last_modified = os.path.getmtime(file_path)
        except OSError:
            last_modified = 0.0

        file_rec = FileRecord(
            id=file_id,
            path=file_path,
            language=self._language_name if self._language_name != "unknown" else None,
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )
        return ParseResult(file=file_rec)
