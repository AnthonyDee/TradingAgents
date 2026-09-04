from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    extract_text_content,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
    get_verified_market_snapshot,
)
from tradingagents.agents.utils.prefetch import (
    DataSource,
    fetch_sources,
    format_sources_received,
    render_tagged_blocks,
)
from tradingagents.agents.utils.structured import NO_EXTERNAL_TOOLS


def create_fundamentals_analyst(llm, mcp_tools=None, max_side_retries=3, analyst_key="fundamentals"):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)
        ticker = str(state["company_of_interest"])

        # Pre-fetch company profile / headline ratios plus each financial
        # statement, so the LLM gets the full picture in one (no tool loop).
        blocks, confirmations = fetch_sources([
            DataSource("fundamentals", lambda: get_fundamentals.func(ticker, current_date)),
            DataSource("balance_sheet", lambda: get_balance_sheet.func(ticker, "quarterly", current_date)),
            DataSource("cashflow", lambda: get_cashflow.func(ticker, "quarterly", current_date)),
            DataSource("income_statement", lambda: get_income_statement.func(ticker, "quarterly", current_date)),
            DataSource("market_snapshot", lambda: get_verified_market_snapshot.func(ticker, current_date, 30)),
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
        ordered_report = f"{report_text}\n\n{sources_line}" if report_text else sources_line

        return {
            "messages": [AIMessage(content=ordered_report)],
            "fundamentals_report": ordered_report,
            "sources_received": {analyst_key: {**confirmations}},
        }

    return fundamentals_analyst_node


def _invoke_with_retry(chain, messages, max_retries: int) -> str:
    reminder = HumanMessage(
        content=(
            "Analyze the fundamental data blocks provided in this prompt and "
            "write your report now. Do not call tools and do not echo the raw "
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


def _build_system_message(data_block: str, sources_line: str) -> str:
    return f"""You are a researcher tasked with analyzing a company's fundamental information to inform traders. You have been given pre-fetched financial data in the tagged blocks below; use them as the source of truth and never invent or guess figures that are not present.

{sources_line}

## Data (pre-fetched, in this prompt)

{data_block}

## How to write your report

- ``fundamentals`` holds the company profile and headline ratios (market cap, PE/PB, EPS, margins, returns, liquidity, leverage). ``balance_sheet``, ``cashflow``, and ``income_statement`` hold the quarterly financial statements. ``market_snapshot`` is the verified current price / OHLCV source of truth.
- Before stating the current share price, a price level, or a recent percentage move, cite ``market_snapshot``. Never guess or infer a price from fundamentals alone.
- Cover financial documents, company profile, basic financials, and financial history. Include as much concrete detail as the data supports, with specific, actionable insights grounded in the figures.
- Only cite the tagged data blocks above.
- If a data block is missing or a source is marked ``empty``/``unavailable``/``error`` in the sources line, say so explicitly rather than guessing.
- Append a Markdown table at the end to organize the key points.{get_language_instruction()}"""


__all__ = ["create_fundamentals_analyst"]
