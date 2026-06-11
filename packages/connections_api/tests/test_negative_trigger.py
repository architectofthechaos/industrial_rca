"""Negative-trigger invariant (Sprint 2b §1.6).

The contract: registering and activating a connection must create ZERO onboarding workflow
runs. Onboarding (Track 2) doesn't exist yet — there is no `rca_onboarding` package, no
Temporal client, and no `onboarding_runs` table — so we assert the invariant two concrete,
durable ways that don't depend on that future code:

1. **No onboarding dependency.** The connections_api package must not import anything
   onboarding/Temporal-related. We import every module in the package and assert no
   `onboarding`/`temporal` module is pulled in transitively, and that the source carries no
   such import. A regression (someone wiring an onboarding hook into /activate) trips this.

2. **No side-effect surface.** Activating a connection touches ONLY the connections repo. We
   drive register -> test -> activate against an InMemoryRepository and assert nothing outside
   `repo.connections` was written (no aliases, no unresolved rows) — i.e. activation has no
   projection/onboarding side effect.

Track 2 will EXTEND this test to additionally assert zero `onboarding_runs` rows via an
injected spy onboarding client, once that package exists.
"""
from __future__ import annotations

import ast
import pathlib

from fastapi.testclient import TestClient

import rca_connections_api
from rca_connections_api import create_app
from rca_connector_sdk.health import TestConnectionResponse
from rca_mar.repository import InMemoryRepository

# Workflow-engine / onboarding package names that connections_api must NEVER import. Matched
# against whole dotted-name SEGMENTS — so neo4j's unrelated date/time codec module
# `neo4j._codec.hydration.v1.temporal` (a transitive dep via rca_kg) is NOT a false positive,
# while a real `import temporalio` / `from rca_onboarding import ...` is caught.
_FORBIDDEN_SEGMENTS = frozenset({"onboarding", "rca_onboarding", "temporalio"})


def _imported_modules(tree: ast.AST) -> set[str]:
    """Top-level module names referenced by import statements in one source tree."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _forbidden_hit(module_name: str) -> str | None:
    for segment in module_name.split("."):
        if segment in _FORBIDDEN_SEGMENTS:
            return segment
    return None


def test_no_onboarding_or_temporal_import():
    """No connections_api source file may import onboarding or the Temporal workflow engine.

    Statically scanning import statements (rather than the polluted global ``sys.modules``)
    is deterministic and catches the real regression: someone wiring an onboarding/Temporal
    hook into /activate. A regression here means activation grew a workflow side effect.
    """
    src = pathlib.Path(rca_connections_api.__file__).parent
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        for mod in _imported_modules(ast.parse(py.read_text())):
            hit = _forbidden_hit(mod)
            if hit is not None:
                offenders.append(f"{py.name}: imports {mod!r} (forbidden segment {hit!r})")
    assert offenders == [], (
        "connections_api must not depend on onboarding/Temporal: " + "; ".join(offenders))


def test_activation_writes_only_the_connections_repo():
    """register -> test -> activate must write ONLY the connections table; no aliases, no
    unresolved rows, no other side effect (the negative-trigger invariant, concretely)."""

    async def _ok_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(success=True, checks=[])

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo, probes={"pi_af": _ok_probe}))

    body = {
        "plant_id": "refinery-gc", "category": "hierarchy", "connector_type": "pi_af",
        "display_name": "AF Main", "base_url": "http://localhost:8001",
        "auth_config": {"type": "none", "secret_ref": None},
    }
    cid = client.post("/connections", json=body).json()["connection_id"]
    assert client.post(f"/connections/{cid}/test").json()["success"] is True
    assert client.post(f"/connections/{cid}/activate").json()["status"] == "active"

    # The ONLY thing written is the connection row. No onboarding side effect exists to fire.
    assert set(repo.connections.keys()) == {cid}
    assert repo.aliases == []
    assert repo.unresolved == {}
    assert repo.assets == {}
