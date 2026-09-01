# TradingAgents/graph/setup.py

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_msg_delete,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from tradingagents.agents.utils.agent_states import AgentState

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
RISK_ANALYSIS_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        realtime_quote_tools: list | None = None,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        # Read-only realtime market-data tools (e.g. Robinhood quotes) injected
        # into the tool-calling analysts so they can cite live prices.
        self.realtime_quote_tools = realtime_quote_tools or []

    def setup_graph(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        selected_researchers: list | None = None,
        selected_risk: list | None = None,
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
            selected_researchers: List of ResearcherType to include, e.g. ["bull"] or ["bull","bear"].
                Defaults to ("bull", "bear") when None.
            selected_risk: List of RiskAnalystType to include, e.g. ["aggressive","conservative","neutral"].
                Defaults to all three when None.
        """
        plan = build_analyst_execution_plan(selected_analysts)

        analyst_factories = {
            "market": lambda: create_market_analyst(
                self.quick_thinking_llm, mcp_tools=self.realtime_quote_tools
            ),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(
                self.quick_thinking_llm, mcp_tools=self.realtime_quote_tools
            ),
            "fundamentals": lambda: create_fundamentals_analyst(
                self.quick_thinking_llm, mcp_tools=self.realtime_quote_tools
            ),
        }

        # ---- Researcher nodes ----
        # Determine which researchers are enabled; default both when None
        if selected_researchers is None:
            selected_researchers = ["bull", "bear"]
        enabled_researchers = set(selected_researchers)

        if "bull" in enabled_researchers:
            bull_researcher_node = create_bull_researcher(self.deep_thinking_llm)
        else:
            bull_researcher_node = None

        if "bear" in enabled_researchers:
            bear_researcher_node = create_bear_researcher(self.deep_thinking_llm)
        else:
            bear_researcher_node = None

        # ---- Risk debator nodes ----
        if selected_risk is None:
            selected_risk = ["aggressive", "conservative", "neutral"]
        enabled_risk = set(selected_risk)

        aggressive_analyst = (
            create_aggressive_debator(self.quick_thinking_llm)
            if "aggressive" in enabled_risk
            else None
        )
        neutral_analyst = (
            create_neutral_debator(self.quick_thinking_llm)
            if "neutral" in enabled_risk
            else None
        )
        conservative_analyst = (
            create_conservative_debator(self.quick_thinking_llm)
            if "conservative" in enabled_risk
            else None
        )

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for spec in plan.specs:
            workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
            workflow.add_node(spec.clear_node, create_msg_delete())
            workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # Add researcher nodes conditionally (only add if enabled)
        if bull_researcher_node is not None:
            workflow.add_node("Bull Researcher", bull_researcher_node)
        if bear_researcher_node is not None:
            workflow.add_node("Bear Researcher", bear_researcher_node)

        # Add risk debator nodes conditionally
        if aggressive_analyst is not None:
            workflow.add_node("Aggressive Analyst", aggressive_analyst)
        if conservative_analyst is not None:
            workflow.add_node("Conservative Analyst", conservative_analyst)
        if neutral_analyst is not None:
            workflow.add_node("Neutral Analyst", neutral_analyst)

        # Add other always-on nodes
        workflow.add_node("Research Manager", create_research_manager(self.deep_thinking_llm))
        workflow.add_node("Trader", create_trader(self.quick_thinking_llm))
        workflow.add_node("Portfolio Manager", create_portfolio_manager(self.deep_thinking_llm))

        # ---- Define edges ----

        # Start with the first analyst
        workflow.add_edge(START, plan.specs[0].agent_node)

        # Connect analysts in sequence
        for i, spec in enumerate(plan.specs):
            current_analyst = spec.agent_node
            current_tools = spec.tool_node
            current_clear = spec.clear_node

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to the research team junction
            if i < len(plan.specs) - 1:
                workflow.add_edge(current_clear, plan.specs[i + 1].agent_node)
            else:
                # Last analyst's clear node → junction to research team
                # If bull enabled → Bull Researcher; else if bear enabled → Bear Researcher;
                # else (no researcher enabled) → skip debate → Research Manager directly.
                if "bull" in enabled_researchers:
                    workflow.add_edge(current_clear, "Bull Researcher")
                elif "bear" in enabled_researchers:
                    workflow.add_edge(current_clear, "Bear Researcher")
                else:
                    # No researcher enabled → route straight to Research Manager
                    workflow.add_edge(current_clear, "Research Manager")

        # ---- Debate routing: Bull / Bear researchers ----
        # Build path maps that include only the enabled researchers + the terminal.
        if "bull" in enabled_researchers and "bear" in enabled_researchers:
            # Both enabled: full two-agent debate path map
            debate_path_map = {
                "Bull Researcher": "Bull Researcher",
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            }
        elif "bull" in enabled_researchers:
            # Only Bull: after Bull, always route to Research Manager
            debate_path_map = {
                "Bull Researcher": "Research Manager",
                "Research Manager": "Research Manager",
            }
        elif "bear" in enabled_researchers:
            # Only Bear: entry routes to Bear; after Bear → Research Manager
            debate_path_map = {
                "Bear Researcher": "Research Manager",
                "Research Manager": "Research Manager",
            }
        else:
            # No researcher enabled → should not reach here (entry goes to Research Manager already)
            debate_path_map = {
                "Research Manager": "Research Manager",
            }

        # Both research-debate edges share the per-configuration path map (#1088).
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            if debate_node in workflow.nodes:
                workflow.add_conditional_edges(
                    debate_node,
                    self.conditional_logic.should_continue_debate,
                    debate_path_map,
                )

        # ---- Research Manager → Trader → Risk → PM ----
        workflow.add_edge("Research Manager", "Trader")

        # ---- Risk debator edges ----
        # Build a path map over the enabled risk debators only, keyed by the
        # title-case node names the router returns and mapped to the next
        # enabled debator in cycle order (or the Portfolio Manager). Only the
        # enabled debator nodes exist in the graph, so the map must reference
        # nothing else — LangGraph validates every target eagerly (#1088).
        risk_node_names = {
            "aggressive": "Aggressive Analyst",
            "conservative": "Conservative Analyst",
            "neutral": "Neutral Analyst",
        }
        risk_path_map: dict[str, str] = {}
        for key in ("aggressive", "conservative", "neutral"):
            if key not in enabled_risk:
                continue
            # Next enabled debator in circular order
            nxt = None
            for i in range(1, 4):
                nxt_key = ("aggressive", "conservative", "neutral")[
                    (("aggressive", "conservative", "neutral").index(key) + i) % 3
                ]
                if nxt_key in enabled_risk:
                    nxt = risk_node_names[nxt_key]
                    break
            risk_path_map[risk_node_names[key]] = nxt or "Portfolio Manager"
        # The router's terminal return always maps to the (always-present) PM.
        risk_path_map["Portfolio Manager"] = "Portfolio Manager"

        # Add conditional edges for each enabled risk debator
        for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            if risk_node in workflow.nodes:
                workflow.add_conditional_edges(
                    risk_node,
                    self.conditional_logic.should_continue_risk_analysis,
                    risk_path_map,
                )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
