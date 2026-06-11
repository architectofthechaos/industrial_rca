"""MarResolver -> Maximo connector wire-in (hermetic).

PARKED by Sprint 2b Track 3 Task 5. The Maximo connector was rewritten as the ``work_order``
entity MCP (``make_work_order_mcp``), which routes via ConnectionRouter + AssetGateway and no
longer accepts the TagResolver/SourceBinding wiring this test exercised (the old
``make_maximo_mcp`` + ``maximo.get_workorders``). Re-enabling registry-resolved work-order
fetch needs a MAR -> AssetGateway adapter (MAR-wiring work, not in Task 5's scope); the
original SourceBinding-based test is preserved in git history. Skip cleanly until then.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="MAR->connector wiring rewritten for the work_order entity MCP (AssetGateway); "
           "re-enabled when the MAR AssetGateway adapter lands (Task 5 parked this)"
)


def test_maximo_uses_mar_resolved_handle():
    """Placeholder: revived against make_work_order_mcp + a MAR-backed AssetGateway."""
