"""SurrealDB repository for staging batches, entities, and relationships."""

from __future__ import annotations

from typing import Any

from kg_world_anvil.db.client import DatabaseClient
from kg_world_anvil.db.relations import (
    ensure_staging_relation_table,
    is_staging_relation_table,
    predicate_from_record_id,
)
from kg_world_anvil.extraction.predicates import is_absence_relationship
from kg_world_anvil.models import (
    CanonicalPredicate,
    ChunkExtraction,
    ChunkRecord,
    ExtractionResult,
    StagingBatch,
    StagingBatchStatus,
    StagingEdge,
    StagingEntity,
    attributes_to_dict,
)
from kg_world_anvil.ingestion.provenance import map_extraction_span_to_chunk_seqs
from kg_world_anvil.normalization.names import (
    canonical_key,
    entity_identity_key,
    normalize_display_name,
    normalize_entity_type,
)
from kg_world_anvil.db.repository import (
    GraphRepository,
    _all_results,
    _first_result,
    _record_id,
    _to_record_id,
)


class StagingRepository:
    def __init__(self, client: DatabaseClient, prod_repo: GraphRepository) -> None:
        self.client = client
        self.prod_repo = prod_repo

    async def get_batch(self, batch_id: str) -> StagingBatch | None:
        batch_ref = _to_record_id(batch_id, "staging_batch")
        rows = await self.client.query("SELECT * FROM $id;", {"id": batch_ref})
        row = _first_result(rows)
        if not row:
            return None
        return self._row_to_batch(row)

    async def get_draft_batch(self) -> StagingBatch | None:
        sql = """
        SELECT * FROM staging_batch
        WHERE status = $status
        ORDER BY created_at DESC
        LIMIT 1;
        """
        rows = await self.client.query(sql, {"status": StagingBatchStatus.DRAFT.value})
        row = _first_result(rows)
        if not row:
            return None
        return self._row_to_batch(row)

    async def create_draft_batch(self, document_id: str) -> StagingBatch:
        doc_ref = _to_record_id(document_id, "document")
        sql = """
        CREATE staging_batch SET
            document = $doc,
            status = $status,
            created_at = time::now(),
            updated_at = time::now()
        RETURN AFTER;
        """
        rows = await self.client.query(
            sql,
            {"doc": doc_ref, "status": StagingBatchStatus.DRAFT.value},
        )
        return self._row_to_batch(_first_result(rows))

    async def discard_draft_batch(self, batch_id: str) -> None:
        await self.delete_staging_batch(batch_id, status=StagingBatchStatus.DISCARDED)

    async def mark_batch_committed(self, batch_id: str) -> None:
        batch_ref = _to_record_id(batch_id, "staging_batch")
        await self.client.query(
            """
            UPDATE $id SET status = $status, updated_at = time::now() RETURN AFTER;
            """,
            {"id": batch_ref, "status": StagingBatchStatus.COMMITTED.value},
        )

    async def replace_draft_for_document(
        self,
        document_id: str,
        extraction: ExtractionResult,
        *,
        extractions: list[ChunkExtraction] | None = None,
        rag_chunks: list[ChunkRecord] | None = None,
    ) -> StagingBatch:
        existing_draft = await self.get_draft_batch()
        if existing_draft and existing_draft.id:
            if existing_draft.document_id != document_id:
                raise RuntimeError(
                    "A draft staging batch already exists for another document. "
                    "Commit or discard it before extracting again."
                )
            await self._clear_batch_contents(existing_draft.id)
            batch = existing_draft
        else:
            batch = await self.create_draft_batch(document_id)

        batch_id = batch.id or ""
        batch_ref = _to_record_id(batch_id, "staging_batch")

        entity_chunk_ids: dict[str, list[str]] = {}
        edge_chunk_ids: dict[tuple[str, str, str], list[str]] = {}

        if extractions and rag_chunks:
            for item in extractions:
                for extracted in item.result.entities:
                    display_name = normalize_display_name(extracted.name)
                    entity_type = normalize_entity_type(extracted.type)
                    key = entity_identity_key(display_name, entity_type)
                    seqs = map_extraction_span_to_chunk_seqs(
                        item.start_char,
                        item.end_char,
                        rag_chunks,
                        mention_texts=[display_name],
                    )
                    chunk_ids = _seqs_to_chunk_ids(rag_chunks, seqs)
                    entity_chunk_ids.setdefault(key, [])
                    entity_chunk_ids[key] = _distinct_ids(entity_chunk_ids[key] + chunk_ids)

                for rel in item.result.relationships:
                    rel_key = (
                        canonical_key(normalize_display_name(rel.subject)),
                        rel.predicate.value,
                        canonical_key(normalize_display_name(rel.object)),
                    )
                    seqs = map_extraction_span_to_chunk_seqs(
                        item.start_char,
                        item.end_char,
                        rag_chunks,
                        mention_texts=[rel.subject, rel.object],
                    )
                    chunk_ids = _seqs_to_chunk_ids(rag_chunks, seqs)
                    edge_chunk_ids.setdefault(rel_key, [])
                    edge_chunk_ids[rel_key] = _distinct_ids(edge_chunk_ids[rel_key] + chunk_ids)

        name_to_id: dict[str, str] = {}
        for extracted in extraction.entities:
            display_name = normalize_display_name(extracted.name)
            entity_type = normalize_entity_type(extracted.type)
            key = canonical_key(display_name)
            identity_key = entity_identity_key(display_name, entity_type)
            entity = await self._create_staging_entity(
                batch_ref=batch_ref,
                name=display_name,
                key=key,
                entity_type=entity_type,
                attributes=attributes_to_dict(extracted.attributes),
                source_chunks=entity_chunk_ids.get(identity_key, []),
            )
            if entity.id:
                name_to_id[key] = entity.id

        for rel in extraction.relationships:
            from_key = canonical_key(normalize_display_name(rel.subject))
            to_key = canonical_key(normalize_display_name(rel.object))
            from_id = name_to_id.get(from_key)
            to_id = name_to_id.get(to_key)
            if not from_id or not to_id:
                continue
            rel_key = (from_key, rel.predicate.value, to_key)
            await self.create_staging_relationship(
                from_id,
                to_id,
                rel.predicate.value,
                rel.confidence,
                document_id,
                rel.detail.strip(),
                source_chunks=edge_chunk_ids.get(rel_key, []),
            )

        return batch

    async def list_staging_entities(self, batch_id: str) -> list[StagingEntity]:
        batch_ref = _to_record_id(batch_id, "staging_batch")
        sql = "SELECT * FROM staging_entity WHERE batch = $batch;"
        rows = await self.client.query(sql, {"batch": batch_ref})
        return [self._row_to_staging_entity(r) for r in _all_results(rows)]

    async def list_staging_edges(self, batch_id: str) -> list[StagingEdge]:
        entities = await self.list_staging_entities(batch_id)
        entity_ids = {e.id for e in entities if e.id}
        if not entity_ids:
            return []

        entity_refs = [_to_record_id(eid, "staging_entity") for eid in entity_ids]
        edges: list[StagingEdge] = []
        seen: set[str] = set()

        for table in await self.find_staging_relation_tables():
            for entity_ref in entity_refs:
                if entity_ref is None:
                    continue
                sql = f"""
                SELECT id, in, out, confidence, detail, source_chunks
                FROM {table}
                WHERE in = $id OR out = $id;
                """
                rows = _all_results(await self.client.query(sql, {"id": entity_ref}))
                for row in rows:
                    edge_id = _record_id(row.get("id"))
                    if not edge_id or edge_id in seen:
                        continue
                    from_id = _record_id(row.get("in"))
                    to_id = _record_id(row.get("out"))
                    if from_id not in entity_ids or to_id not in entity_ids:
                        continue
                    seen.add(edge_id)
                    conf = row.get("confidence")
                    edges.append(
                        StagingEdge(
                            id=edge_id,
                            predicate=predicate_from_record_id(edge_id).removeprefix("staging_"),
                            detail=str(row.get("detail") or ""),
                            confidence=float(conf) if conf is not None else 1.0,
                            from_entity_id=from_id,
                            to_entity_id=to_id,
                            source_chunks=[_record_id(item) for item in (row.get("source_chunks") or [])],
                        )
                    )
        return edges

    async def delete_staging_batch(
        self,
        batch_id: str,
        *,
        status: StagingBatchStatus = StagingBatchStatus.DISCARDED,
    ) -> None:
        await self._clear_batch_contents(batch_id)
        batch_ref = _to_record_id(batch_id, "staging_batch")
        if status == StagingBatchStatus.DISCARDED:
            await self.client.query(
                "UPDATE $id SET status = $status, updated_at = time::now();",
                {"id": batch_ref, "status": status.value},
            )
        else:
            await self.client.query("DELETE $id;", {"id": batch_ref})

    async def find_staging_relation_tables(self) -> list[str]:
        rows = await self.client.query("INFO FOR DB;")
        info = _first_result(rows)
        if not isinstance(info, dict):
            return []
        tables = info.get("tables") or info.get("Tables") or {}
        if not isinstance(tables, dict):
            return []
        result: list[str] = []
        for name, definition in tables.items():
            if not is_staging_relation_table(name):
                continue
            if "RELATION" in str(definition).upper():
                result.append(name)
        return result

    async def create_staging_relationship(
        self,
        from_id: str,
        to_id: str,
        predicate: str,
        confidence: float = 1.0,
        document_id: str | None = None,
        detail: str = "",
        source_chunks: list[str] | None = None,
    ) -> StagingEdge:
        if is_absence_relationship(predicate):
            raise ValueError(f"Absence relationships are not stored: {predicate}")
        normalized = predicate.strip().lower()
        allowed = {p.value for p in CanonicalPredicate}
        if normalized not in allowed:
            raise ValueError(f"Unknown relationship predicate: {predicate}")

        from_ref = _to_record_id(from_id, "staging_entity")
        to_ref = _to_record_id(to_id, "staging_entity")
        doc_ref = _to_record_id(document_id, "document")
        chunk_refs = [_to_record_id(chunk_id, "chunk") for chunk_id in (source_chunks or [])]
        chunk_refs = [ref for ref in chunk_refs if ref is not None]
        relation_table = await ensure_staging_relation_table(self.client, predicate)
        sql = f"""
        RELATE $from->{relation_table}->$to SET
            confidence = $confidence,
            detail = $detail,
            source_document = $doc,
            source_chunks = $chunks,
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
                "chunks": chunk_refs,
            },
        )
        row = _first_result(rows)
        edge_id = _record_id(row.get("id"))
        return StagingEdge(
            id=edge_id,
            predicate=normalized,
            detail=row.get("detail") or detail,
            confidence=row.get("confidence", confidence),
            from_entity_id=from_id,
            to_entity_id=to_id,
            source_chunks=[_record_id(item) for item in (row.get("source_chunks") or [])],
        )

    async def _clear_batch_contents(self, batch_id: str) -> None:
        entities = await self.list_staging_entities(batch_id)
        entity_ids = [e.id for e in entities if e.id]
        if entity_ids:
            for table in await self.find_staging_relation_tables():
                for entity_id in entity_ids:
                    entity_ref = _to_record_id(entity_id, "staging_entity")
                    await self.client.query(
                        f"DELETE {table} WHERE in = $id OR out = $id;",
                        {"id": entity_ref},
                    )
        batch_ref = _to_record_id(batch_id, "staging_batch")
        await self.client.query(
            "DELETE staging_entity WHERE batch = $batch;",
            {"batch": batch_ref},
        )

    async def _create_staging_entity(
        self,
        *,
        batch_ref: Any,
        name: str,
        key: str,
        entity_type: str,
        attributes: dict[str, Any],
        source_chunks: list[str] | None = None,
    ) -> StagingEntity:
        chunk_refs = [_to_record_id(chunk_id, "chunk") for chunk_id in (source_chunks or [])]
        chunk_refs = [ref for ref in chunk_refs if ref is not None]
        sql = """
        CREATE staging_entity SET
            batch = $batch,
            name = $name,
            canonical_key = $key,
            type = $type,
            aliases = [],
            broader_types = [],
            attributes = $attributes,
            embedding = NONE,
            source_chunks = $chunks,
            created_at = time::now()
        RETURN AFTER;
        """
        rows = await self.client.query(
            sql,
            {
                "batch": batch_ref,
                "name": name,
                "key": key,
                "type": entity_type,
                "attributes": attributes,
                "chunks": chunk_refs,
            },
        )
        return self._row_to_staging_entity(_first_result(rows))

    def _row_to_batch(self, row: dict[str, Any]) -> StagingBatch:
        doc = row.get("document")
        doc_id = _record_id(doc)
        status_raw = row.get("status", StagingBatchStatus.DRAFT.value)
        try:
            status = StagingBatchStatus(status_raw)
        except ValueError:
            status = StagingBatchStatus.DRAFT
        return StagingBatch(
            id=_record_id(row.get("id")),
            document_id=doc_id,
            status=status,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_staging_entity(self, row: dict[str, Any]) -> StagingEntity:
        batch = row.get("batch")
        return StagingEntity(
            id=_record_id(row.get("id")),
            batch_id=_record_id(batch),
            name=row.get("name", ""),
            canonical_key=row.get("canonical_key", ""),
            type=row.get("type", ""),
            aliases=list(row.get("aliases") or []),
            broader_types=list(row.get("broader_types") or []),
            attributes=dict(row.get("attributes") or {}),
            embedding=list(row.get("embedding") or []) or None,
            source_chunks=[_record_id(item) for item in (row.get("source_chunks") or [])],
            is_new=False,
        )


def _seqs_to_chunk_ids(rag_chunks: list[ChunkRecord], seqs: list[int]) -> list[str]:
    by_seq = {chunk.seq: chunk.id for chunk in rag_chunks if chunk.id is not None}
    return [by_seq[seq] for seq in seqs if seq in by_seq]


def _distinct_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
