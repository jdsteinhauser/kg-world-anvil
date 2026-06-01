"""Collapse staging entities by canonical_key within a batch."""

from __future__ import annotations

from typing import Any

from kg_world_anvil.models import CollapsedStagingEntity, StagingEntity
from kg_world_anvil.normalization.dedup import build_duplicate_groups, pick_survivor_type
from kg_world_anvil.normalization.names import canonical_key


def collapse_staging_entities(
    entities: list[StagingEntity],
    *,
    survivor_types: dict[str, str] | None = None,
    policy: str = "type-rank",
    type_rank: list[str] | None = None,
) -> list[CollapsedStagingEntity]:
    """Group staging entities by canonical_key and merge fields into collapsed survivors."""
    if not entities:
        return []

    groups = build_duplicate_groups(entities)
    collapsed: list[CollapsedStagingEntity] = []
    survivor_types = survivor_types or {}

    for group in groups:
        survivor_type = survivor_types.get(group.canonical_key)
        if not survivor_type:
            survivor_type = pick_survivor_type(
                group,
                policy,
                type_rank=type_rank,
            )
        merged = _merge_group(group.members, survivor_type, group.canonical_key)
        collapsed.append(merged)

    grouped_ids = {mid for c in collapsed for mid in c.member_ids}
    for entity in entities:
        if entity.id and entity.id in grouped_ids:
            continue
        collapsed.append(
            CollapsedStagingEntity(
                canonical_key=canonical_key(entity.canonical_key or entity.name),
                survivor_type=entity.type,
                name=entity.name,
                aliases=list(entity.aliases),
                broader_types=list(entity.broader_types),
                attributes=dict(entity.attributes),
                member_ids=[entity.id] if entity.id else [],
            )
        )

    return collapsed


def _merge_group(
    members: list[StagingEntity],
    survivor_type: str,
    display_key: str,
) -> CollapsedStagingEntity:
    survivor_type_cf = survivor_type.strip().casefold()
    survivor = next(
        (m for m in members if m.type.strip().casefold() == survivor_type_cf),
        members[0],
    )
    aliases: list[str] = list(survivor.aliases)
    broader_types: list[str] = list(survivor.broader_types)
    attributes: dict[str, Any] = dict(survivor.attributes)
    name = survivor.name
    member_ids: list[str] = []

    for member in members:
        if member.id:
            member_ids.append(member.id)
        if member.name and member.name != name and member.name not in aliases:
            aliases.append(member.name)
        for alias in member.aliases:
            if alias and alias != name and alias not in aliases:
                aliases.append(alias)
        if (
            member.type.strip().casefold() != survivor.type.strip().casefold()
            and member.type not in broader_types
        ):
            broader_types.append(member.type)
        for bt in member.broader_types:
            if bt and bt not in broader_types and bt != survivor.type:
                broader_types.append(bt)
        attributes.update(member.attributes)

    return CollapsedStagingEntity(
        canonical_key=display_key,
        survivor_type=survivor.type,
        name=name,
        aliases=aliases,
        broader_types=broader_types,
        attributes=attributes,
        member_ids=member_ids,
    )
