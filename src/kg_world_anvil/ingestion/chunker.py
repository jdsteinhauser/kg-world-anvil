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
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        if end < len(text):
            break_at = chunk.rfind("\n\n")
            if break_at > chunk_size // 2:
                end = start + break_at
                chunk = text[start:end]
        chunks.append(chunk.strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]
