"""Onboarding test fixtures: in-memory deps bundle over the fake PI AF app.

Everything hermetic — no Postgres, no Neo4j, no Temporal server. The shared constants and
helper functions live in ``onb_helpers`` (uniquely named to avoid the cross-package bare
``conftest`` module collision under pytest's prepend import mode); only the fixtures live here.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI

from rca_mar.repository import InMemoryRepository
from rca_kg.write import InMemoryHierarchyWriter

from rca_onboarding.activities import ActivityDeps
from rca_onboarding.runs_repo import InMemoryOnboardingRunsRepo

from onb_helpers import TENANT, make_fake_af_app, make_http_factory


@pytest.fixture
def fake_af_app() -> FastAPI:
    return make_fake_af_app()


@pytest.fixture
def deps(fake_af_app: FastAPI) -> ActivityDeps:
    return ActivityDeps(
        repo=InMemoryRepository(), kg=InMemoryHierarchyWriter(),
        http_factory=make_http_factory(fake_af_app), threshold=0.92,
        runs=InMemoryOnboardingRunsRepo(), tenant_id=TENANT)
