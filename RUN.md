# RUN.md — Live P-101A probe + flywheel reproduction runbook

This is the exact, copy-pasteable reproduction for the Sprint 4 live demo: a real end-to-end RCA
probe on **P-101A** running against the live simulated stack over MCP, with HITL, budget
exhaustion, and the **flywheel** (run it twice — the second probe reads the first probe's
persisted failure event through the agent's KG path).

Everything here runs against a **live** stack and **real LLM API keys**. The stack-gated pytest
tests (`tests/test_live_probe_*.py`, `tests/test_flywheel.py`) reproduce all of it automatically
— see the last section.

---

## 0. Prerequisites

- **Docker** (Desktop or engine) — runs Postgres (pgvector), Neo4j, and the Temporal dev cluster.
- **[Task](https://taskfile.dev)** (`task`) — the repo's command runner (`Taskfile.yaml`).
- **[uv](https://docs.astral.sh/uv/)** — the Python package/venv manager.
- **Live LLM SDKs.** The Anthropic + Voyage SDKs are an *optional* extra (`rca-llm[live]`) so
  the hermetic suite stays SDK-free. Install them into the workspace venv:

  ```bash
  uv sync                                  # base workspace deps
  uv pip install -e 'packages/llm[live]'   # adds anthropic + voyageai (the rca-llm[live] extra)
  ```

- **API keys** — export both before starting the worker (the worker process needs them; the
  REST API and Temporal do not):

  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...
  export VOYAGE_API_KEY=pa-...
  ```

---

## 1. Bring up the full stack

**Shell A** — infra + migrations + KG seed + simulators + refplant connections, all in one task:

```bash
task stack:up
```

`stack:up` runs, in order: `infra:up` (Postgres + Neo4j + Temporal + Temporal UI, `--wait` for
health) → `mar:migrate` → `kg:migrate` → `kg:seed` (ISO 14224 BB1 ontology + refplant hierarchy)
→ `cd rca_simulator && task up` (the four sims: PI :8001, Maximo :8002, SAP :8003, SharePoint
:8004) → `python scripts/seed_refplant_assets.py` (loads the MAR `assets` table from the
authoritative register so `asset.search`/`asset.get` can resolve P-101A) →
`python scripts/seed_refplant_connections.py` (registers the four refplant connections as
`active`, demoting any conflicting register-default actives so each category has exactly one
active source). It finishes by printing `stack up. Now run: task probe:worker`.

> Asset seed runs **before** the connection seed: seeding asset aliases also upserts the
> register's default connections, two of which land `active` in the `cmms`/`historian` slots;
> the connection seed then reconciles those to the probe's `maximo-main`/`pi-main`. Both scripts
> are idempotent — re-running `stack:up` never errors. If you ever need to seed assets manually:
> `uv run python scripts/seed_refplant_assets.py`.

> First Temporal boot provisions its DBs in the shared Postgres; the healthcheck can take 20–40s.

**Shell B** — the probe worker on the `rca-probes` queue, wired to Postgres persistence:

```bash
PROBE_USE_POSTGRES=1 task probe:worker
```

This is `python -m rca_agents.worker`: it builds the in-process entity MCP host (MAR + KG + the
four connectors), wraps it in a `fastmcp.Client`, assembles `ProbeActivityDeps` with the live
`McpToolBox` + `Neo4jAssetGraph` + the live `AnthropicTransport`/`VoyageEmbeddingTransport` LLM
client + Postgres repos, and serves the workflow. **Needs `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY`
exported in this shell.**

**Shell C** — the Probe REST API on `:8400`:

```bash
task api:probes
```

(OpenAPI docs at <http://localhost:8400/docs>.)

---

## 2. Run a probe (the happy path)

### 2.1 Submit

```bash
curl -sS -XPOST localhost:8400/probes/run \
  -H 'content-type: application/json' \
  -d '{
        "prompt": "RCA on P-101A seal leak",
        "plant_id": "refinery-gc",
        "requested_by": "pilot@deepiq.com"
      }'
```

Response (202) — note the `probe_run_id`; use it for `{id}` below:

```json
{"workflow_id": "probe-<uuid>", "probe_run_id": "<uuid>"}
```

### 2.2 Poll for the first HITL gate (plan approval)

```bash
curl -sS localhost:8400/probes/runs/<id>/hitl/pending
```

`204 No Content` means the workflow hasn't paused yet — keep polling. When planning finishes it
returns the **plan-approval** `HitlTurn` (`agent_name: "planning"`, an `approval` question, and a
`proposed_plan`).

### 2.3 Answer the plan-approval turn

Echo the `turn_id` and the question's `question_id` from the pending turn into a `HitlResponse`:

```bash
curl -sS -XPOST localhost:8400/probes/runs/<id>/hitl/respond \
  -H 'content-type: application/json' \
  -d '{
        "turn_id": "<turn_id from pending>",
        "approved": true,
        "actions_approved": true,
        "responded_by": "pilot@deepiq.com",
        "responded_at": "2026-03-30T12:00:00+00:00",
        "answers": [
          {"question_id": "<question_id from pending>", "answer": "approve"}
        ]
      }'
```

### 2.4 Drive the remaining gates (incl. the mid-5-Whys human-knowledge question, D2)

Keep polling `.../hitl/pending` and answering. The RCA agent raises a **mid-5-Whys** turn when an
answer needs human knowledge: `agent_name: "rca"`, a `context` question (NOT `approval`), no
`proposed_conclusion`, with `context_for_engineer` like *"My evidence can't answer this — your
input?"*. Answer it with a concrete textual fact, e.g.:

```bash
curl -sS -XPOST localhost:8400/probes/runs/<id>/hitl/respond \
  -H 'content-type: application/json' \
  -d '{
        "turn_id": "<five-whys turn_id>",
        "responded_by": "pilot@deepiq.com",
        "responded_at": "2026-03-30T12:00:00+00:00",
        "answers": [
          {"question_id": "<question_id>",
           "answer": "Seal flush line was partially blocked at the last PM; marginal flush flow dried the seal faces."}
        ]
      }'
```

The final gate is the **conclusion-review** turn (`agent_name: "rca"`, an `approval` question,
`proposed_conclusion` set). Approve it exactly like the plan-approval turn (§2.3) with
`"approved": true, "actions_approved": true`.

### 2.5 Read the conclusion

```bash
curl -sS localhost:8400/probes/runs/<id>/conclusion
```

You get the finalized `RcaConclusion` — a ranked `primary_hypothesis` (rank 1, an ISO 14224
failure mode + mechanism + narrative), `fishbone`, the `five_whys` chain, and
`recommended_actions`. The run finalizes at terminal status **`completed`**; the close phase has
persisted a `HistoricalFailureEvent` to the KG and (if actions were approved) a follow-up WO
(`GET .../followup_wo`).

---

## 3. Budget-exhaustion variant (D4)

Submit the same probe but with a **tight** token budget so the per-call budget gate trips early.
The REST `StartProbeRequest` does not expose the limits, so drive this one directly through the
Temporal client (the worker reads the limits off `ProbeWorkflowInput`):

```python
# python -  (with the worker venv active)
import asyncio, uuid
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from rca_agents.api import workflow_id_for
from rca_agents.models import ProbeWorkflowInput
from rca_agents.workflow import ProbeWorkflow

async def main():
    c = await Client.connect("localhost:7233", namespace="default",
                             data_converter=pydantic_data_converter)
    rid = str(uuid.uuid4())
    await c.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt="RCA on P-101A seal leak", plant_id="refinery-gc",
                           requested_by="pilot@deepiq.com", probe_run_id=rid,
                           input_tokens_limit=200, output_tokens_limit=50),
        id=workflow_id_for(rid), task_queue="rca-probes")
    print("probe_run_id:", rid)

asyncio.run(main())
```

Then read the run status:

```bash
curl -sS localhost:8400/probes/runs/<id>
```

Expected terminal status: **`budget_exceeded`** (the exact `rca_contracts.ProbeRunStatus` value).
A partial result is retrievable (the run row + whatever artifacts the early phases persisted).
**No "extend budget?" HITL turn fires** — budget exhaustion halts the probe cleanly; the agent
never bargains for more budget.

---

## 4. The flywheel — run it twice, watch the KG warm up (#14)

This is the headline demo. Run probe **#1** to completion (§2). Its close phase wrote a
`HistoricalFailureEvent` on P-101A to the KG. Now submit probe **#2** on the same asset:

```bash
curl -sS -XPOST localhost:8400/probes/run \
  -H 'content-type: application/json' \
  -d '{"prompt": "RCA on P-101A seal leak (second look)", "plant_id": "refinery-gc", "requested_by": "pilot@deepiq.com"}'
```

Drive #2's HITL turns to completion the same way, then read its conclusion:

```bash
curl -sS localhost:8400/probes/runs/<id-2>/conclusion
```

Probe #2's gather step calls `kg.get_asset_context(P-101A)` over MCP and now sees a **warm** KG:
`kg_warm: true` and a non-empty `prior_events_on_asset` carrying probe #1's failure event
(same ISO 14224 failure mode / conclusion lineage). That prior-event context flows into #2's
evidence package and conclusion — the system is learning from its own history.

---

## 5. The stack-gated pytest tests reproduce all of the above

With the stack up (§1, all three shells), the live tests run the entire flow automatically:

```bash
cd packages/agents
RCA_STACK=1 uv run pytest tests/test_live_probe_smoke.py \
                          tests/test_live_probe_walkthrough.py \
                          tests/test_flywheel.py -q
```

- `test_live_probe_smoke.py` — submits a P-101A probe via the Temporal client and asserts it
  reaches the plan-approval HITL gate within ~60s (Task 3.4 / WI3).
- `test_live_probe_walkthrough.py` — drives the full walkthrough incl. the mid-5-Whys
  human-knowledge turn to a `completed` ranked conclusion (D2), and the tight-budget probe to
  `budget_exceeded` with a partial result and no extend-budget turn (D4). (Task 4.1 / WI4.)
- `test_flywheel.py` — runs probe #1 to completion, then reads `get_asset_context(P-101A)` back
  through an in-process entity host + `fastmcp.Client` + `McpToolBox` (i.e. `kg.get_asset_context`
  over MCP, not a direct Neo4j query) and asserts `kg_warm is True` with a non-empty
  `prior_events_on_asset` (Task 6.1 / WI6, #14).

**Without `RCA_STACK=1` these tests SKIP cleanly**, so the hermetic CI suite stays green and
network/SDK-free.

---

## 6. Tear down

```bash
cd rca_simulator && task down && cd ..                      # stop + remove the simulators
docker compose -f infra/docker-compose.yaml down            # stop Postgres + Neo4j + Temporal
```
