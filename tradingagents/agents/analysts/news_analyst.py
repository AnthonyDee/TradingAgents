from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    analyst_tool_loop_stuck,
    extract_text_content,
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_verified_market_snapshot,
    invoke_no_tools_fallback,
)


def create_news_analyst(llm, mcp_tools=None, max_side_retries=3):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
            get_macro_indicators,
            get_prediction_markets,
            get_verified_market_snapshot,
        ]
        # Realtime market-data tools (e.g. Robinhood quotes) from connected MCP
        # servers. Empty when none configured.
        tools.extend(mcp_tools or [])

        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(ticker, start_date, end_date) for {asset_label}-specific news by ticker symbol, get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news, get_macro_indicators(indicator, curr_date, look_back_days) to ground macro commentary in actual data from FRED (e.g. 'cpi', 'core_pce', 'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve'), get_prediction_markets(topic, limit) for live market-implied probabilities of forward-looking events (e.g. 'Fed rate cut', 'recession 2026', geopolitical or sector events), and get_verified_market_snapshot(symbol, curr_date, look_back_days) for the verified current price and recent OHLCV of the ticker. Before making any claim about the current share price, price level, or recent percentage move, call get_verified_market_snapshot and treat its latest row as the source of truth; do not invent or guess a price. Provide specific, actionable insights with supporting evidence to help traders make informed decisions. If a realtime quote tool (get_realtime_quote(symbol)) appears in your tool list, call it for the current ticker. In your report, explicitly state the live quote: the current/last trade price, the bid and ask (when non-zero), and the quote's as-of timestamp, then reconcile it with the verified snapshot close (note any gap and which value you treat as the current price). Prefer the live quote for the current-price framing when its timestamp is recent; otherwise defer to the verified snapshot and phrase the price as of the relevant date. Always call get_verified_market_snapshot as well. If the realtime quote call errors or returns '[realtime quote unavailable]', explicitly say the live quote is unavailable and proceed using the verified snapshot as the current price — do not keep retrying the quote call."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
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

        # Only overwrite the report with a non-empty write-up. During the tool
        # loop the model commonly returns empty content alongside tool_calls;
        # writing "" on those rounds would clobber any report already produced
        # and, if the loop ends truncated, leave the report empty so it drops
        # out of the final report (#1094). The graph's analyst completion gate
        # re-runs this node when the report is still empty.
        text = extract_text_content(result).strip()

        # If the model is stuck in an empty tool loop, synthesize a report once
        # without tool-binding so this section always appears (#1094).
        if not text and not (state.get("news_report") or "").strip() and analyst_tool_loop_stuck(
            state["messages"], max_side_retries
        ):
            result = invoke_no_tools_fallback(prompt, llm, state["messages"])
            text = extract_text_content(result).strip()

        ordered_report = text if text else state.get("news_report", "")

        return {
            "messages": [result],
            "news_report": ordered_report,
        }

    return news_analyst_node
