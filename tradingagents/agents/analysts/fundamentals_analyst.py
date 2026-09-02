from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    _is_tool_output_only,
    analyst_tool_loop_stuck,
    extract_text_content,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
    get_verified_market_snapshot,
    has_tool_calls,
    invoke_no_tools_fallback,
    rescue_tool_output,
)


def create_fundamentals_analyst(llm, mcp_tools=None, max_side_retries=3):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
            get_verified_market_snapshot,
        ]
        # Realtime market-data tools (e.g. Robinhood quotes) from connected MCP
        # servers. Empty when none configured.
        tools.extend(mcp_tools or [])

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements, and `get_verified_market_snapshot(symbol, curr_date, look_back_days)` for the verified current price and recent OHLCV of the ticker. Before stating the current share price or any price-level/percentage-move claim, call get_verified_market_snapshot and treat its latest row as the source of truth; never guess or infer a price from fundamentals alone. If a realtime quote tool (get_realtime_quote(symbol)) appears in your tool list, call it for the current ticker. In your report, explicitly state the live quote: the current/last trade price, the bid and ask (when non-zero), and the quote's as-of timestamp, then reconcile it with the verified snapshot close (note any gap and which value you treat as the current price). Prefer the live quote for the current-price framing when its timestamp is recent; otherwise defer to the verified snapshot and phrase the price as of the relevant date. Always call get_verified_market_snapshot as well. If the realtime quote call errors or returns '[realtime quote unavailable]', explicitly say the live quote is unavailable and proceed using the verified snapshot as the current price — do not keep retrying the quote call."
            + get_language_instruction(),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        # If the model returned empty content with no tool calls, it failed
        # to engage with the tools. Re-invoke with an explicit reminder.
        if not extract_text_content(result).strip() and not has_tool_calls(result):
            from langchain_core.messages import HumanMessage

            reminder = HumanMessage(
                content=(
                    "You have not yet called any tools. You MUST call "
                    "get_fundamentals to retrieve financial data, then "
                    "get_balance_sheet, get_cashflow, and "
                    "get_income_statement for specifics, and "
                    "get_verified_market_snapshot for current price. "
                    "Do not write a report without fetching data first."
                )
            )
            result = chain.invoke(state["messages"] + [reminder])

        # Only overwrite the report with a non-empty write-up. During the tool
        # loop the model commonly returns empty content alongside tool_calls;
        # writing "" on those rounds would clobber any report already produced
        # and, if the loop ends truncated, leave the report empty so it drops
        # out of the final report (#1094). The graph's analyst completion gate
        # re-runs this node when the report is still empty.
        text = extract_text_content(result).strip()

        is_dump = bool(text) and _is_tool_output_only(text)
        loop_stuck = analyst_tool_loop_stuck(state["messages"], max_side_retries)

        if text and not is_dump and not has_tool_calls(result):
            ordered_report = text
        elif has_tool_calls(result):
            if loop_stuck:
                # LLM stuck in tool loop — force fallback to generate report
                fallback = invoke_no_tools_fallback(prompt, llm, state["messages"])
                ordered_report = extract_text_content(fallback).strip() or rescue_tool_output(
                    state["messages"]
                )
                if extract_text_content(fallback).strip():
                    result = fallback
            else:
                # LLM produced tool calls (possibly with empty text) — let the
                # graph's tool loop execute them on the next round.
                ordered_report = ""
        elif state.get("fundamentals_report") or "":
            ordered_report = state["fundamentals_report"]
        elif loop_stuck:
            # Exhausted retries — the LLM never wrote prose, so rescue the
            # most useful fetched tool data as the section.
            fallback = invoke_no_tools_fallback(prompt, llm, state["messages"])
            ordered_report = extract_text_content(fallback).strip() or rescue_tool_output(
                state["messages"]
            )
            if extract_text_content(fallback).strip():
                result = fallback
        else:
            ordered_report = ""

        return {
            "messages": [result],
            "fundamentals_report": ordered_report,
        }

    return fundamentals_analyst_node
