import functools
import logging
from collections.abc import Mapping
from typing import Any

import yfinance as yf
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.agents.utils.fundamental_data_tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from tradingagents.agents.utils.macro_data_tools import get_macro_indicators
from tradingagents.agents.utils.market_data_validation_tools import get_verified_market_snapshot
from tradingagents.agents.utils.news_data_tools import (
    get_global_news,
    get_insider_transactions,
    get_news,
)
from tradingagents.agents.utils.prediction_markets_tools import get_prediction_markets
from tradingagents.agents.utils.technical_indicators_tools import get_indicators

# Public surface: the data tools are imported here so agents and the graph
# import them from one place, plus the instrument/language helpers defined below.
__all__ = [
    "get_stock_data",
    "get_indicators",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_global_news",
    "get_insider_transactions",
    "get_macro_indicators",
    "get_prediction_markets",
    "get_verified_market_snapshot",
    "build_instrument_context",
    "resolve_instrument_identity",
    "get_instrument_context_from_state",
    "get_language_instruction",
    "create_msg_delete",
    "extract_text_content",
    "has_text_content",
    "analyst_tool_loop_stuck",
    "invoke_no_tools_fallback",
    "rescue_tool_output",
    "has_tool_calls",
]

logger = logging.getLogger(__name__)


def extract_text_content(message: Any) -> str:
    """Return the text content of a message as a single string.

    Works whether ``message.content`` is a plain string (OpenAI-style final
    text) or a list of content blocks (Anthropic-style, e.g.
    ``[{"type": "text", "text": "..."}, ...]``). Text blocks are concatenated;
    non-text blocks (tool_use, images) are ignored. Returns ``""`` when there
    is no textual content — such as a pure tool-calling leg with no prose.

    Unlike reading ``message.content`` directly, this intentionally does not
    gate on ``message.tool_calls``: many thinking/reasoning providers return a
    final assistant message that carries report text *and* a recorded
    ``tool_calls`` entry, and the report should be kept in that case.
    """
    content = message.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def has_text_content(message: Any) -> bool:
    """Return True when ``message`` carries non-empty textual content.

    Used to decide loop termination: a final assistant message that contains
    real prose is the report, even if it also lists ``tool_calls``. This stops
    the analyst loop from re-invoking tools (or hitting the recursion limit)
    once the model has already delivered its write-up.
    """
    return bool(extract_text_content(message).strip())


def has_tool_calls(message: Any) -> bool:
    """Return True when ``message`` carries at least one tool call.

    Works across providers: checks ``AIMessage.tool_calls`` first (OpenAI /
    xAI style) then falls back to scanning ``content`` blocks for
    ``type == "tool_use"`` (Anthropic style).
    """
    if getattr(message, "tool_calls", None):
        return True
    content = getattr(message, "content", None)
    if isinstance(content, (list, tuple)):
        return any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content)
    return False


def _trailing_empty_rounds(messages) -> int:
    """Count consecutive trailing assistant messages that carry no text.

    Mirrors the gate's trailing-empty scan in ``graph/conditional_logic.py``.
    An analyst's tool loop alternates ``AIMessage -> ToolMessage``, so a run
    of trailing empty ``AIMessage`` entries corresponds to the active
    analyst's empty reply rounds.
    """
    count = 0
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            if not has_text_content(message):
                count += 1
                continue
            break
        continue
    return count


def analyst_tool_loop_stuck(messages, max_side_retries: int) -> bool:
    """Return True when the analyst tool loop is about to hit the retry budget.

    The tool-calling analysts re-enter their node once per tool round. Each
    empty round (an assistant turn that emits tools but no prose) pushes the
    trailing-empty count up toward ``max_side_retries``; once it reaches
    ``max_side_retries - 1``, the gate would force-continue with an empty
    report on the very next check. At that point the analyst should stop
    waiting for tools and synthesize a textual report, so a never-writing
    model can't silently drop its section from the final report (#1094).
    """
    if max_side_retries is None or max_side_retries <= 0:
        return False
    return _trailing_empty_rounds(messages) >= max_side_retries - 1


# Headers that a data tool introduces on its verbatim output. When any of these
# appears in the model's turn, it is likely echoing tool output rather than
# writing original analysis.
_TOOL_OUTPUT_HEADERS = (
    "Verified market data snapshot",
    "Stock data for",
    "technical indicator",
    "Recent verified closes",
    "Latest verified OHLCV row",
    "Company Fundamentals for",
    "Balance Sheet data for",
    "Cash Flow data for",
    "Income Statement data for",
    "Insider Transactions data for",
    "News, from",
    "Global Market News, from",
    "FRED:",
    "Polymarket prediction markets:",
)


def _is_tool_output_only(text: str) -> bool:
    """Return True when *text* is a raw tool-data dump with no real analysis.

    Handle two shapes of dump:

    1. Verbatim tool output — recognized by a data-tool header (e.g.
       "Verified market data snapshot for SPY", "Stock data for ...").
    2. Generic table/bullet dumps with little-to-no narrative prose.

    A genuine analyst report instead contains narrative paragraphs (sequences
    of sentences) and interpretive language. The reason this can't be a pure
    prose-length check is that the verified snapshot carries a long disclaimers
    footer that reads like prose, so a length heuristic would misclassify the
    verbatim snapshot as an analysis.
    """
    if not text:
        return False

    lowered = text.lower()
    for header in _TOOL_OUTPUT_HEADERS:
        if header.lower() in lowered:
            # Verbatim tool output present. It's still a *report* only if the
            # model added substantial original analysis on top; otherwise it's
            # a dump. Give a genuine write-up that happens to quote a snapshot
            # field the benefit of the doubt only when it actually reads like
            # analysis rather than echoing the tables.
            return not _has_substantial_analysis(text)

    return _table_dominant_dump(text)


def _has_substantial_analysis(text: str) -> bool:
    """True when *text* contains real interpretive/narrative prose.

    Looks for multiple prose sentences with analytic framing (recommendation,
    interpretation, trend description) that go beyond echoing data. A verbatim
    dump only has the tool's own deterministic footer sentence, which is not
    the model's analysis, so it scores low.
    """
    # Words/patterns that indicate the model is interpreting rather than
    # transcribing. These essentially never appear in raw tool output.
    analytic_markers = (
        "indicates",
        "suggests",
        "signals",
        "implies",
        "reflects",
        "weigh",
        "recommend",
        "sugg",
        "trend",
        "momentum",
        "support",
        "resistance",
        "overbought",
        "oversold",
        "outlook",
        "bullish",
        "bearish",
        "neutral",
        "breakout",
        "pullback",
        "consolidat",
        "uptrend",
        "downtrend",
        "watch",
    )
    hits = sum(1 for marker in analytic_markers if marker in text.lower())
    return hits >= 3


def _table_dominant_dump(text: str) -> bool:
    """Heuristic for generic table/bullet dumps without verbose tool headers."""
    table_len = 0
    prose_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("---"):
            continue
        # Heading, bullet, numbered, or short label line -> structural.
        if (
            stripped.startswith("#")
            or stripped.startswith("*")
            or stripped.startswith("- ")
            or stripped.startswith("+")
            or any(stripped.startswith(f"{n}.") for n in range(0, 10))
        ):
            table_len += len(stripped)
            continue
        # A line that is a single short label -> structural.
        if len(stripped.split(" ")) <= 3:
            table_len += len(stripped)
            continue
        prose_lines.append(stripped)

    if not prose_lines:
        return True
    prose_len = sum(len(line) for line in prose_lines)
    return prose_len < table_len


def rescue_tool_output(messages) -> str:
    """Rescue the most useful data-tool output from *messages* as a last resort.

    Scans backwards through the tool messages and returns the newest usable
    output from a built-in data tool (e.g. ``get_stock_data`` /
    ``get_indicators`` / ``get_verified_market_snapshot`` /
    ``get_fundamentals`` / ``get_balance_sheet`` / ``get_cashflow`` /
    ``get_income_statement`` / ``get_news`` / ``get_global_news`` /
    ``get_macro_indicators`` / ``get_prediction_markets``), skipping error and
    unavailable sentinels. Returns ``""`` when nothing usable is found.
    """
    _ERROR_MARKERS = (
        "[realtime quote unavailable]",
        "NO_DATA_AVAILABLE",
        "DATA_UNAVAILABLE",
    )
    # Built-in data tools whose output is substantive enough to stand in as a
    # last-resort report when the LLM writes nothing.
    _DATA_TOOLS = {
        "get_stock_data",
        "get_indicators",
        "get_verified_market_snapshot",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
        "get_news",
        "get_global_news",
        "get_macro_indicators",
        "get_prediction_markets",
    }

    def _usable_tool_output(msg):
        content = msg.content if isinstance(msg.content, str) else extract_text_content(msg)
        content = content.strip()
        if not content:
            return None
        if content.startswith("Error"):
            return None
        if any(marker in content for marker in _ERROR_MARKERS):
            return None
        return content

    for msg in reversed(messages):
        if getattr(msg, "type", None) != "tool":
            continue
        if (getattr(msg, "name", "") or "") not in _DATA_TOOLS:
            continue
        out = _usable_tool_output(msg)
        if out is None:
            continue
        return out
    return ""


def invoke_no_tools_fallback(prompt, llm, state_messages) -> AIMessage:
    """Invoke an analyst's prompt WITHOUT tool-binding to force a textual report.

    The tool-calling analysts run ``prompt | llm.bind_tools(tools)``; when a
    model gets stuck emitting tool calls that return empty data (or simply
    never writes prose), this runs the same prompt against the bare LLM so it
    synthesizes a report from whatever the earlier tool rounds already fetched
    into ``state_messages``. Returns an ``AIMessage`` so the node can hand it
    to the router as the final (text-bearing) turn, ending the loop cleanly.
    """
    chain = prompt | llm
    result = chain.invoke(state_messages)
    fallback_text = extract_text_content(result).strip()
    if not fallback_text:
        # Try to rescue actual tool data first so verified data isn't lost
        rescued = rescue_tool_output(state_messages)
        if rescued:
            return AIMessage(content=rescued)
        # Last-resort so the section still surfaces in the final report even if
        # the provider returns an empty assistant turn.
        fallback_text = (
            "Analysis of the requested instrument was inconclusive because the "
            "live data tools returned no usable output this run. Please treat "
            "this section with caution."
        )
    return result if has_text_content(result) else AIMessage(content=fallback_text)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config

    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def _clean_identity_value(value: Any) -> str | None:
    """Return a trimmed string, or None for empty / placeholder-ish values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """Resolve deterministic identity metadata (company name, sector, …) for a ticker.

    This exists to stop the pipeline from hallucinating a *different* company
    when a chart pattern suggests a different industry than the real one
    (#814): without a ground-truth name, the market analyst would pattern-match
    the price action to a narrative and invent an identity that then cascaded
    through every downstream agent.

    Best-effort by design: if yfinance is unavailable, rate-limited, or doesn't
    recognise the ticker, we return ``{}`` and the caller falls back to
    ticker-only context rather than failing before analysis starts. Cached so
    the lookup happens at most once per ticker per process.

    The symbol is normalized first (e.g. ``XAUUSD`` -> ``GC=F``) so identity
    resolves for the same instrument the price path actually fetches (#983).
    """
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    try:
        info = yf.Ticker(normalize_symbol(ticker)).info or {}
    except Exception as exc:  # noqa: BLE001 — fail open, never block the run
        logger.debug("Could not resolve instrument identity for %s: %s", ticker, exc)
        return {}

    identity: dict[str, str] = {}
    company_name = _clean_identity_value(info.get("longName")) or _clean_identity_value(
        info.get("shortName")
    )
    if company_name:
        identity["company_name"] = company_name
    for source_key, target_key in (
        ("sector", "sector"),
        ("industry", "industry"),
        ("exchange", "exchange"),
        ("quoteType", "quote_type"),
    ):
        value = _clean_identity_value(info.get(source_key))
        if value:
            identity[target_key] = value
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    identity: Mapping[str, str] | None = None,
) -> str:
    """Describe the exact instrument so agents preserve identity and ticker.

    When ``identity`` is provided (resolved deterministically via
    :func:`resolve_instrument_identity`), the company name and business
    classification are injected so agents anchor to the real company rather
    than pattern-matching the price chart to a wrong one (#814).
    """
    is_crypto = asset_type == "crypto"
    instrument_label = "asset" if is_crypto else "instrument"
    context = (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
    )

    details = []
    if identity:
        name = identity.get("company_name") or identity.get("name")
        if name:
            details.append(f"{'Name' if is_crypto else 'Company'}: {name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector and industry:
            details.append(f"Business classification: {sector} / {industry}")
        elif sector:
            details.append(f"Sector: {sector}")
        elif industry:
            details.append(f"Industry: {industry}")
        if identity.get("exchange"):
            details.append(f"Exchange: {identity['exchange']}")

    if details:
        context += (
            f" Resolved identity: {'; '.join(details)}. "
            "Do not substitute a different company or ticker unless a tool "
            "result explicitly disproves this resolved identity."
        )

    if is_crypto:
        context += (
            " Treat it as a crypto asset rather than a company, and do not "
            "assume company fundamentals are available."
        )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    """Return the instrument context for the current run.

    Prefers the identity-resolved context computed once at run start and
    stored on the state (see ``TradingAgentsGraph.resolve_instrument_context``).
    Falls back to a ticker-only context — with no network lookup — when the
    state was constructed without it (bare programmatic states, tests), so a
    consumer is never forced to make a yfinance call mid-graph.
    """
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "stock"),
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add a context-anchored placeholder.

        The placeholder must not be a bare ``"Continue"``: some
        OpenAI-compatible providers interpret that literally as the user task
        and produce output about the word "continue" instead of analysing the
        instrument (#888). Anchoring it to the resolved instrument context and
        date keeps the next analyst on-task even if the provider treats the
        placeholder as a standalone request.
        """
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {"messages": removal_operations + [placeholder]}

    return delete_messages
