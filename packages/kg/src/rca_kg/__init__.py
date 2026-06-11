"""rca_kg — Knowledge Graph (Sprint 2a).

ISO 14224 ontology + plant hierarchy skeleton + KG MCP tools. Owns the shared
slug utility so MAR and KG mint canonical-id segments identically. Kept lean
(no eager submodule re-exports) so `rca_kg.slugs` imports don't drag in neo4j.
"""
__version__ = "0.0.1"
