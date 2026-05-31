"""SurrealDB repository for documents, entities, and relationships."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from surrealdb import RecordID

from kg_world_anvil.db.client import DatabaseClient
from kg_world_anvil.db.relations import (
    ensure_relation_table,
    predicate_from_record_id,
)
from kg_world_anvil.models import DocumentRecord, GraphEdge, ResolvedEntity, TextFormat


def _record_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, RecordID):
        return str(value)
    if hasattr(value, "id") and hasattr(value, "table_name"):
        return str(value)
    if hasattr(value, "id"):
        rid = value.id
        if hasattr(value, "table") and value.table and ":" not in str(rid):
            return f"{value.table}:{rid}"
        return str(rid)
    if isinstance(value, dict) and "id" in value:
        return str(value["id"])
    return str(value)


def _to_record_id(value: str | None, table: str) -> RecordID | None:
    if not value:
        return None
    if isinstance(value, RecordID):
        return value
    if ":" in value:
        return RecordID.parse(value)
    return RecordID(table, value)


def _first_result(results: list) -> Any:
    if not results:
        return None
    first = results[0]
    if isinstance(first, dict) and "result" in first:
        inner = first["result"]
        if isinstance(inner, list):
            return inner[0] if inner else None
        return inner
    if isinstance(first, list):
        return first[0] if first else None
    return first


def _all_results(results: list) -> list[Any]:
    if not results:
        return []
    first = results[0]
    if isinstance(first, dict) and "result" in first:
        inner = first["result"]
        return inner if isinstance(inner, list) else [inner]
    if isinstance(first, list):
        return first
    return [first]


class GraphRepository:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    async def get_document_by_hash(self, content_hash: str) -> DocumentRecord | None:
        sql = "SELECT * FROM document WHERE content_hash = $hash LIMIT 1;"
        rows = await self.client.query(sql, {"hash": content_hash})
        row = _first_result(rows)
        if not row:
            return None
        return DocumentRecord(
            id=_record_id(row.get("id")),
            raw=row.get("raw", ""),
            format=TextFormat(row.get("format", "plain")),
            content_hash=row.get("content_hash", content_hash),
            ingested_at=row.get("ingested_at"),
        )

    async def create_document(self, raw: str, fmt: TextFormat, content_hash: str) -> DocumentRecord:
        sql = """
        CREATE document SET
            raw = $raw,
            format = $format,
            content_hash = $hash,
            ingested_at = time::now()
        RETURN AFTER;
        """
        rows = await self.client.query(
            sql, {"raw": raw, "format": fmt.value, "hash": content_hash}
        )
        row = _first_result(rows)
        return DocumentRecord(
            id=_record_id(row.get("id")),
            raw=raw,
            format=fmt,
            content_hash=content_hash,
            ingested_at=row.get("ingested_at"),
        )

    async def find_entity_by_key(self, canonical_key: str, entity_type: str) -> ResolvedEntity | None:
        sql = """
        SELECT * FROM entity
        WHERE canonical_key = $key AND type = $type
        LIMIT 1;
        """
        rows = await self.client.query(sql, {"key": canonical_key, "type": entity_type})
        row = _first_result(rows)
        if not row:
            return None
        return self._row_to_entity(row)

    async def find_entity_by_name_or_alias(self, name: str) -> list[ResolvedEntity]:
        sql = """
        SELECT * FROM entity
        WHERE name = $name OR $name INSIDE aliases
        LIMIT 20;
        """
        rows = await self.client.query(sql, {"name": name})
        return [self._row_to_entity(r) for r in _all_results(rows)]

    async def list_entities(self, search: str = "", limit: int = 100) -> list[ResolvedEntity]:
        if search:
            sql = """
            SELECT * FROM entity
            WHERE string::lowercase(name) CONTAINS string::lowercase($search)
               OR array::any(aliases, |$a| string::lowercase($a) CONTAINS string::lowercase($search))
            LIMIT $limit;
            """
            rows = await self.client.query(sql, {"search": search, "limit": limit})
        else:
            sql = "SELECT * FROM entity LIMIT $limit;"
            rows = await self.client.query(sql, {"limit": limit})
        return [self._row_to_entity(r) for r in _all_results(rows)]

    async def upsert_entity(
        self,
        entity: ResolvedEntity,
        document_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> ResolvedEntity:
        doc_ref = _to_record_id(document_id, "document")
        entity_ref = _to_record_id(entity.id, "entity") if entity.id else None
        if entity.id:
            sql = """
            UPDATE $id SET
                name = $name,
                aliases = $aliases,
                attributes = $attributes,
                embedding = IF $embedding IS NONE THEN embedding ELSE $embedding END,
                source_documents = IF $doc IS NONE THEN source_documents
                    ELSE array::distinct(source_documents + [$doc]) END,
                updated_at = time::now()
            RETURN AFTER;
            """
            rows = await self.client.query(
                sql,
                {
                    "id": entity_ref,
                    "name": entity.name,
                    "aliases": entity.aliases,
                    "attributes": entity.attributes,
                    "embedding": embedding,
                    "doc": doc_ref,
                },
            )
        else:
            sql = """
            CREATE entity SET
                name = $name,
                canonical_key = $key,
                type = $type,
                aliases = $aliases,
                attributes = $attributes,
                embedding = $embedding,
                source_documents = IF $doc IS NONE THEN [] ELSE [$doc] END,
                created_at = time::now(),
                updated_at = time::now()
            RETURN AFTER;
            """
            rows = await self.client.query(
                sql,
                {
                    "name": entity.name,
                    "key": entity.canonical_key,
                    "type": entity.type,
                    "aliases": entity.aliases,
                    "attributes": entity.attributes,
                    "embedding": embedding,
                    "doc": doc_ref,
                },
            )
        row = _first_result(rows)
        return self._row_to_entity(row)

    async def create_relationship(
        self,
        from_id: str,
        to_id: str,
        predicate: str,
        confidence: float = 1.0,
        document_id: str | None = None,
    ) -> GraphEdge:
        from_ref = _to_record_id(from_id, "entity")
        to_ref = _to_record_id(to_id, "entity")
        doc_ref = _to_record_id(document_id, "document")
        relation_table = await ensure_relation_table(self.client, predicate)
        sql = f"""
        RELATE $from->{relation_table}->$to SET
            confidence = $confidence,
            source_document = $doc,
            extracted_at = time::now()
        RETURN AFTER;
        """
        rows = await self.client.query(
            sql,
            {
                "from": from_ref,
                "to": to_ref,
                "confidence": confidence,
                "doc": doc_ref,
            },
        )
        row = _first_result(rows)
        edge_id = _record_id(row.get("id"))
        return GraphEdge(
            id=edge_id,
            predicate=predicate_from_record_id(edge_id) or relation_table,
            confidence=row.get("confidence", confidence),
            source_document_id=_record_id(row.get("source_document")),
            from_entity_id=from_id,
            from_entity_name="",
            to_entity_id=to_id,
            to_entity_name="",
        )

    async def get_entity_neighbors(self, entity_id: str) -> list[GraphEdge]:
        entity_ref = _to_record_id(entity_id, "entity")
        outbound_sql = """
        SELECT
            id,
            confidence,
            source_document,
            in AS from_entity,
            out AS to_entity
        FROM $id->?;
        """
        inbound_sql = """
        SELECT
            id,
            confidence,
            source_document,
            in AS from_entity,
            out AS to_entity
        FROM $id<-?;
        """
        outbound = _all_results(await self.client.query(outbound_sql, {"id": entity_ref}))
        inbound = _all_results(await self.client.query(inbound_sql, {"id": entity_ref}))
        edges: list[GraphEdge] = []
        seen: set[str] = set()
        for row in outbound + inbound:
            edge_id = _record_id(row.get("id"))
            if not edge_id or edge_id in seen:
                continue
            seen.add(edge_id)
            from_entity = row.get("from_entity") or row.get("in")
            to_entity = row.get("to_entity") or row.get("out")
            from_id = _record_id(from_entity)
            to_id = _record_id(to_entity)
            from_name = from_entity.get("name", "") if isinstance(from_entity, dict) else ""
            to_name = to_entity.get("name", "") if isinstance(to_entity, dict) else ""
            conf = row.get("confidence")
            edges.append(
                GraphEdge(
                    id=edge_id,
                    predicate=predicate_from_record_id(edge_id),
                    confidence=float(conf) if conf is not None else 1.0,
                    source_document_id=_record_id(row.get("source_document")),
                    from_entity_id=from_id,
                    from_entity_name=from_name,
                    to_entity_id=to_id,
                    to_entity_name=to_name,
                )
            )
        return edges

    async def get_all_entities_for_matching(self) -> list[ResolvedEntity]:
        rows = await self.client.query("SELECT * FROM entity;")
        return [self._row_to_entity(r) for r in _all_results(rows)]

    async def run_select(self, sql: str, vars: dict | None = None) -> list[dict[str, Any]]:
        rows = await self.client.query(sql, vars or {})
        return _all_results(rows)

    def _row_to_entity(self, row: dict[str, Any]) -> ResolvedEntity:
        return ResolvedEntity(
            id=_record_id(row.get("id")),
            name=row.get("name", ""),
            canonical_key=row.get("canonical_key", ""),
            type=row.get("type", ""),
            aliases=list(row.get("aliases") or []),
            attributes=dict(row.get("attributes") or {}),
            embedding=list(row.get("embedding") or []) or None,
            is_new=False,
        )


def rows_to_query_result(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    if not rows:
        return [], []
    columns = list(rows[0].keys())
    table_rows: list[list[Any]] = []
    for row in rows:
        table_rows.append([_serialize_cell(row.get(col)) for col in columns])
    return columns, table_rows


def _serialize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if hasattr(value, "id"):
        return str(value.id)
    if isinstance(value, dict) and "id" in value:
        return str(value["id"])
    return json.dumps(value, default=str)
