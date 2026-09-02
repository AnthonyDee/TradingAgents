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
import time
import traceback
from tradingagents.default_config import DEFAULT_CONFIG
try:
    from ebooklib import epub
    import markdown
    HAVE_EPUB = True
except Exception:
    HAVE_EPUB = False

try:
    import requests as _requests
    HAVE_REQUESTS = True
except Exception:
    HAVE_REQUESTS = False

# Wikimedia Commons requires a descriptive User-Agent; use for all requests.
_WIKIMEDIA_UA = "TradingAgents/1.0 (https://github.com/TradingAgents; analysis report cover)"

# Short topical query derived from the report's key idea; falls back to ticker.
_COVER_FALLBACK_QUERIES = {
    "market": "stock market trading chart",
    "trading": "stock market trading chart",
    "investment": "investment finance growth",
    "finance": "finance money economy",
    "growth": "economic growth finance",
    "stock": "stock market trading",
    "buy": "stock market trading",
    "sell": "stock market trading",
    "hold": "stock market trading",
}


def _extract_cover_query(final_state: dict, ticker: str) -> str:
    """Derive a short image-search query from the report's key idea.

    Prefers the Portfolio Manager decision, then the Trading plan, collapsing
    to a short topical phrase. Falls back to the ticker if nothing usable is
    found.
    """
    candidates = []
    risk = final_state.get("risk_debate_state") or {}
    if risk.get("judge_decision"):
        candidates.append(risk["judge_decision"])
    if final_state.get("trader_investment_plan"):
        candidates.append(final_state["trader_investment_plan"])

    text = "\n".join(c for c in candidates if isinstance(c, str)).strip()
    if not text:
        return ticker

    words = re.findall(r"[A-Za-z][A-Za-z0-9\-']*", text)
    common = {
        "the", "a", "an", "of", "and", "or", "to", "for", "on", "in", "with",
        "is", "are", "be", "it", "this", "that", "we", "recommend",
        "recommends", "our", "as", "at", "by", "from", "position", "weight",
        "target", "price", "based", "analysis", "report", "analyst", "review",
    }
    topic_candidates = [w.lower() for w in words if w.lower() not in common]
    for label in ("buy", "sell", "hold", "growth", "investment", "market",
                  "stock", "trading", "finance"):
        if label in topic_candidates:
            return _COVER_FALLBACK_QUERIES[label]

    if topic_candidates:
        query = " ".join(dict.fromkeys(topic_candidates[:4]))
        return query.capitalize()
    return ticker


def _fetch_cover_image(query: str, max_bytes: int = 4 * 1024 * 1024) -> bytes | None:
    """Fetch a JPEG/PNG photo for ``query`` from Wikimedia Commons (keyless).

    Returns the image bytes (an ~800px thumbnail) or ``None`` on any failure.
    Never raises.
    """
    if not HAVE_REQUESTS:
        return None
    try:
        res = _requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}",
                "gsrlimit": 8,
                "gsrnamespace": 6,
                "prop": "imageinfo",
                "iiprop": "url|mime|size",
                "iiurlwidth": 800,
            },
            headers={"User-Agent": _WIKIMEDIA_UA},
            timeout=15,
        )
        res.raise_for_status()
        pages = res.json().get("query", {}).get("pages", {})
        if not pages:
            return None

        def _area(info):
            w = info.get("width") or 0
            h = info.get("height") or 0
            return (w * h, w, h)

        # Sort by: JPEG first, then landscape (width >= height), then area.
        ranked = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime") or ""
            url = info.get("thumburl") or info.get("url")
            if mime not in ("image/jpeg", "image/png") or not url:
                continue
            ranked.append((mime, _area(info), url))
        ranked.sort(key=lambda t: (t[0] == "image/jpeg", t[1][1] >= t[1][2], t[1][0]), reverse=True)
        if not ranked:
            return None

        # Try the top few candidates; Wikimedia throttles (429) under load, so
        # retry with backoff and fall through to the next image on failure.
        ua = {"User-Agent": _WIKIMEDIA_UA}
        for attempt in range(3):
            for mime, _sz, url in ranked[:4]:
                try:
                    img = _requests.get(url, headers=ua, timeout=20)
                    if img.status_code == 429:
                        continue  # throttled -> try next candidate
                    img.raise_for_status()
                    ctype = img.headers.get("Content-Type", "")
                    if not ctype.startswith("image/"):
                        continue
                    if len(img.content) > max_bytes:
                        continue
                    return img.content
                except Exception:
                    continue
            if attempt < 2:
                # brief backoff before retrying the whole candidate list
                time.sleep(1.0)
        return None
    except Exception:
        return None


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
        if key in final_state:
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


def build_epub(final_state: dict, ticker: str, config: dict | None = None, cover_image: bytes | None = None) -> bytes:
    """Build an EPUB byte string for a run's final state.

    Produces the exact same EPUB format the CLI writes (cover page, analyst
    sub-chapters nested under their parent, per-section chapters, styled
    tables). Returns the raw EPUB bytes so callers can serve or stream it
    without writing to disk. Raises if ebooklib isn't available.

    ``cover_image`` (optional) embeds an image on the cover page, above the
    ticker title, date, and author.
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

    cover_image_item = None
    if cover_image:
        cover_image_item = epub.EpubImage(
            media_type="image/jpeg",
            content=cover_image,
            file_name="cover_image.jpg",
        )
        book.add_item(cover_image_item)

    if cover_image_item:
        cover_html = f"""
        <html>
        <head><title>{ticker} Report</title></head>
        <body style="text-align:center;">
            <div style="padding-top:2em;">
                <img src="cover_image.jpg" alt="{ticker} cover"
                     style="width:75%; border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,0.25);"/>
            </div>
            <h1 style="margin-top:1.2em; margin-bottom:0.2em;">{ticker} Analysis Report</h1>
            <p style="font-size:1.2em;">{now.strftime('%A')}</p>
            <p style="font-size:1.2em;">{now.strftime('%B %d, %Y')}</p>
            <p style="font-size:1.2em;">{now.strftime('%I:%M %p')}</p>
            <p>Author: {author_name}</p>
        </body>
        </html>
        """
    else:
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

            # Fetch a cover photo related to the report's key idea (non-fatal).
            cover_image = None
            try:
                cover_query = _extract_cover_query(final_state, ticker)
                cover_image = _fetch_cover_image(cover_query)
                if cover_image:
                    (save_path / "cover_image.jpg").write_bytes(cover_image)
            except Exception:
                cover_image = None

            epub_bytes = build_epub(final_state, ticker, config, cover_image=cover_image)
            epub_path.write_bytes(epub_bytes)
        except Exception:
            traceback.print_exc()
            # fall back to just markdown
    return complete_md_path
