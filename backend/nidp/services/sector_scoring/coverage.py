"""Primitive coverage checker for sector-aware stock scoring.

Every primitive read by the scorers is declared here with:
  - The sector profiles that require it
  - The NIDP feed that should be supplying it (for actionable gap reporting)

When `check_coverage()` is called before scoring, it returns the full list of
missing fields and groups them by feed so the ops team can see exactly which
ingester pipeline to fix.

Usage:
    result = check_coverage(profile, prims, tech_data, bank_metrics)
    result.missing          # ["roe_pct", "roce_pct", ...]
    result.coverage_pct     # 62.5
    result.missing_by_feed  # {"nse_financials": ["roce_pct"], "ti_engine": [...]}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .classifier import BANK, NBFC, CYCLICAL, IT, FMCG, PHARMA, CAPGOODS, DEFAULT

# ── Feed ownership map ────────────────────────────────────────────────────────
# Maps each primitive key to the NIDP feed/ingester responsible for populating it.
# Used in gap reports so engineers know which pipeline to fix.
FEED_MAP: Dict[str, str] = {
    # ── NSE Financials (quarterly P&L + balance sheet) ────────────────────
    "roe_pct":                      "nse_financials",
    "roce_pct":                     "nse_financials",
    "profit_margin_pct":            "nse_financials",
    "pat_growth_yoy_pct":           "nse_financials",
    "revenue_growth_yoy_pct":       "nse_financials",
    "eps_growth_yoy_pct":           "nse_financials",
    "debt_to_equity":               "nse_financials",
    "interest_coverage":            "nse_financials",
    "ev_ebitda":                    "nse_financials",
    "pe_ttm":                       "nse_financials",
    "pb":                           "nse_financials",
    "profit_margin_trend_pct":      "nse_financials",
    "debt_trend_pct":               "nse_financials",
    "dividend_yield_pct":           "nse_financials",
    # ── Derived metrics (computed from NSE financials time-series) ────────
    "revenue_growth_3y_cagr_pct":   "derived_metrics",
    "eps_growth_3y_cagr_pct":       "derived_metrics",
    "earnings_consistency_score":   "derived_metrics",
    "pe_overvaluation_pct":         "derived_metrics",  # pe_vs_sector_pct
    "pe_vs_sector_pct":             "derived_metrics",
    # ── Shareholding (BSE/NSE disclosure filings) ─────────────────────────
    "promoter_pct":                 "shareholding",
    "fii_pct":                      "shareholding",
    "dii_pct":                      "shareholding",
    "mf_pct":                       "shareholding",
    "promoter_pledged_pct":         "shareholding",
    "promoter_pct_change_qoq":      "shareholding",
    "fii_pct_change_qoq":           "shareholding",
    "dii_pct_change_qoq":           "shareholding",
    # ── Technical indicators (TI engine, daily price data) ────────────────
    "rsi14":                        "ti_engine",
    "macd":                         "ti_engine",
    "macd_signal":                  "ti_engine",
    "macd_hist":                    "ti_engine",
    "return_252d_pct":              "ti_engine",
    "volatility_1y_pct":            "ti_engine",
    "accumulation_score":           "ti_engine",
    "momentum_score":               "ti_engine",
    "liquidity_score":              "ti_engine",
    "max_drawdown_1y_pct":          "ti_engine",
    "beta_1y":                      "ti_engine",
    # ── Extra tech_data fields (stock_features_daily extra cols) ──────────
    "close":                        "ti_engine",
    "sma50":                        "ti_engine",
    "sma200":                       "ti_engine",
    "sma50_slope":                  "ti_engine",
    "dist_52w_high_pct":            "ti_engine",
    "return_60d_pct":               "ti_engine",
    "vol_z20":                      "ti_engine",
    "deliv_pct_avg_20":             "ti_engine",
    # ── Bank metrics (bank_npa_patch + bank_scoring) ──────────────────────
    "gnpa_pct":                     "bank_npa_patch",
    "nnpa_pct":                     "bank_npa_patch",
    "pcr_implied_pct":              "bank_scoring",
    "nii_retention_pct":            "bank_scoring",
    "pat_margin_pct":               "bank_scoring",   # bank_metrics_daily
    "pat_yoy_growth_pct":           "bank_scoring",
    "earnings_consistency":         "bank_scoring",
    # ── Market cap / valuation (price_data + NSE master) ─────────────────
    "market_cap_bucket":            "price_data",
    "market_cap_cr":                "price_data",
    "enterprise_value_cr":          "price_data",
    # ── Flags (derived by TI/scoring engine) ──────────────────────────────
    "earnings_decline_flag":        "derived_metrics",
    "debt_spike_flag":              "derived_metrics",
}

# ── Per-profile required primitives ──────────────────────────────────────────
# These are the keys the scorer actually reads (not just nice-to-haves).
# Grouped by (source, key) tuples.  Source = "prims", "tech_data", "bank_metrics".
#
# "prims"       → from v_v3_stock_primitives (stock_features_daily)
# "tech_data"   → extra fields fetched separately from stock_features_daily
# "bank_metrics"→ from bank_metrics_daily (BANK profile only)

_COMMON_PRIMS = [
    # Governance (universal)
    ("prims", "promoter_pct"),
    ("prims", "promoter_pct_change_qoq"),
    ("prims", "promoter_pledged_pct"),
    ("prims", "fii_pct_change_qoq"),
    ("prims", "dii_pct_change_qoq"),
    # Technical (universal)
    ("prims", "return_252d_pct"),
    ("prims", "volatility_1y_pct"),
    ("prims", "rsi14"),
    ("prims", "macd"),
    ("prims", "macd_signal"),
    ("prims", "macd_hist"),
    ("prims", "accumulation_score"),
    # Tech-data (extra cols from stock_features_daily)
    ("tech_data", "close"),
    ("tech_data", "sma50"),
    ("tech_data", "sma200"),
    ("tech_data", "sma50_slope"),
    ("tech_data", "dist_52w_high_pct"),
    ("tech_data", "return_60d_pct"),
    ("tech_data", "vol_z20"),
    ("tech_data", "deliv_pct_avg_20"),
]

PROFILE_PRIMITIVES: Dict[str, List[tuple[str, str]]] = {
    BANK: _COMMON_PRIMS + [
        ("bank_metrics", "gnpa_pct"),
        ("bank_metrics", "nnpa_pct"),
        ("bank_metrics", "pcr_implied_pct"),
        ("bank_metrics", "nii_retention_pct"),
        ("bank_metrics", "pat_margin_pct"),
        ("bank_metrics", "roe_pct"),
        ("bank_metrics", "pat_yoy_growth_pct"),
        ("bank_metrics", "earnings_consistency"),
        ("prims", "revenue_growth_yoy_pct"),
        ("prims", "pe_ttm"),
        ("prims", "pb"),
    ],
    NBFC: _COMMON_PRIMS + [
        ("prims", "roe_pct"),
        ("prims", "roce_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "interest_coverage"),
        ("prims", "debt_to_equity"),
        ("prims", "debt_trend_pct"),
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "eps_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "pe_ttm"),
    ],
    IT: _COMMON_PRIMS + [
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "pat_growth_yoy_pct"),
        ("prims", "eps_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "roce_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "roe_pct"),
        ("prims", "interest_coverage"),
        ("prims", "pe_ttm"),
        ("prims", "pe_overvaluation_pct"),
        ("prims", "market_cap_bucket"),
    ],
    FMCG: _COMMON_PRIMS + [
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "revenue_growth_yoy_pct"),
        ("prims", "pat_growth_yoy_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "profit_margin_trend_pct"),
        ("prims", "roe_pct"),
        ("prims", "roce_pct"),
        ("prims", "pe_ttm"),
        ("prims", "pe_overvaluation_pct"),
    ],
    CYCLICAL: _COMMON_PRIMS + [
        ("prims", "debt_to_equity"),
        ("prims", "interest_coverage"),
        ("prims", "profit_margin_pct"),
        ("prims", "profit_margin_trend_pct"),
        ("prims", "roce_pct"),
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "eps_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "ev_ebitda"),
        ("prims", "pe_ttm"),
        ("prims", "revenue_growth_yoy_pct"),
        ("prims", "debt_spike_flag"),
    ],
    PHARMA: _COMMON_PRIMS + [
        ("prims", "eps_growth_3y_cagr_pct"),
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "roce_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "roe_pct"),
        ("prims", "profit_margin_trend_pct"),
        ("prims", "pe_ttm"),
        ("prims", "pe_overvaluation_pct"),
    ],
    CAPGOODS: _COMMON_PRIMS + [
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "revenue_growth_yoy_pct"),
        ("prims", "pat_growth_yoy_pct"),
        ("prims", "profit_margin_trend_pct"),
        ("prims", "roce_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "roe_pct"),
        ("prims", "debt_to_equity"),
        ("prims", "interest_coverage"),
        ("prims", "pe_ttm"),
        ("prims", "pe_overvaluation_pct"),
    ],
    DEFAULT: _COMMON_PRIMS + [
        ("prims", "roe_pct"),
        ("prims", "roce_pct"),
        ("prims", "profit_margin_pct"),
        ("prims", "debt_to_equity"),
        ("prims", "interest_coverage"),
        ("prims", "revenue_growth_3y_cagr_pct"),
        ("prims", "eps_growth_3y_cagr_pct"),
        ("prims", "earnings_consistency_score"),
        ("prims", "pe_ttm"),
        ("prims", "pe_overvaluation_pct"),
    ],
}


@dataclass
class CoverageResult:
    profile:        str
    total:          int
    present:        int
    missing:        List[str]           = field(default_factory=list)
    missing_by_feed: Dict[str, List[str]] = field(default_factory=dict)
    coverage_pct:   float               = 0.0


def check_coverage(
    profile: str,
    prims: Dict[str, Any],
    tech_data: Optional[Dict[str, Any]] = None,
    bank_metrics: Optional[Dict[str, Any]] = None,
) -> CoverageResult:
    """Check which required primitives are present vs missing for a given profile.

    Args:
        profile:      Sector profile string (BANK, IT, DEFAULT, etc.)
        prims:        Row from v_v3_stock_primitives.
        tech_data:    Extra fields from stock_features_daily (close, sma50, …).
        bank_metrics: Row from bank_metrics_daily (BANK profile only).

    Returns:
        CoverageResult with missing field names grouped by their owning feed.
    """
    td = tech_data or {}
    bm = bank_metrics or {}

    required = PROFILE_PRIMITIVES.get(profile, PROFILE_PRIMITIVES[DEFAULT])
    missing_fields: List[str] = []

    for source, key in required:
        if source == "prims":
            present = prims.get(key) is not None
        elif source == "tech_data":
            present = td.get(key) is not None
        elif source == "bank_metrics":
            present = bm.get(key) is not None
        else:
            present = False

        if not present:
            missing_fields.append(key)

    # Group missing by feed for actionable reporting
    missing_by_feed: Dict[str, List[str]] = {}
    for key in missing_fields:
        feed = FEED_MAP.get(key, "unknown")
        missing_by_feed.setdefault(feed, []).append(key)

    total = len(required)
    present_count = total - len(missing_fields)
    coverage_pct = round(100.0 * present_count / total, 2) if total > 0 else 0.0

    return CoverageResult(
        profile=profile,
        total=total,
        present=present_count,
        missing=missing_fields,
        missing_by_feed=missing_by_feed,
        coverage_pct=coverage_pct,
    )


def aggregate_feed_gaps(
    coverage_results: List[CoverageResult],
) -> Dict[str, Any]:
    """Aggregate coverage results across all stocks.

    Returns a summary dict:
      {
        "total_stocks": N,
        "fully_covered": M,
        "by_feed": {
          "nse_financials": {
            "stocks_with_gaps": K,
            "fields": {
              "roe_pct": {"missing_count": X, "missing_pct": Y}
            }
          },
          ...
        },
        "by_field": {
          "roe_pct": {"missing_count": X, "missing_pct": Y, "feed": "nse_financials"}
        }
      }
    """
    total = len(coverage_results)
    fully_covered = sum(1 for r in coverage_results if not r.missing)

    # Count per-field misses
    field_miss: Dict[str, int] = {}
    for r in coverage_results:
        for f in r.missing:
            field_miss[f] = field_miss.get(f, 0) + 1

    # Build by_feed summary
    by_feed: Dict[str, Any] = {}
    by_field: Dict[str, Any] = {}
    for field_name, miss_count in sorted(field_miss.items(), key=lambda x: -x[1]):
        feed = FEED_MAP.get(field_name, "unknown")
        pct = round(100.0 * miss_count / total, 1) if total else 0.0
        by_field[field_name] = {
            "missing_count": miss_count,
            "missing_pct": pct,
            "feed": feed,
        }
        by_feed.setdefault(feed, {"stocks_with_gaps": 0, "fields": {}})
        by_feed[feed]["fields"][field_name] = {
            "missing_count": miss_count,
            "missing_pct": pct,
        }

    # Count stocks with at least one gap per feed
    for r in coverage_results:
        seen_feeds: set = set()
        for mf, fields in r.missing_by_feed.items():
            if fields and mf not in seen_feeds:
                by_feed.setdefault(mf, {"stocks_with_gaps": 0, "fields": {}})
                by_feed[mf]["stocks_with_gaps"] += 1
                seen_feeds.add(mf)

    return {
        "total_stocks":    total,
        "fully_covered":   fully_covered,
        "coverage_pct":    round(100.0 * fully_covered / total, 1) if total else 0.0,
        "by_feed":         by_feed,
        "by_field":        by_field,
    }
