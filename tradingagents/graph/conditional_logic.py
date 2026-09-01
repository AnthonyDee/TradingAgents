# TradingAgents/graph/conditional_logic.py

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import has_text_content


def _trailing_empty_rounds(messages) -> int:
    """Count consecutive trailing assistant messages that carry no text.

    An analyst's tool loop alternates ``AIMessage -> ToolMessage``, so a run of
    trailing empty ``AIMessage`` entries corresponds to this analyst's empty
    reply rounds. The count stops at the first non-empty message (earlier
    analyst prose or a tool result), which keeps the count scoped to the active
    analyst rather than the whole shared message channel.
    """
    count = 0
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            if not has_text_content(message):
                count += 1
                continue
            # non-empty assistant message -> stop counting
            break
        # skip non-AIMessage entries (e.g. ToolMessage) and keep scanning
        continue
    return count


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        max_side_retries=3,
    ):
        """Initialize with configuration parameters.

        ``max_side_retries`` bounds how many extra bull/bear turns are allowed
        after a side returns empty text, before the debate is forced to the
        Research Manager so it never runs off the recursion limit.
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_side_retries = max_side_retries

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue.

        The analyst completes only once it has produced text. An empty reply
        (a stalled model or a tool-only round with no prose) is retried, bounded
        by ``max_side_retries`` so a model that never writes a report can't loop
        forever. Without this, an empty final message would clear the analyst
        and silently drop its report from the final report (#1094).
        """
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message):
            return "Msg Clear Market"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear Market"
        return "tools_market"

    def should_continue_social(self, state: AgentState):
        """Determine if sentiment-analyst tool round should continue.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message):
            return "Msg Clear Sentiment"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear Sentiment"
        return "tools_social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message):
            return "Msg Clear News"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear News"
        return "tools_news"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message):
            return "Msg Clear Fundamentals"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear Fundamentals"
        return "tools_fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue.

        The Research Manager only completes once BOTH the bull and bear have
        produced substantive arguments. A side whose message came back empty is
        retried (bounded by ``max_side_retries``), so the judge never settles on
        "no debate evidence". After the retry budget is exhausted the debate is
        forced to the Research Manager, which renders an explicit note when it
        has no evidence to weight.
        """
        debate = state["investment_debate_state"]
        count = debate["count"]
        current = debate.get("current_response", "")

        budget = 2 * self.max_debate_rounds + self.max_side_retries
        if count >= budget:
            return "Research Manager"

        bull_empty = not (debate.get("bull_history") or "").strip()
        bear_empty = not (debate.get("bear_history") or "").strip()

        if count >= 2 * self.max_debate_rounds and not bull_empty and not bear_empty:
            return "Research Manager"

        # Keep debating / retrying until each side has produced content.
        if current.startswith("Bull"):
            if bear_empty:
                return "Bear Researcher"
            return "Bull Researcher"

        if bear_empty and not bull_empty:
            return "Bear Researcher"

        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
