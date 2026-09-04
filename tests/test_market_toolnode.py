"""The market analyst pre-fetches the verified market snapshot deterministically
in code, so exact OHLCV / indicator claims are always grounded — replacing the
old ToolNode wiring where the snapshot was bound to the LLM but could go missing
from the executor (a wiring gap that made the model report it "unavailable").

Regression guard: the analyst must actually call
``get_verified_market_snapshot.func`` and ``get_stock_data.func`` rather than
rely on the LLM to summon a tool.
"""
import inspect

import pytest

import tradingagents.agents.analysts.market_analyst as ma


@pytest.mark.unit
def test_market_analyst_prefetches_verified_snapshot_in_code():
    src = inspect.getsource(ma)
    assert "get_verified_market_snapshot.func(" in src
    assert "get_stock_data.func(" in src


@pytest.mark.unit
def test_market_analyst_no_longer_binds_tools():
    # The market analyst is single-shot: it must not ask the LLM to choose a
    # tool (no bind_tools / tool loop), so it can't strand verification.
    src = inspect.getsource(ma)
    assert "bind_tools" not in src
