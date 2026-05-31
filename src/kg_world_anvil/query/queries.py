"""Saved and parameterized graph queries."""

from __future__ import annotations

from typing import Any

from kg_world_anvil.db.repository import GraphRepository, rows_to_query_result
from kg_world_anvil.models import QueryResultRow, ResolvedEntity


SAVED_QUERIES: dict[str, dict[str, Any]] = {
    "find_entity": {
        "label": "Find entity by name or alias",
        "params": ["name"],
        "description": "Search entities matching a name or alias.",
    },
    "entity_relationships": {
        "label": "List entity relationships",
        "params": ["entity_name"],
        "description": "Show all relationships for an entity.",
    },
    "entities_by_type": {
        "label": "Entities by type",
        "params": ["type"],
        "description": "List entities of a given type.",
    },
    "path_between": {
        "label": "Path between two entities",
        "params": ["from_name", "to_name"],
        "description": "Find graph paths between two entities (depth 3).",
    },
    "search_attribute": {
        "label": "Search by attribute value",
        "params": ["key", "value"],
        "description": "Find entities with a matching attribute.",
    },
}


class QueryService:
    def __init__(self, repo: GraphRepository) -> None:
        self.repo = repo

    async def run_saved(self, query_id: str, params: dict[str, str]) -> QueryResultRow:
        if query_id == "find_entity":
            entities = await self.repo.find_entity_by_name_or_alias(params["name"])
            rows = [e.model_dump() for e in entities]
            cols, table = rows_to_query_result(rows)
            return QueryResultRow(columns=cols, rows=table)

        if query_id == "entity_relationships":
            entities = await self.repo.find_entity_by_name_or_alias(params["entity_name"])
            if not entities:
                return QueryResultRow(columns=[], rows=[])
            entity = entities[0]
            edges = await self.repo.get_entity_neighbors(entity.id or "")
            rows = [e.model_dump() for e in edges]
            cols, table = rows_to_query_result(rows)
            return QueryResultRow(columns=cols, rows=table)

        if query_id == "entities_by_type":
            sql = "SELECT * FROM entity WHERE type = $type LIMIT 100;"
            rows = await self.repo.run_select(sql, {"type": params["type"]})
            cols, table = rows_to_query_result(rows)
            return QueryResultRow(columns=cols, rows=table)

        if query_id == "path_between":
            sql = """
            SELECT * FROM (
                SELECT path FROM (
                    SELECT ->?->entity AS path FROM entity
                    WHERE name = $from_name
                )
            )
            WHERE array::any(path, |$n| $n.name = $to_name)
            LIMIT 10;
            """
            rows = await self.repo.run_select(
                sql, {"from_name": params["from_name"], "to_name": params["to_name"]}
            )
            cols, table = rows_to_query_result(rows)
            return QueryResultRow(columns=cols, rows=table)

        if query_id == "search_attribute":
            sql = """
            SELECT * FROM entity
            WHERE attributes[$key] = $value
            LIMIT 100;
            """
            rows = await self.repo.run_select(
                sql, {"key": params["key"], "value": params["value"]}
            )
            cols, table = rows_to_query_result(rows)
            return QueryResultRow(columns=cols, rows=table)

        raise ValueError(f"Unknown saved query: {query_id}")

    async def run_raw(self, sql: str) -> QueryResultRow:
        validate_readonly(sql)
        rows = await self.repo.run_select(sql)
        cols, table = rows_to_query_result(rows)
        return QueryResultRow(columns=cols, rows=table)


def validate_readonly(sql: str) -> None:
    normalized = " ".join(sql.strip().lower().split())
    forbidden = (
        "create ",
        "update ",
        "delete ",
        "relate ",
        "insert ",
        "define ",
        "remove ",
        "drop ",
    )
    for token in forbidden:
        if token in normalized:
            raise ValueError(f"Mutating statements are not allowed in query mode: {token.strip()}")
