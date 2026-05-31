"""Tests for SurrealDB record reference helpers."""

from surrealdb import RecordID

from kg_world_anvil.db.repository import _to_record_id


def test_to_record_id_adds_table_prefix():
    ref = _to_record_id("ao0fr913zp7hmh8fvpfj", "document")
    assert isinstance(ref, RecordID)
    assert ref.table_name == "document"
    assert str(ref.id) == "ao0fr913zp7hmh8fvpfj"


def test_to_record_id_preserves_existing_prefix():
    ref = _to_record_id("document:abc123", "document")
    assert isinstance(ref, RecordID)
    assert ref.table_name == "document"
    assert str(ref.id) == "abc123"


def test_to_record_id_none():
    assert _to_record_id(None, "document") is None
    assert _to_record_id("", "document") is None


def test_normalize_relation_table():
    from kg_world_anvil.db.relations import normalize_relation_table, predicate_from_record_id

    assert normalize_relation_table("parent_of") == "parent_of"
    assert normalize_relation_table("Located In") == "located_in"
    assert normalize_relation_table("123bad") == "rel_123bad"
    assert predicate_from_record_id("knows:abc123") == "knows"
