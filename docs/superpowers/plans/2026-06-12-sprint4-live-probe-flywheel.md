# Sprint 4 — Live Probe & The Flywheel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the P-101A probe run for real against the live simulated stack over MCP, twice, persisting everything to Postgres + the KG, with the second probe reading the first's failure event through the agent (the flywheel).

**Architecture:** A composition-root host (`rca_agents/host.py`) mounts the existing MAR + KG(+`Neo4jAssetGraph`) + 4 connector `FastMCP` factories into one in-process `FastMCP`; a `ConnectionRouter` (built from `connections_api` active connections, falling back to a static dev router) points the connectors at the simulators. `McpToolBox` drives that host through a transport-agnostic `fastmcp.Client` (in-process now, HTTP later = one-line swap) and adapts each tool's `ToolResponse` to the `ToolBox` Protocol shape. The worker entrypoint assembles `ProbeActivityDeps` from the real `LLMClient`, `McpToolBox`, `Neo4jAssetGraph`, a new `McpWorkOrderCreator`, and (WI5) Postgres repos. Equipment-class binding is a KG-owned dotted→`equipment-class:*` map consumed by MAR at registration; the KG upsert hard-fails on an unresolved class.

**Tech Stack:** Python 3.12, `uv` monorepo, FastMCP / `fastmcp.Client`, Temporal (`temporalio`), SQLAlchemy 2.0 async + asyncpg (Postgres), Neo4j (`neo4j` async driver), Pydantic v2, `pytest`/`pytest-asyncio`, `ruff` + `mypy`, `task` (Taskfile).

**Decisions carried in (see `sprint4_spec.md` § Gap Resolutions G1–G14):**
- **G10 (owner override of D5/§8):** in-process `fastmcp.Client` over a mounted host this sprint; `McpToolBox` is built against a `Client` so HTTP is a later construction-only swap.
- **G11:** `McpWorkOrderCreator` is built new (it did not exist).
- **G12:** Temporal already in infra; D3 = swap Postgres image to pgvector + verify Temporal auto-setup.
- **Invariant scope:** the "no source imports" rule (§8) applies to *agent-logic + toolbox* modules (`gather_graph.py`, `planning_graph.py`, `rca_graph.py`, `base.py`, `toolbox.py`, `mcp_toolbox.py`). The composition root (`host.py`, `worker.py __main__`) is exempt — it is allowed to import the servers it wires.

---

## File Structure

**New files:**
- `packages/kg/src/rca_kg/class_map.py` — KG-owned dotted→`equipment-class:*` export + `UnknownEquipmentClass`. Parses the seed cypher (no live Neo4j dependency).
- `packages/kg/migrations/0005_class_dotted_alias.cypher` — sets `n.dotted` on existing `EquipmentClass` nodes (idempotent, for already-migrated graphs).
- `packages/agents/src/rca_agents/mcp_toolbox.py` — `McpToolBox(ToolBox)` over a `fastmcp.Client`. Imports ONLY `fastmcp` + `rca_contracts`.
- `packages/agents/src/rca_agents/host.py` — composition root: `build_entity_host(...)`, `router_from_connections(...)`. Imports the servers.
- `packages/agents/src/rca_agents/repos_pg.py` — Postgres impls of the 4 probe repo Protocols (WI5).
- `packages/llm/src/rca_llm/audit_pg.py` — `PostgresLlmAuditSink` (WI5).
- `packages/agents/src/rca_agents/deps.py` — `build_probe_deps(...)` assembling `ProbeActivityDeps` (WI3); used by `worker.__main__`.
- `packages/mar/migrations/versions/0006_asset_class_kg.py` — adds `assets.iso14224_class_kg` column (WI1, flagged new migration per §2).
- `scripts/seed_refplant_connections.py` — registers the 4 refplant connections as `active` in `connections_api` (WI3/D6).
- `RUN.md` — the live-probe + flywheel runbook (WI4/WI6).
- `tests/` additions under `packages/agents/tests/`, `packages/kg/tests/`, `packages/mar/tests/`, `packages/llm/tests/`.

**Modified files:**
- `infra/docker-compose.yaml` — Postgres image → `pgvector/pgvector:pg16` (WI1).
- `packages/kg/seed/iso14224_bb1.cypher` — add `n.dotted` to `EquipmentClass` nodes (WI1).
- `packages/kg/src/rca_kg/assets.py` — hard-fail on unresolved `EquipmentClass` in both `Neo4jAssetGraph.upsert_asset` and `InMemoryAssetGraph.upsert_asset` (WI1).
- `packages/agents/src/rca_agents/gather_graph.py:133` — drop the `or "equipment-class:bb1"` fallback (WI1).
- `packages/mar/src/rca_mar/models.py`, `repository_pg.py`, `repository.py`, `seed.py`, `asset.py` (contract) — surface + populate `iso14224_class_kg` (WI1).
- `packages/agents/src/rca_agents/worker.py` — add `__main__` + dep construction (WI3).
- `packages/agents/src/rca_agents/wo.py` — add `McpWorkOrderCreator` (WI3/G11).
- `packages/llm/src/rca_llm/client.py` — none required; audit sink is injected (WI5).
- `Taskfile.yaml` — `stack:up`, `probe:host` targets (WI1/WI4).

---

## TIER A — Live single probe

### Task 1.1: Switch Postgres to pgvector image; verify Temporal auto-setup (D3, G12)

**Files:**
- Modify: `infra/docker-compose.yaml:4`

- [ ] **Step 1: Edit the image**

In `infra/docker-compose.yaml`, change the postgres service image:

```yaml
  postgres:
    image: pgvector/pgvector:pg16
```

(Leave `POSTGRES_USER/PASSWORD/DB`, ports, volume, healthcheck unchanged — `pgvector/pgvector:pg16` is a standard Postgres-16 base, so the `rca_mar` DB and Temporal auto-setup behavior are preserved.)

- [ ] **Step 2: Bring up infra and verify Temporal initializes on the new image**

Run:
```bash
task infra:up
docker compose -f infra/docker-compose.yaml ps
docker compose -f infra/docker-compose.yaml exec -T postgres \
  psql -U rca -d temporal -c "select 1" >/dev/null && echo "TEMPORAL_DB_OK"
docker compose -f infra/docker-compose.yaml exec -T temporal \
  tctl --address temporal:7233 cluster health 2>&1 | tail -1
```
Expected: all services `healthy`; `TEMPORAL_DB_OK` printed (auto-setup created the `temporal` DB on the pgvector image); `tctl cluster health` reports `SERVING`.

- [ ] **Step 3: Commit**

```bash
git add infra/docker-compose.yaml
git commit -m "feat(sprint4 WI1): switch shared Postgres to pgvector/pgvector:pg16 (D3)"
```

---

### Task 1.2: KG-owned dotted→`equipment-class:*` export (D1, G4)

**Files:**
- Modify: `packages/kg/seed/iso14224_bb1.cypher` (add `n.dotted`)
- Create: `packages/kg/migrations/0005_class_dotted_alias.cypher`
- Create: `packages/kg/src/rca_kg/class_map.py`
- Test: `packages/kg/tests/test_class_map.py`

- [ ] **Step 1: Write the failing test**

`packages/kg/tests/test_class_map.py`:
```python
import pytest
from rca_kg.class_map import UnknownEquipmentClass, iso_to_kg_map, resolve_equipment_class


def test_map_has_centrifugal_pump():
    m = iso_to_kg_map()
    assert m["pump.centrifugal"] == "equipment-class:bb1"
    assert m["pump"] == "equipment-class:pump"


def test_resolve_known():
    assert resolve_equipment_class("pump.centrifugal") == "equipment-class:bb1"


def test_resolve_unknown_raises():
    with pytest.raises(UnknownEquipmentClass):
        resolve_equipment_class("compressor.reciprocating")


def test_every_value_is_a_seeded_node_id():
    # all mapped ids must be 'equipment-class:*' (consistency with the seed)
    assert all(v.startswith("equipment-class:") for v in iso_to_kg_map().values())
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/kg && uv run pytest tests/test_class_map.py -q`
Expected: FAIL — `ModuleNotFoundError: rca_kg.class_map`.

- [ ] **Step 3: Add `n.dotted` to the seed nodes**

In `packages/kg/seed/iso14224_bb1.cypher`, extend the two coded `EquipmentClass` MERGEs so each carries a canonical dotted alias (leave `rotating-equipment` without one — it has no `code` and no dotted form):
```cypher
MERGE (n:EquipmentClass {id: "equipment-class:pump"}) SET n.code = "PU", n.name = "Pump", n.dotted = "pump", ...;
MERGE (n:EquipmentClass {id: "equipment-class:bb1"}) SET n.code = "BB1", n.name = "Centrifugal pump", n.dotted = "pump.centrifugal", ...;
```
(Preserve all existing `SET` properties; only add `n.dotted = "..."`.)

- [ ] **Step 4: Create the migration for already-seeded graphs**

`packages/kg/migrations/0005_class_dotted_alias.cypher`:
```cypher
// 0005 — backfill the dotted ISO alias on EquipmentClass nodes (D1).
MATCH (n:EquipmentClass {id: "equipment-class:pump"}) SET n.dotted = "pump";
MATCH (n:EquipmentClass {id: "equipment-class:bb1"})  SET n.dotted = "pump.centrifugal";
```

- [ ] **Step 5: Implement the export**

`packages/kg/src/rca_kg/class_map.py`:
```python
"""KG-owned ISO-14224 dotted-class -> KG node-id export (D1).

Ontology truth lives in the KG seed. MAR consumes this map at asset registration so the
agent only ever hands the KG a native ``equipment-class:*`` id. The map is parsed from the
seed cypher (no live Neo4j dependency, so MAR registration stays decoupled from the graph).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_SEED = Path(__file__).resolve().parent.parent.parent / "seed" / "iso14224_bb1.cypher"
# one EquipmentClass MERGE statement; capture id + (optional) dotted alias
_ID = re.compile(r'MERGE\s*\(n:EquipmentClass\s*\{id:\s*"(?P<id>[^"]+)"\}\)(?P<body>[^;]*);',
                 re.IGNORECASE | re.DOTALL)
_DOTTED = re.compile(r'n\.dotted\s*=\s*"(?P<dotted>[^"]+)"', re.IGNORECASE)


class UnknownEquipmentClass(ValueError):
    """A dotted ISO class with no matching EquipmentClass node in the KG seed."""


@lru_cache(maxsize=1)
def iso_to_kg_map() -> dict[str, str]:
    text = _SEED.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in _ID.finditer(text):
        dotted = _DOTTED.search(m.group("body"))
        if dotted:
            out[dotted.group("dotted")] = m.group("id")
    if not out:
        raise RuntimeError(f"no dotted EquipmentClass aliases found in {_SEED}")
    return out


def resolve_equipment_class(dotted: str) -> str:
    """Map a dotted ISO class (``pump.centrifugal``) to its KG id (``equipment-class:bb1``)."""
    try:
        return iso_to_kg_map()[dotted]
    except KeyError as exc:
        raise UnknownEquipmentClass(
            f"no KG EquipmentClass for ISO class {dotted!r}; "
            f"known: {sorted(iso_to_kg_map())}") from exc


__all__ = ["iso_to_kg_map", "resolve_equipment_class", "UnknownEquipmentClass"]
```

- [ ] **Step 6: Run the test to confirm it passes**

Run: `cd packages/kg && uv run pytest tests/test_class_map.py -q`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add packages/kg/seed/iso14224_bb1.cypher packages/kg/migrations/0005_class_dotted_alias.cypher \
        packages/kg/src/rca_kg/class_map.py packages/kg/tests/test_class_map.py
git commit -m "feat(sprint4 WI1): KG-owned dotted->equipment-class export + dotted seed alias (D1)"
```

---

### Task 1.3: KG asset-upsert hard-fails on unresolved EquipmentClass (D1, G4)

**Files:**
- Modify: `packages/kg/src/rca_kg/assets.py` (`InMemoryAssetGraph.upsert_asset` ~`:151`, `Neo4jAssetGraph.upsert_asset` ~`:292-318`)
- Test: `packages/kg/tests/test_asset_layer.py` (extend)

- [ ] **Step 1: Write the failing test (in-memory path is hermetic)**

Add to `packages/kg/tests/test_asset_layer.py`:
```python
import pytest
from rca_kg.assets import InMemoryAssetGraph
from rca_kg.class_map import UnknownEquipmentClass  # reuse the same exception type


@pytest.mark.asyncio
async def test_upsert_unknown_class_hard_fails():
    g = InMemoryAssetGraph()  # empty graph: no EquipmentClass nodes
    with pytest.raises(UnknownEquipmentClass):
        await g.upsert_asset(
            canonical_id="asset:p:u:x", name="X", iso14224_class="equipment-class:nope",
            iso14224_class_confidence=0.9, iso14224_class_method="register",
            probed_at=__import__("datetime").datetime(2026, 3, 30, tzinfo=__import__("datetime").timezone.utc))
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/kg && uv run pytest tests/test_asset_layer.py::test_upsert_unknown_class_hard_fails -q`
Expected: FAIL — currently the upsert silently skips and returns, no exception raised.

- [ ] **Step 3: Make `InMemoryAssetGraph.upsert_asset` hard-fail**

In `assets.py`, replace the silent in-memory skip (`:151-152`):
```python
        if self._node("EquipmentClass", iso14224_class) is not None:
            self._add_edge(canonical_id, "INSTANCE_OF", iso14224_class)
```
with:
```python
        if self._node("EquipmentClass", iso14224_class) is None:
            raise UnknownEquipmentClass(
                f"EquipmentClass {iso14224_class!r} not in KG; cannot link INSTANCE_OF "
                f"for {canonical_id!r}")
        self._add_edge(canonical_id, "INSTANCE_OF", iso14224_class)
```
Add at the top of `assets.py`: `from .class_map import UnknownEquipmentClass`.

- [ ] **Step 4: Make `Neo4jAssetGraph.upsert_asset` hard-fail**

The current Cypher (`:310-312`) `OPTIONAL MATCH`es the class and `FOREACH`-skips on null. Replace the class-link portion: first require the node exists, then `MERGE` the edge. In `Neo4jAssetGraph.upsert_asset`, before issuing the upsert write, add a guard read:
```python
        exists = await self._read(
            "MATCH (ec:EquipmentClass {id: $cls}) RETURN ec.id AS id", cls=iso14224_class)
        if not exists:
            raise UnknownEquipmentClass(
                f"EquipmentClass {iso14224_class!r} not in KG; refusing to upsert "
                f"{canonical_id!r} (would orphan the asset)")
```
and change the write Cypher's class link from the `OPTIONAL MATCH ... FOREACH (... CASE WHEN ec IS NULL ...)` form to an unconditional:
```cypher
MATCH (ec:EquipmentClass {id: $cls})
MERGE (a)-[:INSTANCE_OF]->(ec)
```
(Leave the `LOCATED_IN` `OPTIONAL MATCH`/`FOREACH` block as-is — location is genuinely optional; only the class is mandatory per D1.)

- [ ] **Step 5: Keep the existing hermetic probe test green**

The probe workflow test uses `seeded_asset_graph()` pre-loaded with the `equipment-class:bb1` node, so its upsert finds the node and does not raise. Run the full KG suite + the agents probe-workflow test:

Run:
```bash
cd packages/kg && uv run pytest -q
cd ../agents && uv run pytest tests/test_probe_workflow.py -q
```
Expected: PASS. If any pre-existing KG test upserted with a deliberately-absent class expecting a silent skip, update it to seed the class node first (search: `grep -rn "upsert_asset" packages/kg/tests`).

- [ ] **Step 6: Commit**

```bash
git add packages/kg/src/rca_kg/assets.py packages/kg/tests/test_asset_layer.py
git commit -m "feat(sprint4 WI1): KG asset-upsert hard-fails on unresolved EquipmentClass (D1)"
```

---

### Task 1.4: MAR persists the KG-native class at registration (D1, G4)

**Files:**
- Create: `packages/mar/migrations/versions/0006_asset_class_kg.py`
- Modify: `packages/mar/src/rca_mar/models.py` (`Asset`), `repository_pg.py` (`_to_descriptor`), `repository.py` (`InMemoryRepository`), `seed.py`, and the `AssetDescriptor` contract (locate via `grep -rn "class AssetDescriptor" packages/`)
- Test: `packages/mar/tests/test_class_binding.py`

- [ ] **Step 1: Write the failing test**

`packages/mar/tests/test_class_binding.py`:
```python
import pytest
from rca_mar.class_binding import kg_class_for  # thin MAR adapter over rca_kg.class_map


def test_dotted_maps_to_kg_id():
    assert kg_class_for("pump.centrifugal") == "equipment-class:bb1"


def test_unknown_dotted_returns_none():
    # MAR must not crash registration on an unmapped class; it stores NULL and is logged.
    assert kg_class_for("turbine.gas") is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/mar && uv run pytest tests/test_class_binding.py -q`
Expected: FAIL — `ModuleNotFoundError: rca_mar.class_binding`.

- [ ] **Step 3: Add the MAR adapter (registration must not crash on an unknown class)**

`packages/mar/src/rca_mar/class_binding.py`:
```python
"""MAR-side consumption of the KG-owned ISO->KG class map (D1).

MAR resolves the dotted class to a KG-native id at registration and persists it. An unmapped
class stores NULL (logged) rather than crashing onboarding; the hard-fail is the KG upsert's
job at probe time, not MAR's at registration.
"""
from __future__ import annotations

from rca_kg.class_map import UnknownEquipmentClass, resolve_equipment_class


def kg_class_for(dotted: str) -> str | None:
    try:
        return resolve_equipment_class(dotted)
    except UnknownEquipmentClass:
        return None


__all__ = ["kg_class_for"]
```
(Confirm `rca_kg` is a dependency of the `mar` package; if not, add it to `packages/mar/pyproject.toml` and re-`uv sync`.)

- [ ] **Step 4: Run the adapter test**

Run: `cd packages/mar && uv run pytest tests/test_class_binding.py -q`
Expected: PASS.

- [ ] **Step 5: Add the column (migration 0006) — FLAGGED new migration per §2**

`packages/mar/migrations/versions/0006_asset_class_kg.py`:
```python
"""add assets.iso14224_class_kg (D1 — KG-native equipment-class id)

Revision ID: 0006_asset_class_kg
Revises: 0005_probe_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_asset_class_kg"
down_revision = "0005_probe_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("iso14224_class_kg", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "iso14224_class_kg")
```

- [ ] **Step 6: Surface the column on the model + descriptor + populate it at registration**

- In `models.py` `Asset`: add `iso14224_class_kg: Mapped[str | None] = mapped_column(String, nullable=True)`.
- In the `AssetDescriptor` contract: add `iso14224_class_kg: str | None = None`.
- In `repository_pg.py` `_to_descriptor`: include `iso14224_class_kg=row.iso14224_class_kg`.
- In `seed.py` / the registration path: when building/registering an asset, set `iso14224_class_kg = kg_class_for(asset.iso14224_class)` (import `from .class_binding import kg_class_for`). Apply the same in `InMemoryRepository.upsert_asset` if it constructs descriptors.

- [ ] **Step 7: Write a registration test asserting the KG id is persisted**

Add to `packages/mar/tests/test_class_binding.py`:
```python
@pytest.mark.asyncio
async def test_inmemory_register_persists_kg_class():
    from rca_mar.repository import InMemoryRepository
    from rca_mar.seed import seed_from_register
    from pathlib import Path
    repo = InMemoryRepository()
    reg = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
    await seed_from_register(repo, reg)
    # P-101A is pump.centrifugal -> equipment-class:bb1
    hits = await repo.search_assets(iso14224_class="pump.centrifugal")
    assert hits and all(h.iso14224_class_kg == "equipment-class:bb1" for h in hits)
```

- [ ] **Step 8: Run MAR suite (in-memory hermetic) + apply migration against live DB**

Run:
```bash
cd packages/mar && uv run pytest tests/test_class_binding.py -q && uv run pytest -q
# live DB (infra up from Task 1.1):
task mar:migrate    # applies 0006
```
Expected: tests PASS; `alembic upgrade head` reaches `0006_asset_class_kg`.

- [ ] **Step 9: Commit**

```bash
git add packages/mar/migrations/versions/0006_asset_class_kg.py packages/mar/src/rca_mar/ \
        packages/mar/tests/test_class_binding.py packages/contracts/src/rca_contracts/
git commit -m "feat(sprint4 WI1): MAR resolves+persists KG-native class at registration (D1)"
```

---

### Task 1.5: Remove the gather-agent hardcoded class fallback (G5)

**Files:**
- Modify: `packages/agents/src/rca_agents/gather_graph.py:133`

- [ ] **Step 1: Edit**

Change:
```python
        equipment_class = context.get("iso14224_class") or "equipment-class:bb1"
```
to:
```python
        equipment_class = context.get("iso14224_class")
```
Rationale: the class must come from the MAR→KG-resolved context, not a hardcoded mask. `FakeToolBox.get_asset_context` still returns `equipment-class:bb1` (`toolbox.py:144`), so hermetic tests stay green; live runs now surface an unresolved class to the WI1 hard-fail instead of silently using `bb1`.

- [ ] **Step 2: Run the agents suite**

Run: `cd packages/agents && uv run pytest -q`
Expected: PASS (478 hermetic tests unaffected — FakeToolBox supplies the class).

- [ ] **Step 3: Commit**

```bash
git add packages/agents/src/rca_agents/gather_graph.py
git commit -m "feat(sprint4 WI1): drop hardcoded equipment-class fallback in gather (G5)"
```

---

### Task 1.6: `stack:up` umbrella Taskfile target (WI1 acceptance)

**Files:**
- Modify: `Taskfile.yaml`

- [ ] **Step 1: Add the targets**

Add to `Taskfile.yaml`:
```yaml
  stack:up:
    desc: Bring up the FULL live stack — infra (pgvector+Neo4j+Temporal) + migrations + KG seed + simulators + refplant connections. Then run `task probe:worker`.
    cmds:
      - task: infra:up
      - task: mar:migrate
      - task: kg:migrate
      - task: kg:seed
      - cd rca_simulator && task up
      - uv run python scripts/seed_refplant_connections.py     # WI3/D6 (idempotent)
      - echo "stack up. Now run: task probe:worker"

  probe:host:
    desc: (optional) Serve the entity MCP host over HTTP for a true out-of-process run (Sprint 5 path)
    cmds:
      - uv run python -m rca_agents.host
```
(`seed_refplant_connections.py` is created in Task 3.5; if running `stack:up` before WI3, comment that line.)

- [ ] **Step 2: Verify the stack comes up healthy + connectors test_connection pass**

Run (after WI3's seed exists):
```bash
task stack:up
uv run python scripts/check_connectors.py    # created in Task 3.5; calls each connector's test_connection
```
Expected: infra healthy; simulators up on :8001–:8004; every connector `test_connection` → `success=True`.

- [ ] **Step 3: Commit**

```bash
git add Taskfile.yaml
git commit -m "feat(sprint4 WI1): stack:up umbrella target (full live stack)"
```

---

### Task 2.1: `McpToolBox` pure adaptation helpers (WI2, G7)

These are the source-shape→ToolBox-shape transforms, tested without any MCP host.

**Files:**
- Create: `packages/agents/src/rca_agents/mcp_toolbox.py` (helpers first)
- Test: `packages/agents/tests/test_mcp_toolbox_helpers.py`

- [ ] **Step 1: Write the failing test**

`packages/agents/tests/test_mcp_toolbox_helpers.py`:
```python
from datetime import datetime, timezone
from rca_agents.mcp_toolbox import (
    summarize_series, alarm_to_log, descriptor_to_summary, severity_for,
)

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


def test_summarize_series_computes_stats_and_trend():
    series = {"tag": {"tag_name": "P-101A.vibration_radial"},
              "values": [{"value": 2.1}, {"value": 4.0}, {"value": 6.6}]}
    out = summarize_series(series, role="vibration_radial", lookback_hours=720)
    assert out["tag_name"] == "P-101A.vibration_radial"
    assert out["role"] == "vibration_radial"
    assert out["mean"] == pytest_approx(4.2333, 4)
    assert out["max"] == 6.6
    assert out["severity"] in {"normal", "elevated", "critical"}
    assert "6.6" in out["summary"]


def test_severity_rule():
    assert severity_for(mean=2.0, mx=6.6) == "critical"     # max > 2*mean
    assert severity_for(mean=4.0, mx=6.0) == "elevated"     # 1.5*mean < max <= 2*mean
    assert severity_for(mean=10.0, mx=11.0) == "normal"


def test_alarm_to_log_renames():
    a = {"message": "slight whine", "timestamp": "2026-03-06T00:00:00+00:00", "tag_name": "P-101A"}
    log = alarm_to_log(a, index=0, canonical_id="asset:r:u:p-101a")
    assert log["text"] == "slight whine"
    assert log["at"] == "2026-03-06T00:00:00+00:00"
    assert log["author"] is None
    assert log["log_id"]


def test_descriptor_to_summary_synthesizes_name_and_confidence():
    d = {"canonical_id": "asset:r:u:p-101a", "tag": "P-101A", "service": "charge pump"}
    s = descriptor_to_summary(d, keywords="P-101A seal leak")
    assert s["canonical_id"] == "asset:r:u:p-101a"
    assert s["name"] == "P-101A"
    assert 0.0 < s["confidence"] <= 1.0


def pytest_approx(v, n):
    import pytest
    return pytest.approx(v, abs=10 ** -n)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/agents && uv run pytest tests/test_mcp_toolbox_helpers.py -q`
Expected: FAIL — `ImportError` (helpers not defined).

- [ ] **Step 3: Implement the helpers**

Create `packages/agents/src/rca_agents/mcp_toolbox.py` with the module imports + helpers (class added in Task 2.2):
```python
"""Live ToolBox adapter (WI2, G7/G10).

``McpToolBox`` implements the ``ToolBox`` Protocol by driving the mounted entity MCP host
through a transport-agnostic ``fastmcp.Client`` and adapting each tool's ``ToolResponse`` to
the shape the agents read (see ``FakeToolBox`` for the reference shape). This module imports
ONLY ``fastmcp`` + ``rca_contracts`` — never a connector/MAR/KG/simulator module (§8 invariant).
Source routing is endpoint/config-driven inside the host the client points at; the in-process
vs HTTP choice is purely how the ``Client`` is constructed at startup.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean as _mean
from typing import Any
from uuid import uuid4

from rca_contracts import ProvenanceEntry, ToolResponse


def severity_for(*, mean: float, mx: float) -> str:
    """Coarse stand-in severity from per-tag stats (real anomaly detection is the LLM's job
    downstream; the toolbox only supplies stats + a hint)."""
    if mean and mx > 2.0 * mean:
        return "critical"
    if mean and mx > 1.5 * mean:
        return "elevated"
    return "normal"


def summarize_series(series: dict, *, role: str | None, lookback_hours: int) -> dict:
    values = [float(v["value"]) for v in series.get("values", []) if v.get("value") is not None]
    tag_name = (series.get("tag") or {}).get("tag_name") or series.get("tag_name")
    if not values:
        return {"tag_name": tag_name, "role": role, "summary": "no samples in window",
                "mean": None, "max": None, "severity": "normal"}
    mn, mx, first, last = _mean(values), max(values), values[0], values[-1]
    return {
        "tag_name": tag_name, "role": role,
        "summary": f"{role or tag_name}: {first:.1f} -> {last:.1f} "
                   f"(min {min(values):.1f}, max {mx:.1f}) over {lookback_hours}h",
        "mean": round(mn, 4), "max": round(mx, 4), "severity": severity_for(mean=mn, mx=mx),
    }


def alarm_to_log(a: dict, *, index: int, canonical_id: str) -> dict:
    return {"log_id": f"log:{canonical_id}:{a.get('timestamp', index)}",
            "text": a.get("message", ""), "author": None, "at": a.get("timestamp")}


def descriptor_to_summary(d: dict, *, keywords: str) -> dict:
    cid = d["canonical_id"]
    name = d.get("tag") or cid.split(":")[-1].upper()
    kw = (keywords or "").lower()
    exact = name.lower() in kw or cid.split(":")[-1] in kw
    return {"canonical_id": cid, "name": name, "confidence": 0.95 if exact else 0.6}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd packages/agents && uv run pytest tests/test_mcp_toolbox_helpers.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/agents/src/rca_agents/mcp_toolbox.py packages/agents/tests/test_mcp_toolbox_helpers.py
git commit -m "feat(sprint4 WI2): McpToolBox adaptation helpers (stats/renames/summary)"
```

---

### Task 2.2: `McpToolBox` class against a stub MCP host (WI2, G7)

**Files:**
- Modify: `packages/agents/src/rca_agents/mcp_toolbox.py` (add the class)
- Test: `packages/agents/tests/test_mcp_toolbox.py` (+ a stub-host fixture)

- [ ] **Step 1: Write the failing test (stub host returns canned ToolResponses)**

`packages/agents/tests/test_mcp_toolbox.py`:
```python
import json
from datetime import datetime, timezone
import pytest
from fastmcp import Client, FastMCP
from rca_agents.mcp_toolbox import McpToolBox
from rca_agents.toolbox import ToolBox

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
CID = "asset:refinery-gc:unit-101:p-101a"


def _ok(data, connection_id=None):
    prov = {"tool_name": "x", "tool_version": "v1", "source": "sim",
            "connection_id": connection_id, "source_query": "q",
            "queried_at": REF.isoformat(), "response_id": "0190d3c9-0000-7000-8000-000000000abc",
            "record_count": len(data) if isinstance(data, list) else 1,
            "truncated": False, "raw_tags": [], "notes": None}
    return {"data": data, "provenance": prov, "error": None}


@pytest.fixture
def stub_host() -> FastMCP:
    host = FastMCP("stub-entity-host")

    @host.tool(name="tag.list_for_asset")
    async def list_tags(request: dict):
        return _ok([{"tag_name": "P-101A.vibration_radial", "role": "vibration_radial"}],
                   connection_id="refinery-gc.historian.pi-main")

    @host.tool(name="tag.get_history")
    async def hist(request: dict):
        return _ok({"tag": {"tag_name": request["tag_name"]},
                    "values": [{"value": 2.1}, {"value": 6.6}]},
                   connection_id="refinery-gc.historian.pi-main")

    @host.tool(name="work_order.list_for_asset")
    async def wos(request: dict):
        return _ok([{"work_order_id": "WO-50012402", "description": "seal leak",
                     "status": "WAPPR", "priority": "1", "failure_code": "LEK",
                     "opened_at": "2026-03-28T00:00:00+00:00"}],
                   connection_id="refinery-gc.cmms.maximo-main")

    @host.tool(name="document.search_for_asset")
    async def docs(request: dict):
        return _ok([{"document_id": "RCA-2025-014", "title": "prior seal RCA",
                     "doc_type": "rca_report", "excerpt": "dry-running seal face"}],
                   connection_id="refinery-gc.document.sp-main")

    @host.tool(name="operator_log.list_for_asset")
    async def logs(request: dict):
        return _ok([{"message": "slight whine", "timestamp": "2026-03-06T00:00:00+00:00",
                     "tag_name": "P-101A"}],
                   connection_id="refinery-gc.operator_log.pi-main")

    @host.tool(name="asset.get")
    async def aget(request: dict):
        return _ok({"canonical_id": CID, "tag": "P-101A", "service": "charge pump",
                    "iso14224_class": "pump.centrifugal", "iso14224_class_kg": "equipment-class:bb1"})

    @host.tool(name="asset.search")
    async def asearch(request: dict):
        return _ok([{"canonical_id": CID, "tag": "P-101A"}])

    @host.tool(name="kg.get_asset_context")
    async def kgctx(request: dict):
        return _ok({"kg_warm": False, "asset": {"id": CID, "name": "P-101A"},
                    "iso14224_class": request.get("iso14224_class"),
                    "applicable_failure_modes": [{"code": "ELP", "id": "failure-mode:elp",
                                                  "name": "External leakage"}],
                    "prior_events_on_asset": [], "prior_events_for_class_at_plant": []})

    @host.tool(name="kg.upsert_asset")
    async def upsert(request: dict):
        return _ok({"canonical_id": request["canonical_id"], "created": True})

    @host.tool(name="kg.link_failure_mode")
    async def link(request: dict):
        return _ok({"canonical_id": request["canonical_id"],
                    "failure_mode_code": request["failure_mode_code"], "linked": True})

    return host


@pytest.fixture
async def tb(stub_host):
    async with Client(stub_host) as client:
        yield McpToolBox(client)


def test_satisfies_protocol(tb):
    assert isinstance(tb, ToolBox)  # structural Protocol check


@pytest.mark.asyncio
async def test_tag_history_fans_out_and_summarizes(tb):
    tags, prov = await tb.tag_history(CID, reference_time=REF, lookback_hours=720)
    assert tags[0]["tag_name"] == "P-101A.vibration_radial"
    assert tags[0]["role"] == "vibration_radial"
    assert tags[0]["max"] == 6.6 and tags[0]["severity"] == "critical"
    assert prov.connection_id == "refinery-gc.historian.pi-main"  # non-null (G5)
    assert prov.section == "tag" and prov.record_count == 1


@pytest.mark.asyncio
async def test_operator_logs_renamed(tb):
    logs, prov = await tb.operator_logs_for_asset(CID, reference_time=REF, lookback_hours=720)
    assert logs[0]["text"] == "slight whine" and logs[0]["at"] == "2026-03-06T00:00:00+00:00"
    assert prov.connection_id == "refinery-gc.operator_log.pi-main"


@pytest.mark.asyncio
async def test_get_asset_context_bridges_mar_class(tb):
    # McpToolBox.get_asset_context reads MAR's KG class and feeds kg.get_asset_context
    ctx = await tb.get_asset_context(CID)
    assert ctx["iso14224_class"] == "equipment-class:bb1"
    assert ctx["applicable_failure_modes"][0]["code"] == "ELP"


@pytest.mark.asyncio
async def test_upsert_and_link_return_bools(tb):
    assert await tb.upsert_asset(canonical_id=CID, name="P-101A",
                                 iso14224_class="equipment-class:bb1", confidence=0.95,
                                 method="register", reference_time=REF) is True
    assert await tb.link_failure_mode(canonical_id=CID, failure_mode_code="ELP") is True


@pytest.mark.asyncio
async def test_work_orders_and_documents_passthrough(tb):
    wos, p1 = await tb.work_orders_for_asset(CID)
    assert wos[0]["work_order_id"] == "WO-50012402" and p1.connection_id
    docs, p2 = await tb.documents_for_asset(CID, "seal leak")
    assert docs[0]["document_id"] == "RCA-2025-014" and p2.connection_id
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/agents && uv run pytest tests/test_mcp_toolbox.py -q`
Expected: FAIL — `McpToolBox` class not defined / no `__init__`.

- [ ] **Step 3: Implement the `McpToolBox` class**

Append to `packages/agents/src/rca_agents/mcp_toolbox.py`:
```python
class McpToolBox:
    """Production ToolBox over a mounted entity MCP host (in-process or HTTP fastmcp.Client)."""

    def __init__(self, client: Any, *, plant_id: str | None = None) -> None:
        self._c = client            # an *open* fastmcp.Client
        self._plant_id = plant_id

    async def _call(self, tool: str, request: dict) -> ToolResponse[Any]:
        res = await self._c.call_tool(tool, {"request": request})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp: ToolResponse[Any] = ToolResponse[Any].model_validate(payload)
        return resp

    @staticmethod
    def _conn_id(resp: ToolResponse[Any]) -> str | None:
        return resp.provenance.connection_id if resp.provenance else None

    # --- cold context (MAR + KG) ---
    async def search_assets(self, keywords: str, plant_id: str | None) -> list[dict]:
        resp = await self._call("asset.search", {"tag_pattern": _pattern(keywords),
                                                  "canonical_id_pattern": _pattern(keywords)})
        rows = resp.data or []
        return [descriptor_to_summary(d, keywords=keywords) for d in rows]

    async def asset_summary(self, canonical_id: str) -> dict | None:
        resp = await self._call("asset.get", {"canonical_id": canonical_id})
        if resp.error is not None:
            return None                         # not_found -> None (contract)
        return dict(resp.data) if resp.data else None

    async def get_asset_context(self, canonical_id: str,
                                iso14224_class: str | None = None) -> dict:
        # D1 bridge: if no class hint, read MAR's resolved KG class and feed it to the KG.
        if iso14224_class is None:
            a = await self.asset_summary(canonical_id) or {}
            iso14224_class = a.get("iso14224_class_kg") or a.get("iso14224_class")
        req = {"canonical_id": canonical_id}
        if iso14224_class is not None:
            req["iso14224_class"] = iso14224_class
        resp = await self._call("kg.get_asset_context", req)
        ctx = dict(resp.data or {})
        # ensure the class the agent reads is the KG-native one resolved from MAR
        if iso14224_class is not None and not ctx.get("iso14224_class"):
            ctx["iso14224_class"] = iso14224_class
        return ctx

    # --- warm evidence (connectors) ---
    async def tag_history(self, canonical_id: str, *, reference_time: datetime,
                          lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        listed = await self._call("tag.list_for_asset", {"canonical_id": canonical_id})
        start = reference_time - timedelta(hours=lookback_hours)
        out: list[dict] = []
        conn = self._conn_id(listed)
        for t in (listed.data or []):
            hist = await self._call("tag.get_history", {
                "canonical_id": canonical_id, "tag_name": t["tag_name"],
                "start": start.isoformat(), "end": reference_time.isoformat(), "mode": "stored"})
            conn = self._conn_id(hist) or conn
            out.append(summarize_series(hist.data or {}, role=t.get("role"),
                                        lookback_hours=lookback_hours))
        prov = ProvenanceEntry(section="tag", item_id=canonical_id, tool_name="tag.get_history",
                               connection_id=conn, queried_at=reference_time,
                               response_id=uuid4(), record_count=len(out))
        return out, prov

    async def work_orders_for_asset(self, canonical_id: str
                                    ) -> tuple[list[dict], ProvenanceEntry]:
        resp = await self._call("work_order.list_for_asset", {"canonical_id": canonical_id})
        rows = [dict(w) for w in (resp.data or [])]
        prov = ProvenanceEntry(section="work_order", item_id=canonical_id,
                               tool_name="work_order.list_for_asset",
                               connection_id=self._conn_id(resp), queried_at=_qa(resp, canonical_id),
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    async def documents_for_asset(self, canonical_id: str, query: str
                                  ) -> tuple[list[dict], ProvenanceEntry]:
        resp = await self._call("document.search_for_asset",
                                {"canonical_id": canonical_id, "query": query})
        rows = [dict(d) for d in (resp.data or [])]
        prov = ProvenanceEntry(section="document", item_id=canonical_id,
                               tool_name="document.search_for_asset",
                               connection_id=self._conn_id(resp), queried_at=_qa(resp, canonical_id),
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    async def operator_logs_for_asset(self, canonical_id: str, *, reference_time: datetime,
                                      lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        start = reference_time - timedelta(hours=lookback_hours)
        resp = await self._call("operator_log.list_for_asset", {
            "canonical_id": canonical_id, "start": start.isoformat(),
            "end": reference_time.isoformat()})
        rows = [alarm_to_log(a, index=i, canonical_id=canonical_id)
                for i, a in enumerate(resp.data or [])]
        prov = ProvenanceEntry(section="operator_log", item_id=canonical_id,
                               tool_name="operator_log.list_for_asset",
                               connection_id=self._conn_id(resp), queried_at=reference_time,
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    # --- writes (KG) ---
    async def upsert_asset(self, *, canonical_id: str, name: str, iso14224_class: str,
                           confidence: float, method: str, reference_time: datetime) -> bool:
        resp = await self._call("kg.upsert_asset", {
            "canonical_id": canonical_id, "name": name, "iso14224_class": iso14224_class,
            "iso14224_class_confidence": confidence, "iso14224_class_method": method,
            "reference_time": reference_time.isoformat()})
        if resp.error is not None:
            raise RuntimeError(f"kg.upsert_asset failed: {resp.error}")   # hard-fail (D1)
        return bool((resp.data or {}).get("created", False))

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> bool:
        resp = await self._call("kg.link_failure_mode", {
            "canonical_id": canonical_id, "failure_mode_code": failure_mode_code})
        return resp.error is None


def _pattern(keywords: str) -> str | None:
    tok = next((w for w in (keywords or "").split() if "-" in w or w.isupper()), None)
    return f"%{tok}%" if tok else None


def _qa(resp: ToolResponse[Any], canonical_id: str) -> datetime:
    # use the connector's provenance timestamp; fall back to a parse-safe constant only if absent
    if resp.provenance and resp.provenance.queried_at:
        return resp.provenance.queried_at
    raise RuntimeError("connector response missing provenance.queried_at")


__all__ = ["McpToolBox", "summarize_series", "alarm_to_log", "descriptor_to_summary",
           "severity_for"]
```
Note on `_qa`: WO/document tools don't take `reference_time`, so their `queried_at` comes from the connector's own provenance (which the simulator stamps deterministically under a frozen sim clock) — this avoids the `FakeToolBox._now()` wall-clock pattern (G8). Tag/operator-log use the passed `reference_time` directly.

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd packages/agents && uv run pytest tests/test_mcp_toolbox.py -q`
Expected: PASS (all tests, including the `isinstance(tb, ToolBox)` structural check).

- [ ] **Step 5: Architectural-invariant test (§8 / WI2 acceptance)**

`packages/agents/tests/test_no_source_imports.py`:
```python
import ast
from pathlib import Path
import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "rca_agents"
GUARDED = ["gather_graph.py", "planning_graph.py", "rca_graph.py", "base.py",
           "toolbox.py", "mcp_toolbox.py"]
FORBIDDEN = ("rca_connector_", "rca_mar", "rca_kg", "rca_simulator")


@pytest.mark.parametrize("fname", GUARDED)
def test_agent_and_toolbox_modules_import_no_source(fname):
    tree = ast.parse((SRC / fname).read_text())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    bad = [m for m in mods if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert not bad, f"{fname} imports source modules directly: {bad}"
```

Run: `cd packages/agents && uv run pytest tests/test_no_source_imports.py -q`
Expected: PASS — `mcp_toolbox.py` imports only `fastmcp` + `rca_contracts`. (`host.py`/`worker.py` are NOT in `GUARDED` — they are the composition root.)

- [ ] **Step 6: Commit**

```bash
git add packages/agents/src/rca_agents/mcp_toolbox.py packages/agents/tests/test_mcp_toolbox.py \
        packages/agents/tests/test_no_source_imports.py
git commit -m "feat(sprint4 WI2): McpToolBox over fastmcp.Client + §8 invariant test"
```

---

### Task 3.1: Entity host composition root (`host.py`) (WI3, G9, G10)

**Files:**
- Create: `packages/agents/src/rca_agents/host.py`
- Test: `packages/agents/tests/test_host_build.py` (stack-gated; uses live Neo4j + sims when available)

- [ ] **Step 1: Implement the host builder (mirrors `scripts/run_mcp_host.build_host`, with KG given a real `Neo4jAssetGraph` + Postgres MAR + registry router)**

`packages/agents/src/rca_agents/host.py`:
```python
"""Composition root: mount MAR + KG(+asset_graph) + connector MCP servers into one FastMCP.

This is the ONLY agents-package module allowed to import connector/MAR/KG servers (it is the
entrypoint, not agent logic — see §8 scope note). The worker builds the host, wraps it in a
fastmcp.Client, and hands the client to McpToolBox. Swapping in-process for HTTP is a Client
construction change here, nothing in the toolbox or agents changes.
"""
from __future__ import annotations

import os
from uuid import UUID

from fastmcp import FastMCP
from rca_connector_sdk import (CanonicalSlugAssetGateway, ConnectionInfo,
                               StaticConnectionRouter)
from rca_connector_documents.server import make_document_mcp
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp
from rca_kg.assets import Neo4jAssetGraph
from rca_kg.queries import Neo4jGateway
from rca_kg.server import make_kg_mcp
from rca_mar.config import make_engine, make_session_factory
from rca_mar.repository_pg import PostgresRepository
from rca_mar.server import make_mar_mcp

PLANT_ID = os.environ.get("PLANT_ID", "refinery-gc")
TENANT_ID = UUID(os.environ.get("TENANT_ID", "0190d3c9-0000-7000-8000-0000000000ff"))
HISTORIAN_SIM_URL = os.environ.get("HISTORIAN_SIM_URL", "http://127.0.0.1:8001")
CMMS_SIM_URL = os.environ.get("CMMS_SIM_URL", "http://127.0.0.1:8002")
DOCUMENT_SIM_URL = os.environ.get("DOCUMENT_SIM_URL", "http://127.0.0.1:8004")


def _static_dev_router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(connection_id=f"{PLANT_ID}.historian.pi-main", plant_id=PLANT_ID,
                       category="historian", connector_type="pi_historian",
                       base_url=HISTORIAN_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.operator_log.pi-event-frames", plant_id=PLANT_ID,
                       category="operator_log", connector_type="pi_event_frames",
                       base_url=HISTORIAN_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.cmms.maximo-main", plant_id=PLANT_ID,
                       category="cmms", connector_type="maximo", base_url=CMMS_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.document.sharepoint-main", plant_id=PLANT_ID,
                       category="document", connector_type="sharepoint", base_url=DOCUMENT_SIM_URL),
    ])


async def router_from_connections() -> StaticConnectionRouter:
    """D6: build the static router from connections_api active connections; fall back to the
    static dev router when the registry is empty (un-seeded dev box)."""
    try:
        repo = PostgresRepository(make_session_factory(make_engine()))
        rows = await repo.list_connections(status="active")
        infos = [ConnectionInfo(connection_id=r.connection_id, plant_id=r.plant_id,
                                category=r.category, connector_type=r.connector_type,
                                base_url=r.base_url, extra_config=r.extra_config or {})
                 for r in rows]
        if infos:
            return StaticConnectionRouter(infos)
    except Exception:  # noqa: BLE001 — registry not reachable on a fresh dev box
        pass
    return _static_dev_router()


async def build_entity_host(*, router: StaticConnectionRouter | None = None,
                            mar_repo=None, asset_graph: Neo4jAssetGraph | None = None) -> FastMCP:
    router = router or await router_from_connections()
    gateway = CanonicalSlugAssetGateway()
    if mar_repo is None:
        mar_repo = PostgresRepository(make_session_factory(make_engine()))
    asset_graph = asset_graph or Neo4jAssetGraph()
    host = FastMCP("entity-mcp-host")
    host.mount(make_mar_mcp(repo=mar_repo, tenant_id=TENANT_ID))
    host.mount(make_kg_mcp(gateway=Neo4jGateway(), asset_graph=asset_graph))   # asset tools ON
    host.mount(make_tag_mcp(router=router, assets=gateway, default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_operator_log_mcp(router=router, assets=gateway,
                                     default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_work_order_mcp(router=router, assets=gateway, default_base_url=CMMS_SIM_URL))
    host.mount(make_document_mcp(router=router, assets=gateway, default_base_url=DOCUMENT_SIM_URL))
    return host


def main() -> None:  # `python -m rca_agents.host` -> serve over HTTP (Sprint 5 path)
    import asyncio
    host = asyncio.run(build_entity_host())
    host.run(transport="http", host="127.0.0.1", port=int(os.environ.get("MCP_HOST_PORT", "8100")))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write a build/tool-surface test (hermetic with an in-memory MAR + InMemory asset graph)**

`packages/agents/tests/test_host_build.py`:
```python
import pytest
from fastmcp import Client
from rca_agents.host import build_entity_host, _static_dev_router
from rca_kg.assets import InMemoryAssetGraph
from rca_mar.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_host_mounts_all_entity_tools():
    host = await build_entity_host(router=_static_dev_router(),
                                   mar_repo=InMemoryRepository(),
                                   asset_graph=InMemoryAssetGraph())
    async with Client(host) as c:
        names = {t.name for t in await c.list_tools()}
    for required in ["asset.get", "asset.search", "kg.get_asset_context", "kg.upsert_asset",
                     "kg.link_failure_mode", "tag.get_history", "tag.list_for_asset",
                     "work_order.list_for_asset", "document.search_for_asset",
                     "operator_log.list_for_asset"]:
        assert required in names, f"{required} not mounted; have {sorted(names)}"
```
(Note: `build_entity_host` accepts injected `mar_repo`/`asset_graph` so this test is hermetic — no Neo4j/Postgres. `InMemoryAssetGraph` here is passed via the `asset_graph=` arg; `make_kg_mcp` accepts the Protocol.)

- [ ] **Step 3: Run it**

Run: `cd packages/agents && uv run pytest tests/test_host_build.py -q`
Expected: PASS — all 10 entity tools mounted with verbatim names (no-prefix mount).

- [ ] **Step 4: Add `host.py` to the §8 invariant exemption note + run the invariant test**

Confirm `host.py` is NOT in `GUARDED` (Task 2.2) — it is intentionally exempt. Run `uv run pytest tests/test_no_source_imports.py -q` → still PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agents/src/rca_agents/host.py packages/agents/tests/test_host_build.py
git commit -m "feat(sprint4 WI3): entity host composition root (KG+asset_graph, registry router) (G9/G10)"
```

---

### Task 3.2: `McpWorkOrderCreator` (WI3, G11)

**Files:**
- Modify: `packages/agents/src/rca_agents/wo.py`
- Test: `packages/agents/tests/test_wo_creator.py`

- [ ] **Step 1: Write the failing test (stub host with `work_order.create`)**

`packages/agents/tests/test_wo_creator.py`:
```python
from datetime import datetime, timezone
import pytest
from fastmcp import Client, FastMCP
from rca_agents.wo import McpWorkOrderCreator

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def host():
    h = FastMCP("wo-stub")

    @h.tool(name="work_order.create")
    async def create(request: dict):
        return {"data": {"work_order_id": "WO-RCA-0001", "status": "WAPPR",
                         "description": request["description"]},
                "provenance": {"tool_name": "work_order.create", "tool_version": "v1",
                               "source": "maximo", "connection_id": "refinery-gc.cmms.maximo-main",
                               "source_query": "create", "queried_at": REF.isoformat(),
                               "response_id": "0190d3c9-0000-7000-8000-0000000000ee",
                               "record_count": 1, "truncated": False, "raw_tags": [], "notes": None},
                "error": None}
    return h


@pytest.mark.asyncio
async def test_create_returns_work_order_dict(host):
    async with Client(host) as client:
        wo = McpWorkOrderCreator(client)
        out = await wo.create(canonical_id="asset:r:u:p-101a", description="replace seal",
                              priority="immediate", work_type="CM",
                              references={"probe_run_id": "p1", "conclusion_id": "c1"},
                              requested_by="agent", reported_at=REF)
    assert out["work_order_id"] == "WO-RCA-0001"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/agents && uv run pytest tests/test_wo_creator.py -q`
Expected: FAIL — `ImportError: cannot import name 'McpWorkOrderCreator'`.

- [ ] **Step 3: Implement it (satisfies the `WorkOrderCreator` Protocol at `activities.py:42`)**

Add to `packages/agents/src/rca_agents/wo.py`:
```python
from datetime import datetime
from typing import Any
from rca_contracts import ToolResponse


class McpWorkOrderCreator:
    """Calls the Maximo ``work_order.create`` MCP tool over a fastmcp.Client (G11).

    The connector mints a deterministic wonum from references.{probe_run_id, conclusion_id}, so
    Temporal activity retries are idempotent (maximo server.py:108,226).
    """

    def __init__(self, client: Any) -> None:
        self._c = client

    async def create(self, *, canonical_id: str, description: str, priority: str,
                     work_type: str, references: dict, requested_by: str,
                     reported_at: datetime) -> dict:
        res = await self._c.call_tool("work_order.create", {"request": {
            "canonical_id": canonical_id, "description": description, "priority": priority,
            "work_type": work_type, "references": references, "requested_by": requested_by,
            "reported_at": reported_at.isoformat()}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp: ToolResponse[Any] = ToolResponse[Any].model_validate(payload)
        if resp.error is not None:
            raise RuntimeError(f"work_order.create failed: {resp.error}")
        return dict(resp.data or {})
```
Add `"McpWorkOrderCreator"` to `wo.py`'s `__all__`.

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd packages/agents && uv run pytest tests/test_wo_creator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agents/src/rca_agents/wo.py packages/agents/tests/test_wo_creator.py
git commit -m "feat(sprint4 WI3): build McpWorkOrderCreator over work_order.create (G11)"
```

---

### Task 3.3: `build_probe_deps` + worker `__main__` (WI3, G2, G6)

**Files:**
- Create: `packages/agents/src/rca_agents/deps.py`
- Modify: `packages/agents/src/rca_agents/worker.py` (add `run()` + `__main__`)
- Test: `packages/agents/tests/test_deps_build.py`

- [ ] **Step 1: Write the failing test (deps assembled with in-memory repos + injected host/client)**

`packages/agents/tests/test_deps_build.py`:
```python
import pytest
from fastmcp import Client
from rca_agents.activities import ProbeActivityDeps
from rca_agents.deps import build_probe_deps
from rca_agents.host import build_entity_host, _static_dev_router
from rca_agents.mcp_toolbox import McpToolBox
from rca_kg.assets import InMemoryAssetGraph
from rca_mar.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_build_probe_deps_assembles_nine_fields():
    host = await build_entity_host(router=_static_dev_router(), mar_repo=InMemoryRepository(),
                                   asset_graph=InMemoryAssetGraph())
    async with Client(host) as client:
        deps = build_probe_deps(toolbox=McpToolBox(client), asset_graph=InMemoryAssetGraph(),
                                wo_client=client, use_postgres=False)
        assert isinstance(deps, ProbeActivityDeps)
        for f in ["llm", "toolbox", "asset_graph", "wo_creator", "runs", "memory",
                  "evidence", "conclusions", "agent_factories"]:
            assert getattr(deps, f) is not None
        assert set(deps.agent_factories) == {"planning", "gather", "rca"}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/agents && uv run pytest tests/test_deps_build.py -q`
Expected: FAIL — `ModuleNotFoundError: rca_agents.deps`.

- [ ] **Step 3: Implement `deps.py`**

`packages/agents/src/rca_agents/deps.py`:
```python
"""Assemble ProbeActivityDeps (WI3). Composition root — imports real impls. The `use_postgres`
flag selects in-memory (Tier A / tests) vs Postgres repos (WI5)."""
from __future__ import annotations

from typing import Any

from rca_llm import LLMClientImpl, default_registry
from rca_llm.transports import AnthropicTransport, VoyageEmbeddingTransport

from .activities import ProbeActivityDeps
from .repos import (InMemoryEvidencePackageRepo, InMemoryProbeMemoryRepo,
                    InMemoryProbeRunsRepo, InMemoryRcaConclusionRepo)
from .wo import McpWorkOrderCreator
from .worker import default_agent_factories


def build_llm(*, use_postgres: bool) -> Any:
    audit = None
    if use_postgres:
        from rca_llm.audit_pg import PostgresLlmAuditSink   # WI5
        audit = PostgresLlmAuditSink()
    return LLMClientImpl(registry=default_registry(), transport=AnthropicTransport(),
                         embedding_transport=VoyageEmbeddingTransport(), audit=audit)


def build_repos(*, use_postgres: bool):
    if use_postgres:
        from .repos_pg import (PgEvidencePackageRepo, PgProbeMemoryRepo, PgProbeRunsRepo,
                               PgRcaConclusionRepo)                # WI5
        return (PgProbeRunsRepo(), PgProbeMemoryRepo(), PgEvidencePackageRepo(),
                PgRcaConclusionRepo())
    return (InMemoryProbeRunsRepo(), InMemoryProbeMemoryRepo(),
            InMemoryEvidencePackageRepo(), InMemoryRcaConclusionRepo())


def build_probe_deps(*, toolbox: Any, asset_graph: Any, wo_client: Any,
                     use_postgres: bool = True) -> ProbeActivityDeps:
    runs, memory, evidence, conclusions = build_repos(use_postgres=use_postgres)
    return ProbeActivityDeps(
        llm=build_llm(use_postgres=use_postgres), toolbox=toolbox, asset_graph=asset_graph,
        wo_creator=McpWorkOrderCreator(wo_client), runs=runs, memory=memory,
        evidence=evidence, conclusions=conclusions,
        agent_factories=default_agent_factories())


__all__ = ["build_probe_deps", "build_llm", "build_repos"]
```

- [ ] **Step 4: Run the deps test**

Run: `cd packages/agents && uv run pytest tests/test_deps_build.py -q`
Expected: PASS.

- [ ] **Step 5: Add the worker `run()` + `__main__`**

Append to `packages/agents/src/rca_agents/worker.py`:
```python
async def run() -> None:
    """Live entrypoint: build the in-process entity host + client, assemble deps, serve."""
    import os
    from fastmcp import Client
    from temporalio.client import Client as TemporalClient
    from temporalio.contrib.pydantic import pydantic_data_converter

    from .config import temporal_host, temporal_namespace
    from .deps import build_probe_deps
    from .host import build_entity_host, router_from_connections
    from .mcp_toolbox import McpToolBox
    from rca_kg.assets import Neo4jAssetGraph

    use_pg = os.environ.get("PROBE_USE_POSTGRES", "1") == "1"
    asset_graph = Neo4jAssetGraph()
    host = await build_entity_host(router=await router_from_connections(),
                                   asset_graph=asset_graph)
    async with Client(host) as mcp_client:        # one open in-process client for the worker
        deps = build_probe_deps(toolbox=McpToolBox(mcp_client), asset_graph=asset_graph,
                                wo_client=mcp_client, use_postgres=use_pg)
        client = await TemporalClient.connect(temporal_host(), namespace=temporal_namespace(),
                                              data_converter=pydantic_data_converter)
        worker = await make_worker(client, deps)
        await worker.run()


def main() -> None:
    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()
```
Add `"run", "main"` to `worker.py`'s `__all__`.

- [ ] **Step 6: Smoke-check the entrypoint imports + boots to connect (stack must be up)**

Run:
```bash
cd packages/agents && uv run python -c "import rca_agents.worker as w; print(hasattr(w,'main'))"
# with `task stack:up` + `task probe:worker` in another shell, confirm it registers:
# logs show: Worker started on task_queue=rca-probes
```
Expected: `True`; with the stack up, `python -m rca_agents.worker` boots, connects to Temporal, and registers on `rca-probes` serving `ProbeWorkflow`.

- [ ] **Step 7: Commit**

```bash
git add packages/agents/src/rca_agents/deps.py packages/agents/src/rca_agents/worker.py \
        packages/agents/tests/test_deps_build.py
git commit -m "feat(sprint4 WI3): build_probe_deps + worker run()/__main__ (G2/G6)"
```

---

### Task 3.4: Live first-HITL integration test (WI3 acceptance)

**Files:**
- Test: `packages/agents/tests/test_live_probe_smoke.py` (marked `@pytest.mark.stack`, skipped unless `RCA_STACK=1`)

- [ ] **Step 1: Write the stack-gated test**

`packages/agents/tests/test_live_probe_smoke.py`:
```python
import os
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RCA_STACK") != "1",
                                reason="requires the live stack (task stack:up + probe:worker)")


@pytest.mark.asyncio
async def test_probe_reaches_first_hitl_with_real_data():
    """Submit a probe via the API client and assert it reaches the plan-approval HITL gate
    using REAL simulator-derived data (not FakeToolBox)."""
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.workflow import ProbeWorkflow
    from rca_agents.api import workflow_id_for
    import uuid

    client = await Client.connect("localhost:7233", namespace="default",
                                  data_converter=pydantic_data_converter)
    rid = str(uuid.uuid4())
    await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt="RCA on P-101A seal leak", plant_id="refinery-gc",
                           requested_by="pilot", probe_run_id=rid),
        id=workflow_id_for(rid), task_queue="rca-probes")
    handle = client.get_workflow_handle(workflow_id_for(rid))
    # poll the pending HITL turn (plan approval) — proves planning ran on live MAR/KG data
    import asyncio
    for _ in range(60):
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if turn:
            assert turn["questions"]
            return
        await asyncio.sleep(1)
    pytest.fail("probe did not reach a HITL gate within 60s")
```

- [ ] **Step 2: Run it against the live stack**

Run (3 shells): `task stack:up`; `task probe:worker`; then
```bash
cd packages/agents && RCA_STACK=1 uv run pytest tests/test_live_probe_smoke.py -q
```
Expected: PASS — the probe reaches a HITL gate driven by real P-101A data. (Skipped automatically when `RCA_STACK` is unset, so CI stays hermetic.)

- [ ] **Step 3: Register the `stack` marker + commit**

Add to `packages/agents/pyproject.toml` `[tool.pytest.ini_options] markers = ["stack: requires the live stack"]`. Commit:
```bash
git add packages/agents/tests/test_live_probe_smoke.py packages/agents/pyproject.toml
git commit -m "test(sprint4 WI3): live first-HITL smoke test (stack-gated)"
```

---

### Task 3.5: Seed refplant connections + connector health check (WI1/WI3, D6, G9)

**Files:**
- Create: `scripts/seed_refplant_connections.py`
- Create: `scripts/check_connectors.py`

- [ ] **Step 1: Implement the connection seed (idempotent)**

`scripts/seed_refplant_connections.py` registers the 4 refplant connections via the MAR repo and marks them `active` (matching `_static_dev_router` ids/categories/types/base_urls). Use `rca_mar.repository_pg.PostgresRepository.upsert_connection` (verify the method name with `grep -n "def upsert_connection\|def add_connection\|def create_connection" packages/mar/src/rca_mar/repository*.py`) with rows:
```python
ROWS = [
    ("refinery-gc.historian.pi-main", "historian", "pi_historian", "http://127.0.0.1:8001"),
    ("refinery-gc.operator_log.pi-event-frames", "operator_log", "pi_event_frames", "http://127.0.0.1:8001"),
    ("refinery-gc.cmms.maximo-main", "cmms", "maximo", "http://127.0.0.1:8002"),
    ("refinery-gc.document.sharepoint-main", "document", "sharepoint", "http://127.0.0.1:8004"),
]
```
Set `status="active"`, `plant_id="refinery-gc"`, `display_name` derived. Print one line per row.

- [ ] **Step 2: Implement the connector health check**

`scripts/check_connectors.py` builds each connector `FastMCP` with the dev router and calls its `test_connection` tool over an in-process `fastmcp.Client` (mirror `connections_api/registry.py:_mcp_probe`), asserting `success=True` for pi_historian/pi_event_frames/maximo/sharepoint against the live sims. Exit non-zero on any failure.

- [ ] **Step 3: Run both against the live stack**

Run:
```bash
task infra:up && cd rca_simulator && task up && cd ..
uv run python scripts/seed_refplant_connections.py
uv run python scripts/check_connectors.py
```
Expected: 4 connections seeded `active`; all `test_connection` probes succeed.

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_refplant_connections.py scripts/check_connectors.py
git commit -m "feat(sprint4 WI1/WI3): seed refplant connections (active) + connector health check (D6)"
```

---

### Task 4.1: Live single-probe walkthrough + budget-exhaustion (WI4, D2, D4)

**Files:**
- Create: `RUN.md`
- Test: `packages/agents/tests/test_live_probe_walkthrough.py` (stack-gated)

- [ ] **Step 1: Write the stack-gated end-to-end test (plan HITL → mid-5-Whys HITL → conclusion)**

`packages/agents/tests/test_live_probe_walkthrough.py` (skipif `RCA_STACK != 1`). Submit the P-101A probe, then drive HITL turns by polling `pending_hitl_turn` and signaling `hitl_response` with a scripted/seeded answer (mirror `test_probe_workflow._drive_until_complete`). Assert:
```python
# 1. at least TWO distinct HITL turns fire (plan approval + the mid-5-Whys human-knowledge Q, D2)
assert seen_turn_types >= {"plan_approval"}  # and a "five_whys" question type mid-analysis
# 2. final status is a terminal success and a conclusion exists with a ranked primary hypothesis
conclusion = await handle.result()
assert conclusion.status in {"completed", "concluded"}
```
For the mid-5-Whys assertion, detect a turn whose question `question_type`/context indicates a five-whys human-knowledge question (per `rca_graph._run_five_whys`) and answer it, then confirm the workflow resumes and finalizes.

- [ ] **Step 2: Write the budget-exhaustion test (D4)**

Same file, second test: submit with a tight budget (`input_tokens_limit=200, output_tokens_limit=50`) and assert the workflow finalizes with terminal status `budget_exceeded` and a partial result is retrievable (no "extend budget?" HITL turn fires). Verify the terminal status string against the `ProbeRunStatus` enum (`grep -rn "budget_exceeded" packages/`).

- [ ] **Step 3: Run against the live stack**

Run: `RCA_STACK=1 uv run pytest tests/test_live_probe_walkthrough.py -q` (stack + worker up).
Expected: PASS — one clean ranked `RcaConclusion` on real P-101A data; mid-analysis HITL fires & resumes; budget path yields `budget_exceeded` + partial.

- [ ] **Step 4: Write `RUN.md`**

`RUN.md` documents the exact reproduction: prereqs (Docker, `uv`, `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY`), `task stack:up`, `task probe:worker`, the `POST /probes/run` curl, polling `GET .../hitl/pending`, answering via `POST .../hitl/respond`, and reading `GET .../conclusion`. Include the budget-exhaustion variant and the flywheel second-probe steps (Task 6).

- [ ] **Step 5: Commit**

```bash
git add RUN.md packages/agents/tests/test_live_probe_walkthrough.py
git commit -m "feat(sprint4 WI4): live P-101A walkthrough + budget-exhaustion test + RUN.md (D2/D4)"
```

---

## TIER B — Hardening to the full flywheel

### Task 5.1: `PostgresLlmAuditSink` (WI5)

**Files:**
- Create: `packages/llm/src/rca_llm/audit_pg.py`
- Test: `packages/llm/tests/test_audit_pg.py` (DB-gated, `RCA_DB=1`)

- [ ] **Step 1: Write the failing DB-gated test**

`packages/llm/tests/test_audit_pg.py` (skipif `RCA_DB != 1`): construct `PostgresLlmAuditSink()`, build an `LlmCallRecord` (fields per `audit.py:16-32`), `await sink.record(rec)`, then query the `llm_calls` table (via MAR session factory) and assert the row exists with matching `correlation_id`, `prompt_name`, tokens, `cached`.

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd packages/llm && RCA_DB=1 uv run pytest tests/test_audit_pg.py -q`
Expected: FAIL — `ModuleNotFoundError: rca_llm.audit_pg`.

- [ ] **Step 3: Implement the sink (insert into the existing `LlmCall` ORM / `llm_calls` table)**

`packages/llm/src/rca_llm/audit_pg.py`:
```python
"""Postgres audit sink for LLM calls (WI5). Table + ORM (`rca_mar.models.LlmCall`) + migration
(0005) already exist — this only inserts. Insert is idempotent on llm_call_id (G: activity retry)."""
from __future__ import annotations

from typing import Any
from sqlalchemy.dialects.postgresql import insert as pg_insert
from rca_mar.config import make_engine, make_session_factory
from rca_mar.models import LlmCall
from .audit import AuditSink, LlmCallRecord


class PostgresLlmAuditSink(AuditSink):
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def record(self, call: LlmCallRecord) -> None:
        values = call.model_dump()
        async with self._sf() as s, s.begin():
            stmt = pg_insert(LlmCall).values(**values).on_conflict_do_nothing(
                index_elements=[LlmCall.llm_call_id])
            await s.execute(stmt)


__all__ = ["PostgresLlmAuditSink"]
```
(Confirm `LlmCallRecord` field names match `LlmCall` columns 1:1 — G3 says they do; if `model_dump()` includes an extra/renamed key, map it explicitly.)

- [ ] **Step 4: Run the DB test**

Run: `cd packages/llm && RCA_DB=1 uv run pytest tests/test_audit_pg.py -q` (infra up).
Expected: PASS — row written and retrievable; second `record()` of the same id is a no-op (idempotent).

- [ ] **Step 5: Commit**

```bash
git add packages/llm/src/rca_llm/audit_pg.py packages/llm/tests/test_audit_pg.py
git commit -m "feat(sprint4 WI5): PostgresLlmAuditSink writing the existing llm_calls table"
```

---

### Task 5.2: Postgres probe repos — runs + memory (WI5)

**Files:**
- Create: `packages/agents/src/rca_agents/repos_pg.py` (runs + memory first)
- Test: `packages/agents/tests/test_repos_pg.py` (DB-gated)

- [ ] **Step 1: Write failing DB-gated tests for `PgProbeRunsRepo` + `PgProbeMemoryRepo`**

`packages/agents/tests/test_repos_pg.py` (skipif `RCA_DB != 1`): create a run, `get_run` returns it; `update_status` mutates phase/status; `snapshot` then `get` returns merged memory; `append_turn`/`append_response` accumulate. Assert idempotency: calling `create_run` twice with the same id does not duplicate (matches Temporal retry semantics).

- [ ] **Step 2: Run to confirm failure**

Run: `cd packages/agents && RCA_DB=1 uv run pytest tests/test_repos_pg.py -q`
Expected: FAIL — `ModuleNotFoundError: rca_agents.repos_pg`.

- [ ] **Step 3: Implement `PgProbeRunsRepo` + `PgProbeMemoryRepo`**

`packages/agents/src/rca_agents/repos_pg.py` — use the MAR session-factory pattern (`make_engine`/`make_session_factory`), the `ProbeRun`/`ProbeMemory` ORM models, and `pg_insert(...).on_conflict_do_update/nothing` for idempotency. `ProbeRunsRepo`:
```python
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from rca_mar.config import make_engine, make_session_factory
from rca_mar.models import ProbeRun, ProbeMemory


class PgProbeRunsRepo:
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def create_run(self, *, probe_run_id: UUID, workflow_id: str, plant_id: str,
                         prompt: str, reference_time: datetime, requested_by: str,
                         started_at: datetime) -> None:
        async with self._sf() as s, s.begin():
            stmt = pg_insert(ProbeRun).values(
                probe_run_id=probe_run_id, workflow_id=workflow_id, plant_id=plant_id,
                prompt=prompt, reference_time=reference_time, requested_by=requested_by,
                status="running", started_at=started_at).on_conflict_do_nothing(
                index_elements=[ProbeRun.probe_run_id])
            await s.execute(stmt)

    async def update_status(self, probe_run_id: UUID, *, status: str, phase: str | None = None,
                            final_canonical_id: str | None = None, token_usage: dict | None = None,
                            errors: list | None = None, completed_at: datetime | None = None) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ProbeRun, probe_run_id)
            if row is None:
                return
            row.status = status
            if phase is not None: row.phase = phase
            if final_canonical_id is not None: row.final_canonical_id = final_canonical_id
            if token_usage is not None: row.token_usage = token_usage
            if errors is not None: row.errors = errors
            if completed_at is not None: row.completed_at = completed_at

    async def get_run(self, probe_run_id: UUID) -> dict | None:
        async with self._sf() as s:
            row = await s.get(ProbeRun, probe_run_id)
            if row is None:
                return None
            return {c.name: getattr(row, c.name) for c in ProbeRun.__table__.columns}
```
`PgProbeMemoryRepo.snapshot/get/append_turn/append_response` upsert the single `ProbeMemory` row per `probe_run_id`, merging JSONB fields (`conversation`, `current_plan`, `plan_history`, `working_knowledge`, `agent_scratchpad`, `token_usage`). `append_turn`/`append_response` read-modify-write the `conversation`/turn list within `s.begin()`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd packages/agents && RCA_DB=1 uv run pytest tests/test_repos_pg.py -q`
Expected: PASS (runs + memory).

- [ ] **Step 5: Commit**

```bash
git add packages/agents/src/rca_agents/repos_pg.py packages/agents/tests/test_repos_pg.py
git commit -m "feat(sprint4 WI5): Pg probe-runs + probe-memory repos (idempotent)"
```

---

### Task 5.3: Postgres probe repos — evidence + conclusion (WI5)

**Files:**
- Modify: `packages/agents/src/rca_agents/repos_pg.py`
- Test: `packages/agents/tests/test_repos_pg.py` (extend)

- [ ] **Step 1: Write failing DB-gated tests for `PgEvidencePackageRepo` + `PgRcaConclusionRepo`**

Extend `test_repos_pg.py`: `put(package)` then `get(id)` and `get_for_probe(probe_run_id)` round-trip a full `EvidencePackage`/`RcaConclusion` (validate equality on `model_dump(mode="json")`). Assert idempotent `put` (no dup rows). Use a minimal real `EvidencePackage`/`RcaConclusion` built from contract factories or the probe-workflow fixtures.

- [ ] **Step 2: Run to confirm failure**

Run: `cd packages/agents && RCA_DB=1 uv run pytest tests/test_repos_pg.py -k "evidence or conclusion" -q`
Expected: FAIL — repos not defined.

- [ ] **Step 3: Implement `PgEvidencePackageRepo` + `PgRcaConclusionRepo`**

Append to `repos_pg.py` — store the full pydantic model as JSONB `payload` plus the indexed columns. `EvidencePackageRepo`:
```python
from rca_contracts import EvidencePackage, RcaConclusion
from rca_mar.models import EvidencePackageRow, RcaConclusionRow


class PgEvidencePackageRepo:
    def __init__(self, session_factory=None):
        self._sf = session_factory or make_session_factory(make_engine())

    async def put(self, package: EvidencePackage) -> None:
        v = dict(evidence_package_id=package.evidence_package_id,
                 probe_run_id=package.probe_run_id, canonical_id=package.canonical_id,
                 investigated_failure_modes=list(package.investigated_failure_modes),
                 schema_version=package.schema_version,
                 payload=package.model_dump(mode="json"), assembled_at=package.assembled_at)
        async with self._sf() as s, s.begin():
            await s.execute(pg_insert(EvidencePackageRow).values(**v).on_conflict_do_update(
                index_elements=[EvidencePackageRow.evidence_package_id],
                set_={"payload": v["payload"]}))

    async def get(self, evidence_package_id: UUID) -> EvidencePackage | None:
        async with self._sf() as s:
            row = await s.get(EvidencePackageRow, evidence_package_id)
            return EvidencePackage.model_validate(row.payload) if row else None

    async def get_for_probe(self, probe_run_id: UUID) -> EvidencePackage | None:
        async with self._sf() as s:
            row = (await s.execute(select(EvidencePackageRow).where(
                EvidencePackageRow.probe_run_id == probe_run_id)
                .order_by(EvidencePackageRow.assembled_at.desc()))).scalars().first()
            return EvidencePackage.model_validate(row.payload) if row else None
```
`PgRcaConclusionRepo.put(conclusion, *, status)` mirrors this against `RcaConclusionRow` (payload + indexed `conclusion_id`, `probe_run_id`, `evidence_package_id`, `canonical_id`, `status`, `agent_name`, `agent_version`, `generated_at`, `finalized_at`, `llm_call_ids`), with `get`/`get_for_probe`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd packages/agents && RCA_DB=1 uv run pytest tests/test_repos_pg.py -q`
Expected: PASS (all 4 repos).

- [ ] **Step 5: Commit**

```bash
git add packages/agents/src/rca_agents/repos_pg.py packages/agents/tests/test_repos_pg.py
git commit -m "feat(sprint4 WI5): Pg evidence-package + rca-conclusion repos (idempotent)"
```

---

### Task 5.4: Wire Postgres repos + audit into the live worker; full-persistence DB test (WI5, closes #3/#5)

**Files:**
- Modify: (already done in `deps.py` Task 3.3 — `use_postgres=True` path)
- Test: `packages/agents/tests/test_live_persistence.py` (stack+DB-gated)

- [ ] **Step 1: Confirm `deps.py` selects Postgres when `PROBE_USE_POSTGRES=1`**

The worker `run()` defaults `use_pg=True`; `build_repos(use_postgres=True)` returns the Pg repos and `build_llm(use_postgres=True)` injects `PostgresLlmAuditSink`. No new code — verify wiring.

- [ ] **Step 2: Write the stack+DB-gated full-persistence test**

`packages/agents/tests/test_live_persistence.py` (skipif `RCA_STACK != 1`): run a full live probe to completion, then directly query Postgres (via MAR session factory) and assert rows exist in `probe_runs`, `probe_memory`, `evidence_packages`, `rca_conclusions`, and `llm_calls` for that `probe_run_id`, and that each is retrievable through its repo. Assert no duplicate rows after a forced activity retry (idempotency #5) — e.g. by re-invoking `create_run`/`put` with the same ids and re-counting.

- [ ] **Step 3: Run against the live stack + worker (with `PROBE_USE_POSTGRES=1`)**

Run: `RCA_STACK=1 uv run pytest tests/test_live_persistence.py -q`
Expected: PASS — runs/memory/evidence/conclusion/llm_calls all written and retrievable; idempotent on replay.

- [ ] **Step 4: Commit**

```bash
git add packages/agents/tests/test_live_persistence.py
git commit -m "test(sprint4 WI5): full Postgres persistence + idempotency on the live stack (#3/#5)"
```

---

### Task 6.1: The flywheel — second-probe read through the agent (WI6, closes #14 — DEFINITION OF DONE)

**Files:**
- Test: `packages/agents/tests/test_flywheel.py` (stack-gated)

- [ ] **Step 1: Write the stack-gated flywheel test**

`packages/agents/tests/test_flywheel.py` (skipif `RCA_STACK != 1`):
```python
# 1. Run probe #1 on P-101A to completion -> persist_conclusion_to_kg writes a
#    HistoricalFailureEvent via Neo4jAssetGraph.persist_failure_event.
# 2. Run probe #2 on the SAME asset. Capture the gather step's get_asset_context result
#    (through the live McpToolBox, i.e. kg.get_asset_context over MCP — NOT a direct Neo4j read).
# 3. Assert the second probe's context shows the first probe's event:
assert ctx2["kg_warm"] is True
assert any(e for e in ctx2["prior_events_on_asset"])      # >= 1 prior event
# 4. (sanity) the event references probe #1's conclusion_id / failure mode.
```
Capture probe #2's gather context either by reading the persisted `EvidencePackage` of probe #2 (its `iso14224_context` + provenance reflect the warm read) OR by calling `McpToolBox.get_asset_context(P101A)` directly through the same in-process client the worker uses, asserting `kg_warm is True` and a non-empty `prior_events_on_asset`. The key invariant: the read goes through `kg.get_asset_context` over MCP, not a direct `Neo4jAssetGraph` query.

- [ ] **Step 2: Run against the live stack**

Run: `RCA_STACK=1 uv run pytest tests/test_flywheel.py -q` (stack + worker up; run after the worker has processed probe #1).
Expected: PASS — second-probe `get_asset_context` returns probe #1's persisted event(s); `kg_warm` is `True`. **This is the headline demo moment.**

- [ ] **Step 3: Document the flywheel steps in `RUN.md`**

Add the "Run it twice — watch the KG warm up" section (submit probe #1, wait for completion, submit probe #2, show `GET .../conclusion` for #2 referencing prior events / `kg_warm`).

- [ ] **Step 4: Commit**

```bash
git add packages/agents/tests/test_flywheel.py RUN.md
git commit -m "feat(sprint4 WI6): flywheel — second probe reads first event via agent (#14)"
```

---

### Task 7.1: Full-probe determinism harness (WI7, closes #15)

**Files:**
- Test: `packages/agents/tests/test_probe_determinism.py`

- [ ] **Step 1: Write the determinism test (seeded sim + cached LLM → byte-identical conclusion)**

`packages/agents/tests/test_probe_determinism.py`: run the probe workflow TWICE with (a) a fixed `reference_time`, (b) a pre-seeded `InMemoryResponseCache` + `replay_from_cache=True` (so no upstream LLM variance), and (c) the seeded simulator path (or `FakeToolBox` for the hermetic variant). Hash `RcaConclusion.model_dump_json()` (excluding inherently-volatile fields if any — assert none leak) from both runs and assert equality:
```python
h1 = hashlib.sha256(conclusion1.model_dump_json().encode()).hexdigest()
h2 = hashlib.sha256(conclusion2.model_dump_json().encode()).hexdigest()
assert h1 == h2
```
Drive both runs through the same `_drive_until_complete` HITL script so the human inputs are identical. Prefer the hermetic `FakeToolBox` + scripted LLM path for CI determinism (the live seeded-sim variant is a `stack`-gated companion).

- [ ] **Step 2: Run it**

Run: `cd packages/agents && uv run pytest tests/test_probe_determinism.py -q`
Expected: PASS — identical conclusion hash across two runs.

- [ ] **Step 3: Commit**

```bash
git add packages/agents/tests/test_probe_determinism.py
git commit -m "test(sprint4 WI7): twice-run seeded probe yields identical conclusion (#15)"
```

---

### Task 7.2: `reference_time` everywhere assertion (WI7, G8)

**Files:**
- Test: `packages/agents/tests/test_reference_time_propagation.py`

- [ ] **Step 1: Write the test that fails if any activity/LLM call ignores the frozen `reference_time`**

`packages/agents/tests/test_reference_time_propagation.py`:
- Static guard: parse the agent + toolbox modules (reuse the AST approach) and assert NO direct wall-clock call (`datetime.now`, `datetime.utcnow`, `time.time`) appears in `gather_graph.py`, `planning_graph.py`, `rca_graph.py`, `base.py`, `mcp_toolbox.py`. (`FakeToolBox._now()` lives in `toolbox.py`; assert the constant there is never `datetime.now()` — or exclude `toolbox.py` from the live-determinism path and document it.)
- Behavioral guard: run a probe with a distinctive `reference_time` (e.g. `2026-03-30T12:00:00Z`) and assert every produced timestamp that should be frozen (Evidence Package `reference_time`/`assembled_at`, conclusion `generated_at`, provenance `queried_at` for tag/operator-log sections) equals the frozen `reference_time` (or a value derived from it), with NO wall-clock drift.

- [ ] **Step 2: Run it**

Run: `cd packages/agents && uv run pytest tests/test_reference_time_propagation.py -q`
Expected: PASS — no wall-clock leakage on the determinism path; frozen `reference_time` flows through activities, McpToolBox, and the LLM correlation.

- [ ] **Step 3: Normalize `McpToolBox` timestamps if the test surfaces drift**

If the behavioral guard fails on WO/document `queried_at` (which come from connector provenance), make `McpToolBox` stamp those `ProvenanceEntry.queried_at` from `reference_time` too (consistent with tag/operator-log), and re-run. (This resolves the G8 FakeToolBox inconsistency in the live path.)

- [ ] **Step 4: Commit**

```bash
git add packages/agents/src/rca_agents/mcp_toolbox.py packages/agents/tests/test_reference_time_propagation.py
git commit -m "test(sprint4 WI7): assert frozen reference_time everywhere; no wall-clock leak (G8)"
```

---

### Task 8.1: Cross-cutting acceptance — lint, type, full hermetic suite (§5 #9)

**Files:** none (verification gate)

- [ ] **Step 1: Run the full hermetic test suite (no regressions)**

Run:
```bash
task test            # or: uv run pytest across packages (hermetic only; RCA_STACK/RCA_DB unset)
```
Expected: the existing 478 hermetic tests + all new hermetic tests green; no regressions.

- [ ] **Step 2: Lint + type-check clean**

Run:
```bash
task lint            # ruff + mypy across packages
```
Expected: `ruff` clean, `mypy` clean. Fix any findings in the new modules (`mcp_toolbox.py`, `host.py`, `repos_pg.py`, `audit_pg.py`, `class_map.py`, `deps.py`, `wo.py`).

- [ ] **Step 3: Run the full live acceptance once (all stack/DB-gated tests)**

Run (stack + worker up, `PROBE_USE_POSTGRES=1`, API keys set):
```bash
RCA_STACK=1 RCA_DB=1 uv run pytest packages/agents/tests/test_live_probe_walkthrough.py \
  packages/agents/tests/test_live_persistence.py packages/agents/tests/test_flywheel.py \
  packages/agents/tests/test_probe_determinism.py -q
```
Expected: all §5 acceptance items hold simultaneously on the live stack — single probe + mid-analysis HITL (D2), MAR→KG class binding with hard-fail (D1), full Postgres persistence (#3/#5), flywheel (#14), determinism + `reference_time` (#15), budget-exhaustion (D4), pgvector image runs Temporal (D3), §8 invariant test green.

- [ ] **Step 4: Sprint-4 state report + final commit**

Write `sprint4_state_report.md` (mirror `sprint3_state_report.md`): what shipped, the G1–G14 resolutions + any new G15+ discovered during execution, acceptance evidence, and deferred items (full HTTP host + `RegistryConnectionRouter`, real pgvector `vector` column, `PostgresResponseCache`). Commit:
```bash
git add sprint4_state_report.md
git commit -m "docs(sprint4): state report — shipped, gap resolutions, acceptance, deferred"
```

---

## Self-Review (run against the spec)

**Spec coverage — every §5 item maps to a task:**
1. `python -m rca_agents.worker` runs the probe over MCP → Tasks 3.1, 3.3, 3.4.
2. P-101A single probe + mid-analysis HITL (D2) → Task 4.1.
3. MAR→KG class binding once at registration; unresolved hard-fails (D1) → Tasks 1.2, 1.3, 1.4, 1.5.
4. Full Postgres persistence (#3/#5) → Tasks 5.1–5.4.
5. Flywheel second-probe read (#14) → Task 6.1.
6. Determinism + `reference_time` (#15) → Tasks 7.1, 7.2.
7. Budget-exhaustion (D4) → Task 4.1 step 2; pgvector runs Temporal (D3) → Task 1.1.
8. §8 invariant (no source imports; config-only sim↔real) → Task 2.2 step 5 (+ G10 deviation flagged).
9. ruff + mypy clean; 478 hermetic tests green → Task 8.1.

**Per-WI coverage:** WI1→1.1–1.6; WI2→2.1–2.2; WI3→3.1–3.5; WI4→4.1; WI5→5.1–5.4; WI6→6.1; WI7→7.1–7.2.

**Type/name consistency:** `McpToolBox(client)` constructor, `build_entity_host(*, router, mar_repo, asset_graph)`, `build_probe_deps(*, toolbox, asset_graph, wo_client, use_postgres)`, `McpWorkOrderCreator(client)`, `resolve_equipment_class`/`UnknownEquipmentClass`, `kg_class_for`, `PostgresLlmAuditSink`, `PgProbeRunsRepo`/`PgProbeMemoryRepo`/`PgEvidencePackageRepo`/`PgRcaConclusionRepo` — used consistently across Tasks 2.x, 3.x, 5.x.

**Known heuristics flagged (not placeholders — documented stand-ins):** `McpToolBox.search_assets` confidence/keyword mapping (`_pattern`), `summarize_series` severity rule. Both are documented as toolbox-side stand-ins (real fuzzy search + anomaly detection are Sprint 5 / the LLM's job) and are exercised by tests.

**Verify-at-execution flags (confirm method names before coding the step):** MAR connection upsert method name (Task 3.5 step 1), `ProbeRunStatus.budget_exceeded` string (Task 4.1 step 2), `LlmCallRecord`↔`LlmCall` column parity (Task 5.1 step 3), any KG test relying on the old silent-skip (Task 1.3 step 5).
