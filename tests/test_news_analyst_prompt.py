"""Guard the news analyst against tool-signature drift (#1116, retained under the
new pre-fetch wiring).

The news analyst used to advertise ``get_news(query, ...)`` while the tool takes
a ``ticker``, tricking the LLM into hallucinating free-text query calls. Under
the pre-fetch pattern the analyst calls ``get_news.func(ticker, start_date,
end_date)`` directly in code, so we guard that the tool is still invoked with a
ticker first arg (never a free-text ``query``).
"""
import inspect

import pytest

import tradingagents.agents.analysts.news_analyst as na
from tradingagents.agents.utils.news_data_tools import get_news


@pytest.mark.unit
def test_get_news_takes_ticker_not_query():
    arg_names = set(get_news.args.keys())
    assert "ticker" in arg_names
    assert "query" not in arg_names


@pytest.mark.unit
def test_news_invokes_get_news_with_ticker():
    src = inspect.getsource(na)
    assert "get_news.func(ticker, start_date," in src
    assert "get_news(query" not in src
