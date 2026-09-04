"""The final report must disclose when OHLCV data is a day prior to the current
date because the latest session was unsettled (see related degrade behavior in
test_ohlcv_latest_bar.py). The agent-facing tool text carries an explicit note so
the report tells the user the figures are from the previous settled session, not
today's.
"""
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.y_finance as y_finance


@pytest.mark.unit
class RecencyNoteUnitTests(unittest.TestCase):
    def _bulk_returning(self, unsettled, served, with_keys=True):
        data = {
            "2026-05-07": "12.3",
        }
        if with_keys:
            data["__latest_unsettled_date__"] = unsettled
            data["__served_latest_date__"] = served
        return data

    def test_note_emitted_when_latest_bar_unsettled(self):
        bulk = self._bulk_returning("2026-05-08", "2026-05-07")
        with mock.patch.object(
            y_finance, "_get_stock_stats_bulk", return_value=bulk
        ):
            out = y_finance.get_stock_stats_indicators_window(
                "HOOD", "rsi", "2026-05-08", 30
            )
        self.assertIn("2026-05-08 is not yet settled", out)
        self.assertIn("2026-05-07", out)
        self.assertIn("one trading day prior", out)
        # The unsettled date's own line is truthful, not "Not a trading day".
        self.assertIn("2026-05-08: N/A: bar not yet settled", out)

    def test_no_note_when_data_current(self):
        # No recency keys -> no disclosure appended.
        bulk = self._bulk_returning("2026-05-08", "2026-05-07", with_keys=False)
        with mock.patch.object(
            y_finance, "_get_stock_stats_bulk", return_value=bulk
        ):
            out = y_finance.get_stock_stats_indicators_window(
                "HOOD", "rsi", "2026-05-08", 30
            )
        self.assertNotIn("is not yet settled", out)
        self.assertNotIn("one trading day prior", out)


if __name__ == "__main__":
    unittest.main()
