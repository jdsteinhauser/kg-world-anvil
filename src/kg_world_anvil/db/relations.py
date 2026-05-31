"""Dynamic named relation tables for SurrealDB graph edges."""

from __future__ import annotations

import re

from kg_world_anvil.db.client import DatabaseClient

_RELATION_FIELD_STATEMENTS = (
    "DEFINE FIELD confidence ON {table} TYPE float DEFAULT 1.0;",
    "DEFINE FIELD source_document ON {table} TYPE option<record<document>> DEFAULT NONE;",
    "DEFINE FIELD extracted_at ON {table} TYPE datetime DEFAULT time::now();",
)


def normalize_relation_table(predicate: str) -> str:
    """Convert an extracted predicate into a safe SurrealDB relation table name."""
    name = predicate.strip().lower().replace(" ", "_").replace("-", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    if not name:
        return "related_to"
    if name[0].isdigit():
        return f"rel_{name}"
    return name


def predicate_from_record_id(record_id: str) -> str:
    if ":" in record_id:
        return record_id.split(":", 1)[0]
    return record_id


async def ensure_relation_table(client: DatabaseClient, predicate: str) -> str:
    """Ensure a SCHEMAFULL relation table exists for the given predicate."""
    table = normalize_relation_table(predicate)
    statements = [
        f"DEFINE TABLE {table} TYPE RELATION FROM entity TO entity SCHEMAFULL;",
        *[stmt.format(table=table) for stmt in _RELATION_FIELD_STATEMENTS],
    ]
    for statement in statements:
        try:
            await client.query(statement)
        except Exception:
            # Table/field may already exist from a prior ingest.
            pass
    return table
