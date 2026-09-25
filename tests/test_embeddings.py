"""Tests for Embedder and EmbeddingStore (mocked optional dependencies)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_embedder(dim: int = 3):
    """Return an Embedder with a mocked sentence-transformers model."""
    from codeprism.embeddings.embedder import Embedder

    class _FakeArray:
        def __init__(self, data):
            self._data = data

        def tolist(self):
            return self._data

    mock_model = MagicMock()
    mock_model.encode.side_effect = lambda texts, **_: _FakeArray([[0.0] * dim for _ in texts])

    embedder = Embedder.__new__(Embedder)
    embedder._model = mock_model
    embedder.model_name = "test-model"
    embedder.device = "cpu"
    return embedder


def _make_store():
    """Return an EmbeddingStore with a mocked ChromaDB collection."""
    from codeprism.embeddings.store import EmbeddingStore

    mock_col = MagicMock()
    mock_col.count.return_value = 0

    store = EmbeddingStore.__new__(EmbeddingStore)
    store._client = MagicMock()
    store._col = mock_col
    return store, mock_col


# ── Embedder ──────────────────────────────────────────────────────────────────


def test_embedder_encode_returns_list_of_vectors():
    embedder = _make_embedder(dim=4)
    result = embedder.encode(["def foo(): pass", "class Bar: pass"])
    assert isinstance(result, list)
    assert len(result) == 2
    assert len(result[0]) == 4


def test_embedder_encode_empty_input_returns_empty():
    embedder = _make_embedder()
    result = embedder.encode([])
    assert result == []
    embedder._model.encode.assert_not_called()


def test_embedder_encode_one_returns_single_vector():
    embedder = _make_embedder(dim=3)
    result = embedder.encode_one("hello world")
    assert isinstance(result, list)
    assert len(result) == 3


def test_embedder_encode_one_calls_encode_with_single_item():
    embedder = _make_embedder()
    embedder.encode_one("some text")
    embedder._model.encode.assert_called_once()
    args = embedder._model.encode.call_args[0][0]
    assert args == ["some text"]


def test_embedder_raises_without_sentence_transformers():
    # Temporarily hide sentence_transformers from sys.modules
    original = sys.modules.pop("sentence_transformers", ...)
    sys.modules["sentence_transformers"] = None  # type: ignore[assignment]
    try:
        # Force re-import so the ImportError path is triggered
        import importlib

        import codeprism.embeddings.embedder as _mod

        importlib.reload(_mod)
        with pytest.raises(ImportError, match="sentence-transformers"):
            _mod.Embedder("all-MiniLM-L6-v2")
    finally:
        if original is ...:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = original
        import importlib

        import codeprism.embeddings.embedder as _mod

        importlib.reload(_mod)


# ── EmbeddingStore ────────────────────────────────────────────────────────────


def test_store_upsert_calls_chroma():
    store, col = _make_store()
    store.upsert("sym1", [0.1, 0.2, 0.3], {"name": "foo", "file_path": "a.py"})
    col.upsert.assert_called_once_with(
        ids=["sym1"],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"name": "foo", "file_path": "a.py"}],
    )


def test_store_upsert_uses_empty_metadata_by_default():
    store, col = _make_store()
    store.upsert("sym1", [0.1])
    col.upsert.assert_called_once_with(ids=["sym1"], embeddings=[[0.1]], metadatas=[{}])


def test_store_upsert_batch_skips_empty():
    store, col = _make_store()
    store.upsert_batch([], [], [])
    col.upsert.assert_not_called()


def test_store_upsert_batch_passes_correct_args():
    store, col = _make_store()
    store.upsert_batch(["s1", "s2"], [[0.1], [0.2]], [{"a": 1}, {"b": 2}])
    col.upsert.assert_called_once_with(
        ids=["s1", "s2"],
        embeddings=[[0.1], [0.2]],
        metadatas=[{"a": 1}, {"b": 2}],
    )


def test_store_count_delegates_to_chroma():
    store, col = _make_store()
    col.count.return_value = 42
    assert store.count() == 42


def test_store_delete_calls_chroma():
    store, col = _make_store()
    store.delete("sym1")
    col.delete.assert_called_once_with(ids=["sym1"])


def test_store_search_empty_collection_returns_empty():
    store, col = _make_store()
    col.count.return_value = 0
    assert store.search([0.1, 0.2]) == []
    col.query.assert_not_called()


def test_store_search_returns_correct_results():
    store, col = _make_store()
    col.count.return_value = 2
    col.query.return_value = {
        "ids": [["sym1", "sym2"]],
        "distances": [[0.1, 0.3]],
        "metadatas": [
            [
                {"file_path": "a.py", "name": "foo"},
                {"file_path": "b.py", "name": "bar"},
            ]
        ],
    }

    results = store.search([0.1, 0.2], top_k=2)
    assert len(results) == 2
    assert results[0].symbol_id == "sym1"
    assert results[0].file_path == "a.py"
    assert results[0].symbol_name == "foo"
    assert results[1].symbol_id == "sym2"
    assert results[1].distance == pytest.approx(0.3)


def test_store_search_top_k_capped_at_collection_size():
    store, col = _make_store()
    col.count.return_value = 3
    col.query.return_value = {
        "ids": [["s1"]],
        "distances": [[0.0]],
        "metadatas": [[{"file_path": "x.py", "name": "f"}]],
    }

    store.search([0.1], top_k=100)
    call_args = col.query.call_args[1]
    assert call_args["n_results"] == 3  # capped at count()


def test_store_raises_without_chromadb():
    original = sys.modules.pop("chromadb", ...)
    sys.modules["chromadb"] = None  # type: ignore[assignment]
    try:
        import importlib

        import codeprism.embeddings.store as _mod

        importlib.reload(_mod)
        with pytest.raises(ImportError, match="chromadb"):
            _mod.EmbeddingStore("/tmp/test")
    finally:
        if original is ...:
            sys.modules.pop("chromadb", None)
        else:
            sys.modules["chromadb"] = original
        import importlib

        import codeprism.embeddings.store as _mod

        importlib.reload(_mod)
