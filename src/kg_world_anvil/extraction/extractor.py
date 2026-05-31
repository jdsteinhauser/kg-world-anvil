"""OpenAI structured extraction from text chunks."""

from __future__ import annotations

from openai import OpenAI

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    EntityAttribute,
    attributes_to_dict,
)

SYSTEM_PROMPT = """You extract a knowledge graph from source text.

Rules:
- Only extract entities and relationships explicitly supported by the text.
- Do not invent facts not present in the source.
- Use concise entity types (person, location, organization, event, concept, item, etc.).
- Use snake_case relationship predicates (e.g. parent_of, located_in, member_of).
- Include optional attributes as key-value pairs only when clearly stated in the text.
- Prefer canonical names over nicknames when both appear.
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
        return dedupe_extraction(merged)


def dedupe_extraction(result: ExtractionResult) -> ExtractionResult:
    entity_map: dict[tuple[str, str], ExtractedEntity] = {}
    for entity in result.entities:
        key = (entity.name.strip().lower(), entity.type.strip().lower())
        if key not in entity_map:
            entity_map[key] = entity
        else:
            existing = entity_map[key]
            merged_attrs = attributes_to_dict(existing.attributes)
            merged_attrs.update(attributes_to_dict(entity.attributes))
            existing.attributes = [
                EntityAttribute(key=k, value=v) for k, v in merged_attrs.items()
            ]

    rel_set: set[tuple[str, str, str]] = set()
    relationships: list[ExtractedRelationship] = []
    for rel in result.relationships:
        key = (
            rel.subject.strip().lower(),
            rel.predicate.strip().lower(),
            rel.object.strip().lower(),
        )
        if key not in rel_set:
            rel_set.add(key)
            relationships.append(rel)

    return ExtractionResult(
        entities=list(entity_map.values()),
        relationships=relationships,
    )
