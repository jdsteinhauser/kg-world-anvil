"""Tests for extraction deduplication."""

from kg_world_anvil.extraction.extractor import dedupe_extraction
from kg_world_anvil.models import (
    CanonicalPredicate,
    EntityAttribute,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    attributes_to_dict,
)


def test_dedupe_entities_and_relationships():
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Alice",
                type="person",
                attributes=[EntityAttribute(key="role", value="hero")],
            ),
            ExtractedEntity(
                name="alice",
                type="person",
                attributes=[EntityAttribute(key="age", value="30")],
            ),
        ],
        relationships=[
            ExtractedRelationship(
                subject="Alice",
                predicate=CanonicalPredicate.KNOWS,
                object="Bob",
                confidence=1.0,
            ),
            ExtractedRelationship(
                subject="alice",
                predicate=CanonicalPredicate.KNOWS,
                object="bob",
                confidence=1.0,
            ),
        ],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.entities) == 1
    attrs = attributes_to_dict(deduped.entities[0].attributes)
    assert attrs["role"] == "hero"
    assert attrs["age"] == "30"
    assert len(deduped.relationships) == 1
