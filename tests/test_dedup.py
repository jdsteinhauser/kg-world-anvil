"""Tests for entity deduplication."""

from __future__ import annotations

import pytest

from kg_world_anvil.models import DuplicateGroup, ResolvedEntity
from kg_world_anvil.normalization.dedup import (
    EntityDeduplicator,
    build_duplicate_groups,
    pick_survivor_type,
    plan_merge,
)


def _entity(
    entity_id: str,
    name: str,
    entity_type: str,
    *,
    aliases: list[str] | None = None,
    attributes: dict | None = None,
    broader_types: list[str] | None = None,
    canonical_key_override: str | None = None,
) -> ResolvedEntity:
    from kg_world_anvil.normalization.names import canonical_key

    return ResolvedEntity(
        id=entity_id,
        name=name,
        canonical_key=canonical_key_override or canonical_key(name),
        type=entity_type,
        aliases=aliases or [],
        broader_types=broader_types or [],
        attributes=attributes or {},
    )


def test_build_duplicate_groups_same_canonical_key_different_types():
    entities = [
        _entity("entity:1", "Twickenham", "city"),
        _entity("entity:2", "Twickenham", "settlement"),
        _entity("entity:3", "Twickenham", "location"),
    ]
    groups = build_duplicate_groups(entities)
    assert len(groups) == 1
    assert groups[0].canonical_key == "twickenham"
    assert len(groups[0].members) == 3
    types = {m.type for m in groups[0].members}
    assert types == {"city", "settlement", "location"}


def test_build_duplicate_groups_links_alias_overlap():
    entities = [
        _entity("entity:1", "Twickenham", "city"),
        _entity("entity:2", "Twick Town", "settlement", aliases=["Twickenham"]),
    ]
    groups = build_duplicate_groups(entities)
    assert len(groups) == 1
    assert len(groups[0].members) == 2


def test_build_duplicate_groups_links_article_prefixed_keys():
    entities = [
        _entity("entity:1", "Twickenham", "city", canonical_key_override="twickenham"),
        _entity("entity:2", "a Twickenham", "settlement", canonical_key_override="a twickenham"),
    ]
    groups = build_duplicate_groups(entities)
    assert len(groups) == 1
    assert len(groups[0].members) == 2


def test_build_duplicate_groups_links_the_prefix_variants():
    entities = [
        _entity("entity:1", "Hollow Spine", "location"),
        _entity(
            "entity:2",
            "The Hollow Spine",
            "location",
            canonical_key_override="the hollow spine",
        ),
    ]
    groups = build_duplicate_groups(entities)
    assert len(groups) == 1
    assert len(groups[0].members) == 2


def test_build_duplicate_groups_ignores_unrelated_entities():
    entities = [
        _entity("entity:1", "Twickenham", "city"),
        _entity("entity:2", "London", "city"),
    ]
    groups = build_duplicate_groups(entities)
    assert groups == []


def test_plan_merge_folds_loser_types_into_broader_types():
    group = DuplicateGroup(
        canonical_key="twickenham",
        members=[
            _entity("entity:1", "Twickenham", "city"),
            _entity("entity:2", "Twickenham", "settlement"),
            _entity("entity:3", "Twickenham", "location"),
        ],
        suggested_survivor_type="city",
    )
    merge_plan = plan_merge(group, "city")
    assert merge_plan is not None
    assert merge_plan.survivor_id == "entity:1"
    assert merge_plan.survivor_type == "city"
    assert set(merge_plan.loser_ids) == {"entity:2", "entity:3"}
    assert "settlement" in merge_plan.broader_types
    assert "location" in merge_plan.broader_types


def test_plan_merge_merges_aliases_and_attributes():
    group = DuplicateGroup(
        canonical_key="twickenham",
        members=[
            _entity("entity:1", "Twickenham", "city", attributes={"population": "5000"}),
            _entity(
                "entity:2",
                "Twick",
                "settlement",
                aliases=["Twickenham-on-Thames"],
                attributes={"region": "Oran"},
            ),
        ],
        suggested_survivor_type="city",
    )
    merge_plan = plan_merge(group, "city")
    assert merge_plan is not None
    assert "Twick" in merge_plan.merged_aliases
    assert "Twickenham-on-Thames" in merge_plan.merged_aliases
    assert merge_plan.merged_attributes["population"] == "5000"
    assert merge_plan.merged_attributes["region"] == "Oran"


def test_pick_survivor_type_most_connected():
    group = DuplicateGroup(
        canonical_key="twickenham",
        members=[
            _entity("entity:1", "Twickenham", "city"),
            _entity("entity:2", "Twickenham", "settlement"),
        ],
        suggested_survivor_type="city",
    )
    edge_counts = {"entity:1": 2, "entity:2": 10}
    chosen = pick_survivor_type(group, "most-connected", edge_counts=edge_counts)
    assert chosen == "settlement"


def test_pick_survivor_type_type_rank():
    group = DuplicateGroup(
        canonical_key="twickenham",
        members=[
            _entity("entity:1", "Twickenham", "location"),
            _entity("entity:2", "Twickenham", "city"),
            _entity("entity:3", "Twickenham", "settlement"),
        ],
        suggested_survivor_type="location",
    )
    rank = ["city", "town", "settlement", "location"]
    chosen = pick_survivor_type(group, "type-rank", type_rank=rank)
    assert chosen == "city"


def test_pick_survivor_type_most_attributes():
    group = DuplicateGroup(
        canonical_key="twickenham",
        members=[
            _entity("entity:1", "Twickenham", "city", attributes={"a": "1"}),
            _entity("entity:2", "Twickenham", "settlement", attributes={"a": "1", "b": "2"}),
        ],
        suggested_survivor_type="city",
    )
    chosen = pick_survivor_type(group, "most-attributes")
    assert chosen == "settlement"


class FakeDedupRepo:
    def __init__(self, entities: list[ResolvedEntity]) -> None:
        self.entities = list(entities)
        self.deleted: list[str] = []
        self.merged: list[dict] = []
        self.rewired: list[tuple[str, str]] = []

    async def get_all_entities_for_matching(self) -> list[ResolvedEntity]:
        return list(self.entities)

    async def count_entity_edges(self, entity_id: str) -> int:
        return {"entity:1": 1, "entity:2": 5, "entity:3": 0}.get(entity_id, 0)

    async def reassign_edges(self, from_id: str, to_id: str) -> int:
        self.rewired.append((from_id, to_id))
        return 3

    async def merge_entity_fields(
        self,
        survivor_id: str,
        *,
        name: str,
        aliases: list[str],
        broader_types: list[str],
        attributes: dict,
        source_documents: list[str] | None = None,
    ) -> ResolvedEntity:
        self.merged.append(
            {
                "survivor_id": survivor_id,
                "name": name,
                "aliases": aliases,
                "broader_types": broader_types,
                "attributes": attributes,
            }
        )
        survivor = next(e for e in self.entities if e.id == survivor_id)
        survivor.name = name
        survivor.aliases = aliases
        survivor.broader_types = broader_types
        survivor.attributes = attributes
        return survivor

    async def delete_entity(self, entity_id: str) -> None:
        self.deleted.append(entity_id)
        self.entities = [e for e in self.entities if e.id != entity_id]


@pytest.mark.asyncio
async def test_run_auto_merges_all_groups():
    entities = [
        _entity("entity:1", "Twickenham", "city"),
        _entity("entity:2", "Twickenham", "settlement"),
        _entity("entity:3", "Twickenham", "location"),
    ]
    repo = FakeDedupRepo(entities)
    dedup = EntityDeduplicator(repo)
    result = await dedup.run_auto("most-connected")
    assert result.groups_found == 1
    assert result.groups_merged == 1
    assert result.entities_removed == 2
    assert result.edges_rewired == 6
    assert set(repo.deleted) == {"entity:1", "entity:3"}
    assert len(repo.entities) == 1
    assert repo.entities[0].id == "entity:2"
    assert repo.entities[0].type == "settlement"
    assert set(repo.merged[0]["broader_types"]) == {"city", "location"}
