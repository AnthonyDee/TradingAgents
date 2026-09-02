"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

from types import SimpleNamespace

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree


def _state():
    return {
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
    }


def _mock_graph(selected_analysts=None):
    return SimpleNamespace(
        config={"results_dir": "/tmp/results"},
        selected_analysts=selected_analysts or ["market", "news"],
    )


@pytest.mark.unit
def test_write_report_tree_creates_files(tmp_path):
    out = write_report_tree(_state(), "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "1_analysts" / "news.md").read_text() == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text() == "PM DECISION"
    complete = out.read_text()
    assert "# AAPL Report" in complete
    assert "MKT" in complete and "PM DECISION" in complete
    assert "The Sentiment Analyst did not contribute to this report." in complete
    assert "The Fundamentals Analyst did not contribute to this report." in complete


@pytest.mark.unit
def test_write_report_tree_with_selected_analysts(tmp_path):
    # Test with only market and news selected
    out = write_report_tree(_state(), "AAPL", tmp_path, selected_analysts=["market", "news"])
    complete = out.read_text()
    assert "### Market Analyst" in complete
    assert "MKT" in complete
    assert "### News Analyst" in complete
    assert "NEWS" in complete
    # Sentiment and Fundamentals should not appear since they weren't selected
    assert "Sentiment Analyst" not in complete
    assert "Fundamentals Analyst" not in complete


@pytest.mark.unit
def test_save_reports_explicit_path(tmp_path):
    # Unbound: with an explicit save_path, the method doesn't touch self/config.
    mock_self = _mock_graph()
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL", save_path=tmp_path)
    assert (tmp_path / "complete_report.md").exists()
    assert out == tmp_path / "complete_report.md"


@pytest.mark.unit
def test_save_reports_defaults_under_results_dir(tmp_path):
    mock_self = _mock_graph()
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL")
    assert out.exists()
    assert out.parent.parent.name == "reports"  # results_dir/reports/AAPL_<stamp>/...
    assert out.parent.name.startswith("AAPL_")
