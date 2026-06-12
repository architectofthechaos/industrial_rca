import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RCA_DB") != "1",
                                reason="requires Postgres (task infra:up)")


@pytest.mark.asyncio
async def test_audit_sink_writes_and_is_idempotent():
    from datetime import datetime, timezone

    from sqlalchemy import select

    from rca_llm.audit import LlmCallRecord
    from rca_llm.audit_pg import PostgresLlmAuditSink
    from rca_mar.config import make_engine, make_session_factory
    from rca_mar.models import LlmCall

    sink = PostgresLlmAuditSink()
    call_id = uuid.uuid4()
    rec = LlmCallRecord(llm_call_id=call_id, correlation_id="corr-1", probe_run_id=None,
                        prompt_name="detect_tag_anomalies", prompt_version="v1",
                        prompt_hash="abc", model="claude-opus-4-8", model_version="x",
                        temperature=0.0, input_tokens=10, output_tokens=5, latency_ms=12,
                        cached=False, request_payload={"a": 1}, response_payload={"b": 2},
                        created_at=datetime(2026, 3, 30, tzinfo=timezone.utc))
    await sink.record(rec)
    await sink.record(rec)  # idempotent — second write must not raise/dup
    sf = make_session_factory(make_engine())
    async with sf() as s:
        rows = (await s.execute(select(LlmCall).where(LlmCall.llm_call_id == call_id))).scalars().all()
    assert len(rows) == 1 and rows[0].correlation_id == "corr-1" and rows[0].prompt_name == "detect_tag_anomalies"
