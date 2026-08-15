"""Embedder — wraps sentence-transformers to produce symbol/docstring vectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_IMPORT_ERROR = (
    "sentence-transformers is required for embeddings support.\n"
    "Install with:  pip install codeprism[embeddings]"
)


class Embedder:
    """
    Thin wrapper around sentence-transformers SentenceTransformer.

    Usage::

        embedder = Embedder("all-MiniLM-L6-v2")
        vectors = embedder.encode(["def process(): ...", "class Foo: ..."])
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(_IMPORT_ERROR) from exc

        self._model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name
        self.device = device

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return a list of embedding vectors (one per input text)."""
        if not texts:
            return []
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def encode_one(self, text: str) -> list[float]:
        """Convenience wrapper for a single string."""
        return self.encode([text])[0]
