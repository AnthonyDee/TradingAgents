"""The analyst nodes must only write a *prose analysis* as their report — never
a verbatim dump of the raw tool output (e.g. the verified market snapshot
tables). A raw table dump must not be allowed to satisfy the completion gate as
a "finished report" (that would end the analyst without any analysis).

Regression guard for market analyst returning raw snapshot tables as its
report instead of interpreting the data.
"""

import unittest

from langchain_core.messages import ToolMessage

from tradingagents.agents.utils.agent_utils import (
    _is_tool_output_only,
    rescue_tool_output,
)


class ToolOutputOnlyDetectionTests(unittest.TestCase):
    def test_table_only_output_is_a_dump(self):
        dump = (
            "| Field | Value |\n"
            "|---|---:|\n"
            "| Close | 761.78 |\n"
            "| RSI | 48.62 |\n"
        )
        self.assertTrue(_is_tool_output_only(dump))

    def test_verified_snapshot_verbatim_is_a_dump(self):
        snapshot = (
            "## Verified market data snapshot for SPY\n\n"
            "### Latest verified OHLCV row\n\n"
            "| Field | Value |\n|---|---:|\n| Close | 761.78 |\n\n"
            "### Verified technical indicators (latest row)\n\n"
            "| Indicator | Value |\n|---|---:|\n| rsi | 48.62 |\n\n"
            "### Recent verified closes (last 30 rows)\n\n"
            "| Date | Close |\n|---|---:|\n| 2026-09-01 | 761.78 |\n\n"
            "Use this snapshot as the source of truth for exact OHLCV, "
            "price-level, and indicator-value claims. If another tool output "
            "conflicts with it, flag the discrepancy rather than inventing a "
            "reconciled number."
        )
        # Even though the snapshot carries a prose disclaimers footer, echoing it
        # verbatim as the report is a data dump, not analysis.
        self.assertTrue(_is_tool_output_only(snapshot))

    def test_snapshot_header_with_real_analysis_is_not_a_dump(self):
        mixed = (
            "## Verified market data snapshot for SPY\n"
            "SPY closed at 761.78, below the 10-day EMA, suggesting near-term "
            "weakness. RSI at 48.62 is neutral and the MACD histogram turning "
            "negative signals fading momentum. The pullback is approaching the "
            "lower Bollinger band near support."
        )
        self.assertFalse(_is_tool_output_only(mixed))

    def test_analysis_with_summary_table_is_not_a_dump(self):
        analysis = (
            "SPY pulled back from 777.88 to close at 761.78 on 09-01, settling "
            "below the 10-day EMA as momentum faded.\n\n"
            "| Metric | Value |\n|---|---:|\n| Close | 761.78 |\n"
            "| RSI | 48.62 |\n"
        )
        self.assertFalse(_is_tool_output_only(analysis))

    def test_empty_is_not_a_dump(self):
        self.assertFalse(_is_tool_output_only(""))


class RescueToolOutputTests(unittest.TestCase):
    def _tool_msg(self, name, content):
        return ToolMessage(content=content, name=name, tool_call_id="1")

    def test_returns_newest_data_tool_output(self):
        msgs = [
            self._tool_msg("get_stock_data", "raw stock csv"),
            self._tool_msg(
                "get_verified_market_snapshot",
                "## Verified market data snapshot for SPY\n...tables...",
            ),
        ]
        self.assertEqual(
            rescue_tool_output(msgs), "## Verified market data snapshot for SPY\n...tables..."
        )

    def test_skips_error_and_unavailable_sentinels(self):
        msgs = [
            self._tool_msg("get_stock_data", "raw stock csv 2"),
            self._tool_msg("get_realtime_quote", "[realtime quote unavailable] MCP error"),
            self._tool_msg("get_stock_data", "NO_DATA_AVAILABLE"),
        ]
        # The newer-but-usable data tool output wins; error/empty sentinels skipped.
        self.assertEqual(rescue_tool_output(msgs), "raw stock csv 2")

    def test_ignores_non_data_tools_and_empty_history(self):
        self.assertEqual(rescue_tool_output([]), "")
        msgs = [self._tool_msg("get_news", "some headlines")]
        self.assertEqual(rescue_tool_output(msgs), "")


if __name__ == "__main__":
    unittest.main()
