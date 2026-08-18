"""Metric registry — the single source of truth for screener metrics (PLAT-4).

Today the same catalogue is duplicated in nine places (``_SCREENER_PRIMITIVES``,
``_PRIMITIVE_COLS``, ``SCREENER_KEY_TO_FEATURE``, ``STOCK_FEATURE_COLS``,
``screenerPrimitives.ts``, ``_SCREEN_METRICS``, ``_lbl``, two preset lists and
three sort whitelists). They drift. This module is the one new code imports; the
others are migrated onto it incrementally (see the workspace plan, step 8).

Why a Python module served over HTTP rather than a DB table: the definitions are
*code* (formula text, explainer copy, applicability), so a copy edit would
otherwise need a forward-only migration — and every NIDP migration is visible to
whatever reads that database. Coverage *measurement* is data and does live in the
DB (``nidp.metric_coverage_daily``, migration 130); this module carries only the
threshold and the definition.

**Availability is measured, never assumed.** ``pb`` has 177 non-null readings that
are all exactly 0.0000 — a plain null-rate check calls that 7.5% covered and offers
a filter that silently matches nothing. The degeneracy rule (``distinct_non_null <=
1``) is what catches it, and it is why ``measure_coverage`` selects COUNT(DISTINCT)
rather than COUNT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Bump when a definition, formula, explainer or threshold changes. Saved screens
# pin this so a reloaded screen can be told its definitions moved (E1).
REGISTRY_VERSION = "1.0.0"

# A metric is offered only if it clears BOTH: coverage >= min_coverage_pct AND
# distinct_non_null > 1. The second half is not optional — see module docstring.
_MIN_DISTINCT = 2


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str                      # percent | ratio | currency_cr | score | count | days
    column: str                    # column on nidp.stock_features_daily
    category: str                  # valuation | profitability | growth | leverage | liquidity | classification
    formula: str
    source_dataset: str
    explainer: str                 # plain English; C7 is a 100% count check
    min_coverage_pct: float = 5.0
    sector_applicability: str = "all"
    # Set when a metric is barred for a reason coverage cannot express — e.g. a
    # window the price history cannot support. Barred metrics are never offered.
    hard_block_reason: Optional[str] = None
    is_text: bool = False          # sector/industry: filterable by set membership


# ── The launch set ──────────────────────────────────────────────────────────
# Coverage figures in the comments were measured on nidp_staging 2026-08-17 over
# 2,373 symbols. They are NOT hardcoded into behaviour — `offered` is computed at
# request time from nidp.metric_coverage_daily. They are recorded so a reviewer
# can see what the numbers looked like when these thresholds were chosen.

_METRICS: List[Metric] = [
    Metric(
        key="deliv_pct_avg_20", label="Avg Delivery %", unit="percent",
        column="deliv_pct_avg_20", category="liquidity",
        formula="mean(delivered quantity / traded quantity) over the last 20 sessions",
        source_dataset="nidp.prices_eod",
        explainer="Of the shares traded, how many were actually bought to keep rather "
                  "than flipped the same day. Higher suggests genuine accumulation.",
        min_coverage_pct=50.0,   # measured 100.0%, 2,335 distinct
    ),
    Metric(
        key="pe_ttm", label="P/E (TTM)", unit="ratio",
        column="pe_ttm", category="valuation",
        formula="Market capitalisation / profit after tax (trailing twelve months)",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="What you pay for each rupee of yearly profit. Lower can mean cheaper, "
                  "but a very low number often means the market expects profits to fall.",
        min_coverage_pct=10.0,   # measured 27.6%, 656 distinct
    ),
    Metric(
        key="roe_pct", label="Return on Equity", unit="percent",
        column="roe_pct", category="profitability",
        formula="Profit after tax (TTM) / average shareholders' equity x 100",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="How much profit the company makes on the money its owners have put in. "
                  "Higher is generally better.",
        min_coverage_pct=5.0,    # measured 7.2%, 170 distinct
    ),
    Metric(
        key="debt_to_equity", label="Debt to Equity", unit="ratio",
        column="debt_to_equity", category="leverage",
        formula="Total borrowings / shareholders' equity",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="How much the company has borrowed compared with its own money. "
                  "Lower means less risk if business slows.",
        min_coverage_pct=5.0,    # measured 7.5%, 144 distinct
    ),
    Metric(
        key="market_cap_cr", label="Market Cap", unit="currency_cr",
        column="market_cap_cr", category="valuation",
        formula="Share price x shares outstanding",
        source_dataset="nidp.stock_features_daily",
        explainer="The total value of the company on the exchange, in rupees crore.",
        min_coverage_pct=5.0,    # measured 7.5%, 179 distinct
    ),
    Metric(
        key="sector", label="Sector", unit="count",
        column="sector", category="classification", is_text=True,
        formula="Exchange-reported sector, normalised",
        source_dataset="nidp.sector_master",
        explainer="The broad industry the company operates in.",
        min_coverage_pct=50.0,
    ),

    # ── Barred. Present so the UI can say WHY a metric a user expects is absent,
    #    rather than silently omitting it (A4's "stated reason on hover").
    Metric(
        key="pb", label="Price to Book", unit="ratio", column="pb", category="valuation",
        formula="Market capitalisation / book value of equity",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="What you pay for each rupee of the company's net assets.",
        hard_block_reason="No usable values — every available reading is 0.00",
    ),
    Metric(
        key="piotroski_score", label="Piotroski F-Score", unit="score",
        column="piotroski_score", category="profitability",
        formula="9-point fundamental quality checklist",
        source_dataset="nidp.stock_features_daily",
        explainer="A 0-9 checklist of fundamental health. Higher is stronger.",
        hard_block_reason="Not currently computed",
    ),
    Metric(
        key="current_ratio", label="Current Ratio", unit="ratio",
        column="current_ratio", category="leverage",
        formula="Current assets / current liabilities",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="Whether short-term assets cover short-term dues.",
        hard_block_reason="Not currently computed",
    ),
    Metric(
        key="cfo_pat_ratio", label="Cash Flow / PAT", unit="ratio",
        column="cfo_pat_ratio", category="profitability",
        formula="Cash from operations / profit after tax",
        source_dataset="nidp.nse_financials_quarterly",
        explainer="Whether reported profit is arriving as real cash.",
        hard_block_reason="Not currently computed",
    ),
    Metric(
        key="sma200", label="200-day Moving Average", unit="ratio",
        column="sma200", category="liquidity",
        formula="mean(close) over the last 200 sessions",
        source_dataset="nidp.prices_eod",
        explainer="The average price over roughly the last ten months.",
        hard_block_reason="Needs 200 sessions of history; the deepest symbol has 206 "
                          "and most have far fewer",
    ),
]

BY_KEY: Dict[str, Metric] = {m.key: m for m in _METRICS}

# A3: no symbol has >= 252 bars (max observed 206 across 4,737 symbols on
# 2026-08-17), so nothing may be SERVED under a 1Y/3Y label. Enforced centrally
# rather than by remembering not to add one.
BARRED_LABEL_SUFFIXES = ("_1y", "_3y")

# The 12 categories the classifier actually implements. The PRD describes 70+
# event types; those come from a design document, not the running system.
EVENT_CATEGORIES: List[str] = [
    "other", "regulatory", "management", "earnings", "mna", "dividend",
    "qip", "rating", "orders", "litigation", "capex", "buyback",
]
EVENT_IMPACTS: List[str] = ["high", "medium", "low"]
EVENT_SENTIMENTS: List[str] = ["positive", "neutral", "negative"]


def filterable_columns() -> Dict[str, Metric]:
    """Whitelist for predicate building. A key absent here can never reach SQL."""
    return dict(BY_KEY)


def is_offered(metric: Metric, coverage: Optional[Dict[str, Any]]) -> bool:
    """Offered = not hard-blocked AND measured coverage clears both thresholds.

    Unknown coverage is treated as NOT offered. Failing closed matters: offering a
    metric whose coverage we could not measure is exactly the silent-wrong-result
    the product exists to avoid.
    """
    if metric.hard_block_reason:
        return False
    if metric.key.endswith(BARRED_LABEL_SUFFIXES):
        return False
    if not coverage:
        return False
    pct = coverage.get("covered_pct")
    distinct = coverage.get("distinct_non_null")
    if pct is None or distinct is None:
        return False
    return pct >= metric.min_coverage_pct and distinct >= _MIN_DISTINCT


def hidden_reason(metric: Metric, coverage: Optional[Dict[str, Any]]) -> str:
    """Why a metric is not offered, in words a beginner can act on."""
    if metric.hard_block_reason:
        return metric.hard_block_reason
    if not coverage:
        return "Coverage for this metric has not been measured today"
    distinct = coverage.get("distinct_non_null")
    pct = coverage.get("covered_pct")
    if distinct is not None and distinct < _MIN_DISTINCT:
        return (f"No usable values — every available reading is identical"
                if distinct == 1 else "No values available today")
    if pct is not None and pct < metric.min_coverage_pct:
        return (f"Only {pct:.1f}% of companies have this today "
                f"(needs {metric.min_coverage_pct:.0f}%)")
    return "Not available today"


def to_payload(metric: Metric, coverage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "key": metric.key,
        "label": metric.label,
        "unit": metric.unit,
        "column": metric.column,
        "category": metric.category,
        "formula": metric.formula,
        "source_dataset": metric.source_dataset,
        "explainer": metric.explainer,
        "sector_applicability": metric.sector_applicability,
        "min_coverage_pct": metric.min_coverage_pct,
        "measured": coverage or {},
        "offered": is_offered(metric, coverage),
    }
