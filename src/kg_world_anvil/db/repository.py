"""SurrealDB repository for documents, entities, and relationships."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from surrealdb import RecordID

from kg_world_anvil.db.client import DatabaseClient
from kg_world_anvil.db.relations import (
    ensure_relation_table,
    is_staging_table_name,
    normalize_relation_table,
    predicate_from_record_id,
)
from kg_world_anvil.extraction.predicates import is_absence_relationship
from kg_world_anvil.models import CanonicalPredicate, DocumentRecord, GraphEdge, ResolvedEntity, TextFormat, coerce_text_format
from kg_world_anvil.normalization.names import canonical_key, normalize_display_name, normalize_entity_type


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
    if all(isinstance(item, dict) and "result" not in item for item in results):
        return list(results)
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
            format=coerce_text_format(row.get("format")),
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

    async def find_entity_by_key(self, canonical_key_val: str, entity_type: str) -> ResolvedEntity | None:
        entity_type_cf = normalize_entity_type(entity_type)
        for entity in await self.find_entities_by_canonical_key(canonical_key_val):
            if entity.type.strip().casefold() == entity_type_cf:
                return entity
        return None

    async def find_entities_by_canonical_key(self, key: str) -> list[ResolvedEntity]:
        normalized = canonical_key(key)
        return [
            entity
            for entity in await self.get_all_entities_for_matching()
            if canonical_key(entity.canonical_key or entity.name) == normalized
        ]

    async def find_entity_by_name_or_alias(self, name: str) -> list[ResolvedEntity]:
        key = canonical_key(name)
        sql = """
        SELECT * FROM entity
        WHERE name = $name
           OR $name INSIDE aliases
           OR canonical_key = $key
        LIMIT 20;
        """
        rows = await self.client.query(sql, {"name": normalize_display_name(name), "key": key})
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
        if not entity.id:
            existing = await self.find_entity_by_key(entity.canonical_key, entity.type)
            if existing and existing.id:
                entity = entity.model_copy(update={"id": existing.id})
                entity_ref = _to_record_id(entity.id, "entity")
        if entity.id:
            sql = """
            UPDATE $id SET
                name = $name,
                aliases = $aliases,
                broader_types = $broader_types,
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
                    "broader_types": entity.broader_types,
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
                broader_types = $broader_types,
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
                    "type": normalize_entity_type(entity.type),
                    "aliases": entity.aliases,
                    "broader_types": entity.broader_types,
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
        detail: str = "",
    ) -> GraphEdge:
        if is_absence_relationship(predicate):
            raise ValueError(f"Absence relationships are not stored: {predicate}")
        normalized = predicate.strip().lower()
        allowed = {p.value for p in CanonicalPredicate}
        if normalized not in allowed:
            raise ValueError(f"Unknown relationship predicate: {predicate}")
        from_ref = _to_record_id(from_id, "entity")
        to_ref = _to_record_id(to_id, "entity")
        doc_ref = _to_record_id(document_id, "document")
        relation_table = await ensure_relation_table(self.client, predicate)
        sql = f"""
        RELATE $from->{relation_table}->$to SET
            confidence = $confidence,
            detail = $detail,
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
                "detail": detail,
                "doc": doc_ref,
            },
        )
        row = _first_result(rows)
        edge_id = _record_id(row.get("id"))
        return GraphEdge(
            id=edge_id,
            predicate=predicate_from_record_id(edge_id) or relation_table,
            detail=row.get("detail") or detail,
            confidence=row.get("confidence", confidence),
            source_document_id=_record_id(row.get("source_document")),
            from_entity_id=from_id,
            from_entity_name="",
            to_entity_id=to_id,
            to_entity_name="",
        )

    async def relationship_exists(
        self,
        from_id: str,
        to_id: str,
        predicate: str,
    ) -> bool:
        table = await ensure_relation_table(self.client, predicate)
        from_ref = _to_record_id(from_id, "entity")
        to_ref = _to_record_id(to_id, "entity")
        sql = f"SELECT id FROM {table} WHERE in = $from AND out = $to LIMIT 1;"
        try:
            rows = await self.client.query(sql, {"from": from_ref, "to": to_ref})
        except Exception:
            return False
        return _first_result(rows) is not None

    async def get_entity_neighbors(self, entity_id: str) -> list[GraphEdge]:
        entity_ref = _to_record_id(entity_id, "entity")
        outbound_sql = """
        SELECT
            id,
            confidence,
            detail,
            source_document,
            in AS from_entity,
            out AS to_entity
        FROM $id->?;
        """
        inbound_sql = """
        SELECT
            id,
            confidence,
            detail,
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
                    detail=str(row.get("detail") or ""),
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

    async def find_relation_tables(self) -> list[str]:
        """Return names of SCHEMAFULL relation tables (predicate edges)."""
        rows = await self.client.query("INFO FOR DB;")
        info = _first_result(rows)
        if not isinstance(info, dict):
            return []
        tables = info.get("tables") or info.get("Tables") or {}
        if not isinstance(tables, dict):
            return []
        relation_tables: list[str] = []
        for name, definition in tables.items():
            if is_staging_table_name(name):
                continue
            if name in ("document", "entity"):
                continue
            def_str = str(definition).upper()
            if "RELATION" in def_str:
                relation_tables.append(name)
        return relation_tables

    async def count_entity_edges(self, entity_id: str) -> int:
        edges = await self.get_entity_neighbors(entity_id)
        return len(edges)

    async def reassign_edges(self, from_id: str, to_id: str) -> int:
        """Move all edges from from_id to to_id; drop self-loops and duplicate edges."""
        if from_id == to_id:
            return 0
        from_ref = _to_record_id(from_id, "entity")
        to_ref = _to_record_id(to_id, "entity")
        rewired = 0
        for table in await self.find_relation_tables():
            in_sql = f"UPDATE {table} SET in = $to WHERE in = $from RETURN AFTER;"
            out_sql = f"UPDATE {table} SET out = $to WHERE out = $from RETURN AFTER;"
            in_rows = _all_results(
                await self.client.query(in_sql, {"from": from_ref, "to": to_ref})
            )
            out_rows = _all_results(
                await self.client.query(out_sql, {"from": from_ref, "to": to_ref})
            )
            rewired += len(in_rows) + len(out_rows)

            await self.client.query(
                f"DELETE {table} WHERE in = out AND (in = $to OR out = $to);",
                {"to": to_ref},
            )
            await self._dedupe_relation_edges(table, to_id)

        return rewired

    async def _dedupe_relation_edges(self, table: str, entity_id: str) -> None:
        """Remove duplicate edges with the same in/out endpoints touching entity_id."""
        entity_ref = _to_record_id(entity_id, "entity")
        sql = f"""
        SELECT id, in, out FROM {table}
        WHERE in = $id OR out = $id;
        """
        rows = _all_results(await self.client.query(sql, {"id": entity_ref}))
        seen: dict[tuple[str, str], str] = {}
        for row in rows:
            in_id = _record_id(row.get("in"))
            out_id = _record_id(row.get("out"))
            edge_id = _record_id(row.get("id"))
            if not edge_id:
                continue
            key = (in_id, out_id)
            if key in seen:
                dup_ref = _to_record_id(edge_id, table)
                if dup_ref:
                    await self.client.query(f"DELETE $id;", {"id": dup_ref})
            else:
                seen[key] = edge_id

    async def merge_entity_fields(
        self,
        survivor_id: str,
        *,
        name: str,
        aliases: list[str],
        broader_types: list[str],
        attributes: dict[str, Any],
        source_documents: list[str] | None = None,
    ) -> ResolvedEntity:
        entity_ref = _to_record_id(survivor_id, "entity")
        doc_refs = [_to_record_id(doc_id, "document") for doc_id in (source_documents or [])]
        doc_refs = [d for d in doc_refs if d is not None]
        sql = """
        UPDATE $id SET
            name = $name,
            aliases = $aliases,
            broader_types = $broader_types,
            attributes = $attributes,
            source_documents = IF array::len($docs) = 0 THEN source_documents
                ELSE array::distinct(source_documents + $docs) END,
            updated_at = time::now()
        RETURN AFTER;
        """
        rows = await self.client.query(
            sql,
            {
                "id": entity_ref,
                "name": name,
                "aliases": aliases,
                "broader_types": broader_types,
                "attributes": attributes,
                "docs": doc_refs,
            },
        )
        row = _first_result(rows)
        return self._row_to_entity(row)

    async def delete_entity(self, entity_id: str) -> None:
        entity_ref = _to_record_id(entity_id, "entity")
        await self.client.query("DELETE $id;", {"id": entity_ref})

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
            broader_types=list(row.get("broader_types") or []),
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
