"""Tests for canonical predicate helpers."""

from kg_world_anvil.extraction.extractor import SYSTEM_PROMPT
from kg_world_anvil.models import CanonicalPredicate, format_predicate_prompt, predicate_values


def test_predicate_values_lists_all_enum_members():
    values = predicate_values()
    assert "member_of" in values
    assert "associated_with" in values
    assert len(values) == len(CanonicalPredicate)


def test_format_predicate_prompt_includes_key_predicates():
    prompt = format_predicate_prompt()
    assert "member_of" in prompt
    assert "associated_with" in prompt
    assert "detail" in prompt


def test_system_prompt_prefers_specific_place_names():
    assert "most specific proper name" in SYSTEM_PROMPT
    assert "Twickenham" in SYSTEM_PROMPT
    assert "Oran County" in SYSTEM_PROMPT
    assert "NOT \"city\"" in SYSTEM_PROMPT or 'NOT "city"' in SYSTEM_PROMPT


def test_system_prompt_roles_as_relationships_to_named_person():
    assert "do NOT create a standalone generic role entity" in SYSTEM_PROMPT
    assert "Mayor Alice announced" in SYSTEM_PROMPT
