"""Sprint 4 WI7 (G8) — the frozen ``reference_time`` is the ONLY clock the probe reads.

G8: a probe is reproducible because every "now" on the determinism path is the workflow's
frozen ``reference_time`` (``workflow.now()`` captured once at start and threaded into every
``LegContext``), never a wall clock. Two guards enforce this:

(a) STATIC AST guard — the agent leg modules + both toolbox adapters contain NO wall-clock call
    (``datetime.now``/``datetime.utcnow``/``date.today``/``time.time``). ``FakeToolBox._now`` is
    fine: it returns a literal ``datetime(2026, 3, 30, ...)`` *constructor*, not a clock read, so
    the same "no wall-clock call" assertion covers ``toolbox.py`` too.

(b) BEHAVIORAL guard — run the full hermetic probe with a distinctive frozen REF and assert the
    frozen value reaches the produced artifacts: ``EvidencePackage.reference_time`` /
    ``.assembled_at`` (gather stamps both from ctx.reference_time) and ``RcaConclusion.generated_at``
    (the rca agent stamps it from ctx.reference_time). Any non-REF timestamp means a wall clock
    leaked onto the determinism path — the test fails and the leak is the finding.

The AST-walk style mirrors ``tests/test_no_source_imports.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Reuse the end-to-end hermetic harness + its distinctive frozen reference_time.
from test_probe_workflow import REF, _deps, _only_probe, _run

SRC = Path(__file__).resolve().parent.parent / "src" / "rca_agents"

# Same "no wall-clock call" set as the source-import guard: the three graphs, the leg base, and
# both toolbox adapters. Activities/workflow legitimately read workflow.now() (the frozen clock).
GUARDED = [
    "gather_graph.py", "planning_graph.py", "rca_graph.py",
    "base.py", "toolbox.py", "mcp_toolbox.py",
]

# attribute names that read a wall clock: x.now() / x.utcnow() / x.today()
_WALL_CLOCK_ATTRS = {"now", "utcnow", "today"}


def _wall_clock_calls(path: Path) -> list[str]:
    """Return descriptions of any wall-clock call sites in a module.

    Flags ``ast.Call`` whose func is an attribute named now/utcnow/today (e.g.
    ``datetime.now(...)``, ``datetime.utcnow(...)``, ``date.today(...)``) or the bare
    ``time.time(...)`` reader. A literal ``datetime(2026, 3, 30, ...)`` constructor is a plain
    ``ast.Name`` call, not an attribute, so it is correctly NOT flagged.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _WALL_CLOCK_ATTRS:
                hits.append(f"{path.name}:{node.lineno} -> .{func.attr}()")
            # time.time()
            elif func.attr == "time" and isinstance(func.value, ast.Name) \
                    and func.value.id == "time":
                hits.append(f"{path.name}:{node.lineno} -> time.time()")
    return hits


# --------------------------------------------------------------------- (a) static guard
def test_no_wall_clock_calls_in_agent_and_toolbox_modules():
    offenders: dict[str, list[str]] = {}
    for fname in GUARDED:
        path = SRC / fname
        assert path.exists(), f"guarded source file missing: {fname}"
        hits = _wall_clock_calls(path)
        if hits:
            offenders[fname] = hits
    assert not offenders, (
        "G8 violated — a wall-clock call exists on the determinism path; every 'now' must come "
        f"from the frozen reference_time: {offenders}")


# --------------------------------------------------------------------- (b) behavioral guard
async def test_frozen_reference_time_propagates_to_evidence_and_conclusion():
    deps = _deps()
    result = await _run(deps)
    assert result.status == "completed"

    probe = _only_probe(deps)
    ep = await deps.evidence.get_for_probe(probe)
    conclusion = await deps.conclusions.get_for_probe(probe)
    assert ep is not None and conclusion is not None

    # gather stamps both the window anchor and the assembly time from ctx.reference_time
    assert ep.reference_time == REF, (
        f"EvidencePackage.reference_time {ep.reference_time} != frozen REF {REF} — wall clock leak")
    assert ep.assembled_at == REF, (
        f"EvidencePackage.assembled_at {ep.assembled_at} != frozen REF {REF} — wall clock leak")
    # the rca agent stamps generated_at from ctx.reference_time
    assert conclusion.generated_at == REF, (
        f"RcaConclusion.generated_at {conclusion.generated_at} != frozen REF {REF} — wall clock "
        "leak")
