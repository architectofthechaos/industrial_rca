"""Assemble ProbeActivityDeps (WI3). Composition root — imports real impls. The `use_postgres`
flag selects in-memory (Tier A / tests) vs Postgres repos + audit (WI5)."""
from __future__ import annotations

from typing import Any

from rca_llm import LLMClientImpl, default_registry

from .activities import ProbeActivityDeps
from .repos import (InMemoryEvidencePackageRepo, InMemoryProbeMemoryRepo,
                    InMemoryProbeRunsRepo, InMemoryRcaConclusionRepo)
from .wo import McpWorkOrderCreator
from .worker import default_agent_factories


def build_llm(*, use_postgres: bool) -> Any:
    """Build the non-bypassable LLM client.

    The live Anthropic/Voyage transports (and their SDKs) are imported LAZILY here — same
    invariant as ``rca_llm.transports``: the hermetic suite runs without the ``rca-llm[live]``
    SDKs installed. If they are unavailable we still return a real ``LLMClientImpl`` (with its
    default replay-only transport) so ``deps.llm`` is always present and non-None; an actual
    upstream call on that client fails loudly. The live entrypoint (``worker.run``) runs in an
    environment where the SDKs + keys are installed, so it gets the real transports.
    """
    audit = None
    if use_postgres:
        from rca_llm.audit_pg import PostgresLlmAuditSink   # WI5 (lazy)
        audit = PostgresLlmAuditSink()
    try:
        from rca_llm.transports import AnthropicTransport, VoyageEmbeddingTransport
        transport: Any = AnthropicTransport()
        embedding_transport: Any = VoyageEmbeddingTransport()
    except (ImportError, ModuleNotFoundError):
        # rca-llm[live] SDKs not installed (hermetic env) — fall back to the default
        # replay-only transports so deps assembly stays network/SDK-free.
        transport = None
        embedding_transport = None
    return LLMClientImpl(registry=default_registry(), transport=transport,
                         embedding_transport=embedding_transport, audit=audit)


def build_repos(*, use_postgres: bool):
    if use_postgres:
        from .repos_pg import (PgEvidencePackageRepo, PgProbeMemoryRepo, PgProbeRunsRepo,
                               PgRcaConclusionRepo)          # WI5 (lazy)
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
