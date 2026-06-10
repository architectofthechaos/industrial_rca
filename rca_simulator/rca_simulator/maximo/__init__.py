"""S2.3 — Maximo simulator (Maximo OSLC REST).

Stands in for IBM Maximo. Seeds WO/SR/failure-report history matching scenario
timelines. Emits local-time-without-TZ timestamps and some legacy (non-ISO-14224)
failure codes on purpose, to exercise connector normalization.

Modules
-------
app.py      FastAPI OSLC routes: /maxrest/oslc/os/{mxwo,mxsr,mxfailrep}
            + idempotent write-back.
oslc.py     oslc.where / oslc.select parsing, paging, OSLC response shaping.
seed.py     scenario events -> WO/SR/failrep history.
Dockerfile  Container image.

Ref: SPEC-007 (Maximo section), TASK-S2.3.
"""
