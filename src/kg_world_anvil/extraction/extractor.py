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
from kg_world_anvil.extraction.predicates import (
    format_absence_relationship_prompt,
    is_relationship_negated_in_text,
)
from kg_world_anvil.normalization.names import canonical_key, normalize_display_name, normalize_entity_type


def normalize_extraction_result(result: ExtractionResult) -> ExtractionResult:
    """Clean entity and relationship names before dedupe and storage."""
    entities = [
        ExtractedEntity(
            name=normalize_display_name(entity.name),
            type=normalize_entity_type(entity.type),
            attributes=entity.attributes,
        )
        for entity in result.entities
    ]
    relationships = [
        ExtractedRelationship(
            subject=normalize_display_name(rel.subject),
            predicate=rel.predicate,
            object=normalize_display_name(rel.object),
            confidence=rel.confidence,
            detail=rel.detail,
        )
        for rel in result.relationships
    ]
    return ExtractionResult(entities=entities, relationships=relationships)

SYSTEM_PROMPT = f"""You extract a knowledge graph from articles and timelines.
These articles and timelinesare from WorldAnvil, and they are specifically about
world-building, manuscript writing, and TTRPG campaigns.

Rules:
- The types of texts/articles you will encounter are about buildings, characters, countries, militaries, gods/deities,
  geographical features, items (coins, tools, weapons, etc.), organizations (including families), religions, species,
  vehicles, settlements, conditions (diseases, injuries, etc.), conflicts, documents, cultures/ethnicities, languages,
  materials (wood, metal, stone, etc.), military formations, myths, natural laws, plots, professions, prose, titles,
  spells, technology and traditions.
- Do not include indefinite articles on entity names
- If name can be inferred from the context
- Titles should be treated separately from the entity name. If the entity is never named,
  create a role entity instead.
- Timeline events should be created with a start date/year, end date/year, and a brief description.
- If entities are said to have a relationship, extract the relationship as a relationship between the two entities.
- If entities are said to not be associated with each other, no relationship should be extracted.
- Include optional attributes as key-value pairs only when clearly stated in the text.
- Only extract entities and relationships explicitly supported by the text.
- Do not invent facts not present in the source. If you do not have enough information to extract an entity or relationship,
  do not extract anything.


Relationships (important):
{format_predicate_prompt()}

Absence and negated relationships (never extract):
{format_absence_relationship_prompt()}

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
- Emit final display-ready names in every entity and relationship field (no quotes, markdown, or duplicate variants); downstream code stores names as given.
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
        normalized = normalize_extraction_result(deduped)
        return filter_negated_relationships(normalized, text)


def filter_negated_relationships(result: ExtractionResult, source_text: str) -> ExtractionResult:
    """Drop relationships whose source text explicitly negates the link."""
    kept: list[ExtractedRelationship] = []
    for rel in result.relationships:
        negated = is_relationship_negated_in_text(rel.subject, rel.object, source_text)
        if negated:
            continue
        kept.append(rel)
    return ExtractionResult(entities=result.entities, relationships=kept)


def dedupe_extraction(result: ExtractionResult) -> ExtractionResult:
    entity_map: dict[tuple[str, str], ExtractedEntity] = {}
    for entity in result.entities:
        clean_name = normalize_display_name(entity.name)
        clean_type = normalize_entity_type(entity.type)
        key = (canonical_key(clean_name), clean_type)
        if key not in entity_map:
            entity_map[key] = ExtractedEntity(
                name=clean_name,
                type=clean_type,
                attributes=entity.attributes,
            )
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
            canonical_key(normalize_display_name(rel.subject)),
            rel.predicate.value,
            canonical_key(normalize_display_name(rel.object)),
        )
        if key not in rel_map:
            rel_map[key] = ExtractedRelationship(
                subject=normalize_display_name(rel.subject),
                predicate=rel.predicate,
                object=normalize_display_name(rel.object),
                confidence=rel.confidence,
                detail=rel.detail,
            )
        else:
            existing = rel_map[key]
            if rel.detail.strip() and not existing.detail.strip():
                existing.detail = rel.detail.strip()

    return ExtractionResult(
        entities=list(entity_map.values()),
        relationships=list(rel_map.values()),
    )
