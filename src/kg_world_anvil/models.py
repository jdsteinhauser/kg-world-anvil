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


def parse_text_format(value: object | None) -> TextFormat | None:
    """Parse a format hint; return None for auto-detect / unset Select values."""
    if value is None:
        return None
    fmt_value = str(value).strip()
    if not fmt_value or fmt_value.casefold() in {"auto", "select.null"}:
        return None
    return TextFormat(fmt_value)


def coerce_text_format(value: object | None, *, default: TextFormat = TextFormat.PLAIN) -> TextFormat:
    """Parse stored format values, falling back when invalid or unset."""
    parsed = parse_text_format(value)
    return parsed if parsed is not None else default


class EntityAttribute(BaseModel):
    key: str = Field(description="Attribute name")
    value: str = Field(description="Attribute value from the source text")


class CanonicalPredicate(str, Enum):
    """Controlled vocabulary for relationship types stored in the graph."""

    LOCATED_IN = "located_in"
    PART_OF = "part_of"
    CONTAINS = "contains"
    MEMBER_OF = "member_of"
    LEADS = "leads"
    REPORTS_TO = "reports_to"
    ALLIED_WITH = "allied_with"
    OPPOSED_TO = "opposed_to"
    KNOWS = "knows"
    PARENT_OF = "parent_of"
    SPOUSE_OF = "spouse_of"
    SIBLING_OF = "sibling_of"
    CREATED_BY = "created_by"
    FOUNDED_BY = "founded_by"
    OWNED_BY = "owned_by"
    PARTICIPATED_IN = "participated_in"
    OCCURRED_AT = "occurred_at"
    MENTIONS = "mentions"
    DEPICTS = "depicts"
    INSPIRED_BY = "inspired_by"
    ASSOCIATED_WITH = "associated_with"


def predicate_values() -> list[str]:
    return [p.value for p in CanonicalPredicate]


def format_predicate_prompt() -> str:
    lines = ["Use ONLY these relationship predicates:"]
    for predicate in CanonicalPredicate:
        lines.append(f"- {predicate.value}")
    lines.append(
        "Put extra nuance in detail (e.g. predicate=member_of, detail='serves as mayor'). "
        "Use associated_with only when no other predicate fits."
    )
    return "\n".join(lines)


class ExtractedEntity(BaseModel):
    name: str = Field(description="Entity display name as found in source text")
    type: str = Field(description="Entity type, e.g. person, location, organization, concept")
    attributes: list[EntityAttribute] = Field(
        description="Optional key-value attributes extracted from the text; use empty list if none",
    )


class ExtractedRelationship(BaseModel):
    subject: str = Field(description="Subject entity name")
    predicate: CanonicalPredicate = Field(description="Canonical relationship type from the allowed list")
    object: str = Field(description="Object entity name")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0", ge=0.0, le=1.0)
    detail: str = Field(
        default="",
        description="Optional nuance from the source text; empty string if none",
    )


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
    broader_types: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    source_chunks: list[str] = Field(default_factory=list)
    is_new: bool = False


class DuplicateGroup(BaseModel):
    canonical_key: str
    members: list[ResolvedEntity] = Field(default_factory=list)
    suggested_survivor_type: str = ""


class MergePlan(BaseModel):
    canonical_key: str
    survivor_id: str
    survivor_type: str
    survivor_name: str
    loser_ids: list[str] = Field(default_factory=list)
    merged_aliases: list[str] = Field(default_factory=list)
    broader_types: list[str] = Field(default_factory=list)
    merged_attributes: dict[str, Any] = Field(default_factory=dict)
    edges_to_rewire: int = 0


class StagingBatchStatus(str, Enum):
    DRAFT = "draft"
    COMMITTED = "committed"
    DISCARDED = "discarded"


class StagingBatch(BaseModel):
    id: str | None = None
    document_id: str
    status: StagingBatchStatus = StagingBatchStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StagingEntity(ResolvedEntity):
    batch_id: str = ""


class StagingEdge(BaseModel):
    id: str | None = None
    predicate: str
    detail: str = ""
    confidence: float = 1.0
    from_entity_id: str
    to_entity_id: str
    source_chunks: list[str] = Field(default_factory=list)


class CollapsedStagingEntity(BaseModel):
    canonical_key: str
    survivor_type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    broader_types: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_chunks: list[str] = Field(default_factory=list)
    member_ids: list[str] = Field(default_factory=list)


class PromoteResult(BaseModel):
    entities_created: int = 0
    entities_updated: int = 0
    edges_created: int = 0
    edges_skipped: int = 0
    staging_groups_collapsed: int = 0


class DocumentRecord(BaseModel):
    id: str | None = None
    raw: str
    format: TextFormat
    content_hash: str
    ingested_at: datetime | None = None


class ChunkRecord(BaseModel):
    id: str | None = None
    document_id: str
    seq: int
    text: str
    start_char: int = 0
    end_char: int = 0
    embedding: list[float] | None = None


class ChunkSearchHit(BaseModel):
    id: str
    document_id: str
    seq: int
    text: str
    distance: float = 0.0


class RAGCitation(BaseModel):
    document_id: str
    seq: int
    snippet: str


class RAGAnswer(BaseModel):
    question: str
    answer: str
    citations: list[RAGCitation] = Field(default_factory=list)


class ChunkExtraction(BaseModel):
    """Extraction result for one extraction chunk with document char span."""

    start_char: int
    end_char: int
    text: str
    result: ExtractionResult


class GraphEdge(BaseModel):
    id: str | None = None
    predicate: str
    detail: str = ""
    confidence: float = 1.0
    source_document_id: str | None = None
    source_chunks: list[str] = Field(default_factory=list)
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
