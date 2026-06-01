"""Entity display name cleanup and canonical key generation."""

from __future__ import annotations

import re
import unicodedata

# Leading articles and other low-information prefixes.
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)

# Wrapping quotes and similar punctuation artifacts.
_WRAP_QUOTES_RE = re.compile(r'^["\'`“”‘’]+|["\'`“”‘’]+$')

# Trailing possessive or clitic suffixes on role-style names.
_TRAILING_POSSESSIVE_RE = re.compile(r"(?:['’]s|['’])$", re.IGNORECASE)

# Markdown / emphasis artifacts occasionally copied from source text.
_MARKUP_CHARS_RE = re.compile(r"[*_]+")


def normalize_entity_name(name: str) -> str:
    """Return a cleaned display name with articles and common artifacts removed."""
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = _MARKUP_CHARS_RE.sub("", normalized)
    normalized = _WRAP_QUOTES_RE.sub("", normalized.strip())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _LEADING_ARTICLE_RE.sub("", normalized)
    normalized = _TRAILING_POSSESSIVE_RE.sub("", normalized).strip()
    normalized = normalized.strip(".,;:!?")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def canonical_key(name: str) -> str:
    """Deterministic lookup key for entity resolution and deduplication."""
    return normalize_entity_name(name).casefold()


def entity_identity_key(name: str, entity_type: str) -> tuple[str, str]:
    """Stable identity tuple used across ingest, review, and commit."""
    return canonical_key(name), entity_type.strip().casefold()


def names_equivalent(a: str, b: str) -> bool:
    return canonical_key(a) == canonical_key(b)
