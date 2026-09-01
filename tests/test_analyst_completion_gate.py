"""Unit tests for the pre-research analyst completion gate.

The research team (Bull/Bear/Research Manager) must not start until each
selected analyst has produced a non-empty report. Each analyst is followed by
a gate that re-runs the analyst when it cleared with an empty report and
advances only once the report is present (or the re-run budget is exhausted,
to avoid an endless loop).
"""

import unittest

from tradingagents.graph.conditional_logic import (
    bump_analyst_rerun,
    resolve_analyst_gate,
)
from tradingagents.graph.setup import (
    _gate_path_map,
    _make_analyst_gate_node,
    _make_analyst_gate_router,
)


class ResolveAnalystGateTests(unittest.TestCase):
    def _state(self, **kwargs):
        base = {
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "analyst_reruns": {},
        }
        base.update(kwargs)
        return base

    def test_advances_to_next_analyst_when_report_present(self):
        state = self._state(market_report="full market analysis")
        self.assertEqual(
            resolve_analyst_gate(
                state,
                report_key="market_report",
                agent_key="market",
                agent_node="Market Analyst",
                next_node="News Analyst",
                research_entry="Bull Researcher",
                is_last=False,
                max_reruns=3,
            ),
            "News Analyst",
        )

    def test_enters_research_when_last_analyst_has_report(self):
        state = self._state(news_report="full news analysis")
        self.assertEqual(
            resolve_analyst_gate(
                state,
                report_key="news_report",
                agent_key="news",
                agent_node="News Analyst",
                next_node=None,
                research_entry="Bear Researcher",
                is_last=True,
                max_reruns=3,
            ),
            "Bear Researcher",
        )

    def test_reruns_analyst_when_report_empty_within_budget(self):
        state = self._state(analyst_reruns={"market": 1})
        self.assertEqual(
            resolve_analyst_gate(
                state,
                report_key="market_report",
                agent_key="market",
                agent_node="Market Analyst",
                next_node="News Analyst",
                research_entry="Bull Researcher",
                is_last=False,
                max_reruns=3,
            ),
            "Market Analyst",
        )

    def test_force_continues_when_rerun_budget_exhausted(self):
        # reruns > max: give up and advance rather than loop forever.
        state = self._state(analyst_reruns={"market": 4})
        self.assertEqual(
            resolve_analyst_gate(
                state,
                report_key="market_report",
                agent_key="market",
                agent_node="Market Analyst",
                next_node="News Analyst",
                research_entry="Bull Researcher",
                is_last=False,
                max_reruns=3,
            ),
            "News Analyst",
        )

    def test_is_last_force_continues_into_research(self):
        state = self._state(analyst_reruns={"news": 5})
        self.assertEqual(
            resolve_analyst_gate(
                state,
                report_key="news_report",
                agent_key="news",
                agent_node="News Analyst",
                next_node=None,
                research_entry="Research Manager",
                is_last=True,
                max_reruns=3,
            ),
            "Research Manager",
        )


class BumpAnalystRerunTests(unittest.TestCase):
    def test_increments_only_when_report_empty(self):
        self.assertEqual(
            bump_analyst_rerun(
                {"market_report": "", "analyst_reruns": {}},
                agent_key="market",
                report_key="market_report",
            ),
            {"market": 1},
        )

    def test_no_increment_when_report_present(self):
        self.assertEqual(
            bump_analyst_rerun(
                {"market_report": "done", "analyst_reruns": {}},
                agent_key="market",
                report_key="market_report",
            ),
            {},
        )

    def test_accumulates_across_reruns(self):
        state = {"market_report": "", "analyst_reruns": {"market": 2}}
        bumped = bump_analyst_rerun(
            state, agent_key="market", report_key="market_report"
        )
        self.assertEqual(bumped, {"market": 3})


class AnalystGateEdgeBuildTests(unittest.TestCase):
    """The gate node + router routing behaves like setup.py's wiring."""

    def test_gate_path_map_is_compact_for_last_analyst(self):
        pm = _gate_path_map("Market Analyst", "News Analyst", "Bull Researcher")
        self.assertEqual(pm, {
            "Market Analyst": "Market Analyst",
            "News Analyst": "News Analyst",
            "Bull Researcher": "Bull Researcher",
        })

        pm_last = _gate_path_map("News Analyst", None, "Research Manager")
        self.assertEqual(pm_last, {
            "News Analyst": "News Analyst",
            "Research Manager": "Research Manager",
        })

    def test_gate_node_counts_reruns_and_router_reruns_within_budget(self):
        # Standalone check of the node->router handoff: the gate node bumps the
        # counter for an empty report; the router then re-runs the analyst
        # while within budget and force-continues once exhausted.
        spec = type("Spec", (), {"key": "market", "report_key": "market_report"})()
        gate_node = _make_analyst_gate_node(spec)
        router = _make_analyst_gate_router(
            report_key="market_report",
            agent_key="market",
            agent_node="Market Analyst",
            next_node="News Analyst",
            research_entry="Bull Researcher",
            is_last=False,
            max_reruns=3,
        )

        state = {"market_report": "", "analyst_reruns": {}}
        state.update(gate_node(state))  # empty report -> bump to 1
        self.assertEqual(state["analyst_reruns"], {"market": 1})
        self.assertEqual(router(state), "Market Analyst")  # within budget

        # Three more empty clears -> counter hits 4 (> 3) -> advance.
        for _ in range(3):
            state.update(gate_node(state))
        self.assertEqual(state["analyst_reruns"], {"market": 4})
        self.assertEqual(router(state), "News Analyst")  # exhausted

    def test_gate_node_does_not_count_when_report_present(self):
        spec = type("Spec", (), {"key": "market", "report_key": "market_report"})()
        gate_node = _make_analyst_gate_node(spec)
        state = {"market_report": "done", "analyst_reruns": {}}
        self.assertEqual(gate_node(state), {"analyst_reruns": {}})


class FullGraphWiringTests(unittest.TestCase):
    """The setup.py graph compiles with the gate edges for every analyst
    selection (validates that every edge/path-map target is a registered node)."""

    def _stub_factories(self):
        import tradingagents.graph.setup as setup

        def _node(_llm, *args, **kwargs):
            def _noop(state):
                return {}

            return _noop

        def _msg_delete():
            def _clear(state):
                return {"messages": []}

            return _clear

        patches = {}
        for name in [
            "create_market_analyst",
            "create_sentiment_analyst",
            "create_news_analyst",
            "create_fundamentals_analyst",
            "create_bull_researcher",
            "create_bear_researcher",
            "create_research_manager",
            "create_trader",
            "create_portfolio_manager",
            "create_aggressive_debator",
            "create_conservative_debator",
            "create_neutral_debator",
        ]:
            patches[name] = getattr(setup, name)
            setattr(setup, name, _node)

        patches["create_msg_delete"] = _msg_delete
        # create_msg_delete is used via the module-level import binding:
        setup.create_msg_delete = _msg_delete
        return patches

    def _restore(self, patches):
        import tradingagents.graph.setup as setup

        for name, original in patches.items():
            setattr(setup, name, original)

    def _compile_for(self, analysts):
        from langgraph.graph import StateGraph

        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.setup import GraphSetup

        patches = self._stub_factories()
        try:
            llm = object()  # only passed through to factories, already stubbed
            def _noop(state):
                return {}

            tool_nodes = {
                "market": _noop,
                "social": _noop,
                "news": _noop,
                "fundamentals": _noop,
            }
            logic = ConditionalLogic()
            gs = GraphSetup(llm, llm, tool_nodes, logic)
            workflow = gs.setup_graph(analysts)
            self.assertIsInstance(workflow, StateGraph)
            graph = workflow.compile()
            return graph.get_graph().nodes
        finally:
            self._restore(patches)

    def test_full_graph_compiles_with_all_analysts(self):
        nodes = self._compile_for(("market", "social", "news", "fundamentals"))
        for a in ("Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst"):
            self.assertIn(a, nodes)
            self.assertIn(f"Analyst Gate {a}", nodes)
        self.assertIn("Bull Researcher", nodes)
        self.assertIn("Bear Researcher", nodes)

    def test_full_graph_compiles_with_subset(self):
        nodes = self._compile_for(("market", "news"))
        self.assertIn("Market Analyst", nodes)
        self.assertIn("News Analyst", nodes)
        self.assertIn("Analyst Gate Market Analyst", nodes)
        self.assertIn("Analyst Gate News Analyst", nodes)
        # Unselected analysts' gates must not be registered.
        self.assertNotIn("Analyst Gate Sentiment Analyst", nodes)

    def test_last_analyst_gate_routes_to_research(self):
        nodes = self._compile_for(("news",))
        self.assertIn("Analyst Gate News Analyst", nodes)
        self.assertIn("Bull Researcher", nodes)


if __name__ == "__main__":
    unittest.main()
