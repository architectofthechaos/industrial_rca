"""rca_onboarding — Temporal-backed onboarding pipeline (Sprint 2b Track 2).

Manual-trigger, idempotent pipeline: crawl active connections for a plant, project the
discovered assets into MAR (asset registry + bindings) and the hierarchy into the KG,
reconcile/decommission assets that disappeared from the source, and persist a coverage
report row in `onboarding_runs`. The headline guarantee is idempotency — a re-run with no
source change writes zero rows (see `activities.project_to_mar` / `project_to_kg`).

Kept lean (no eager submodule re-exports) so `import rca_onboarding` doesn't drag in
temporalio for callers that only want the data models.
"""
__version__ = "0.0.1"

# Single-tenant MVP default — matches the seed `tenant_id` and connections_api's
# DEFAULT_TENANT_ID so the worker projects into the same tenant the data is seeded under.
DEFAULT_TENANT_ID = "0190d3c9-0000-7000-8000-0000000000ff"
TASK_QUEUE = "rca-onboarding"
