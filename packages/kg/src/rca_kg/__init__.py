"""rca_kg — Knowledge Graph (Sprint 2a).

ISO 14224 ontology + plant hierarchy skeleton + KG MCP tools. Owns the shared
slug utility so MAR and KG mint canonical-id segments identically.
"""
from .config import (
    kg_database,
    kg_password,
    kg_uri,
    kg_username,
    make_async_driver,
    make_driver,
)
from .slugs import slug

__version__ = "0.0.1"

__all__ = [
    "kg_database",
    "kg_password",
    "kg_uri",
    "kg_username",
    "make_async_driver",
    "make_driver",
    "slug",
]
