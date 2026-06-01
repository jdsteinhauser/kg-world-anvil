"""Entity deduplication: find duplicate groups and merge into a single survivor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from kg_world_anvil.models import DuplicateGroup, MergePlan, ResolvedEntity
from kg_world_anvil.normalization.names import canonical_key


class DedupRepository(Protocol):
    async def get_all_entities_for_matching(self) -> list[ResolvedEntity]: ...
    async def count_entity_edges(self, entity_id: str) -> int: ...
    async def reassign_edges(self, from_id: str, to_id: str) -> int: ...
    async def merge_entity_fields(
        self,
        survivor_id: str,
        *,
        name: str,
        aliases: list[str],
        broader_types: list[str],
        attributes: dict[str, Any],
        source_documents: list[str] | None = None,
    ) -> ResolvedEntity: ...
    async def delete_entity(self, entity_id: str) -> None: ...


@dataclass
class AutoDedupResult:
    groups_found: int
    groups_merged: int
    entities_removed: int
    edges_rewired: int


def _entity_lookup_key(entity: ResolvedEntity) -> str:
    return canonical_key(entity.canonical_key or entity.name)


def _entity_name_keys(entity: ResolvedEntity) -> set[str]:
    keys = {_entity_lookup_key(entity)}
    keys.add(canonical_key(entity.name))
    for alias in entity.aliases:
        keys.add(canonical_key(alias))
    return keys


def _group_entities_by_canonical_key(entities: list[ResolvedEntity]) -> dict[str, list[ResolvedEntity]]:
    groups: dict[str, list[ResolvedEntity]] = {}
    for entity in entities:
        key = _entity_lookup_key(entity)
        groups.setdefault(key, []).append(entity)
    return groups


def _union_find_merge(groups: dict[str, list[ResolvedEntity]]) -> dict[str, str]:
    """Link canonical keys that share a name or alias."""
    keys = list(groups.keys())
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    key_to_name_keys: dict[str, set[str]] = {}
    for key in keys:
        name_keys: set[str] = set()
        for entity in groups[key]:
            name_keys |= _entity_name_keys(entity)
        key_to_name_keys[key] = name_keys

    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1 :]:
            if key_a == key_b:
                continue
            if key_to_name_keys[key_a] & key_to_name_keys[key_b]:
                union(key_a, key_b)

    return {k: find(k) for k in keys}


def build_duplicate_groups(entities: list[ResolvedEntity]) -> list[DuplicateGroup]:
    """Group entities sharing canonical_key or overlapping names/aliases."""
    by_key = _group_entities_by_canonical_key(entities)
    if not by_key:
        return []

    parent_map = _union_find_merge(by_key)
    components: dict[str, dict[str, ResolvedEntity]] = {}

    for _key, members in by_key.items():
        root = parent_map[_key]
        bucket = components.setdefault(root, {})
        for entity in members:
            if entity.id:
                bucket[entity.id] = entity

    result: list[DuplicateGroup] = []
    for root, member_map in components.items():
        members = list(member_map.values())
        if len(members) < 2:
            continue
        display_key = root
        for member in members:
            member_key = _entity_lookup_key(member)
            if member_key == root:
                display_key = member_key
                break
        else:
            display_key = _entity_lookup_key(members[0])
        result.append(
            DuplicateGroup(
                canonical_key=display_key,
                members=members,
                suggested_survivor_type=_suggest_survivor_type(members),
            )
        )
    result.sort(key=lambda g: g.canonical_key)
    return result


def _suggest_survivor_type(members: list[ResolvedEntity]) -> str:
    """Default suggestion: member with the longest type string (often most specific)."""
    if not members:
        return ""
    return max(members, key=lambda m: (len(m.type), m.type)).type


def pick_survivor_type(
    group: DuplicateGroup,
    policy: str,
    *,
    type_rank: list[str] | None = None,
    edge_counts: dict[str, int] | None = None,
) -> str:
    """Choose survivor type using a named policy."""
    members = group.members
    if not members:
        return ""
    if len(members) == 1:
        return members[0].type

    policy = policy.strip().lower()
    if policy == "type-rank" and type_rank:
        rank = {t.casefold(): i for i, t in enumerate(type_rank)}
        ranked = [m for m in members if m.type.strip().casefold() in rank]
        if ranked:
            return min(ranked, key=lambda m: rank[m.type.strip().casefold()]).type

    if policy == "most-attributes":
        return max(members, key=lambda m: (len(m.attributes), len(m.aliases), m.type)).type

    if policy == "most-connected" and edge_counts is not None:
        return max(
            members,
            key=lambda m: (edge_counts.get(m.id or "", 0), len(m.attributes), m.type),
        ).type

    return _suggest_survivor_type(members)


def plan_merge(group: DuplicateGroup, survivor_type: str) -> MergePlan | None:
    """Build a merge plan without writing to the database."""
    survivor_type_cf = survivor_type.strip().casefold()
    survivor = next(
        (m for m in group.members if m.type.strip().casefold() == survivor_type_cf),
        None,
    )
    if survivor is None or not survivor.id:
        return None

    losers = [m for m in group.members if m.id and m.id != survivor.id]
    if not losers:
        return None

    merged_aliases: list[str] = list(survivor.aliases)
    broader_types: list[str] = list(survivor.broader_types)
    merged_attributes: dict[str, Any] = dict(survivor.attributes)
    survivor_name = survivor.name

    for loser in losers:
        if loser.name and loser.name != survivor_name and loser.name not in merged_aliases:
            merged_aliases.append(loser.name)
        for alias in loser.aliases:
            if alias and alias != survivor_name and alias not in merged_aliases:
                merged_aliases.append(alias)
        loser_type = loser.type.strip()
        if loser_type and loser_type.casefold() != survivor.type.strip().casefold():
            if loser_type not in broader_types and loser_type != survivor.type:
                broader_types.append(loser_type)
        for bt in loser.broader_types:
            if bt and bt not in broader_types and bt != survivor.type:
                broader_types.append(bt)
        merged_attributes.update(loser.attributes)
        if len(loser.name) > len(survivor_name):
            survivor_name = loser.name

    return MergePlan(
        canonical_key=group.canonical_key,
        survivor_id=survivor.id,
        survivor_type=survivor.type,
        survivor_name=survivor_name,
        loser_ids=[l.id for l in losers if l.id],
        merged_aliases=merged_aliases,
        broader_types=broader_types,
        merged_attributes=merged_attributes,
        edges_to_rewire=0,
    )


class EntityDeduplicator:
    def __init__(self, repo: DedupRepository) -> None:
        self.repo = repo

    async def find_duplicate_groups(self) -> list[DuplicateGroup]:
        entities = await self.repo.get_all_entities_for_matching()
        return build_duplicate_groups(entities)

    async def plan_merge(self, group: DuplicateGroup, survivor_type: str) -> MergePlan | None:
        plan = plan_merge(group, survivor_type)
        if plan is None:
            return None
        edge_total = 0
        for loser_id in plan.loser_ids:
            edge_total += await self.repo.count_entity_edges(loser_id)
        plan.edges_to_rewire = edge_total
        return plan

    async def apply_merge(self, plan: MergePlan) -> int:
        """Apply merge plan; returns number of edges rewired."""
        if not plan.survivor_id:
            return 0
        rewired = 0
        for loser_id in plan.loser_ids:
            rewired += await self.repo.reassign_edges(loser_id, plan.survivor_id)
            await self.repo.delete_entity(loser_id)
        await self.repo.merge_entity_fields(
            plan.survivor_id,
            name=plan.survivor_name,
            aliases=plan.merged_aliases,
            broader_types=plan.broader_types,
            attributes=plan.merged_attributes,
        )
        return rewired

    async def run_auto(
        self,
        policy: str = "most-connected",
        *,
        type_rank: list[str] | None = None,
    ) -> AutoDedupResult:
        groups = await self.find_duplicate_groups()
        merged = 0
        removed = 0
        rewired = 0

        for group in groups:
            edge_counts: dict[str, int] = {}
            for member in group.members:
                if member.id:
                    edge_counts[member.id] = await self.repo.count_entity_edges(member.id)
            survivor_type = pick_survivor_type(
                group,
                policy,
                type_rank=type_rank,
                edge_counts=edge_counts,
            )
            plan = await self.plan_merge(group, survivor_type)
            if plan is None:
                continue
            rewired += await self.apply_merge(plan)
            merged += 1
            removed += len(plan.loser_ids)

        return AutoDedupResult(
            groups_found=len(groups),
            groups_merged=merged,
            entities_removed=removed,
            edges_rewired=rewired,
        )
