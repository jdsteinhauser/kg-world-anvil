"""Text chunking for LLM extraction."""

from __future__ import annotations

from kg_world_anvil.models import TextFormat


def detect_format(text: str, hint: TextFormat | None = None) -> TextFormat:
    if hint and hint != TextFormat.PLAIN:
        return hint
    stripped = text.lstrip()
    if stripped.startswith("<") and ">" in stripped[:500]:
        return TextFormat.HTML
    if "[/" in text or re_bbcode_tag(text):
        return TextFormat.BBCODE
    if any(marker in text for marker in ("# ", "## ", "```", "**", "- ")):
        return TextFormat.MARKDOWN
    return TextFormat.PLAIN


def re_bbcode_tag(text: str) -> bool:
    import re

    return bool(re.search(r"\[[a-z]+(?:=[^\]]+)?\]", text, re.I))


def clean_text(text: str, fmt: TextFormat) -> str:
    from kg_world_anvil.ingestion.bbcode import clean_bbcode
    from kg_world_anvil.ingestion.html import clean_html
    from kg_world_anvil.ingestion.markdown import clean_markdown
    from kg_world_anvil.ingestion.text import clean_plain_text

    cleaners = {
        TextFormat.PLAIN: clean_plain_text,
        TextFormat.HTML: clean_html,
        TextFormat.MARKDOWN: clean_markdown,
        TextFormat.BBCODE: clean_bbcode,
    }
    return cleaners[fmt](text)


def chunk_text(text: str, chunk_size: int = 4000, overlap: int = 400) -> list[str]:
    return [chunk for _, _, chunk in chunk_spans(text, chunk_size, overlap)]


def chunk_spans(
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[tuple[int, int, str]]:
    """Split text into overlapping spans with char offsets in the source string."""
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        stripped = text.strip()
        start = text.find(stripped)
        if start < 0:
            start = 0
        return [(start, start + len(stripped), stripped)]

    spans: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        if end < len(text):
            break_at = chunk.rfind("\n\n")
            if break_at > chunk_size // 2:
                end = start + break_at
                chunk = text[start:end]
        stripped = chunk.strip()
        if stripped:
            strip_offset = chunk.find(stripped)
            actual_start = start + strip_offset
            actual_end = actual_start + len(stripped)
            spans.append((actual_start, actual_end, stripped))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return spans
