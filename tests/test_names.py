"""Tests for entity lookup keys."""

from kg_world_anvil.extraction.extractor import dedupe_extraction
from kg_world_anvil.models import ExtractedEntity, ExtractionResult
from kg_world_anvil.normalization.names import canonical_key, entity_identity_key, normalize_display_name


def test_canonical_key_collapses_whitespace_and_case():
    assert canonical_key("  Alice  ") == "alice"
    assert canonical_key("Bob\tSmith") == "bob smith"
    assert canonical_key("Alice") == canonical_key("alice")


def test_canonical_key_preserves_distinct_surface_forms():
    assert canonical_key("the mayor") != canonical_key("mayor")
    assert canonical_key("Twickenham") != canonical_key("city")


def test_canonical_key_strips_indefinite_articles():
    assert canonical_key("a Twickenham") == canonical_key("Twickenham")
    assert canonical_key("an Oran County") == canonical_key("Oran County")
    assert normalize_display_name("a Twickenham") == "Twickenham"


def test_canonical_key_keeps_definite_article_in_proper_names():
    assert normalize_display_name("The Hague") == "The Hague"
    assert canonical_key("The Hague") == "the hague"


def test_canonical_key_unifies_multi_word_the_variants():
    assert canonical_key("The Hollow Spine") == canonical_key("Hollow Spine")
    assert normalize_display_name("The Hollow Spine") == "Hollow Spine"
    assert normalize_display_name("the hollow spine") == "hollow spine"


def test_canonical_key_keeps_the_before_single_word():
    assert normalize_display_name("The Beatles") == "The Beatles"
    assert canonical_key("The Beatles") != canonical_key("Beatles")


def test_entity_identity_key_uses_canonical_name():
    assert entity_identity_key("Alice", "person") == entity_identity_key("alice", "person")
    assert entity_identity_key("The Mayor", "person") != entity_identity_key("mayor", "person")


def test_dedupe_extraction_merges_case_variants_only():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Alice", type="person", attributes=[]),
            ExtractedEntity(name="alice", type="person", attributes=[]),
        ],
        relationships=[],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 1
    assert deduped.entities[0].name == "Alice"


def test_dedupe_extraction_merges_indefinite_article_variants():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Twickenham", type="city", attributes=[]),
            ExtractedEntity(name="a Twickenham", type="city", attributes=[]),
        ],
        relationships=[],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 1
    assert deduped.entities[0].name == "Twickenham"


def test_dedupe_extraction_merges_the_prefix_on_multi_word_names():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Hollow Spine", type="location", attributes=[]),
            ExtractedEntity(name="The Hollow Spine", type="location", attributes=[]),
        ],
        relationships=[],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 1
    assert deduped.entities[0].name == "Hollow Spine"


def test_dedupe_extraction_does_not_merge_article_variants():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(name="mayor", type="role", attributes=[]),
            ExtractedEntity(name="the mayor", type="role", attributes=[]),
        ],
        relationships=[],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 2
