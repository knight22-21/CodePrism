"""EmbeddingStore — wraps ChromaDB for symbol vector storage and nearest-neighbour search."""

from __future__ import annotations

from dataclasses import dataclass, field

_IMPORT_ERROR = (
    "chromadb is required for embeddings support.\n"
    "Install with:  pip install codeprism[embeddings]"
)


@dataclass
class SearchResult:
    symbol_id: str
    file_path: str
    symbol_name: str
    distance: float
    metadata: dict = field(default_factory=dict)


class EmbeddingStore:
    """
    Persistent vector store backed by ChromaDB.

    Usage::

        store = EmbeddingStore(persist_directory="/path/to/.codeprism/chroma")
        store.upsert("sym_id", [0.1, 0.2, ...], {"name": "process", "file": "a.py"})
        results = store.search([0.1, 0.2, ...], top_k=5)
    """

    _COLLECTION_NAME = "codeprism_symbols"

    def __init__(self, persist_directory: str) -> None:
        try:
            import chromadb  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(_IMPORT_ERROR) from exc

        self._client = chromadb.PersistentClient(path=persist_directory)
        self._col = self._client.get_or_create_collection(
            name=self._COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        symbol_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        """Insert or update a symbol vector."""
        self._col.upsert(
            ids=[symbol_id],
            embeddings=[vector],
            metadatas=[metadata or {}],
        )

    def upsert_batch(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Batch insert/update for indexing many symbols at once."""
        if not ids:
            return
        self._col.upsert(
            ids=ids,
            embeddings=vectors,
            metadatas=metadatas or [{} for _ in ids],
        )

    def search(self, query_vector: list[float], top_k: int = 10) -> list[SearchResult]:
        """Return the top-k nearest symbols by cosine distance."""
        if self._col.count() == 0:
            return []
        results = self._col.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, self._col.count()),
            include=["metadatas", "distances"],
        )
        output: list[SearchResult] = []
        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]
        for sym_id, dist, meta in zip(ids, distances, metadatas):
            output.append(
                SearchResult(
                    symbol_id=sym_id,
                    file_path=meta.get("file_path", ""),
                    symbol_name=meta.get("name", ""),
                    distance=dist,
                    metadata=meta,
                )
            )
        return output

    def delete(self, symbol_id: str) -> None:
        """Remove a symbol vector (e.g. when a symbol is deleted from the graph)."""
        self._col.delete(ids=[symbol_id])

    def count(self) -> int:
        return self._col.count()
