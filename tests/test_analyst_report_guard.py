"""The analyst nodes must only hand a *prose analysis* (plus the auditable
sources confirmation) to the next stage — never a verbatim dump of raw tool
output. With the pre-fetch pattern, the guarantee is enforced structurally:

- data is fetched deterministically in code and classified into tagged blocks;
- ``fetch_sources`` returns a status (ok / empty / unavailable / error) so a
  downstream consumer can see exactly what was captured;
- raw/unavailable/empty fetches degrade to a status instead of aborting or
  surfacing vendor sentinel text as if it were real data.

Regression guard: replaces the old heuristic rescue helpers (``_is_tool_output_only``
/ ``rescue_tool_output``) that were removed with the tool-loop migration.
"""

import unittest

from tradingagents.agents.utils.prefetch import (
    UNAVAILABLE_MARKERS,
    DataSource,
    fetch_sources,
    format_sources_received,
    render_tagged_blocks,
)


class FetchSourcesClassificationTests(unittest.TestCase):
    def test_ok_status_and_block(self):
        blocks, statuses = fetch_sources([DataSource("news", lambda: "headlines")])
        self.assertEqual(statuses["news"], "ok")
        self.assertEqual(blocks["news"], "headlines")

    def test_empty_and_error_and_unavailable(self):
        def boom():
            raise RuntimeError("vendor down")

        blocks, statuses = fetch_sources([
            DataSource("empty_src", lambda: "   "),
            DataSource("error_src", boom),
            DataSource("unavail_src", lambda: "DATA_UNAVAILABLE for cpi"),
        ])
        self.assertEqual(statuses["empty_src"], "empty")
        self.assertEqual(statuses["error_src"], "error")
        self.assertEqual(statuses["unavail_src"], "unavailable")
        # Never surface raw/unavailable text as a usable block.
        self.assertEqual(blocks, {})

    def test_single_fetch_drives_both_no_double_call(self):
        calls = []
        src = DataSource("news", lambda: (calls.append(1), "data")[1])
        fetch_sources([src])
        self.assertEqual(len(calls), 1)

    def test_sentinel_is_not_passed_through(self):
        # A vendor sentinel must never be mistaken for a real value.
        for marker in UNAVAILABLE_MARKERS:
            blocks, statuses = fetch_sources([DataSource("s", lambda m=marker: f"{m} something")])
            self.assertEqual(statuses["s"], "unavailable", marker)
            self.assertNotIn("s", blocks)


class RenderHelpersTests(unittest.TestCase):
    def test_tagged_blocks_wrap_each_source(self):
        rendered = render_tagged_blocks({"news": "headline", "snap": "table"})
        self.assertIn("<start_of_news>\nheadline\n<end_of_news>", rendered)
        self.assertIn("<start_of_snap>\ntable\n<end_of_snap>", rendered)

    def test_sources_received_line(self):
        self.assertEqual(
            format_sources_received({"news": "ok", "macro": "empty"}),
            "> Data sources received: news=ok, macro=empty",
        )
        self.assertEqual(
            format_sources_received({}),
            "> Data sources received: none",
        )


if __name__ == "__main__":
    unittest.main()
