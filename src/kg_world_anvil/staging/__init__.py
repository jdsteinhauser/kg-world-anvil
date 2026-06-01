"""Staging graph promotion pipeline."""

from kg_world_anvil.staging.collapse import collapse_staging_entities
from kg_world_anvil.staging.promoter import StagingPromoter

__all__ = ["StagingPromoter", "collapse_staging_entities"]
