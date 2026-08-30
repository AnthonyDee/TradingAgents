"""User agent string for TradingAgents dataflow requests.

All dataflow modules (Reddit, StockTwits, RSS feeds) should import
``USER_AGENT`` from this module rather than defining it locally.
"""

USER_AGENT = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"