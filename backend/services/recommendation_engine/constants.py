"""Shared constants for the recommendation engine.

Centralised here so every module reads from one place.
Previously scattered across portfolio_builder.py and ad-hoc engine defaults.
"""

# Maximum number of funds considered "well-consolidated" per asset-class bucket.
# Portfolios with more than this count receive bucket_count_exit signals.
# D-7 decision (2026-06-03): flat rule, V2, no size-tiering.
# Solve concentration at high AUM with the AMC cap, not by inflating fund count.
FUNDS_PER_BUCKET: dict[str, int] = {
    "equity":  3,
    "debt":    2,
    "gold":    1,
    "cash":    1,
    "hybrid":  2,
}

# Mapping from holding asset_class / fund category keywords → bucket key
BUCKET_KEYWORDS: dict[str, str] = {
    "equity":   "equity",
    "elss":     "equity",
    "hybrid":   "hybrid",
    "balanced": "hybrid",
    "arbitrage":"hybrid",
    "debt":     "debt",
    "bond":     "debt",
    "gilt":     "debt",
    "liquid":   "debt",
    "overnight":"debt",
    "money market": "debt",
    "gold":     "gold",
    "silver":   "gold",   # treated as alternate commodity
    "cash":     "cash",
    "savings":  "cash",
}


def classify_bucket(asset_class: str, fund_category: str = "") -> str:
    """Return the canonical bucket name for a holding.

    Checks asset_class first (authoritative), then fund_category keywords.
    Falls back to 'equity' — the safest default for scoring.
    """
    ac = (asset_class or "").lower().strip()
    cat = (fund_category or "").lower().strip()
    for key, bucket in BUCKET_KEYWORDS.items():
        if key in ac:
            return bucket
    for key, bucket in BUCKET_KEYWORDS.items():
        if key in cat:
            return bucket
    return "equity"
