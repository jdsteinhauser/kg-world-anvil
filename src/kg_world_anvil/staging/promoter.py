"""Promote staging batch into the production graph."""

from __future__ import annotations

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.db.staging_repository import StagingRepository
from kg_world_anvil.models import PromoteResult, ResolvedEntity, StagingEntity
from kg_world_anvil.normalization.names import canonical_key, normalize_display_name
from kg_world_anvil.staging.collapse import collapse_staging_entities


class StagingPromoter:
    def __init__(
        self,
        prod_repo: GraphRepository,
        staging_repo: StagingRepository,
        settings: Settings | None = None,
    ) -> None:
        self.prod_repo = prod_repo
        self.staging_repo = staging_repo
        self.settings = settings or get_settings()

    async def promote_draft_batch(
        self,
        batch_id: str,
        *,
        survivor_types: dict[str, str] | None = None,
        skipped_keys: set[str] | None = None,
    ) -> PromoteResult:
        entities = await self.staging_repo.list_staging_entities(batch_id)
        edges = await self.staging_repo.list_staging_edges(batch_id)
        if not entities:
            raise RuntimeError("Staging batch has no entities to promote.")

        skipped_keys = skipped_keys or set()
        type_rank = (
            [t.strip() for t in self.settings.dedup_type_rank.split(",") if t.strip()]
            if self.settings.dedup_type_rank
            else None
        )
        policy = self.settings.dedup_policy
        if type_rank:
            policy = "type-rank"

        collapsed = collapse_staging_entities(
            entities,
            survivor_types=survivor_types,
            policy=policy,
            type_rank=type_rank,
        )

        result = PromoteResult(staging_groups_collapsed=len(collapsed))
        id_map: dict[str, str] = {}
        document_id = (await self._batch_document_id(batch_id)) or None

        for group in collapsed:
            if group.canonical_key in skipped_keys:
                for member_id in group.member_ids:
                    id_map[member_id] = ""
                continue
            prod_entity, created = await self._resolve_to_production(group, document_id)
            if not prod_entity.id:
                continue
            if created:
                result.entities_created += 1
            else:
                result.entities_updated += 1
            for member_id in group.member_ids:
                id_map[member_id] = prod_entity.id

        for edge in edges:
            from_prod = id_map.get(edge.from_entity_id)
            to_prod = id_map.get(edge.to_entity_id)
            if from_prod == "" or to_prod == "":
                continue
            if not from_prod:
                from_prod = await self._resolve_endpoint_from_staging(
                    edge.from_entity_id, entities, document_id
                )
            if not to_prod:
                to_prod = await self._resolve_endpoint_from_staging(
                    edge.to_entity_id, entities, document_id
                )
            if not from_prod or not to_prod:
                continue
            if await self.prod_repo.relationship_exists(
                from_prod, to_prod, edge.predicate
            ):
                result.edges_skipped += 1
                continue
            await self.prod_repo.create_relationship(
                from_prod,
                to_prod,
                edge.predicate,
                edge.confidence,
                document_id,
                edge.detail,
            )
            result.edges_created += 1

        await self.staging_repo.mark_batch_committed(batch_id)
        await self.staging_repo._clear_batch_contents(batch_id)

        return result

    async def _batch_document_id(self, batch_id: str) -> str:
        batch = await self.staging_repo.get_batch(batch_id)
        return batch.document_id if batch else ""

    async def _resolve_to_production(
        self,
        group,
        document_id: str | None,
    ) -> tuple[ResolvedEntity, bool]:
        matches = await self.prod_repo.find_entities_by_canonical_key(group.canonical_key)
        type_cf = group.survivor_type.strip().casefold()
        target = next(
            (e for e in matches if e.type.strip().casefold() == type_cf),
            matches[0] if matches else None,
        )

        if target and target.id:
            raw_name = normalize_display_name(group.name)
            if raw_name not in target.aliases and raw_name != target.name:
                target.aliases.append(raw_name)
            for alias in group.aliases:
                if alias and alias not in target.aliases and alias != target.name:
                    target.aliases.append(alias)
            survivor_cf = group.survivor_type.strip().casefold()
            target_cf = target.type.strip().casefold()
            if survivor_cf != target_cf and group.survivor_type not in target.broader_types:
                target.broader_types.append(group.survivor_type)
            for bt in group.broader_types:
                if (
                    bt
                    and bt not in target.broader_types
                    and bt.strip().casefold() != target.type.strip().casefold()
                ):
                    target.broader_types.append(bt)
            target.attributes.update(group.attributes)
            saved = await self.prod_repo.upsert_entity(target, document_id)
            return saved, False

        new_entity = ResolvedEntity(
            name=group.name,
            canonical_key=group.canonical_key,
            type=group.survivor_type,
            aliases=group.aliases,
            broader_types=group.broader_types,
            attributes=group.attributes,
            is_new=True,
        )
        saved = await self.prod_repo.upsert_entity(new_entity, document_id)
        return saved, True

    async def _resolve_endpoint_from_staging(
        self,
        staging_entity_id: str,
        entities: list[StagingEntity],
        document_id: str | None,
    ) -> str | None:
        entity = next((e for e in entities if e.id == staging_entity_id), None)
        if not entity:
            return None
        key = canonical_key(entity.canonical_key or entity.name)
        matches = await self.prod_repo.find_entities_by_canonical_key(key)
        if matches:
            return matches[0].id
        new_entity = ResolvedEntity(
            name=entity.name,
            canonical_key=key,
            type=entity.type,
            aliases=list(entity.aliases),
            broader_types=list(entity.broader_types),
            attributes=dict(entity.attributes),
            is_new=True,
        )
        saved = await self.prod_repo.upsert_entity(new_entity, document_id)
        return saved.id
