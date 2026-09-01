"""Shared-router / path_map completeness (#1088).

Both `should_continue_risk_analysis` (three risk edges) and
`should_continue_debate` (two research-debate edges) are single routers whose
return set is larger than any one edge previously mapped. Each edge now shares a
complete path map (`RISK_ANALYSIS_PATH_MAP` / `DEBATE_PATH_MAP`), so a
fall-through return can never hit a missing entry -- which would crash LangGraph
mid-run on prompt/i18n/refactor drift in the speaker labels.
"""

import pytest

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import DEBATE_PATH_MAP, RISK_ANALYSIS_PATH_MAP


def _state(latest_speaker, count=0):
    return {"risk_debate_state": {"latest_speaker": latest_speaker, "count": count}}


def _debate_state(current_response, count=0):
    return {"investment_debate_state": {"current_response": current_response, "count": count}}


def _debate_state_full(bull, bear, current_response, count=0):
    return {
        "investment_debate_state": {
            "current_response": current_response,
            "count": count,
            "bull_history": bull,
            "bear_history": bear,
        }
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "latest_speaker",
    [
        "Aggressive",
        "Aggressive Analyst",
        "Conservative",
        "Conservative Analyst",
        "Neutral",
        "Neutral Analyst",
        "",  # drift: empty label
        "Aggressive Risk Analyst",  # drift: node renamed
        "Agresivo",  # drift: i18n / translated label
    ],
)
def test_router_return_always_routable(latest_speaker):
    logic = ConditionalLogic(max_risk_discuss_rounds=1)
    target = logic.should_continue_risk_analysis(_state(latest_speaker))
    assert target in RISK_ANALYSIS_PATH_MAP


@pytest.mark.unit
def test_router_terminates_at_round_limit():
    logic = ConditionalLogic(max_risk_discuss_rounds=1)
    # count >= 3 * rounds routes to the Portfolio Manager (debate ends)
    assert logic.should_continue_risk_analysis(_state("Neutral", count=3)) == "Portfolio Manager"


@pytest.mark.unit
def test_path_map_covers_full_router_range():
    logic = ConditionalLogic(max_risk_discuss_rounds=1)
    returns = {
        logic.should_continue_risk_analysis(_state(s, c))
        for s in ("Aggressive", "Conservative", "Neutral", "drift")
        for c in (0, 99)
    }
    # Every value the router can emit is a key in the shared map...
    assert returns <= set(RISK_ANALYSIS_PATH_MAP)
    # ...and the terminal target is reachable.
    assert "Portfolio Manager" in returns


@pytest.mark.unit
@pytest.mark.parametrize(
    "current_response",
    [
        "Bull",
        "Bull Researcher",
        "Bear",
        "Bear Researcher",
        "",  # drift: empty label
        "Optimista",  # drift: i18n / translated label
    ],
)
def test_debate_router_return_always_routable(current_response):
    logic = ConditionalLogic(max_debate_rounds=1)
    target = logic.should_continue_debate(_debate_state(current_response))
    assert target in DEBATE_PATH_MAP


@pytest.mark.unit
def test_debate_path_map_covers_full_router_range():
    logic = ConditionalLogic(max_debate_rounds=1)
    returns = {
        logic.should_continue_debate(_debate_state(s, c))
        for s in ("Bull", "Bear", "drift")
        for c in (0, 99)
    }
    assert returns <= set(DEBATE_PATH_MAP)
    assert "Research Manager" in returns  # terminal reachable


@pytest.mark.unit
def test_rm_only_when_both_sides_produced_content():
    logic = ConditionalLogic(max_debate_rounds=1)
    # Count at the phase limit but the bear is empty: must NOT settle yet.
    state = _debate_state_full(
        bull="Bull argument", bear="", current_response="Bull Analyst: x", count=1
    )
    assert logic.should_continue_debate(state) == "Bear Researcher"

    # Both present and count at the phase limit: settle.
    state = _debate_state_full(
        bull="Bull argument", bear="Bear argument", current_response="Bear Analyst: x", count=2
    )
    assert logic.should_continue_debate(state) == "Research Manager"


@pytest.mark.unit
def test_retries_empty_bull_sides_but_forces_complete_at_budget():
    logic = ConditionalLogic(max_debate_rounds=1, max_side_retries=2)
    # budget = 2*1 + 2 = 4. Below budget, empty bull is retried (route back to bull).
    state = _debate_state_full(bull="", bear="", current_response="Bear Analyst: x", count=2)
    assert logic.should_continue_debate(state) == "Bull Researcher"
    # At/over budget the debate is forced to the Research Manager.
    state = _debate_state_full(bull="", bear="", current_response="Bear Analyst: x", count=4)
    assert logic.should_continue_debate(state) == "Research Manager"


@pytest.mark.unit
def test_empty_bear_redirects_to_bear_even_when_bull_present():
    logic = ConditionalLogic(max_debate_rounds=1)
    state = _debate_state_full(
        bull="Bull argument", bear="", current_response="Bull Analyst: x", count=1
    )
    assert logic.should_continue_debate(state) == "Bear Researcher"
