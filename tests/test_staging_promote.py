"""Tests for staging collapse and promote."""

from __future__ import annotations

import pytest

from kg_world_anvil.db.relations import is_staging_table_name
from kg_world_anvil.models import (
    CollapsedStagingEntity,
    PromoteResult,
    ResolvedEntity,
    StagingBatch,
    StagingBatchStatus,
    StagingEdge,
    StagingEntity,
)
from kg_world_anvil.normalization.names import canonical_key
from kg_world_anvil.staging.collapse import collapse_staging_entities
from kg_world_anvil.staging.promoter import StagingPromoter


def test_staging_tables_excluded_from_production_relation_scan():
    assert is_staging_table_name("staging_batch")
    assert is_staging_table_name("staging_entity")
    assert is_staging_table_name("staging_located_in")
    assert not is_staging_table_name("located_in")


def _staging_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    *,
    batch_id: str = "staging_batch:1",
    canonical_key_override: str | None = None,
) -> StagingEntity:
    return StagingEntity(
        id=entity_id,
        batch_id=batch_id,
        name=name,
        canonical_key=canonical_key_override or canonical_key(name),
        type=entity_type,
    )


def _prod_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    *,
    broader_types: list[str] | None = None,
) -> ResolvedEntity:
    return ResolvedEntity(
        id=entity_id,
        name=name,
        canonical_key=canonical_key(name),
        type=entity_type,
        broader_types=broader_types or [],
    )


def test_collapse_twickenham_multi_type_to_one_group():
    entities = [
        _staging_entity("staging_entity:1", "Twickenham", "city"),
        _staging_entity("staging_entity:2", "Twickenham", "settlement"),
        _staging_entity("staging_entity:3", "Twickenham", "location"),
    ]
    collapsed = collapse_staging_entities(entities, policy="type-rank")
    multi = [c for c in collapsed if len(c.member_ids) > 1]
    assert len(multi) == 1
    group = multi[0]
    assert group.canonical_key == "twickenham"
    assert len(group.member_ids) == 3
    assert group.survivor_type in {"city", "settlement", "location"}
    assert len(group.broader_types) == 2
    assert group.survivor_type not in group.broader_types


@pytest.mark.asyncio
async def test_promote_updates_existing_prod_entity():
    prod = _prod_entity("entity:1", "Twickenham", "city")
    staging = [
        _staging_entity("staging_entity:1", "Twickenham", "settlement"),
    ]
    prod_repo = FakePromoteProdRepo([prod])
    staging_repo = FakePromoteStagingRepo(
        batch=StagingBatch(id="staging_batch:1", document_id="document:1"),
        entities=staging,
        edges=[],
    )
    promoter = StagingPromoter(prod_repo, staging_repo)

    result = await promoter.promote_draft_batch("staging_batch:1")

    assert result.entities_created == 0
    assert result.entities_updated == 1
    assert "settlement" in prod_repo.entities[0].broader_types
    assert staging_repo.batch_status == StagingBatchStatus.COMMITTED
    assert staging_repo.cleared is True


@pytest.mark.asyncio
async def test_promote_creates_edge_and_skips_duplicate():
    prod_a = _prod_entity("entity:1", "Alpha", "location")
    prod_b = _prod_entity("entity:2", "Beta", "location")
    staging = [
        _staging_entity("staging_entity:1", "Alpha", "location"),
        _staging_entity("staging_entity:2", "Beta", "location"),
    ]
    edges = [
        StagingEdge(
            id="staging_located_in:1",
            predicate="located_in",
            from_entity_id="staging_entity:1",
            to_entity_id="staging_entity:2",
        )
    ]
    prod_repo = FakePromoteProdRepo([prod_a, prod_b])
    staging_repo = FakePromoteStagingRepo(
        batch=StagingBatch(id="staging_batch:1", document_id="document:1"),
        entities=staging,
        edges=edges,
    )
    promoter = StagingPromoter(prod_repo, staging_repo)

    first = await promoter.promote_draft_batch("staging_batch:1")
    assert first.edges_created == 1
    assert first.edges_skipped == 0
    assert len(prod_repo.relationships) == 1

    staging_repo.reset_after_promote(staging, edges)
    second = await promoter.promote_draft_batch("staging_batch:1")
    assert second.edges_created == 0
    assert second.edges_skipped == 1


@pytest.mark.asyncio
async def test_single_draft_guard_blocks_second_document():
    staging_repo = FakePromoteStagingRepo(
        batch=StagingBatch(
            id="staging_batch:1",
            document_id="document:1",
            status=StagingBatchStatus.DRAFT,
        ),
        entities=[],
        edges=[],
    )
    staging_repo.draft_batch = staging_repo.batch

    with pytest.raises(RuntimeError, match="draft staging batch already exists"):
        await staging_repo.replace_draft_for_document("document:2", _empty_extraction())


class FakePromoteProdRepo:
    def __init__(self, entities: list[ResolvedEntity]) -> None:
        self.entities = list(entities)
        self.relationships: list[tuple[str, str, str]] = []
        self.upsert_calls = 0

    async def find_entities_by_canonical_key(self, key: str) -> list[ResolvedEntity]:
        normalized = canonical_key(key)
        return [
            e
            for e in self.entities
            if canonical_key(e.canonical_key or e.name) == normalized
        ]

    async def upsert_entity(
        self,
        entity: ResolvedEntity,
        document_id: str | None = None,
        embedding: list[float] | None = None,
        source_chunks: list[str] | None = None,
    ) -> ResolvedEntity:
        self.upsert_calls += 1
        if entity.id:
            for idx, existing in enumerate(self.entities):
                if existing.id == entity.id:
                    self.entities[idx] = entity
                    return entity
        entity.id = entity.id or f"entity:{len(self.entities) + 1}"
        self.entities.append(entity)
        return entity

    async def relationship_exists(
        self,
        from_id: str,
        to_id: str,
        predicate: str,
    ) -> bool:
        return (from_id, to_id, predicate) in self.relationships

    async def create_relationship(
        self,
        from_id: str,
        to_id: str,
        predicate: str,
        confidence: float = 1.0,
        document_id: str | None = None,
        detail: str = "",
        source_chunks: list[str] | None = None,
    ):
        self.relationships.append((from_id, to_id, predicate))
        return None


class FakePromoteStagingRepo:
    def __init__(
        self,
        *,
        batch: StagingBatch,
        entities: list[StagingEntity],
        edges: list[StagingEdge],
    ) -> None:
        self.batch = batch
        self.entities = list(entities)
        self.edges = list(edges)
        self.draft_batch: StagingBatch | None = batch
        self.batch_status = batch.status
        self.cleared = False

    async def get_batch(self, batch_id: str) -> StagingBatch | None:
        if self.batch.id == batch_id:
            return self.batch
        return None

    async def get_draft_batch(self) -> StagingBatch | None:
        return self.draft_batch

    async def list_staging_entities(self, batch_id: str) -> list[StagingEntity]:
        return list(self.entities)

    async def list_staging_edges(self, batch_id: str) -> list[StagingEdge]:
        return list(self.edges)

    async def mark_batch_committed(self, batch_id: str) -> None:
        self.batch_status = StagingBatchStatus.COMMITTED
        if self.batch:
            self.batch.status = StagingBatchStatus.COMMITTED

    async def _clear_batch_contents(self, batch_id: str) -> None:
        self.cleared = True
        self.entities.clear()
        self.edges.clear()

    async def replace_draft_for_document(self, document_id: str, extraction) -> StagingBatch:
        if (
            self.draft_batch
            and self.draft_batch.status == StagingBatchStatus.DRAFT
            and self.draft_batch.document_id != document_id
        ):
            raise RuntimeError(
                "A draft staging batch already exists for another document. "
                "Commit or discard it before extracting again."
            )
        self.batch = StagingBatch(id="staging_batch:1", document_id=document_id)
        self.draft_batch = self.batch
        return self.batch

    def reset_after_promote(
        self,
        entities: list[StagingEntity],
        edges: list[StagingEdge],
    ) -> None:
        self.entities = list(entities)
        self.edges = list(edges)
        self.batch_status = StagingBatchStatus.DRAFT
        self.cleared = False
        if self.batch:
            self.batch.status = StagingBatchStatus.DRAFT


def _empty_extraction():
    from kg_world_anvil.models import ExtractionResult

    return ExtractionResult(entities=[], relationships=[])
