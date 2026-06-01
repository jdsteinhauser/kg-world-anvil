"""Relationship predicate filtering."""

from __future__ import annotations

import re

# Predicates that assert absence, negation, or lack of connection — not stored in the graph.
_NEGATIVE_PREFIXES = ("not_", "never_", "without_", "lacks_", "lack_of_", "non_")

_NEGATIVE_STEMS = ("unrelated", "unlinked", "unassociated", "disconnected", "unconnected")

_NEGATIVE_PREDICATES = frozenset(
    {
        "unrelated_to",
        "unlinked_to",
        "unassociated_with",
        "not_associated_with",
        "not_linked_to",
        "not_related_to",
        "not_connected_to",
        "disconnected_from",
        "unconnected_to",
    }
)


def normalize_predicate(predicate: str) -> str:
    return predicate.strip().lower().replace(" ", "_").replace("-", "_")


def is_absence_relationship(predicate: str) -> bool:
    """Return True if the predicate represents missing or negated linkage."""
    name = normalize_predicate(predicate)
    if not name:
        return True
    if name in _NEGATIVE_PREDICATES:
        return True
    if name.startswith(_NEGATIVE_PREFIXES):
        return True
    return any(name.startswith(stem) for stem in _NEGATIVE_STEMS)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_NEGATION_IN_TEXT = re.compile(
    r"\b(?:"
    r"not\s+(?:associated|related|linked|connected)(?:\s+(?:with|to))?"
    r"|no\s+(?:known\s+)?(?:association|connection|link|relationship|tie)s?\s+(?:with|between|to)"
    r"|(?:unassociated|unrelated|unlinked|unconnected)\s+(?:with|to)"
    r"|(?:without|lacks?)\s+(?:any\s+)?(?:association|connection|link|relationship)\s*(?:with|to|between)?"
    r"|had\s+nothing\s+to\s+do\s+with"
    r"|no\s+connection\s+between"
    r")\b",
    re.IGNORECASE,
)


def _name_search_forms(name: str) -> list[str]:
    """Lowercase substrings used to locate an entity name in source text."""
    normalized = name.strip().lower()
    forms = [normalized]
    if normalized.startswith("the "):
        forms.append(normalized[4:])
    tokens = [token for token in re.split(r"\W+", normalized) if len(token) >= 3]
    if len(tokens) >= 2:
        forms.append(" ".join(tokens))
    return forms


def _entity_mentioned(text: str, name: str) -> bool:
    lowered = text.lower()
    return any(form in lowered for form in _name_search_forms(name) if len(form) >= 3)


def _entities_comentioned(text: str, subject: str, obj: str) -> bool:
    return _entity_mentioned(text, subject) and _entity_mentioned(text, obj)


def is_relationship_negated_in_text(subject: str, obj: str, text: str) -> bool:
    """Return True when source text negates a link between subject and object."""
    if not text.strip():
        return False
    for block in (*_SENTENCE_SPLIT.split(text), *text.split("\n\n")):
        block = block.strip()
        if not block or not _entities_comentioned(block, subject, obj):
            continue
        if _NEGATION_IN_TEXT.search(block):
            return True
    return False
