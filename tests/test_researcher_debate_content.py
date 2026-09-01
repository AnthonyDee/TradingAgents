"""Regression tests for robust survey content in the research-debate chain.

The Bull and Bear researchers build their stored argument from the LLM's
``response.content`` via ``f"Bull Analyst: {extract_text_content(response)}"``.
Before the fix they read ``response.content`` directly, which could be an empty
string or a list of content blocks (Anthropic-style), yielding a hollow
``"Bull Analyst: "`` stub. The Research Manager would then "complete" with no
bull or bear case to weight, and the Trader / Portfolio Manager reports would
follow on that empty foundation.
"""

import unittest

from langchain_core.messages import AIMessage

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.utils.structured import invoke_structured_or_freetext


def _debate_state(bull=""):
    return {
        "investment_debate_state": {
            "history": "",
            "bull_history": bull,
            "bear_history": "",
            "current_response": "",
            "count": 0,
        },
        "market_report": "MKT",
        "sentiment_report": "SENT",
        "news_report": "NEWS",
        "fundamentals_report": "FUND",
        "asset_type": "stock",
        "instrument_context": "",
        "company_of_interest": "AAPL",
    }


class _StubLLM:
    def __init__(self, message):
        self._message = message

    def invoke(self, prompt):
        return self._message


class BullResearcherContentTests(unittest.TestCase):
    def test_string_content_is_recorded(self):
        node = create_bull_researcher(_StubLLM(AIMessage(content="Strong growth.")))
        out = node(_debate_state())
        self.assertIn("Strong growth.", out["investment_debate_state"]["bull_history"])
        self.assertTrue(
            out["investment_debate_state"]["bull_history"].strip().startswith("Bull Analyst: ")
        )

    def test_list_of_content_blocks_is_flattened(self):
        node = create_bull_researcher(
            _StubLLM(
                AIMessage(
                    content=[
                        {"type": "text", "text": "Strong growth."},
                        {"type": "text", "text": "Wide moat."},
                    ]
                )
            )
        )
        out = node(_debate_state())
        history = out["investment_debate_state"]["bull_history"]
        self.assertIn("Strong growth.", history)
        self.assertIn("Wide moat.", history)
        # A stringified list would contain the literal "[{'" marker.
        self.assertNotIn("{'type'", history)

    def test_empty_content_leaves_history_blank_for_retry(self):
        node = create_bull_researcher(_StubLLM(AIMessage(content="")))
        out = node(_debate_state())
        # An empty reply is not recorded as a hollow "Bull Analyst: " stub, so
        # the debate router can detect the side produced nothing and retry it.
        self.assertEqual(out["investment_debate_state"]["bull_history"].strip(), "")
        self.assertEqual(out["investment_debate_state"]["current_response"], "")


class BearResearcherContentTests(unittest.TestCase):
    def test_string_content_is_recorded(self):
        node = create_bear_researcher(_StubLLM(AIMessage(content="Risky exposure.")))
        out = node(_debate_state())
        self.assertIn("Risky exposure.", out["investment_debate_state"]["bear_history"])
        self.assertTrue(
            out["investment_debate_state"]["bear_history"].strip().startswith("Bear Analyst: ")
        )

    def test_list_of_content_blocks_is_flattened(self):
        node = create_bear_researcher(
            _StubLLM(
                AIMessage(
                    content=[
                        {"type": "text", "text": "Risky exposure."},
                        {"type": "text", "text": "Weak margins."},
                    ]
                )
            )
        )
        out = node(_debate_state())
        history = out["investment_debate_state"]["bear_history"]
        self.assertIn("Risky exposure.", history)
        self.assertIn("Weak margins.", history)
        self.assertNotIn("{'type'", history)


class StructuredFreeTextFallbackTests(unittest.TestCase):
    def test_flattens_list_content_in_free_text_fallback(self):
        class PlainLLM:
            def __init__(self, message):
                self._message = message

            def invoke(self, prompt):
                return self._message

        plain = PlainLLM(
            AIMessage(
                content=[{"type": "text", "text": "Hold."}, {"type": "text", "text": "Reassess."}]
            )
        )
        out = invoke_structured_or_freetext(None, plain, "prompt", None, "Trader")
        self.assertIn("Hold.", out)
        self.assertIn("Reassess.", out)
        self.assertNotIn("{'type'", out)


if __name__ == "__main__":
    unittest.main()
