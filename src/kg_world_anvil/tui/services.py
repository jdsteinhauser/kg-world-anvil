"""Shared application services and state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.consistency.rules import ConsistencyChecker
from kg_world_anvil.db.client import DatabaseClient
from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.extraction.extractor import KnowledgeExtractor
from kg_world_anvil.ingestion.chunker import clean_text, detect_format
from kg_world_anvil.models import (
    ExtractionResult,
    MergeCandidate,
    ResolvedEntity,
    TextFormat,
    attributes_to_dict,
)
from kg_world_anvil.normalization.names import canonical_key, entity_identity_key
from kg_world_anvil.normalization.resolver import EntityResolver
from kg_world_anvil.query.nl import NLQueryTranslator
from kg_world_anvil.query.queries import QueryService


@dataclass
class PendingReview:
    extracted_name: str
    extracted_type: str
    entity: ResolvedEntity
    candidates: list[MergeCandidate] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)


@dataclass
class AppServices:
    settings: Settings
    db_client: DatabaseClient
    repo: GraphRepository
    extractor: KnowledgeExtractor
    resolver: EntityResolver
    query_service: QueryService
    nl_translator: NLQueryTranslator
    consistency: ConsistencyChecker
    pending_reviews: list[PendingReview] = field(default_factory=list)
    last_extraction: ExtractionResult | None = None
    last_document_id: str | None = None

    @classmethod
    async def create(cls) -> AppServices:
        settings = get_settings()
        db_client = DatabaseClient(settings)
        await db_client.connect()
        repo = GraphRepository(db_client)
        return cls(
            settings=settings,
            db_client=db_client,
            repo=repo,
            extractor=KnowledgeExtractor(settings),
            resolver=EntityResolver(repo, settings),
            query_service=QueryService(repo),
            nl_translator=NLQueryTranslator(settings),
            consistency=ConsistencyChecker(repo),
        )

    async def close(self) -> None:
        await self.db_client.close()

    async def ingest_and_extract(
        self,
        raw_text: str,
        fmt: TextFormat | None = None,
    ) -> tuple[ExtractionResult, str]:
        detected = detect_format(raw_text, fmt)
        cleaned = clean_text(raw_text, detected)
        content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

        existing = await self.repo.get_document_by_hash(content_hash)
        if existing and existing.id:
            doc_id = existing.id
        else:
            doc = await self.repo.create_document(cleaned, detected, content_hash)
            doc_id = doc.id or ""

        result = self.extractor.extract_text(cleaned)
        self.last_extraction = result
        self.last_document_id = doc_id
        await self._build_review_queue(result)
        return result, doc_id

    async def _build_review_queue(self, result: ExtractionResult) -> None:
        self.pending_reviews.clear()
        existing = await self.repo.get_all_entities_for_matching()
        seen: set[tuple[str, str]] = set()
        for entity in result.entities:
            key = entity_identity_key(entity.name, entity.type)
            if key in seen:
                continue
            seen.add(key)
            resolved, candidates = await self.resolver.resolve_entity(entity, existing)
            if candidates and resolved.is_new:
                self.pending_reviews.append(
                    PendingReview(
                        extracted_name=entity.name,
                        extracted_type=entity.type,
                        entity=resolved,
                        candidates=candidates,
                        attributes=attributes_to_dict(entity.attributes),
                    )
                )

    async def commit_extraction(
        self,
        merge_decisions: dict[tuple[str, str], str],
    ) -> tuple[int, int]:
        if not self.last_extraction or not self.last_document_id:
            raise RuntimeError("No extraction to commit.")

        entity_id_map: dict[str, str] = {}
        entity_count = 0
        rel_count = 0
        existing = await self.repo.get_all_entities_for_matching()

        for extracted in self.last_extraction.entities:
            key = entity_identity_key(extracted.name, extracted.type)
            decision = merge_decisions.get(key, "create_new")
            resolved, candidates = await self.resolver.resolve_entity(extracted, existing)

            if decision == "merge" and candidates:
                target = next((e for e in existing if e.id == candidates[0].existing_id), None)
                if target:
                    raw_name = extracted.name.strip()
                    if raw_name not in target.aliases and raw_name != target.name:
                        target.aliases.append(raw_name)
                    target.attributes.update(attributes_to_dict(extracted.attributes))
                    saved = await self.repo.upsert_entity(target, self.last_document_id)
                    resolved = saved
            elif decision != "skip":
                embedding = await self.resolver.embed_entity(extracted.name)
                saved = await self.repo.upsert_entity(resolved, self.last_document_id, embedding)
                resolved = saved
                existing.append(saved)
                entity_count += 1
            else:
                continue

            if resolved.id:
                entity_id_map[canonical_key(extracted.name)] = resolved.id

        for rel in self.last_extraction.relationships:
            from_id = entity_id_map.get(canonical_key(rel.subject))
            to_id = entity_id_map.get(canonical_key(rel.object))
            if not from_id:
                subj_entities = await self.repo.find_entity_by_name_or_alias(rel.subject)
                if subj_entities:
                    from_id = subj_entities[0].id
            if not to_id:
                obj_entities = await self.repo.find_entity_by_name_or_alias(rel.object)
                if obj_entities:
                    to_id = obj_entities[0].id
            if from_id and to_id:
                await self.repo.create_relationship(
                    from_id,
                    to_id,
                    rel.predicate.value,
                    rel.confidence,
                    self.last_document_id,
                    rel.detail.strip(),
                )
                rel_count += 1

        self.pending_reviews.clear()
        return entity_count, rel_count
