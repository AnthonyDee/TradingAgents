"""Regression tests for the market-analyst report propagation bug.

A thinking/reasoning provider can return a final assistant message that
carries report text *and* a recorded ``tool_calls`` entry. Previously the
analysts dropped the report whenever ``tool_calls`` was non-empty
(``if len(result.tool_calls) == 0: report = result.content``), leaving
``market_report`` empty so the Bull/Bear/research agents produced reports
without the market analyst's findings.
"""

import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.utils.agent_utils import (
    extract_text_content,
    has_text_content,
)
from tradingagents.graph.conditional_logic import ConditionalLogic


def _minimal_state(ticker="AAPL"):
    return {
        "messages": [],
        "company_of_interest": ticker,
        "asset_type": "stock",
        "instrument_context": "",
        "trade_date": "2026-08-31",
        "past_context": "",
    }


class ExtractTextContentTests(unittest.TestCase):
    def test_string_content_with_tool_call_is_kept(self):
        msg = AIMessage(
            content="The market is bullish over the medium term.",
            tool_calls=[{"name": "get_stock_data", "args": {}, "id": "x"}],
        )
        self.assertEqual(
            extract_text_content(msg),
            "The market is bullish over the medium term.",
        )
        self.assertTrue(has_text_content(msg))

    def test_list_of_text_blocks_is_concatenated(self):
        msg = AIMessage(
            content=[
                {"type": "text", "text": "First paragraph."},
                {"type": "text", "text": "Second paragraph."},
            ]
        )
        self.assertEqual(
            extract_text_content(msg),
            "First paragraph.\nSecond paragraph.",
        )

    def test_tool_blocks_without_text_are_empty(self):
        msg = AIMessage(
            content=[{"type": "tool_use", "id": "x", "name": "get_stock_data"}],
            tool_calls=[{"name": "get_stock_data", "args": {}, "id": "x"}],
        )
        self.assertEqual(extract_text_content(msg), "")
        self.assertFalse(has_text_content(msg))

    def test_empty_content_is_empty(self):
        msg = AIMessage(content="")
        self.assertEqual(extract_text_content(msg), "")
        self.assertFalse(has_text_content(msg))


class _StubLLM(Runnable):
    """A minimal Runnable stand-in for the analyst's LLM.

    ``create_market_analyst`` builds ``prompt | llm.bind_tools(tools)`` then
    calls ``chain.invoke(state["messages"])``. ``bind_tools`` must yield a real
    Runnable for the pipe operator, so it returns a ``RunnableLambda`` that
    ignores the incoming prompt and returns the canned reply.
    """

    def __init__(self, reply):
        self._reply = reply

    def bind_tools(self, tools):
        return RunnableLambda(lambda *_args, **_kwargs: self._reply)

    def invoke(self, *args, **kwargs):
        return self._reply


class MarketAnalystReportPropagationTests(unittest.TestCase):
    def test_report_kept_when_final_message_has_tool_call(self):
        # Mimic a thinking provider: report text AND a tool_call on the same
        # final message. This used to drop market_report.
        reply = AIMessage(
            content="Bullish medium-term trend with rising RSI.",
            tool_calls=[{"name": "get_indicators", "args": {}, "id": "t"}],
        )

        node = create_market_analyst(_StubLLM(reply))
        out = node(_minimal_state())

        self.assertTrue(out["market_report"].startswith("Bullish medium-term trend"), out)
        self.assertIn("RSI", out["market_report"])

    def test_pure_tool_call_leg_produces_empty_report(self):
        reply = AIMessage(
            content="",
            tool_calls=[{"name": "get_stock_data", "args": {}, "id": "t"}],
        )

        node = create_market_analyst(_StubLLM(reply))
        out = node(_minimal_state())
        self.assertEqual(out["market_report"], "")

    def test_report_not_overwritten_by_empty_round(self):
        # An empty tool round must not clobber an existing report.
        # This reproduces the intermittent drop where a later empty AIMessage
        # overwrote a good report because the node used last-write-wins.
        state = _minimal_state()
        state["market_report"] = "Existing detailed market analysis."
        reply = AIMessage(
            content="", tool_calls=[{"name": "get_stock_data", "args": {}, "id": "t"}]
        )
        node = create_market_analyst(_StubLLM(reply))
        out = node(state)
        self.assertEqual(out["market_report"], "Existing detailed market analysis.")


class ConditionalLogicStopTests(unittest.TestCase):
    def setUp(self):
        self.logic = ConditionalLogic()

    def test_market_terminates_when_text_present_even_with_tool_calls(self):
        state = _minimal_state()
        state["messages"] = [
            AIMessage(
                content="Report delivered.",
                tool_calls=[{"name": "get_stock_data", "args": {}, "id": "x"}],
            )
        ]
        self.assertEqual(
            self.logic.should_continue_market(state),
            "Msg Clear Market",
        )

    def test_market_keeps_tool_round_for_textless_tool_call(self):
        state = _minimal_state()
        state["messages"] = [
            AIMessage(
                content="",
                tool_calls=[{"name": "get_stock_data", "args": {}, "id": "x"}],
            )
        ]
        self.assertEqual(
            self.logic.should_continue_market(state),
            "tools_market",
        )

    def test_market_forces_clear_after_max_empty_rounds(self):
        # Three consecutive empty AIMessages should force clear to avoid infinite loop.
        state = _minimal_state()
        from langchain_core.messages import ToolMessage

        state["messages"] = [
            AIMessage(content=""),  # 1
            ToolMessage(content="{}", tool_call_id="1"),
            AIMessage(content=""),  # 2
            ToolMessage(content="{}", tool_call_id="2"),
            AIMessage(content=""),  # 3
        ]
        self.assertEqual(
            self.logic.should_continue_market(state),
            "Msg Clear Market",
        )

    def test_market_retries_when_empty_rounds_below_max(self):
        state = _minimal_state()
        from langchain_core.messages import ToolMessage

        state["messages"] = [
            AIMessage(content=""),  # 1
            ToolMessage(content="{}", tool_call_id="1"),
            AIMessage(content=""),  # 2
        ]
        self.assertEqual(
            self.logic.should_continue_market(state),
            "tools_market",
        )


if __name__ == "__main__":
    unittest.main()
