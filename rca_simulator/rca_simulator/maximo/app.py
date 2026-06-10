"""S2.3 — Maximo OSLC REST simulator (FastAPI).

Serves three object structures the connector reads — ``mxwo`` (work orders),
``mxsr`` (service requests), ``mxfailrep`` (failure reports) — over the OSLC query
surface (``oslc.where`` / ``oslc.select`` / paging), plus an idempotent work-order
write-back. Realism (5xx) is applied via the shared S2.8 harness.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException, Query

from ..fixtures.schema import RefPlant
from ..realism.config import RealismConfig
from ..realism.inject import RealismInjector
from .oslc import apply_select, apply_where, paginate, parse_where
from .seed import seed_failure_reports, seed_service_requests, seed_work_orders


def create_app(rp: RefPlant, *, realism: RealismInjector | None = None) -> FastAPI:
    app = FastAPI(title="Maximo OSLC Simulator")

    # mutable WO store keyed by wonum (seed + write-back); idempotent by key.
    work_orders: dict[str, dict] = {w["wonum"]: w for w in seed_work_orders(rp)}
    failreps = seed_failure_reports(rp)
    service_requests = seed_service_requests(rp)

    def _guard() -> None:
        if realism is not None and realism.maybe_error():
            raise HTTPException(status_code=500, detail="Maximo internal error")

    def _query(records, where, select, page_size, page):
        _guard()
        records = apply_where(records, parse_where(where))
        page_records, total = paginate(records, page_size, page or 1)
        page_records = apply_select(page_records, select)
        return {"member": page_records, "responseInfo": {"totalCount": total}}

    @app.get("/maxrest/oslc/os/mxwo")
    def mxwo(
        where: str | None = Query(None, alias="oslc.where"),
        select: str | None = Query(None, alias="oslc.select"),
        page_size: int | None = Query(None, alias="oslc.pageSize"),
        page: int | None = Query(None, alias="oslc.pageNo"),
    ):
        return _query(list(work_orders.values()), where, select, page_size, page)

    @app.post("/maxrest/oslc/os/mxwo")
    def mxwo_create(record: dict = Body(...)):
        _guard()
        wonum = record.get("wonum")
        if not wonum:
            raise HTTPException(status_code=400, detail="wonum required")
        work_orders[wonum] = {**work_orders.get(wonum, {}), **record}   # idempotent upsert
        return work_orders[wonum]

    @app.get("/maxrest/oslc/os/mxsr")
    def mxsr(
        where: str | None = Query(None, alias="oslc.where"),
        select: str | None = Query(None, alias="oslc.select"),
        page_size: int | None = Query(None, alias="oslc.pageSize"),
        page: int | None = Query(None, alias="oslc.pageNo"),
    ):
        return _query(service_requests, where, select, page_size, page)

    @app.get("/maxrest/oslc/os/mxfailrep")
    def mxfailrep(
        where: str | None = Query(None, alias="oslc.where"),
        select: str | None = Query(None, alias="oslc.select"),
        page_size: int | None = Query(None, alias="oslc.pageSize"),
        page: int | None = Query(None, alias="oslc.pageNo"),
    ):
        return _query(failreps, where, select, page_size, page)

    return app


def build_default_app() -> FastAPI:
    import os

    from ..fixtures.loader import load

    rp = load(os.environ.get("FIXTURE_PATH", "fixtures/refplant"))
    return create_app(rp, realism=RealismInjector(RealismConfig.from_env()))


__all__ = ["create_app", "build_default_app"]
