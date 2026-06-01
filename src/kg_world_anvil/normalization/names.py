"""Stable lookup keys for entity resolution and deduplication."""

from __future__ import annotations

import re
import unicodedata

_INDEFINITE_ARTICLE = re.compile(r"^(a|an)\s+", re.IGNORECASE)
_LEADING_THE = re.compile(r"^the\s+(.+)$", re.IGNORECASE)


def _strip_optional_leading_the(name: str) -> str:
    """Drop leading 'the' on multi-word proper names (e.g. The Hollow Spine -> Hollow Spine).

    Single-word names keep the article (The Hague, The Beatles).
    Lowercase common nouns after 'the' are unchanged (the mayor).
    """
    match = _LEADING_THE.match(name)
    if not match:
        return name
    rest = match.group(1).strip()
    if len(rest.split()) >= 2:
        return rest
    return name


def normalize_display_name(name: str) -> str:
    """Normalize entity display names for storage and lookup."""
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = _INDEFINITE_ARTICLE.sub("", normalized).strip()
    return _strip_optional_leading_the(normalized)


def canonical_key(name: str) -> str:
    """Deterministic lookup key: NFKC, collapsed whitespace, casefold, no leading a/an."""
    normalized = normalize_display_name(name)
    return normalized.casefold()


def entity_identity_key(name: str, entity_type: str) -> tuple[str, str]:
    """Stable identity tuple used across ingest, review, and commit."""
    return canonical_key(name), entity_type.strip().casefold()


def normalize_entity_type(entity_type: str) -> str:
    """Normalize entity type for storage and lookup."""
    return entity_type.strip().casefold()
