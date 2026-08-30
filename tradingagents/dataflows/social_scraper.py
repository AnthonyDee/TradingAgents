"""RSS-based ticker-mention fetcher for the sentiment analyst.

Replaces the old X/Twitter scraper. It pulls a configurable list of financial
news RSS feeds and returns entries whose title/summary mention the ticker. No
API key is required. Feed URLs may optionally contain a ``{ticker}`` placeholder
for ticker-specific feeds; plain URLs are filtered by ticker mention. Every
failure degrades gracefully to a per-feed note rather than raising.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable

import feedparser
import requests
from .symbol_utils import crypto_base
from .user_agent import USER_AGENT

logger = logging.getLogger(__name__)

# Default feed list: (name, url). Override entirely with the TA_RSS_FEEDS env
# var (a JSON list of [name, url] pairs). URLs with a {ticker} placeholder are
# expanded per-ticker; others are fetched once and filtered by mention.
RSS_FEEDS: list[tuple[str, str]] = [
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
    ("Reuters Markets", "https://www.reuters.com/markets/feed"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
]


def _load_feeds() -> list[tuple[str, str]]:
    env = os.getenv("TA_RSS_FEEDS")
    if env:
        try:
            data = json.loads(env)
            if isinstance(data, list):
                return [(str(n), str(u)) for n, u in data]
        except Exception as e:  # noqa: BLE001
            logger.warning("TA_RSS_FEEDS parse failed, using defaults: %s", e)
    return RSS_FEEDS


def fetch_social_posts(
    ticker: str,
    feeds: Iterable[str] | None = None,
    limit_per_platform: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 2.0,
) -> str:
    """Fetch recent RSS items mentioning ticker across the configured feeds."""
    ticker = crypto_base(ticker) or ticker
    sym = ticker.upper()

    feed_list = _load_feeds()
    if feeds is not None:
        wanted = {f.lower() for f in feeds}
        feed_list = [(n, u) for n, u in feed_list if n.lower() in wanted]

    blocks: list[str] = []

    for i, (name, url) in enumerate(feed_list):
        if i > 0:
            time.sleep(inter_request_delay)

        try:
            eff_url = url.replace("{ticker}", ticker) if "{ticker}" in url else url
            resp = requests.get(eff_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:  # noqa: BLE001
            logger.warning("RSS fetch failed for %s (%s): %s", name, ticker, e)
            blocks.append(f"{name}: <unavailable>")
            continue

        matches: list[str] = []
        for entry in parsed.entries:
            text = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}"
            if sym.lower() in text.lower():
                matches.append(text.strip())
            if len(matches) >= limit_per_platform:
                break

        if not matches:
            blocks.append(f"{name}: <no posts found mentioning {sym}>")
            continue

        lines = [f"{name} — {len(matches)} recent posts mentioning {sym}:"]
        for m in matches:
            clean = m.replace("\n", " ").strip()
            if len(clean) > 240:
                clean = clean[:240] + "…"
            lines.append(f"  - {clean}")
        blocks.append("\n".join(lines))

    if not blocks:
        return f"<no social posts found mentioning {sym} across RSS feeds>"

    return "\n\n".join(blocks)
