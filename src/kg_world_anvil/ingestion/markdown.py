"""Markdown to plain text."""

from markdown_it import MarkdownIt

from kg_world_anvil.ingestion.text import clean_plain_text


def clean_markdown(text: str) -> str:
    md = MarkdownIt()
    tokens = md.parse(text)
    parts: list[str] = []
    for token in tokens:
        if token.type == "inline" and token.content:
            parts.append(token.content)
        elif token.type in {"paragraph_open", "heading_open", "list_item_open"}:
            parts.append("\n")
    plain = "".join(parts)
    return clean_plain_text(plain)
