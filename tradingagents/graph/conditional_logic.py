# TradingAgents/graph/conditional_logic.py

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import has_text_content, has_tool_calls


def resolve_analyst_gate(
    state,
    *,
    report_key: str,
    agent_key: str,
    agent_node: str,
    next_node: str | None,
    research_entry: str,
    is_last: bool,
    max_reruns: int,
) -> str:
    """Decide where a single analyst's completion gate sends control next.

    Each analyst is followed by its own gate node. The gate only lets the
    workflow advance toward the research team once this analyst has produced a
    non-empty report; because analysts run serially, reaching the last gate
    with a report guarantees every selected analyst finished.

    Returns:
    - ``agent_node`` to re-run this analyst if it cleared with an empty report
      and has not yet exhausted its re-run budget;
    - ``research_entry`` (when ``is_last``) or ``next_node`` (otherwise)
      when the report is present or the re-run budget is exhausted
      (force-continue, so a never-productive model can't loop forever).
    """
    report_present = bool((state.get(report_key) or "").strip())
    if report_present:
        return research_entry if is_last else next_node

    reruns = state.get("analyst_reruns", {}) or {}
    if reruns.get(agent_key, 0) > max_reruns:
        # Exhausted re-run budget: force-continue rather than loop forever.
        return research_entry if is_last else next_node

    return agent_node


def bump_analyst_rerun(state, *, agent_key: str, report_key: str) -> dict[str, int]:
    """Increment an analyst's re-run counter when it cleared with no report.

    Called from the gate node before the router decides, so the router can
    bound how many times a report-less analyst is re-run.
    """
    if (state.get(report_key) or "").strip():
        return state.get("analyst_reruns", {}) or {}
    reruns = dict(state.get("analyst_reruns", {}) or {})
    reruns[agent_key] = reruns.get(agent_key, 0) + 1
    return reruns


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
        selected_researchers: list | None = None,
        selected_risk: list | None = None,
    ):
        """Initialize with configuration parameters.

        ``max_side_retries`` bounds how many extra bull/bear turns are allowed
        after a side returns empty text, before the debate is forced to the
        Research Manager so it never runs off the recursion limit.
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_side_retries = max_side_retries
        # Store enabled sets; default to full sets when None
        self.selected_researchers = selected_researchers or ["bull", "bear"]
        self.selected_risk = selected_risk or ["aggressive", "conservative", "neutral"]

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue.

        The analyst completes only once it has produced text *without* pending
        tool calls.  When the model returns both text and tool calls in the
        same turn, the tools must still be executed before the analyst can be
        considered done — otherwise the tool loop would be skipped entirely,
        leaving the analyst with no data to analyse.

        An empty reply (a stalled model or a tool-only round with no prose) is
        retried, bounded by ``max_side_retries`` so a model that never writes
        a report can't loop forever.  Without this, an empty final message
        would clear the analyst and silently drop its report from the final
        report (#1094).
        """
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message) and not has_tool_calls(last_message):
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
        if has_text_content(last_message) and not has_tool_calls(last_message):
            return "Msg Clear Sentiment"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear Sentiment"
        return "tools_social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message) and not has_tool_calls(last_message):
            return "Msg Clear News"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear News"
        return "tools_news"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if has_text_content(last_message) and not has_tool_calls(last_message):
            return "Msg Clear Fundamentals"
        if _trailing_empty_rounds(messages) >= self.max_side_retries:
            return "Msg Clear Fundamentals"
        return "tools_fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue.

        Returns the next node in the debate, respecting which researchers
        are enabled. Budget = len(enabled_researchers) * max_debate_rounds
        + max_side_retries. An early exit forces Research Manager when both
        sides have produced content and count >= 2 * max_debate_rounds.
        The returned value is a node name (e.g. "Bull Researcher") that
        must exist in the graph's path map.
        """

        enabled = self.selected_researchers  # e.g. ["bull"], ["bear"], ["bull","bear"]
        count = state["investment_debate_state"]["count"]
        current_response = state["investment_debate_state"].get("current_response", "")

        bull_empty = not (state["investment_debate_state"].get("bull_history", "") or "").strip()
        bear_empty = not (state["investment_debate_state"].get("bear_history", "") or "").strip()

        budget = len(enabled) * self.max_debate_rounds + self.max_side_retries

        if count >= budget:
            return "Research Manager"

        # Early exit: if both sides have produced content and count has hit
        # the phase limit (2 * max_debate_rounds), force Research Manager.
        if count >= 2 * self.max_debate_rounds and not bull_empty and not bear_empty:
            return "Research Manager"

        # Determine the next speaker based on who spoke last and who is enabled.
        # Preserve original behavior: if current_response starts with "Bull",
        # next is "Bear Researcher" (and vice versa), unless the counterpart
        # is disabled, in which case route to Research Manager.
        if current_response.startswith("Bull"):
            if "bear" in enabled:
                return "Bear Researcher"
            # Only bull enabled → route to manager after this response
            return "Research Manager"
        if current_response.startswith("Bear"):
            if "bull" in enabled:
                return "Bull Researcher"
            # Only bear enabled → route to manager after this response
            return "Research Manager"
        # When current_response is empty (first turn), start with the first enabled researcher in list order, mapped to the proper node name.
        if enabled:
            first = enabled[0]  # e.g. "bull" or "bear"
            return f"{first.capitalize()} Researcher"
        return "Research Manager"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue.

        Returns the next enabled risk debator in the cycle, or the
        Portfolio Manager when the count limit is reached.
        Count limit = len(enabled_risk) * max_risk_discuss_rounds.
        """
        enabled = self.selected_risk  # e.g. ["aggressive"], ["conservative","neutral"], all three
        count = state["risk_debate_state"]["count"]
        limit = len(enabled) * self.max_risk_discuss_rounds

        if count >= limit:
            return "Portfolio Manager"

        latest_speaker = state["risk_debate_state"].get("latest_speaker", "")
        risk_list = ["aggressive", "conservative", "neutral"]

        # Determine the next node in the cycle, skipping disabled agents
        if latest_speaker.startswith("Aggressive"):
            # Next should be Conservative, but skip if disabled
            if "conservative" in enabled:
                return "Conservative Analyst"
            # If Conservative disabled, skip to Neutral (if enabled)
            if "neutral" in enabled:
                return "Neutral Analyst"
            # If neither Conservative nor Neutral enabled, go to PM
            return "Portfolio Manager"
        elif latest_speaker.startswith("Conservative"):
            # Next should be Neutral, but skip if disabled
            if "neutral" in enabled:
                return "Neutral Analyst"
            # If Neutral disabled, skip to Aggressive (if enabled)
            if "aggressive" in enabled:
                return "Aggressive Analyst"
            return "Portfolio Manager"
        elif latest_speaker.startswith("Neutral"):
            # Next should be Aggressive (circular), but skip if disabled
            if "aggressive" in enabled:
                return "Aggressive Analyst"
            # If Aggressive disabled, skip to Conservative (if enabled)
            if "conservative" in enabled:
                return "Conservative Analyst"
            return "Portfolio Manager"
        # First turn (latest_speaker empty): start with first enabled in cycle order
        for node in risk_list:
            if node in enabled:
                return f"{node.capitalize()} Analyst"
        return "Portfolio Manager"
