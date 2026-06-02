"""Map extraction spans to RAG chunk provenance."""

from __future__ import annotations

from kg_world_anvil.models import ChunkRecord


def spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def map_extraction_span_to_chunk_seqs(
    extraction_start: int,
    extraction_end: int,
    rag_chunks: list[ChunkRecord],
    *,
    mention_texts: list[str] | None = None,
) -> list[int]:
    """Return RAG chunk seq numbers overlapping an extraction span."""
    overlapping = [
        chunk
        for chunk in rag_chunks
        if spans_overlap(extraction_start, extraction_end, chunk.start_char, chunk.end_char)
    ]
    if mention_texts and overlapping:
        matched: list[int] = []
        for chunk in overlapping:
            chunk_lower = chunk.text.casefold()
            if any(text.casefold() in chunk_lower for text in mention_texts if text.strip()):
                matched.append(chunk.seq)
        if matched:
            return sorted(set(matched))
    return sorted({chunk.seq for chunk in overlapping})
