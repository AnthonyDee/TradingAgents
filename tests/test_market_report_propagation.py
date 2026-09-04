"""Regression tests for the market-analyst report propagation.

The market analyst was migrated from an LLM tool-calling loop to the pre-fetch
pattern: it fetches the verified market snapshot and raw OHLCV deterministically
in code, tags them as prompt blocks, and invokes the LLM once to write prose.
This file guards the contract that:

- the fetched data is *confirmed* as ``sources_received`` (label -> status),
  so the next stage can audit that data was captured and passed on;
- the report is the LLM's prose (plus the confirmation line), never a raw data
  dump as-is;
- empty/failed fetches degrade to ``empty``/``error`` statuses rather than
  aborting or leaking raw output into the report.
"""

import contextlib
import unittest
from unittest import mock

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_verified_market_snapshot,
)


def _minimal_state(ticker="AAPL"):
    return {
        "messages": [],
        "company_of_interest": ticker,
        "asset_type": "stock",
        "instrument_context": "",
        "trade_date": "2026-08-31",
        "past_context": "",
    }


class _StubLLM(Runnable):
    """A stub LLM whose ``invoke`` returns a canned AIMessage.

    ``create_market_analyst`` builds ``prompt | llm`` and calls
    ``chain.invoke(messages)``; the stub's ``invoke`` is reached through the
    runnable pipe and returns the canned reply. ``texts`` (when given) cycles
    through canned replies to simulate a retry that eventually succeeds.
    """

    def __init__(self, reply=None, texts=()):
        self._reply = reply
        self._texts = list(texts)
        self._index = 0

    def invoke(self, *args, **kwargs):
        if self._texts:
            text = self._texts[self._index % len(self._texts)]
            self._index += 1
            return AIMessage(content=text)
        return self._reply


@contextlib.contextmanager
def _patch_fetchers(snapshot_out="snapshot table", ohlcv_out="ohlcv csv"):
    """Patch the two data fetchers the market analyst pre-fetches in code.

    Yields (snapshot_mock, ohlcv_mock) so tests can assert they were called.
    """
    with mock.patch.object(
        get_verified_market_snapshot, "func", return_value=snapshot_out
    ) as snap_mock, mock.patch.object(
        get_stock_data, "func", return_value=ohlcv_out
    ) as ohlcv_mock:
        yield snap_mock, ohlcv_mock


class MarketAnalystReportPropagationTests(unittest.TestCase):
    def test_report_kept_when_model_writes_prose(self):
        with _patch_fetchers() as (snap_patch, ohlcv_patch):
            node = create_market_analyst(_StubLLM(AIMessage(content="Bullish medium-term trend with rising RSI.")))
            out = node(_minimal_state())

        self.assertTrue(out["market_report"].startswith("Bullish medium-term trend"), out)
        self.assertIn("RSI", out["market_report"])
        # Both fetchers were actually invoked (data was captured).
        snap_patch.assert_called()
        ohlcv_patch.assert_called()

    def test_sources_received_confirms_captured_sources(self):
        with _patch_fetchers() as (_snap, _ohlcv):
            node = create_market_analyst(_StubLLM(AIMessage(content="Analysis.")))
            out = node(_minimal_state())

        confirmations = out["sources_received"]["market"]
        self.assertEqual(confirmations["market_snapshot"], "ok")
        self.assertEqual(confirmations["ohlcv"], "ok")
        self.assertIn("market_snapshot=ok", out["market_report"])

    def test_verified_snapshot_is_prefetched_not_emitted_raw(self):
        # The verified snapshot table must not itself be returned verbatim as
        # the report — the report is the LLM's prose plus the confirmation line.
        with _patch_fetchers(snapshot_out="| Close | 761.78 |", ohlcv_out="Date,Close") as _:
            node = create_market_analyst(_StubLLM(AIMessage(content="The pullback is approaching support.")))
            out = node(_minimal_state())

        self.assertIn("support", out["market_report"])
        self.assertNotEqual(out["market_report"], "| Close | 761.78 |")
        self.assertNotIn("| Close | 761.78 |", out["market_report"])

    def test_empty_fetch_reports_empty_status_not_crash(self):
        with _patch_fetchers(snapshot_out="", ohlcv_out="NO_DATA_AVAILABLE"):
            node = create_market_analyst(_StubLLM(AIMessage(content="No live data, so defer.")))
            out = node(_minimal_state())

        confirmations = out["sources_received"]["market"]
        self.assertEqual(confirmations["market_snapshot"], "empty")
        self.assertEqual(confirmations["ohlcv"], "unavailable")
        self.assertIn("No live data", out["market_report"])

    def test_empty_model_prose_degrades_to_confirmation_line_not_raw(self):
        # If the model never writes prose (after bounded retries), the report
        # must not leak raw fetched data — it degrades to the confirmation line.
        with _patch_fetchers(snapshot_out="| Close | 761.78 |", ohlcv_out="raw ohlcv"):
            node = create_market_analyst(_StubLLM(AIMessage(content="")))
            out = node(_minimal_state())

        self.assertIn("> Data sources received:", out["market_report"])
        self.assertNotIn("| Close |", out["market_report"])
        self.assertNotIn("raw ohlcv", out["market_report"])

    def test_bounded_retry_coaxes_text_then_uses_it(self):
        # First invocation empty, retry (with reminder) returns prose.
        node = create_market_analyst(
            _StubLLM(texts=("", "Momentum has shifted after retrying."))
        )
        with _patch_fetchers():
            out = node(_minimal_state())
        self.assertIn("Momentum has shifted", out["market_report"])


if __name__ == "__main__":
    unittest.main()
