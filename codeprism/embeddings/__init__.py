"""Optional semantic-search layer (requires sentence-transformers + chromadb).

Install with:  pip install codeprism[embeddings]
"""

from .embedder import Embedder
from .store import EmbeddingStore

__all__ = ["Embedder", "EmbeddingStore"]
