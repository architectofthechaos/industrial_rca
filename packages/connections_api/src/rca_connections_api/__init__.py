"""rca_connections_api — the category-first Connections REST API (Sprint 2b §1).

A FastAPI app over the MAR ``connections`` table: register a connector (category-first),
test it against its real ``test_connection`` MCP tool, and walk it through the lifecycle
state machine (pending -> active, with one active source per (plant, category)).
"""
from .app import create_app
from .registry import CONNECTOR_PROBES, probe_for
from .state_machine import (
    InvalidTransition,
    assert_patch_transition,
    assert_transition,
)

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "create_app",
    "CONNECTOR_PROBES", "probe_for",
    "InvalidTransition", "assert_transition", "assert_patch_transition",
]
