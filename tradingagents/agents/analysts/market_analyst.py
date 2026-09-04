from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    extract_text_content,
    get_instrument_context_from_state,
    get_language_instruction,
    get_stock_data,
    get_verified_market_snapshot,
)
from tradingagents.agents.utils.prefetch import (
    DataSource,
    fetch_sources,
    format_sources_received,
    render_tagged_blocks,
)
from tradingagents.agents.utils.structured import NO_EXTERNAL_TOOLS


def _snapshot_start_date(trade_date: str) -> str:
    # A month of lookback so the snapshot (which already computes the standard
    # indicator set) has enough bars to anchor OHLCV and price-level claims.
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=45)).strftime("%Y-%m-%d")


def create_market_analyst(llm, mcp_tools=None, max_side_retries=3, analyst_key="market"):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)
        ticker = str(state["company_of_interest"])

        # Pre-fetch the verified snapshot (the source of truth for exact OHLCV
        # and indicator claims — it already carries the standard indicator set,
        # so no LLM-driven indicator selection is needed) and the raw OHLCV CSV
        # for trend context.
        blocks, confirmations = fetch_sources([
            DataSource("market_snapshot", lambda: get_verified_market_snapshot.func(ticker, current_date, 30)),
            DataSource("ohlcv", lambda: get_stock_data.func(ticker, _snapshot_start_date(current_date), current_date)),
        ])

        data_block = render_tagged_blocks(blocks)
        sources_line = format_sources_received(confirmations)

        system_message = _build_system_message(data_block, sources_line)

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

        # Always append the auditable confirmation line so the final markdown
        # records exactly which data sources were received and passed on.
        ordered_report = f"{report_text}\n\n{sources_line}" if report_text else sources_line

        return {
            "messages": [AIMessage(content=ordered_report)],
            "market_report": ordered_report,
            "sources_received": {analyst_key: {**confirmations}},
        }

    return market_analyst_node


def _invoke_with_retry(chain, messages, max_retries: int) -> str:
    """Invoke once and, if the model returns no prose, re-invoke with a reminder.

    Bounded by ``max_retries`` so a model that never writes a report can't loop
    forever; on total failure we return "" and the caller degrades to a clear
    line rather than leaking raw tool data.
    """
    reminder = HumanMessage(
        content=(
            "Analyze the data blocks provided in this prompt and write your "
            "report now. Do not call tools and do not echo the raw data blocks "
            "back — synthesize a narrative report from them."
        )
    )
    attempts = max(max_retries, 1)
    for i in range(attempts):
        msgs = messages if i == 0 else messages + [reminder]
        text = extract_text_content(chain.invoke(msgs)).strip()
        if text:
            return text
    return ""


def _build_system_message(data_block: str, sources_line: str) -> str:
    return f"""You are a trading assistant tasked with analyzing the financial markets for a single instrument. You have been given pre-fetched, verified data in the tagged blocks below. Use them as the source of truth for exact OHLCV, price-level, and indicator-value claims; never invent, guess, or reconcile a conflicting number.

{sources_line}

## Data (pre-fetched, in this prompt)

{data_block}

## How to write your report

- The ``market_snapshot`` block is the **source of truth** for exact OHLCV, the standard technical-indicator set (EMA/SMA/MACD/RSI/Bollinger/ATR), support/resistance levels, and any percentage move. Treat it as authoritative. If the ``ohlcv`` block conflicts with it, flag the discrepancy rather than inventing a reconciled number.
- Do not claim historical validation, support/resistance bounces, or exact percentage moves unless directly supported by the data blocks with concrete dates and prices.
- Analyze the trend (short, medium, long term), momentum, volatility, and volume. Provide specific, actionable insights with supporting evidence for traders.
- Only cite the tagged data blocks above; do not reference data that is not present in them.
- If a data block is missing (e.g. no ``ohlcv`` block) or a source is marked ``empty``/``unavailable``/``error`` in the sources line, say so explicitly rather than guessing.
- Append a Markdown table at the end to organize the key points.{get_language_instruction()}"""


__all__ = ["create_market_analyst"]
