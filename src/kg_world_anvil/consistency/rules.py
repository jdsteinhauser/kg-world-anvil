"""Pluggable consistency rules for the knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.models import InconsistencyIssue


@dataclass
class ConsistencyRule:
    id: str
    name: str
    severity: str
    sql: str
    message_template: str


RULES: list[ConsistencyRule] = [
    ConsistencyRule(
        id="functional_born_in",
        name="Multiple birth locations",
        severity="warning",
        sql="""
        SELECT in.name AS entity, count() AS cnt
        FROM born_in
        GROUP BY in
        HAVING cnt > 1;
        """,
        message_template="Entity '{entity}' has {cnt} born_in relationships.",
    ),
    ConsistencyRule(
        id="type_conflict",
        name="Same canonical key, different types",
        severity="error",
        sql="""
        SELECT canonical_key, array::distinct(type) AS types, count() AS cnt
        FROM entity
        GROUP BY canonical_key
        HAVING cnt > 1;
        """,
        message_template="Canonical key '{canonical_key}' appears with types: {types}.",
    ),
    ConsistencyRule(
        id="reciprocal_parent",
        name="Reciprocal parent_of edges",
        severity="error",
        sql="""
        SELECT
            in.name AS a,
            out.name AS b
        FROM parent_of AS r1
        WHERE EXISTS (
            SELECT * FROM parent_of AS r2
            WHERE r2.in = r1.out
            AND r2.out = r1.in
        );
        """,
        message_template="'{a}' and '{b}' are both parent_of each other.",
    ),
    ConsistencyRule(
        id="orphan_predicate",
        name="Relationships with missing endpoints",
        severity="warning",
        sql="""
        SELECT id, type::table(id) AS predicate FROM parent_of
        WHERE in IS NONE OR out IS NONE;
        """,
        message_template="Relationship {id} ({predicate}) has a missing endpoint.",
    ),
]


class ConsistencyChecker:
    def __init__(self, repo: GraphRepository) -> None:
        self.repo = repo

    async def run_all(self) -> list[InconsistencyIssue]:
        issues: list[InconsistencyIssue] = []
        for rule in RULES:
            issues.extend(await self.run_rule(rule))
        return issues

    async def run_rule(self, rule: ConsistencyRule) -> list[InconsistencyIssue]:
        try:
            rows = await self.repo.run_select(rule.sql)
        except Exception as exc:
            return [
                InconsistencyIssue(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity="error",
                    message=f"Rule failed to execute: {exc}",
                    details={"sql": rule.sql},
                )
            ]

        if not rows:
            return []

        issues: list[InconsistencyIssue] = []
        for row in rows:
            message = format_message(rule.message_template, row)
            issues.append(
                InconsistencyIssue(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=message,
                    details=row,
                )
            )
        return issues


def format_message(template: str, row: dict[str, Any]) -> str:
    try:
        return template.format(**{k: row.get(k, "") for k in row})
    except (KeyError, IndexError):
        return template + " " + str(row)
