"""Tests for relationship predicate filtering."""

from kg_world_anvil.extraction.extractor import dedupe_extraction
from kg_world_anvil.extraction.extractor import filter_negated_relationships
from kg_world_anvil.extraction.predicates import (
    is_absence_relationship,
    is_relationship_negated_in_text,
)
from kg_world_anvil.models import (
    CanonicalPredicate,
    ExtractedRelationship,
    ExtractionResult,
)


def test_is_absence_relationship_detects_negated_predicates():
    assert is_absence_relationship("not_associated_with")
    assert is_absence_relationship("not_linked_to")
    assert is_absence_relationship("not_related_to")
    assert is_absence_relationship("unrelated_to")
    assert is_absence_relationship("without_connection")
    assert is_absence_relationship("lacks_link_to")


def test_is_absence_relationship_allows_positive_predicates():
    assert not is_absence_relationship("parent_of")
    assert not is_absence_relationship("located_in")
    assert not is_absence_relationship("member_of")
    assert not is_absence_relationship("north_of")


def test_dedupe_extraction_merges_relationship_detail():
    result = ExtractionResult(
        entities=[],
        relationships=[
            ExtractedRelationship(
                subject="Alice",
                predicate=CanonicalPredicate.MEMBER_OF,
                object="council",
                confidence=1.0,
                detail="",
            ),
            ExtractedRelationship(
                subject="Alice",
                predicate=CanonicalPredicate.MEMBER_OF,
                object="council",
                confidence=0.9,
                detail="serves as mayor",
            ),
        ],
    )
    deduped = dedupe_extraction(result)
    assert len(deduped.relationships) == 1
    assert deduped.relationships[0].detail == "serves as mayor"


def test_is_relationship_negated_in_text_detects_negation():
    text = (
        "## Overview\n\n**Juniper Belle** was a prize-winning Jersey cow. "
        "She was not associated with The Archivists."
    )
    assert is_relationship_negated_in_text("Juniper Belle", "The Archivists", text)


def test_is_relationship_negated_in_text_allows_positive_link():
    text = "Juniper Belle was associated with the local dairy cooperative."
    assert not is_relationship_negated_in_text("Juniper Belle", "local dairy cooperative", text)


def test_filter_negated_relationships_drops_inverted_associated_with():
    text = "Alice was not associated with Bob."
    result = ExtractionResult(
        entities=[],
        relationships=[
            ExtractedRelationship(
                subject="Alice",
                predicate=CanonicalPredicate.ASSOCIATED_WITH,
                object="Bob",
                confidence=0.9,
            ),
        ],
    )
    filtered = filter_negated_relationships(result, text)
    assert filtered.relationships == []


def test_canonical_predicate_enum_values():
    assert CanonicalPredicate.MEMBER_OF.value == "member_of"
    assert len(CanonicalPredicate) >= 20
