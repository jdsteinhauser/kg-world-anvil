"""Pydantic models for extraction and domain objects."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TextFormat(str, Enum):
    PLAIN = "plain"
    HTML = "html"
    MARKDOWN = "markdown"
    BBCODE = "bbcode"


class EntityAttribute(BaseModel):
    key: str = Field(description="Attribute name")
    value: str = Field(description="Attribute value from the source text")


class ExtractedEntity(BaseModel):
    name: str = Field(description="Entity display name as found in source text")
    type: str = Field(description="Entity type, e.g. person, location, organization, concept")
    attributes: list[EntityAttribute] = Field(
        description="Optional key-value attributes extracted from the text; use empty list if none",
    )


class ExtractedRelationship(BaseModel):
    subject: str = Field(description="Subject entity name")
    predicate: str = Field(description="Relationship type, e.g. parent_of, located_in")
    object: str = Field(description="Object entity name")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0", ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(
        description="Entities found in the text; empty list if none",
    )
    relationships: list[ExtractedRelationship] = Field(
        description="Relationships found in the text; empty list if none",
    )


def attributes_to_dict(attributes: list[EntityAttribute]) -> dict[str, str]:
    return {item.key: item.value for item in attributes}


class MergeCandidate(BaseModel):
    extracted_name: str
    extracted_type: str
    existing_id: str
    existing_name: str
    existing_type: str
    score: float
    match_method: str  # "exact", "fuzzy", "embedding"


class ReviewDecision(str, Enum):
    MERGE = "merge"
    CREATE_NEW = "create_new"
    SKIP = "skip"


class ResolvedEntity(BaseModel):
    id: str | None = None
    name: str
    canonical_key: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    is_new: bool = False


class DocumentRecord(BaseModel):
    id: str | None = None
    raw: str
    format: TextFormat
    content_hash: str
    ingested_at: datetime | None = None


class GraphEdge(BaseModel):
    id: str | None = None
    predicate: str
    confidence: float = 1.0
    source_document_id: str | None = None
    from_entity_id: str
    from_entity_name: str
    to_entity_id: str
    to_entity_name: str


class InconsistencyIssue(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class GeneratedQuery(BaseModel):
    question: str
    surrealql: str
    explanation: str = ""


class QueryResultRow(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
