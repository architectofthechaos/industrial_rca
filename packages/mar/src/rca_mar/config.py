"""MAR configuration: async engine + session factory from DATABASE_URL, thresholds from env."""
from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DEFAULT_URL = "postgresql+asyncpg://rca:rca@127.0.0.1:5432/rca_mar"
DEFAULT_AUTO_ACCEPT_THRESHOLD = 0.92


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def auto_accept_threshold() -> float:
    """Resolution auto-accept confidence gate (Phase 1 spec §2.5); below it -> pending_review."""
    return float(os.environ.get("MAR_AUTO_ACCEPT_THRESHOLD", DEFAULT_AUTO_ACCEPT_THRESHOLD))


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or database_url(), pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
