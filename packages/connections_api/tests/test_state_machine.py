"""Connection state-machine tests (Sprint 2b §1.4) — the legal/illegal transition table."""
from __future__ import annotations

import itertools

import pytest

from rca_connections_api.state_machine import (
    LEGAL_TRANSITIONS,
    PATCH_TRANSITIONS,
    STATUSES,
    InvalidTransition,
    assert_patch_transition,
    assert_transition,
)

_ALL_PAIRS = list(itertools.product(sorted(STATUSES), repeat=2))


@pytest.mark.parametrize("current,target", sorted(LEGAL_TRANSITIONS))
def test_legal_transitions_pass(current, target):
    assert_transition(current, target)   # no raise


@pytest.mark.parametrize("current,target", _ALL_PAIRS)
def test_full_table(current, target):
    """Every (current, target) pair: legal ones pass, everything else (incl. no-ops) raises."""
    if (current, target) in LEGAL_TRANSITIONS:
        assert_transition(current, target)
    else:
        with pytest.raises(InvalidTransition):
            assert_transition(current, target)


def test_unknown_status_rejected():
    with pytest.raises(InvalidTransition):
        assert_transition("pending", "frozen")


def test_no_op_rejected():
    with pytest.raises(InvalidTransition):
        assert_transition("active", "active")


# -- PATCH-allowed subset ------------------------------------------------

@pytest.mark.parametrize("current,target", sorted(PATCH_TRANSITIONS))
def test_patch_allowed_transitions_pass(current, target):
    assert_patch_transition(current, target)   # no raise


@pytest.mark.parametrize("current,target", sorted(LEGAL_TRANSITIONS - PATCH_TRANSITIONS))
def test_patch_rejects_endpoint_driven_transitions(current, target):
    """Transitions that are legal overall but reserved for /activate or /test must NOT be
    reachable via PATCH (e.g. pending->active, *->error, error->pending)."""
    with pytest.raises(InvalidTransition):
        assert_patch_transition(current, target)
