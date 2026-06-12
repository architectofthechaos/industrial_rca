"""Agent/probe configuration (Sprint 3 WI2/WI3) — task queue + thresholds (G6/G12)."""
from __future__ import annotations

import os

TASK_QUEUE = "rca-probes"                       # G12 — distinct from onboarding's rca-onboarding
DEFAULT_TENANT_ID = "0190d3c9-0000-7000-8000-0000000000ff"
DEFAULT_PLANT_ID = "refinery-gc"                # single refplant (G11 plant_id default)

DEFAULT_GATHER_AUTO_ACCEPT_THRESHOLD = 0.85     # G6 — distinct from MAR's 0.92 asset-identity gate
MAX_REPLAN_CYCLES = 2                            # §3.4 — 3rd rejection => planning_aborted
MAX_FIVE_WHYS_DEPTH = 7                          # §5.2 node 5
MAX_CONCLUSION_REGENERATIONS = 1                # §5.2 node 11


def task_queue() -> str:
    return os.environ.get("PROBE_TASK_QUEUE", TASK_QUEUE)


def gather_auto_accept_threshold() -> float:
    return float(os.environ.get("GATHER_AUTO_ACCEPT_THRESHOLD",
                                DEFAULT_GATHER_AUTO_ACCEPT_THRESHOLD))


def temporal_host() -> str:
    return os.environ.get("TEMPORAL_HOST", "localhost:7233")


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def mcp_host_url() -> str:
    """Entity MCP host the live worker reaches over HTTP (D8/G10). Default targets the local
    ``task probe:host`` (FastMCP serves Streamable HTTP at ``/mcp``). Pointing at a different
    host — or a real source's host — is this env var only, no code change."""
    return os.environ.get("MCP_HOST_URL", "http://127.0.0.1:8100/mcp")


__all__ = [
    "TASK_QUEUE", "DEFAULT_TENANT_ID", "DEFAULT_PLANT_ID",
    "DEFAULT_GATHER_AUTO_ACCEPT_THRESHOLD", "MAX_REPLAN_CYCLES", "MAX_FIVE_WHYS_DEPTH",
    "MAX_CONCLUSION_REGENERATIONS",
    "task_queue", "gather_auto_accept_threshold", "temporal_host", "temporal_namespace",
    "mcp_host_url",
]
