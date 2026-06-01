"""Tests for entity name normalization."""

from kg_world_anvil.extraction.extractor import dedupe_extraction
from kg_world_anvil.models import ExtractedEntity, ExtractionResult
from kg_world_anvil.normalization.names import (
    canonical_key,
    entity_identity_key,
    names_equivalent,
    normalize_entity_name,
)


def test_normalize_entity_name_strips_leading_articles():
    assert normalize_entity_name("the mayor") == "mayor"
    assert normalize_entity_name("The Mayor") == "Mayor"
    assert normalize_entity_name("a city council") == "city council"
    assert normalize_entity_name("An Old Bridge") == "Old Bridge"


def test_normalize_entity_name_strips_quotes_and_punctuation():
    assert normalize_entity_name('"the mayor"') == "mayor"
    assert normalize_entity_name("Mayor.") == "Mayor"
    assert normalize_entity_name("**mayor**") == "mayor"


def test_canonical_key_collapses_article_variants():
    assert canonical_key("mayor") == canonical_key("the mayor")
    assert names_equivalent("mayor", "the mayor")


def test_entity_identity_key_uses_canonical_name():
    assert entity_identity_key("The Mayor", "person") == entity_identity_key("mayor", "person")


def test_dedupe_extraction_merges_article_variants():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(name="mayor", type="role", attributes=[]),
            ExtractedEntity(name="the mayor", type="role", attributes=[]),
        ],
        relationships=[],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 1
    assert deduped.entities[0].name == "mayor"
