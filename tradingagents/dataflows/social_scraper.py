"""Modular social media scraper for ticker-specific discussion.

This module provides a base class for scraping social media platforms
and a specific implementation for X (Twitter) using public search
patterns. Like the Reddit implementation, it aims for a lightweight,
no-API-key approach where possible.
"""

from __future__ import annotations

import logging
import time
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from urllib.request import Request, urlopen
import urllib.parse
from urllib.error import HTTPError
from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

class SocialPlatformScraper(ABC):
    """Base class for social media scraping implementations."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    @abstractmethod
    def fetch_posts(self, ticker: str, limit: int, timeout: float) -> list[dict]:
        """Fetch posts for a given ticker. Returns a list of dictionaries."""
        pass

class XScraper(SocialPlatformScraper):
    """X (Twitter) scraper implementation."""
    
    def __init__(self, user_agent: str):
        super().__init__(user_agent)
        # Public search URL pattern
        self._SEARCH_URL = "https://twitter.com/search?q={query}&src=typed_query&f=live"

    def fetch_posts(self, ticker: str, limit: int, timeout: float) -> list[dict]:
        """
        Fetch recent posts from X. Note: X's public web interface is heavily 
        protected by JS/WAF. This implementation serves as a structural 
        template for the lauchpad.
        """
        query = urllib.parse.quote_plus(f"{ticker} lang:en -filter:links")
        url = self._SEARCH_URL.format(query=query)
        req = Request(url, headers={"User-Agent": self.user_agent})
        
        try:
            with urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8")
                # Simple regex extraction for demonstration purposes
                # Real X scraping typically requires a headless browser or API
                posts = []
                # Placeholder logic to simulate extraction from the HTML
                # In a production scenario, a proper parser or API would be used here
                return posts
        except (HTTPError, OSError) as e:
            logger.warning("X fetch failed for %s: %s", ticker, e)
            return []

def fetch_social_posts(
    ticker: str,
    platforms: Iterable[str] = ("x",),
    limit_per_platform: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 2.0,
) -> str:
    """Fetch recent social media posts mentioning ticker across platforms."""
    ticker = crypto_base(ticker) or ticker
    ua = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
    
    # Registry of available scrapers
    SCRAPERS = {
        "x": XScraper(ua),
    }
    
    blocks = []
    total_posts = 0
    
    for i, plat in enumerate(platforms):
        if i > 0:
            time.sleep(inter_request_delay)
            
        scraper = SCRAPERS.get(plat)
        if not scraper:
            blocks.append(f"Platform {plat}: <unsupported platform>")
            continue
            
        posts = scraper.fetch_posts(ticker, limit_per_platform, timeout)
        total_posts += len(posts)
        
        if not posts:
            blocks.append(f"{plat}: <no posts found mentioning {ticker.upper()}>")
            continue
            
        header = f"{plat} — {len(posts)} recent posts mentioning {ticker.upper()}:"
        lines = [header]
        for p in posts:
            text = p.get("text", "").replace("\n", " ").strip()
            if len(text) > 240:
                text = text[:240] + "…"
            lines.append(f"  - {text}")
        blocks.append("\n".join(lines))
        
    if total_posts == 0:
        return f"<no social posts found mentioning {ticker.upper()} across {', '.join(platforms)}>"
        
    return "\n\n".join(blocks)
