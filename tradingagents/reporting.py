"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.

Added: EPUB version
"""

from datetime import datetime
from pathlib import Path

import io
import re
import traceback
from tradingagents.default_config import DEFAULT_CONFIG
try:
    from ebooklib import epub
    import markdown
    HAVE_EPUB = True
except Exception:
    HAVE_EPUB = False


def _prepare_markdown_for_epub(md: str) -> str:
    """Normalize markdown so bullet lists render as lists in the EPUB.

    Python-Markdown requires a blank line before a ``*``/``-`` bullet list;
    without it the bullets are treated as paragraph text and the ``*`` shows
    up literally. This inserts a blank line before any list item whose
    preceding line is non-empty and not already a blank/separator.
    """
    lines = md.split("\n")
    out = []
    list_re = re.compile(r"^\s*[\*\-]\s+\S")
    for i, line in enumerate(lines):
        if list_re.match(line) and i > 0 and lines[i - 1].strip() != "":
            out.append("")
        out.append(line)
    return "\n".join(out)


def _collect_sections(final_state: dict) -> list:
    """Build the ordered per-section markdown content for a run's final state."""
    sections = []

    # 1. Analysts
    analyst_parts = []
    for key, name in [
        ("market_report", "Market Analyst"),
        ("sentiment_report", "Sentiment Analyst"),
        ("news_report", "News Analyst"),
        ("fundamentals_report", "Fundamentals Analyst"),
    ]:
        if final_state.get(key):
            analyst_parts.append((name, final_state[key]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_parts.append(("Bull", debate["bull_history"]))
        if debate.get("bear_history"):
            research_parts.append(("Bear", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        sections.append(f"## III. Trading Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    return sections


def build_epub(final_state: dict, ticker: str, config: dict | None = None) -> bytes:
    """Build an EPUB byte string for a run's final state.

    Produces the exact same EPUB format the CLI writes (cover page, analyst
    sub-chapters nested under their parent, per-section chapters, styled
    tables). Returns the raw EPUB bytes so callers can serve or stream it
    without writing to disk. Raises if ebooklib isn't available.
    """
    if not HAVE_EPUB:
        raise RuntimeError(
            "EPUB export requires 'ebooklib' and 'markdown'. Install them with "
            "`pip install ebooklib markdown`."
        )
    sections = _collect_sections(final_state)

    cfg = config or DEFAULT_CONFIG
    deep = cfg.get("deep_think_llm", "deep")
    quick = cfg.get("quick_think_llm", "quick")
    author_name = f"{deep} & {quick}" if deep != quick else deep
    now = datetime.now()

    book = epub.EpubBook()
    book.set_identifier(f"trading-analysis-{ticker}")
    book.add_author(author_name)
    book.set_title(f"{ticker} Analysis Report")
    book.set_language("en")

    cover_html = f"""
    <html>
    <head><title>{ticker} Report</title></head>
    <body style="text-align:center; padding-top:3em;">
        <h1>{ticker} Analysis Report</h1>
        <p style="font-size:1.2em;">{now.strftime('%A')}</p>
        <p style="font-size:1.2em;">{now.strftime('%B %d, %Y')}</p>
        <p style="font-size:1.2em;">{now.strftime('%I:%M %p')}</p>
        <p>Author: {author_name}</p>
    </body>
    </html>
    """
    cover = epub.EpubHtml(title=f"{ticker} Report", file_name="cover.xhtml", content=cover_html)
    book.add_item(cover)

    chapters = []
    analyst_parent = None
    analyst_children = []
    for idx, sec in enumerate(sections):
        heading = sec.split("\n", 1)[0].lstrip("#").strip()

        if "analyst reports" in heading.lower():
            analyst_parent = epub.EpubHtml(
                title="Analyst Team Reports",
                file_name="chap_analyst_team.xhtml",
                content=markdown.markdown(_prepare_markdown_for_epub("# Analyst Team Reports\n\n"), extensions=["tables", "fenced_code", "sane_lists"]),
            )
            book.add_item(analyst_parent)
            for block in sec.split("\n### ")[1:]:
                name, _, text = block.partition("\n")
                name = name.strip()
                if not name:
                    continue
                fname = f"analyst_{name.split()[0].lower()}.xhtml"
                child = epub.EpubHtml(
                    title=name,
                    file_name=fname,
                    content=markdown.markdown(_prepare_markdown_for_epub(f"# {name}\n\n{text.strip()}"), extensions=["tables", "fenced_code", "sane_lists"]),
                )
                book.add_item(child)
                analyst_children.append(child)
            continue

        fname = f"chap_{idx}_{heading.replace(' ', '_').lower()}.xhtml"
        chap = epub.EpubHtml(
            title=heading,
            file_name=fname,
            content=markdown.markdown(_prepare_markdown_for_epub(sec), extensions=["tables", "fenced_code", "sane_lists"]),
        )
        book.add_item(chap)
        chapters.append(chap)

    toc = [epub.Link(cover.file_name, cover.title, cover.id)]
    if analyst_parent is not None:
        toc.append(
            (epub.Link(analyst_parent.file_name, analyst_parent.title, analyst_parent.id),
             [epub.Link(c.file_name, c.title, c.id) for c in analyst_children])
        )
    toc.extend(chapters)
    book.toc = toc

    spine_items = [cover]
    if analyst_parent is not None:
        spine_items.append(analyst_parent)
        spine_items.extend(analyst_children)
    spine_items.extend(chapters)
    book.spine = ["nav"] + spine_items

    style = """
    body {
        font-size: 90%;
        line-height: 1.4;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        font-size: 0.9em;
        margin: 1em 0;
        page-break-inside: avoid;
    }
    th, td {
        border: 1px solid #aaa;
        padding: 4px 8px;
        text-align: left;
    }
    th {
        background-color: #f0f0f0;
        font-weight: bold;
    }
    ul, ol {
        margin: 0.5em 0;
        padding-left: 1.5em;
    }
    li {
        margin: 0.2em 0;
    }
    """
    css_item = epub.EpubItem(
        file_name="style.css",
        media_type="text/css",
        content=style,
    )
    book.add_item(css_item)
    for chap in [cover] + ([analyst_parent] if analyst_parent else []) + analyst_children + chapters:
        chap.add_link(href="style.css", rel="stylesheet", type="text/css")
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    buffer = io.BytesIO()
    epub.write_epub(buffer, book, {})
    return buffer.getvalue()


def write_report_tree(final_state: dict, ticker: str, save_path, config: dict | None = None) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = _collect_sections(final_state)

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analysts_dir.mkdir(exist_ok=True)
    if final_state.get("market_report"):
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
    if final_state.get("sentiment_report"):
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
    if final_state.get("news_report"):
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
    if final_state.get("fundamentals_report"):
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        research_dir.mkdir(exist_ok=True)
        debate = final_state["investment_debate_state"]
        if debate.get("bull_history"):
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
        if debate.get("bear_history"):
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
        if debate.get("judge_decision"):
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk_dir.mkdir(exist_ok=True)
        risk = final_state["risk_debate_state"]
        if risk.get("aggressive_history"):
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
        if risk.get("conservative_history"):
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
        if risk.get("neutral_history"):
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")

    # Write consolidated report
    header = f"# {ticker} Report\n\n{datetime.now().strftime('%A, %B %d, %Y %H:%M %p')}\n\n"
    complete_md_path = save_path / "complete_report.md"
    complete_md_path.write_text(header + "\n\n".join(sections), encoding="utf-8")
    if HAVE_EPUB:
        try:
            date_suffix = datetime.now().strftime("%Y-%m-%d")
            epub_path = save_path / f"{ticker}_{date_suffix}.epub"
            epub_path.write_bytes(build_epub(final_state, ticker, config))
        except Exception:
            traceback.print_exc()
            # fall back to just markdown
    return complete_md_path
