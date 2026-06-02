"""Shared application services and state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.consistency.rules import ConsistencyChecker
from kg_world_anvil.db.client import DatabaseClient
from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.db.staging_repository import StagingRepository
from kg_world_anvil.extraction.extractor import (
    KnowledgeExtractor,
    dedupe_extraction,
    filter_negated_relationships,
    normalize_extraction_result,
)
from kg_world_anvil.embeddings import EmbeddingClient
from kg_world_anvil.ingestion.chunker import chunk_spans, clean_text, detect_format
from kg_world_anvil.models import (
    ChunkRecord,
    ExtractionResult,
    MergeCandidate,
    MergePlan,
    PromoteResult,
    StagingBatch,
    TextFormat,
)
from kg_world_anvil.normalization.dedup import EntityDeduplicator
from kg_world_anvil.normalization.names import canonical_key
from kg_world_anvil.normalization.resolver import EntityResolver
from kg_world_anvil.query.nl import NLQueryTranslator
from kg_world_anvil.query.queries import QueryService
from kg_world_anvil.query.rag import RAGService
from kg_world_anvil.staging.collapse import collapse_staging_entities
from kg_world_anvil.staging.promoter import StagingPromoter


@dataclass
class PendingReview:
    canonical_key: str
    display_name: str
    staging_types: list[str]
    prod_candidates: list[MergeCandidate] = field(default_factory=list)
    member_count: int = 1


@dataclass
class AppServices:
    settings: Settings
    db_client: DatabaseClient
    repo: GraphRepository
    staging_repo: StagingRepository
    promoter: StagingPromoter
    extractor: KnowledgeExtractor
    resolver: EntityResolver
    query_service: QueryService
    nl_translator: NLQueryTranslator
    rag_service: RAGService
    consistency: ConsistencyChecker
    deduplicator: EntityDeduplicator
    pending_reviews: list[PendingReview] = field(default_factory=list)
    last_extraction: ExtractionResult | None = None
    last_document_id: str | None = None
    draft_batch: StagingBatch | None = None

    @classmethod
    async def create(cls) -> AppServices:
        settings = get_settings()
        db_client = DatabaseClient(settings)
        await db_client.connect()
        repo = GraphRepository(db_client)
        staging_repo = StagingRepository(db_client, repo)
        promoter = StagingPromoter(repo, staging_repo, settings)
        services = cls(
            settings=settings,
            db_client=db_client,
            repo=repo,
            staging_repo=staging_repo,
            promoter=promoter,
            extractor=KnowledgeExtractor(settings),
            resolver=EntityResolver(repo, settings),
            query_service=QueryService(repo),
            nl_translator=NLQueryTranslator(settings),
            rag_service=RAGService(repo, settings),
            consistency=ConsistencyChecker(repo),
            deduplicator=EntityDeduplicator(repo),
        )
        services.draft_batch = await staging_repo.get_draft_batch()
        return services

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

        rag_chunks: list[ChunkRecord] = []
        if self.settings.use_embeddings:
            rag_chunks = await self._index_document_chunks(doc_id, cleaned)

        extractions = self.extractor.extract_with_provenance(cleaned)
        merged = ExtractionResult(entities=[], relationships=[])
        for item in extractions:
            merged.entities.extend(item.result.entities)
            merged.relationships.extend(item.result.relationships)
        result = filter_negated_relationships(
            normalize_extraction_result(dedupe_extraction(merged)),
            cleaned,
        )
        self.last_extraction = result
        self.last_document_id = doc_id

        if self.settings.use_staging:
            self.draft_batch = await self.staging_repo.replace_draft_for_document(
                doc_id,
                result,
                extractions=extractions if rag_chunks else None,
                rag_chunks=rag_chunks or None,
            )
            await self._build_staging_review_queue()
        else:
            await self._build_legacy_review_queue(result)

        return result, doc_id

    async def _index_document_chunks(
        self,
        document_id: str,
        text: str,
    ) -> list[ChunkRecord]:
        spans = chunk_spans(
            text,
            chunk_size=self.settings.rag_chunk_size,
            overlap=self.settings.rag_chunk_overlap,
        )
        if not spans:
            return []
        await self.repo.delete_chunks_for_document(document_id)
        embedder = EmbeddingClient(self.settings)
        embeddings = embedder.embed_texts([span[2] for span in spans]) if embedder.available else None
        return await self.repo.create_chunks(document_id, spans, embeddings)

    async def backfill_chunks(self) -> int:
        if not self.settings.use_embeddings:
            raise RuntimeError("Enable USE_EMBEDDINGS in config to backfill RAG chunks.")
        embedder = EmbeddingClient(self.settings)
        if not embedder.available:
            raise RuntimeError("OpenAI API key is required for chunk embeddings.")

        indexed = 0
        for doc in await self.repo.list_documents():
            if not doc.id or await self.repo.document_has_chunks(doc.id):
                continue
            await self._index_document_chunks(doc.id, doc.raw)
            indexed += 1
        return indexed

    async def _build_staging_review_queue(self) -> None:
        self.pending_reviews.clear()
        if not self.draft_batch or not self.draft_batch.id:
            return

        entities = await self.staging_repo.list_staging_entities(self.draft_batch.id)
        if not entities:
            return

        collapsed = collapse_staging_entities(entities)
        existing = await self.repo.get_all_entities_for_matching()

        for group in collapsed:
            prod_matches = [
                entity
                for entity in existing
                if canonical_key(entity.canonical_key or entity.name) == group.canonical_key
            ]
            candidates: list[MergeCandidate] = []
            for match in prod_matches:
                candidates.append(
                    MergeCandidate(
                        extracted_name=group.name,
                        extracted_type=group.survivor_type,
                        existing_id=match.id or "",
                        existing_name=match.name,
                        existing_type=match.type,
                        score=1.0,
                        match_method="exact_key",
                    )
                )

            needs_review = len(group.member_ids) > 1 or bool(candidates)
            if not needs_review:
                continue

            staging_types = list(
                {
                    entity.type
                    for entity in entities
                    if entity.id in group.member_ids or (
                        len(group.member_ids) == 1
                        and canonical_key(entity.canonical_key or entity.name)
                        == group.canonical_key
                    )
                }
            )
            if not staging_types:
                staging_types = [group.survivor_type]

            self.pending_reviews.append(
                PendingReview(
                    canonical_key=group.canonical_key,
                    display_name=group.name,
                    staging_types=staging_types,
                    prod_candidates=candidates,
                    member_count=len(group.member_ids) or 1,
                )
            )

    async def _build_legacy_review_queue(self, result: ExtractionResult) -> None:
        self.pending_reviews.clear()
        existing = await self.repo.get_all_entities_for_matching()
        seen: set[str] = set()
        for entity in result.entities:
            key = canonical_key(entity.name)
            if key in seen:
                continue
            seen.add(key)
            resolved, candidates = await self.resolver.resolve_entity(entity, existing)
            if candidates:
                self.pending_reviews.append(
                    PendingReview(
                        canonical_key=key,
                        display_name=entity.name,
                        staging_types=[entity.type],
                        prod_candidates=candidates,
                        member_count=1,
                    )
                )

    async def scan_duplicates(self):
        return await self.deduplicator.find_duplicate_groups()

    async def apply_dedup(self, plan: MergePlan) -> int:
        return await self.deduplicator.apply_merge(plan)

    async def promote_draft_batch(
        self,
        merge_decisions: dict[str, str] | None = None,
        survivor_types: dict[str, str] | None = None,
    ) -> PromoteResult:
        if not self.settings.use_staging:
            raise RuntimeError("Staging is disabled; enable use_staging in config.")
        if not self.draft_batch or not self.draft_batch.id:
            raise RuntimeError("No draft staging batch to promote.")

        decisions = merge_decisions or {}
        skipped_keys = {
            key for key, action in decisions.items() if action == "skip"
        }
        survivor_types = dict(survivor_types or {})
        for item in self.pending_reviews:
            decision = decisions.get(item.canonical_key, "create_new")
            if decision == "merge" and item.prod_candidates:
                prod_type = item.prod_candidates[0].existing_type
                survivor_types.setdefault(item.canonical_key, prod_type)
            elif len(item.staging_types) > 1 and item.canonical_key not in survivor_types:
                survivor_types.setdefault(item.canonical_key, item.staging_types[0])

        result = await self.promoter.promote_draft_batch(
            self.draft_batch.id,
            survivor_types=survivor_types,
            skipped_keys=skipped_keys,
        )
        self.pending_reviews.clear()
        self.draft_batch = None
        self.last_extraction = None
        self.last_document_id = None
        return result

    async def discard_draft_batch(self) -> None:
        if not self.draft_batch or not self.draft_batch.id:
            raise RuntimeError("No draft staging batch to discard.")
        await self.staging_repo.discard_draft_batch(self.draft_batch.id)
        self.draft_batch = None
        self.pending_reviews.clear()
        self.last_extraction = None
        self.last_document_id = None
