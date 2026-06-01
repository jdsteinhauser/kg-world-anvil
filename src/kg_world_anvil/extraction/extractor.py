"""OpenAI structured extraction from text chunks."""

from __future__ import annotations

from openai import OpenAI

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.models import (
    EntityAttribute,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    attributes_to_dict,
    format_predicate_prompt,
)
from kg_world_anvil.debug_log import debug_log
from kg_world_anvil.extraction.predicates import is_relationship_negated_in_text
from kg_world_anvil.normalization.names import canonical_key, normalize_entity_name

SYSTEM_PROMPT = f"""You extract a knowledge graph from source text.

Rules:
- Only extract entities and relationships explicitly supported by the text.
- Do not invent facts not present in the source.
- Use concise entity types (person, location, organization, event, concept, item, role, etc.).
- Include optional attributes as key-value pairs only when clearly stated in the text.
- Only extract positive, asserted relationships between entities.
- Do NOT extract negated or absence relationships; if the text only says two things are NOT connected, omit it.
- Never use associated_with when the text negates a connection (e.g. "X was not associated with Y" -> extract X and Y as entities only, no relationship).

Relationships (important):
{format_predicate_prompt()}

Entity naming (important):
- Prefer the most specific proper name available in the text over generic type words.
- For places (city, county, town, village, region, river, lake, mountain, etc.):
  - When the text names a place, use that proper name as the entity — never the bare type word.
  - Resolve later generic references ("the city", "the county") to the proper name introduced earlier in the document.
  - Use the same proper place name consistently across all entities and relationships.
  - Only use a bare generic place noun when the document never names that specific place.
- Do NOT include leading articles unless they are part of a proper name.
- Do NOT include wrapping quotes or emphasis markers in names.
- Keep proper names as written: "The Beatles" stays "The Beatles"; "The Hague" stays "The Hague"; "Oran County" stays "Oran County".
- For titles and roles (mayor, king, captain, etc.):
  - When a title is held by a named person, extract the person as the entity and express the role as a relationship with the role in detail — do NOT create a standalone generic role entity.
  - Only create a role as its own entity when no specific person is named.
- Use the same canonical name consistently across all entities and relationships in your response.
- Examples:
  - "the city of Twickenham" or later "the city" when Twickenham was named -> entity name: "Twickenham" (type: city), NOT "city"
  - "Oran County" or "the county" when Oran County was named -> entity name: "Oran County", NOT "county"
  - "Mayor Alice announced..." -> entity: "Alice" (person); relationship with detail "mayor" (e.g. leads or member_of)
  - "the mayor announced..." with no name given -> entity name: "mayor" (type: role)
  - "Alice works as mayor of Twickenham" -> entity: "Alice"; predicate: member_of or leads, detail: "mayor of Twickenham"
  - "a local bakery" -> entity name: "local bakery" (only when no proper name is given)
  - "the old bridge collapsed" -> entity name: "old bridge" (only when no proper name is given)
"""


class KnowledgeExtractor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key)

    def extract_chunk(self, text: str) -> ExtractionResult:
        completion = self.client.beta.chat.completions.parse(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract entities and relationships from this text:\n\n{text}",
                },
            ],
            response_format=ExtractionResult,
        )
        message = completion.choices[0].message
        if message.parsed is None:
            refusal = message.refusal or "Model refused to extract."
            raise RuntimeError(refusal)
        return message.parsed

    def extract_text(self, text: str, chunk_size: int | None = None, overlap: int | None = None) -> ExtractionResult:
        from kg_world_anvil.ingestion.chunker import chunk_text

        chunks = chunk_text(
            text,
            chunk_size=chunk_size or self.settings.chunk_size,
            overlap=overlap or self.settings.chunk_overlap,
        )
        merged = ExtractionResult(entities=[], relationships=[])
        for chunk in chunks:
            result = self.extract_chunk(chunk)
            merged.entities.extend(result.entities)
            merged.relationships.extend(result.relationships)
        deduped = dedupe_extraction(merged)
        return filter_negated_relationships(deduped, text)


def filter_negated_relationships(result: ExtractionResult, source_text: str) -> ExtractionResult:
    """Drop relationships whose source text explicitly negates the link."""
    kept: list[ExtractedRelationship] = []
    for rel in result.relationships:
        negated = is_relationship_negated_in_text(rel.subject, rel.object, source_text)
        # #region agent log
        debug_log(
            "extractor.py:filter_negated_relationships",
            "relationship negation check",
            {
                "subject": rel.subject,
                "predicate": rel.predicate.value,
                "object": rel.object,
                "negated_in_text": negated,
            },
            hypothesis_id="A",
        )
        # #endregion
        if negated:
            continue
        kept.append(rel)
    return ExtractionResult(entities=result.entities, relationships=kept)


def dedupe_extraction(result: ExtractionResult) -> ExtractionResult:
    entity_map: dict[tuple[str, str], ExtractedEntity] = {}
    for entity in result.entities:
        normalized_name = normalize_entity_name(entity.name)
        key = (canonical_key(entity.name), entity.type.strip().lower())
        if key not in entity_map:
            entity.name = normalized_name
            entity_map[key] = entity
        else:
            existing = entity_map[key]
            merged_attrs = attributes_to_dict(existing.attributes)
            merged_attrs.update(attributes_to_dict(entity.attributes))
            existing.attributes = [
                EntityAttribute(key=k, value=v) for k, v in merged_attrs.items()
            ]

    rel_map: dict[tuple[str, str, str], ExtractedRelationship] = {}
    for rel in result.relationships:
        key = (
            canonical_key(rel.subject),
            rel.predicate.value,
            canonical_key(rel.object),
        )
        if key not in rel_map:
            rel_map[key] = rel
        else:
            existing = rel_map[key]
            if rel.detail.strip() and not existing.detail.strip():
                existing.detail = rel.detail.strip()

    return ExtractionResult(
        entities=list(entity_map.values()),
        relationships=list(rel_map.values()),
    )
