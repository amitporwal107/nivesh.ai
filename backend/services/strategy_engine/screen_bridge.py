"""Bridge: copilot-chat stock screener → Strategy Builder DSL.

Turns the `stock_screener` chat widget's live filter state into a valid STOCK
strategy DSL so a user can save a screen as a strategy from the UI.

The widget emits `filters` as `{"<key>_min": num, "<key>_max": num, …}` plus an
optional `sector` list — the same primitive keys the copilot screener uses. This
module maps each key to the matching `nidp.stock_features_daily` column (the
`feature.*` namespace), attaches sensible default exit/ranking/rebalance (a screen
has none), and returns a DSL doc for `dsl.validate_strategy` + persistence.

Pure — no DB, no HTTP. Unit-tested in tests/test_screen_to_strategy.py.

SCREENER_KEY_TO_FEATURE mirrors `_SCREENER_PRIMITIVES` in
services/copilot_tools/stock_intelligence.py (widget key → feature column). A
drift guard test asserts every column here is in dsl.STOCK_FEATURE_COLS, so a
rename that breaks the mapping fails CI rather than silently dropping a filter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import dsl


# widget primitive key → nidp.stock_features_daily column (feature.* namespace).
# Keep in sync with stock_intelligence._SCREENER_PRIMITIVES.
SCREENER_KEY_TO_FEATURE: Dict[str, str] = {
    # Valuation
    "pe": "pe_ttm",
    "pb": "pb",
    "evEbitda": "ev_ebitda",
    "peVsSector": "pe_vs_sector_pct",
    "divYield": "dividend_yield_pct",
    # Profitability / quality
    "roe": "roe_pct",
    "roce": "roce_pct",
    "profitMargin": "profit_margin_pct",
    "interestCoverage": "interest_coverage",
    "earningsConsistency": "earnings_consistency_score",
    # Growth
    "salesG": "revenue_growth_3y_cagr_pct",
    "profitG": "eps_growth_3y_cagr_pct",
    "salesGyoy": "revenue_growth_yoy_pct",
    "profitGyoy": "pat_growth_yoy_pct",
    "epsGyoy": "eps_growth_yoy_pct",
    "marginTrend": "profit_margin_trend_pct",
    # Financial health
    "de": "debt_to_equity",
    "debtTrend": "debt_trend_pct",
    "liquidity": "liquidity_score",
    # Size
    "mcap": "market_cap_cr",
    # Price / technical
    "return1y": "return_252d_pct",
    "volatility": "volatility_1y_pct",
    "beta": "beta_1y",
    "maxDrawdown": "max_drawdown_1y_pct",
    "rsi": "rsi14",
    "momentum": "momentum_score",
    "accumulation": "accumulation_score",
    # Ownership / smart money
    "promoter": "promoter_pct",
    "promoterPledge": "promoter_pledged_pct",
    "fii": "fii_pct",
    "dii": "dii_pct",
    "fiiChange": "fii_pct_change_qoq",
    "promoterChange": "promoter_pct_change_qoq",
}

# Defaults for the parts a screen doesn't specify. A screen is a point-in-time
# filter; a strategy also needs an exit, a ranking and a cadence.
_DEFAULT_EXIT = {"stoploss_pct": 8.0, "target_rr": 2.0, "max_hold_days": 90}
_DEFAULT_RANKING = {"by": "momentum_score", "limit": 20, "order": "desc"}
_DEFAULT_REBALANCE = "weekly"
_DEFAULT_UNIVERSE = {"type": "index", "ref": "NIFTY500"}


class ScreenBridgeError(ValueError):
    """No screenable conditions could be derived from the screen."""


def build_definition_from_screen(
    *,
    name: str,
    filters: Optional[Dict[str, Any]] = None,
    sector: Optional[List[str]] = None,
    universe: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Build a STOCK strategy DSL from screener widget state.

    Returns (definition, dropped) where `dropped` lists filter keys that could
    not be mapped (unknown primitive, non-numeric value, or a column missing
    from the DSL whitelist) — surfaced to the user, never silently ignored.

    Raises ScreenBridgeError if no usable condition remains.
    """
    predicates: List[Dict[str, Any]] = []
    dropped: List[str] = []

    for fkey, val in (filters or {}).items():
        if fkey.endswith("_min"):
            base, op = fkey[:-4], ">="
        elif fkey.endswith("_max"):
            base, op = fkey[:-4], "<="
        else:
            dropped.append(fkey)
            continue
        col = SCREENER_KEY_TO_FEATURE.get(base)
        if col is None or col not in dsl.STOCK_FEATURE_COLS:
            dropped.append(fkey)
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            dropped.append(fkey)
            continue
        predicates.append({"feature": col, "op": op, "value": num})

    if sector:
        secs = [str(s).strip() for s in sector if isinstance(s, str) and str(s).strip()]
        if secs:
            # DSL sector predicate shape: {"sector": <field>, "op": "in", "value": [...]}
            # (the validator reads `op` separately; the "sector" value is a nominal field name).
            predicates.append({"sector": "sector", "op": "in", "value": secs})

    if not predicates:
        raise ScreenBridgeError(
            "no screenable conditions — set at least one numeric filter or a sector"
        )

    definition: Dict[str, Any] = {
        "version": dsl.DSL_VERSION,
        "asset_class": "STOCK",
        "name": name,
        "description": description or f"Created from stock screener ({len(predicates)} conditions)",
        "universe": universe or dict(_DEFAULT_UNIVERSE),
        "entry": {"all_of": predicates},
        "exit": dict(_DEFAULT_EXIT),
        "ranking": dict(_DEFAULT_RANKING),
        "rebalance": _DEFAULT_REBALANCE,
    }
    return definition, dropped
