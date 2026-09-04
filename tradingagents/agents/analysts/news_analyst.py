from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    extract_text_content,
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_verified_market_snapshot,
)
from tradingagents.agents.utils.prefetch import (
    UNAVAILABLE_MARKERS,
    DataSource,
    fetch_sources,
    format_sources_received,
    render_tagged_blocks,
)
from tradingagents.agents.utils.structured import NO_EXTERNAL_TOOLS


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _join_optional(blocks):
    """Join optional per-item sub-blocks, dropping empty / error / unavailable ones.

    Enrichment vendors (FRED, Polymarket) degrade per-indicator by returning a
    ``DATA_UNAVAILABLE`` sentinel string or raising; a single failing indicator
    should not mark the whole macro/prediction block unavailable, so we filter
    each sub-block independently.
    """
    kept = []
    for chunk in blocks:
        try:
            text = (chunk or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        if any(marker in text for marker in UNAVAILABLE_MARKERS):
            continue
        kept.append(text)
    return "\n\n".join(kept)


# A small, deterministic set of macro indicators the news analyst grounds its
# macroeconomic commentary on. Each is fetched independently; any that the
# configured vendor can't serve simply land in the sources_received line as
# empty / unavailable instead of failing the analyst.
_MACRO_INDICATORS = ("fed_funds_rate", "10y_treasury", "cpi", "unemployment")

# Forward-looking event topics to pull live market-implied probabilities for.
_PREDICTION_TOPICS = ("Fed rate cut", "recession 2026")


def create_news_analyst(llm, mcp_tools=None, max_side_retries=3, analyst_key="news"):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)
        ticker = str(state["company_of_interest"])
        start_date = _seven_days_back(current_date)

        sources = [
            DataSource("news", lambda: get_news.func(ticker, start_date, current_date)),
            DataSource("global_news", lambda: get_global_news.func(current_date)),
            DataSource("market_snapshot", lambda: get_verified_market_snapshot.func(ticker, current_date, 30)),
        ]
        # Macro indicators are kept together under one block so the prompt stays
        # compact; each indicator is its own fetch, so partial failure never
        # aborts the rest.
        sources.append(DataSource(
            "macro",
            lambda: _join_optional(
                f"--- {ind} ---\n{get_macro_indicators.func(ind, current_date, 180)}" for ind in _MACRO_INDICATORS
            ),
        ))
        sources.append(DataSource(
            "prediction_markets",
            lambda: _join_optional(
                f"--- {topic} ---\n{get_prediction_markets.func(topic)}" for topic in _PREDICTION_TOPICS
            ),
        ))

        blocks, confirmations = fetch_sources(sources)
        data_block = render_tagged_blocks(blocks)
        sources_line = format_sources_received(confirmations)

        system_message = _build_system_message(asset_label, data_block, sources_line)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Today's date is {current_date}; treat it as 'now' for all analysis. {instrument_context}\n"
                    + NO_EXTERNAL_TOOLS
                    + "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm

        report_text = _invoke_with_retry(chain, state["messages"], max_side_retries)
        ordered_report = f"{report_text}\n\n{sources_line}" if report_text else sources_line

        return {
            "messages": [AIMessage(content=ordered_report)],
            "news_report": ordered_report,
            "sources_received": {analyst_key: {**confirmations}},
        }

    return news_analyst_node


def _invoke_with_retry(chain, messages, max_retries: int) -> str:
    reminder = HumanMessage(
        content=(
            "Analyze the data blocks provided in this prompt and write your "
            "news/macro report now. Do not call tools and do not echo the raw "
            "data blocks back — synthesize a narrative report from them."
        )
    )
    attempts = max(max_retries, 1)
    for i in range(attempts):
        msgs = messages if i == 0 else messages + [reminder]
        text = extract_text_content(chain.invoke(msgs)).strip()
        if text:
            return text
    return ""


def _build_system_message(asset_label: str, data_block: str, sources_line: str) -> str:
    return f"""You are a news researcher analyzing recent news and trends relevant for trading and macroeconomics. You have been given pre-fetched data in the tagged blocks below; use them as the source of truth and never invent or guess information that is not present.

{sources_line}

## Data (pre-fetched, in this prompt)

{data_block}

## How to write your report

- ``news`` is {asset_label}-specific news by ticker. ``global_news`` is broader macroeconomic news. ``macro`` holds macroeconomic indicator time series (policy rate, Treasury yield, CPI, unemployment). ``prediction_markets`` holds live market-implied probabilities of forward-looking events. ``market_snapshot`` is the verified current price / OHLCV source of truth.
- Before stating the current share price, a price level, or a recent percentage move, cite ``market_snapshot``. Do not guess a price.
- Provide specific, actionable insights with supporting evidence to help traders make informed decisions.
- Only cite the tagged data blocks above.
- If a data block is missing or a source is marked ``empty``/``unavailable``/``error`` in the sources line, say so explicitly rather than guessing.
- Append a Markdown table at the end to organize the key points.{get_language_instruction()}"""


__all__ = ["create_news_analyst"]
