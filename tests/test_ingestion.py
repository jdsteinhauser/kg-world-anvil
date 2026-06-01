"""Tests for ingestion and normalization."""

from kg_world_anvil.ingestion.bbcode import clean_bbcode
from kg_world_anvil.ingestion.chunker import chunk_text, clean_text, detect_format
from kg_world_anvil.ingestion.html import clean_html
from kg_world_anvil.ingestion.markdown import clean_markdown
from kg_world_anvil.models import TextFormat
from kg_world_anvil.normalization.names import canonical_key
from kg_world_anvil.normalization.resolver import cosine_similarity
from kg_world_anvil.query.queries import validate_readonly


def test_clean_html_strips_tags():
    html = "<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
    assert "Title" in clean_html(html)
    assert "<" not in clean_html(html)


def test_clean_markdown():
    md = "# Heading\n\nSome **bold** text."
    plain = clean_markdown(md)
    assert "Heading" in plain
    assert "bold" in plain


def test_clean_bbcode():
    text = "[b]Bold[/b] and [i]italic[/i]"
    plain = clean_bbcode(text)
    assert "Bold" in plain
    assert "[" not in plain


def test_detect_format():
    assert detect_format("<p>Hi</p>") == TextFormat.HTML
    assert detect_format("[b]Hi[/b]") == TextFormat.BBCODE
    assert detect_format("# Title\n\nBody") == TextFormat.MARKDOWN
    assert detect_format("Plain text") == TextFormat.PLAIN


def test_chunk_text_overlap():
    text = "word " * 2000
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


def test_canonical_key():
    assert canonical_key("  Alice  ") == "alice"
    assert canonical_key("Bob\tSmith") == "bob smith"
    assert canonical_key("the mayor") == "the mayor"


def test_cosine_similarity():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_validate_readonly_blocks_mutations():
    validate_readonly("SELECT * FROM entity;")
    try:
        validate_readonly("CREATE entity SET name = 'x';")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_clean_text_pipeline():
    assert clean_text("Hello", TextFormat.PLAIN) == "Hello"
    assert "Hi" in clean_text("<p>Hi</p>", TextFormat.HTML)
