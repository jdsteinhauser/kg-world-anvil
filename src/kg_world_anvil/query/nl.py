"""Natural language to SurrealQL translation."""

from __future__ import annotations

from openai import OpenAI

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.db.client import load_schema_text
from kg_world_anvil.models import GeneratedQuery

SCHEMA_SUMMARY = """
Tables:
- document: raw source text (raw, format, content_hash, ingested_at)
- entity: graph nodes (name, canonical_key, type, aliases[], attributes{}, source_documents[])
- Named relation tables (e.g. parent_of, located_in, knows): each TYPE RELATION FROM entity TO entity
  with fields confidence, source_document, extracted_at. The table name is the relationship type.

Common patterns:
- SELECT * FROM entity WHERE name = 'Alice';
- SELECT * FROM entity WHERE type = 'person';
- SELECT out.name AS target FROM knows WHERE in.name = 'Alice';
- SELECT in.name AS source, out.name AS target FROM parent_of;
- Traverse any edge type: SELECT ->?->entity FROM entity WHERE name = 'Alice';
"""


class NLQueryTranslator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key)

    def translate(self, question: str) -> GeneratedQuery:
        schema = load_schema_text()
        completion = self.client.beta.chat.completions.parse(
            model=self.settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You translate natural language questions into read-only SurrealQL SELECT queries "
                        "for a knowledge graph database. Return only safe read queries. "
                        "Never use CREATE, UPDATE, DELETE, RELATE, DEFINE, or DROP.\n\n"
                        f"Schema summary:\n{SCHEMA_SUMMARY}\n\n"
                        f"Full schema:\n{schema[:4000]}"
                    ),
                },
                {"role": "user", "content": question},
            ],
            response_format=GeneratedQuery,
        )
        message = completion.choices[0].message
        if message.parsed is None:
            raise RuntimeError(message.refusal or "Failed to generate query.")
        generated = message.parsed
        from kg_world_anvil.query.queries import validate_readonly

        validate_readonly(generated.surrealql)
        return generated
