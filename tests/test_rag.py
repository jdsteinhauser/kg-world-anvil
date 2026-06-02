"""Tests for RAG chunk spans, embeddings, and KNN SQL."""

from __future__ import annotations

from unittest.mock import MagicMock

from kg_world_anvil.db.repository import build_chunk_knn_sql
from kg_world_anvil.embeddings import EmbeddingClient
from kg_world_anvil.ingestion.chunker import chunk_spans, chunk_text
from kg_world_anvil.ingestion.provenance import map_extraction_span_to_chunk_seqs
from kg_world_anvil.models import ChunkRecord


def test_chunk_spans_returns_offsets_and_text():
    text = "alpha beta gamma delta epsilon"
    spans = chunk_spans(text, chunk_size=12, overlap=3)
    assert spans
    for start, end, chunk in spans:
        assert 0 <= start < end <= len(text)
        assert chunk == text[start:end].strip() or chunk in text


def test_chunk_text_matches_chunk_spans_content():
    text = "word " * 500
    assert chunk_text(text, chunk_size=200, overlap=20) == [part for _, _, part in chunk_spans(text, 200, 20)]


def test_build_chunk_knn_sql_injects_literal_k():
    sql = build_chunk_knn_sql(6, ef=40)
    assert "<|6,40|>" in sql
    assert "$qvec" in sql
    assert "vector::distance::knn()" in sql


def test_embedding_client_batches_texts(monkeypatch):
    settings = MagicMock()
    settings.openai_api_key = "test-key"
    settings.openai_embedding_model = "text-embedding-3-small"

    client = EmbeddingClient(settings)
    mock_openai = MagicMock()
    item_a = MagicMock(index=0, embedding=[0.1, 0.2])
    item_b = MagicMock(index=1, embedding=[0.3, 0.4])
    mock_openai.embeddings.create.return_value = MagicMock(data=[item_b, item_a])
    client._client = mock_openai

    vectors = client.embed_texts(["hello", "world"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    mock_openai.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input=["hello", "world"],
    )


def test_map_extraction_span_to_chunk_seqs_overlap_and_mention_filter():
    rag_chunks = [
        ChunkRecord(
            id="chunk:0",
            document_id="document:1",
            seq=0,
            text="Alice lives in Twickenham.",
            start_char=0,
            end_char=26,
        ),
        ChunkRecord(
            id="chunk:1",
            document_id="document:1",
            seq=1,
            text="The river flows nearby.",
            start_char=20,
            end_char=43,
        ),
    ]
    seqs = map_extraction_span_to_chunk_seqs(0, 30, rag_chunks, mention_texts=["Twickenham"])
    assert seqs == [0]

    seqs_broad = map_extraction_span_to_chunk_seqs(0, 30, rag_chunks)
    assert seqs_broad == [0, 1]
