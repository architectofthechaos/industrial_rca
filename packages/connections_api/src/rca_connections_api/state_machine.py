"""Connection status state machine (Sprint 2b §1.4).

A connection moves through `pending → active → disabled` with `error` reachable from any
working state after a failed test/health probe. The transitions split into two groups by who
drives them:

* **Endpoint-driven** — only a specific endpoint may perform the move; PATCH must NOT:
    - ``pending → active``   only ``POST /connections/{id}/activate`` (after a successful test)
    - ``pending → error``    only ``POST /connections/{id}/test`` (test failed)
    - ``active  → error``    only ``POST /connections/{id}/test`` (test/health failed)
    - ``error   → pending``  only ``POST /connections/{id}/test`` (test succeeded)

* **PATCH-allowed** — operator-driven lifecycle moves a ``PATCH`` status change may perform:
    - ``active   → disabled``  deactivate (also what ``DELETE`` does as a soft delete)
    - ``disabled → pending``   re-enable; the connection then needs a fresh test before
      it can be activated again.

``LEGAL_TRANSITIONS`` is the full table (every move any path may make). ``PATCH_TRANSITIONS``
is the subset PATCH may request directly. ``assert_transition`` validates against the full
table; ``assert_patch_transition`` additionally rejects endpoint-driven moves so a PATCH
caller can't, e.g., flip ``pending → active`` and bypass the test gate.
"""
from __future__ import annotations

STATUSES = frozenset({"pending", "active", "error", "disabled"})

# The full lifecycle table — (current, target) pairs that are legal for SOME path.
LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("pending", "active"),     # /activate (after a successful test)
    ("pending", "error"),      # /test failure
    ("active", "disabled"),    # deactivate / DELETE soft-delete
    ("active", "error"),       # /test or /health failure
    ("error", "pending"),      # /test success
    ("disabled", "pending"),   # re-enable (needs a fresh test before re-activation)
})

# The subset a PATCH status-change may request directly. Endpoint-driven moves are excluded
# so PATCH cannot bypass the test/activate gates.
PATCH_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("active", "disabled"),    # deactivate
    ("disabled", "pending"),   # re-enable
})


class InvalidTransition(Exception):
    """An illegal connection status transition (Sprint 2b §1.4). The API maps this to a 409."""

    def __init__(self, current: str, target: str, *, reason: str | None = None) -> None:
        self.current = current
        self.target = target
        self.reason = reason
        detail = f"illegal status transition {current!r} -> {target!r}"
        if reason:
            detail = f"{detail}: {reason}"
        super().__init__(detail)


def assert_transition(current: str, target: str) -> None:
    """Raise InvalidTransition unless (current, target) is a legal lifecycle move.

    A no-op (current == target) is rejected — callers should not request a status change that
    changes nothing. Unknown statuses are rejected too.
    """
    if target not in STATUSES:
        raise InvalidTransition(current, target, reason=f"unknown status {target!r}")
    if current == target:
        raise InvalidTransition(current, target, reason="no-op transition")
    if (current, target) not in LEGAL_TRANSITIONS:
        raise InvalidTransition(current, target)


def assert_patch_transition(current: str, target: str) -> None:
    """Raise InvalidTransition unless PATCH itself may make this status move.

    Beyond the full-table check, this rejects endpoint-driven moves (e.g. ``pending → active``
    belongs to ``/activate``; ``* → error`` / ``error → pending`` belong to ``/test``).
    """
    assert_transition(current, target)
    if (current, target) not in PATCH_TRANSITIONS:
        raise InvalidTransition(
            current, target,
            reason="endpoint-driven transition; use /activate or /test, not PATCH")


__all__ = [
    "STATUSES", "LEGAL_TRANSITIONS", "PATCH_TRANSITIONS",
    "InvalidTransition", "assert_transition", "assert_patch_transition",
]
