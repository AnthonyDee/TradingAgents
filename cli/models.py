from enum import Enum


class AnalystType(str, Enum):
    MARKET = "market"
    # Wire value stays "social" for saved-config and string-keyed-caller
    # back-compat; the user-facing label is "Sentiment Analyst".
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"


class ResearcherType(str, Enum):
    BULL = "bull"
    BEAR = "bear"


class RiskAnalystType(str, Enum):
    AGGRESSIVE = "aggressive"
    CONSERVATIVE = "conservative"
    NEUTRAL = "neutral"


class AssetType(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"


# Combined ordered list for the CLI checkbox:
# Analysts → Researchers → Risk debators (Trader is always-on)
AGENT_ORDER = [
    ("Market Analyst", AnalystType.MARKET),
    ("Sentiment Analyst", AnalystType.SOCIAL),
    ("News Analyst", AnalystType.NEWS),
    ("Fundamentals Analyst", AnalystType.FUNDAMENTALS),
    ("Bull Researcher", ResearcherType.BULL),
    ("Bear Researcher", ResearcherType.BEAR),
    ("Aggressive Analyst", RiskAnalystType.AGGRESSIVE),
    ("Conservative Analyst", RiskAnalystType.CONSERVATIVE),
    ("Neutral Analyst", RiskAnalystType.NEUTRAL),
]
