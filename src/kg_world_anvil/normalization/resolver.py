"""Entity resolution against the graph store."""

from __future__ import annotations

import math

from openai import OpenAI
from rapidfuzz import fuzz

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.models import ExtractedEntity, MergeCandidate, ResolvedEntity
from kg_world_anvil.models import attributes_to_dict
from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.normalization.names import (
    canonical_key,
    entity_identity_key,
    normalize_display_name,
    normalize_entity_type,
)


class EntityResolver:
    def __init__(
        self,
        repo: GraphRepository,
        settings: Settings | None = None,
    ) -> None:
        self.repo = repo
        self.settings = settings or get_settings()
        self._openai: OpenAI | None = None
        if self.settings.openai_api_key:
            self._openai = OpenAI(api_key=self.settings.openai_api_key)

    async def resolve_entity(
        self,
        extracted: ExtractedEntity,
        existing_entities: list[ResolvedEntity] | None = None,
    ) -> tuple[ResolvedEntity, list[MergeCandidate]]:
        display_name = normalize_display_name(extracted.name)
        entity_type = normalize_entity_type(extracted.type)
        key = canonical_key(display_name)
        exact = await self.repo.find_entity_by_key(key, entity_type)
        if exact:
            return exact, []

        candidates: list[MergeCandidate] = []
        pool = existing_entities
        if pool is None:
            pool = await self.repo.get_all_entities_for_matching()

        same_key = [
            entity
            for entity in pool
            if canonical_key(entity.canonical_key or entity.name) == key
        ]
        for entity in same_key:
            if entity.type.strip().casefold() == entity_type:
                continue
            candidates.append(
                MergeCandidate(
                    extracted_name=display_name,
                    extracted_type=entity_type,
                    existing_id=entity.id or "",
                    existing_name=entity.name,
                    existing_type=entity.type,
                    score=1.0,
                    match_method="exact_key",
                )
            )

        for entity in pool:
            if entity.type.strip().casefold() != entity_type:
                continue
            score = fuzz.token_sort_ratio(
                key,
                canonical_key(entity.canonical_key or entity.name),
            )
            alias_scores = [
                fuzz.token_sort_ratio(key, canonical_key(alias))
                for alias in entity.aliases
            ]
            best_alias = max(alias_scores) if alias_scores else 0
            best = max(score, best_alias)
            entity_key = canonical_key(entity.canonical_key or entity.name)
            if key == entity_key:
                best = 100
            elif any(key == canonical_key(alias) for alias in entity.aliases):
                best = 100
            if best >= self.settings.fuzzy_match_threshold:
                candidates.append(
                    MergeCandidate(
                        extracted_name=display_name,
                        extracted_type=entity_type,
                        existing_id=entity.id or "",
                        existing_name=entity.name,
                        existing_type=entity.type,
                        score=best / 100.0,
                        match_method="fuzzy",
                    )
                )

        if self.settings.use_embeddings and self._openai:
            embedding_candidates = await self._embedding_candidates(
                ExtractedEntity(name=display_name, type=entity_type, attributes=extracted.attributes),
                pool,
            )
            seen_ids = {c.existing_id for c in candidates}
            for candidate in embedding_candidates:
                if candidate.existing_id not in seen_ids:
                    candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)

        if candidates and candidates[0].score >= 0.95:
            matched = next(e for e in pool if e.id == candidates[0].existing_id)
            return matched, candidates

        new_entity = ResolvedEntity(
            name=display_name,
            canonical_key=key,
            type=entity_type,
            aliases=[],
            attributes=attributes_to_dict(extracted.attributes),
            is_new=True,
        )
        return new_entity, candidates

    async def apply_merge(
        self,
        entity: ResolvedEntity,
        candidate: MergeCandidate,
    ) -> ResolvedEntity:
        if not entity.id:
            entity = await self.repo.find_entity_by_key(
                canonical_key(candidate.existing_name), candidate.existing_type
            ) or entity
        if entity.id:
            alias = candidate.extracted_name.strip()
            if alias and alias != entity.name and alias not in entity.aliases:
                entity.aliases.append(alias)
        return entity

    async def _embedding_candidates(
        self,
        extracted: ExtractedEntity,
        pool: list[ResolvedEntity],
    ) -> list[MergeCandidate]:
        if not self._openai:
            return []
        same_type = [e for e in pool if e.type == extracted.type]
        if not same_type:
            return []

        query_vec = self._embed(extracted.name)
        candidates: list[MergeCandidate] = []
        for entity in same_type:
            target_vec = entity.embedding
            if not target_vec:
                continue
            score = cosine_similarity(query_vec, target_vec)
            if score >= 0.85:
                candidates.append(
                    MergeCandidate(
                        extracted_name=extracted.name,
                        extracted_type=extracted.type,
                        existing_id=entity.id or "",
                        existing_name=entity.name,
                        existing_type=entity.type,
                        score=score,
                        match_method="embedding",
                    )
                )
        return candidates

    def _embed(self, text: str) -> list[float]:
        if not self._openai:
            return []
        response = self._openai.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_entity(self, name: str) -> list[float] | None:
        if not self.settings.use_embeddings or not self._openai:
            return None
        return self._embed(name)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
