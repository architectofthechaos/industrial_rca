"""KG configuration: Neo4j driver factories from KG_* env vars."""
from __future__ import annotations

import os

from neo4j import AsyncDriver, AsyncGraphDatabase, Driver, GraphDatabase

DEFAULT_URI = "bolt://127.0.0.1:7687"
DEFAULT_USERNAME = "neo4j"
DEFAULT_PASSWORD = "rca-dev-password"
DEFAULT_DATABASE = "neo4j"


def kg_uri() -> str:
    return os.environ.get("KG_URI", DEFAULT_URI)


def kg_username() -> str:
    return os.environ.get("KG_USERNAME", DEFAULT_USERNAME)


def kg_password() -> str:
    return os.environ.get("KG_PASSWORD", DEFAULT_PASSWORD)


def kg_database() -> str:
    return os.environ.get("KG_DATABASE", DEFAULT_DATABASE)


def make_driver() -> Driver:
    return GraphDatabase.driver(kg_uri(), auth=(kg_username(), kg_password()))


def make_async_driver() -> AsyncDriver:
    return AsyncGraphDatabase.driver(kg_uri(), auth=(kg_username(), kg_password()))
