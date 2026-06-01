"""Tests for SurrealDB result parsing helpers."""

import pytest

from kg_world_anvil.db.repository import _all_results, _first_result


def test_all_results_flat_row_list():
    rows = [
        {"id": "staging_entity:1", "name": "Alpha"},
        {"id": "staging_entity:2", "name": "Beta"},
        {"id": "staging_entity:3", "name": "Gamma"},
    ]
    assert len(_all_results(rows)) == 3
    assert _all_results(rows)[1]["name"] == "Beta"


def test_all_results_wrapped_result_list():
    rows = [{"result": [{"id": "entity:1"}, {"id": "entity:2"}]}]
    assert len(_all_results(rows)) == 2


def test_all_results_single_wrapped_row():
    rows = [{"result": {"id": "entity:1", "name": "One"}}]
    assert _all_results(rows) == [{"id": "entity:1", "name": "One"}]


def test_first_result_flat_row():
    rows = [{"id": "entity:1", "name": "One"}]
    assert _first_result(rows) == {"id": "entity:1", "name": "One"}


@pytest.mark.asyncio
async def test_relationship_exists_on_missing_table_returns_false():
    from kg_world_anvil.db.repository import GraphRepository

    class FakeClient:
        define_calls = 0
        select_calls = 0

        async def query(self, sql: str, vars=None):
            if sql.strip().startswith("DEFINE"):
                FakeClient.define_calls += 1
                return []
            FakeClient.select_calls += 1
            return []

    repo = GraphRepository(FakeClient())  # type: ignore[arg-type]
    assert await repo.relationship_exists("entity:1", "entity:2", "owned_by") is False
    assert FakeClient.define_calls >= 1
    assert FakeClient.select_calls == 1
