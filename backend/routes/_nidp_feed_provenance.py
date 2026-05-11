"""NIDP Feed Provenance Metadata.

Static provenance + retrieval + validation metadata for every feed in
the NIDP data catalog. Joined with live coverage stats from the VM's
`/v1/catalog` endpoint to produce the Backfill Readiness Matrix.

Each feed declares:
  - source         : Official archive provider (NSE / BSE / AMFI / RBI / SEBI / FRED / Derived)
  - source_url     : Direct link to the official archive landing page
  - retrieval      : How the orchestrator pulls it (archive_bhavcopy / api_json / scraper / derived)
  - ingester       : The `python -m nidp.services.<name>` module that ingests it
  - cadence        : daily / weekly / monthly / quarterly / event-driven / one-shot
  - depth          : How far back the official archive offers (humanized)
  - validation     : Domain rules applied at quality_gate time
  - criticality    : MANDATORY (blocks certification) | RECOMMENDED | OPTIONAL
  - notes          : Free-text caveats — e.g. "NSE moved to JSON, no archive"

Coverage classification (computed at request time from catalog stats):
  - GOLD     : coverage_pct >= 0.95 over the target window
  - SILVER   : coverage_pct >= 0.80
  - PARTIAL  : coverage_pct >= 0.50
  - GAPS     : coverage_pct >  0
  - EMPTY    : coverage_pct == 0
"""
from __future__ import annotations

from typing import Any, Dict


PROVENANCE: Dict[str, Dict[str, Any]] = {
    # ── Market data (NSE bhavcopy archives) ───────────────────────────
    "prices_eod": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/all-reports#cm",
        "retrieval":   "archive_bhavcopy",
        "ingester":    "bhavcopy",
        "cadence":     "daily",
        "depth":       "20+ years",
        "validation":  ["non_null_close", "ohlc_consistency", "volume_non_negative", "symbol_in_master"],
        "criticality": "MANDATORY",
        "notes":       "EOD bhavcopy CSV. ~1900 symbols/day, ~30 KB compressed.",
    },
    "prices_eod_adjusted": {
        "source":      "NSE+derived",
        "source_url":  "internal:price_adjuster",
        "retrieval":   "derived",
        "ingester":    "price_adjuster",
        "cadence":     "daily",
        "depth":       "regenerable from prices_eod + corporate_actions",
        "validation":  ["adj_factor_positive", "tr_>=pr"],
        "criticality": "RECOMMENDED",
        "notes":       "Derived from prices_eod × corporate_actions. Re-runnable.",
    },
    "delivery_data": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/all-reports#cm",
        "retrieval":   "archive_bhavcopy",
        "ingester":    "delivery",
        "cadence":     "daily",
        "depth":       "10+ years",
        "validation":  ["delivery_pct_in_0_100", "delivery_qty<=traded_qty"],
        "criticality": "MANDATORY",
    },
    "index_eod": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/all-reports#cm",
        "retrieval":   "archive_bhavcopy",
        "ingester":    "index_close",
        "cadence":     "daily",
        "depth":       "20+ years",
        "validation":  ["ohlc_consistency", "non_null_close", "index_in_whitelist"],
        "criticality": "MANDATORY",
    },
    "fno_bhavcopy": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/all-reports#derivatives",
        "retrieval":   "archive_bhavcopy",
        "ingester":    "fno_bhavcopy",
        "cadence":     "daily",
        "depth":       "15+ years",
        "validation":  ["expiry_>=trade_date", "strike_positive", "oi_non_negative"],
        "criticality": "MANDATORY",
        "notes":       "F&O CSV; ~80k rows/day across futures + options strikes.",
    },
    # ── Flows & events ────────────────────────────────────────────────
    "fii_dii_flows": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/reports/fii-dii",
        "retrieval":   "api_json",
        "ingester":    "fii_dii",
        "cadence":     "daily",
        "depth":       "rolling ~60 days (archive removed)",
        "validation":  ["net_value=buy-sell"],
        "criticality": "RECOMMENDED",
        "notes":       "NSE moved this to a rolling JSON API in 2023; historical archive not reachable.",
    },
    "bulk_deals": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/market-data/bulk-deals",
        "retrieval":   "api_json",
        "ingester":    "bulk_deals",
        "cadence":     "rolling",
        "depth":       "multi-year",
        "validation":  ["price_positive", "qty_positive", "client_in_known_or_other"],
        "criticality": "RECOMMENDED",
    },
    "block_deals": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/market-data/block-deals",
        "retrieval":   "api_json",
        "ingester":    "block_deals",
        "cadence":     "rolling",
        "depth":       "multi-year",
        "validation":  ["price_positive", "qty_positive"],
        "criticality": "RECOMMENDED",
    },
    "corporate_actions": {
        "source":      "NSE+BSE",
        "source_url":  "https://www.nseindia.com/companies-listing/corporate-filings-actions",
        "retrieval":   "api_json",
        "ingester":    "corporate_actions",
        "cadence":     "rolling",
        "depth":       "10+ years",
        "validation":  ["ex_date_in_past_or_near_future", "purpose_in_known_set"],
        "criticality": "MANDATORY",
        "notes":       "Drives prices_eod_adjusted; missing CA → adjustment errors.",
    },
    # ── Reference ─────────────────────────────────────────────────────
    "index_constituents": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/products-services/indices-equity",
        "retrieval":   "scraper",
        "ingester":    "index_constituents",
        "cadence":     "monthly",
        "depth":       "current + rebalance snapshots",
        "validation":  ["weight_sum_~1.0", "symbol_in_master"],
        "criticality": "RECOMMENDED",
    },
    "nse_holidays": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/resources/exchange-communication-holidays",
        "retrieval":   "api_json",
        "ingester":    "nse_calendar",
        "cadence":     "one-shot",
        "depth":       "current year + next year",
        "validation":  ["unique_per_segment_day"],
        "criticality": "MANDATORY",
        "notes":       "Drives trading_day filter — required before any per-day backfill.",
    },
    "sector_master": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/market-data/securities-available-for-trading",
        "retrieval":   "scraper",
        "ingester":    "nse_equity_master",
        "cadence":     "weekly",
        "depth":       "current snapshot",
        "validation":  ["isin_format", "face_value_positive"],
        "criticality": "MANDATORY",
    },
    # ── Fundamentals ──────────────────────────────────────────────────
    "nse_financials_quarterly": {
        "source":      "NSE+MCA",
        "source_url":  "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
        "retrieval":   "scraper",
        "ingester":    "nse_financials",
        "cadence":     "quarterly",
        "depth":       "5+ years",
        "validation":  ["pat<=revenue", "period_end_in_past"],
        "criticality": "OPTIONAL",
        "notes":       "XBRL filings; rolling ~45 days after each quarter end.",
    },
    "shareholding_pattern": {
        "source":      "NSE",
        "source_url":  "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
        "retrieval":   "scraper",
        "ingester":    "nse_shareholding",
        "cadence":     "quarterly",
        "depth":       "5+ years",
        "validation":  ["pct_sum_~100", "no_negative_pct"],
        "criticality": "OPTIONAL",
    },
    # ── Macro ─────────────────────────────────────────────────────────
    "rbi_yields": {
        "source":      "RBI",
        "source_url":  "https://www.rbi.org.in/Scripts/PublicationsView.aspx?id=21833",
        "retrieval":   "scraper",
        "ingester":    "rbi_yields",
        "cadence":     "daily",
        "depth":       "decades",
        "validation":  ["yield_in_0_30_pct", "tenor_in_known_set"],
        "criticality": "MANDATORY",
    },
    "fred_macro": {
        "source":      "FRED",
        "source_url":  "https://fred.stlouisfed.org/",
        "retrieval":   "api_json",
        "ingester":    "fred_macro",
        "cadence":     "daily",
        "depth":       "50+ years",
        "validation":  ["series_in_whitelist"],
        "criticality": "RECOMMENDED",
        "notes":       "FRED API key in env. US10Y, DXY, VIX, FFR etc.",
    },
    # ── Disclosure ────────────────────────────────────────────────────
    "corporate_announcements": {
        "source":      "NSE+BSE",
        "source_url":  "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        "retrieval":   "scraper",
        "ingester":    "corporate_announcements",
        "cadence":     "rolling",
        "depth":       "multi-year",
        "validation":  ["filed_at_in_past", "category_classified"],
        "criticality": "RECOMMENDED",
    },
    # ── Derived ───────────────────────────────────────────────────────
    "stock_features_daily": {
        "source":      "derived",
        "source_url":  "internal:feature_snapshotter",
        "retrieval":   "derived",
        "ingester":    "feature_snapshotter",
        "cadence":     "daily",
        "depth":       "regenerable from prices_eod",
        "validation":  ["sma_>=0", "rsi_in_0_100"],
        "criticality": "RECOMMENDED",
        "notes":       "Re-computable; lazy-regen after backfill.",
    },
    "market_daily_snapshot": {
        "source":      "derived",
        "source_url":  "internal:snapshot_builder",
        "retrieval":   "derived",
        "ingester":    "snapshot_builder",
        "cadence":     "daily",
        "depth":       "regenerable",
        "validation":  ["breadth_in_known_range"],
        "criticality": "OPTIONAL",
    },
    "stock_daily_snapshot": {
        "source":      "derived",
        "source_url":  "internal:snapshot_builder",
        "retrieval":   "derived",
        "ingester":    "snapshot_builder",
        "cadence":     "daily",
        "depth":       "regenerable",
        "validation":  ["non_null_close"],
        "criticality": "OPTIONAL",
    },
    # ── Intelligence layer (derived) ─────────────────────────────────
    "intelligence_security_master": {
        "source":      "derived",
        "source_url":  "internal:intelligence_layer",
        "retrieval":   "derived",
        "ingester":    "intelligence_layer",
        "cadence":     "weekly",
        "depth":       "current snapshot",
        "validation":  ["isin_format", "domain_in_known_set"],
        "criticality": "OPTIONAL",
    },
    "intelligence_quality_scores": {
        "source":      "derived",
        "source_url":  "internal:quality_gate",
        "retrieval":   "derived",
        "ingester":    "quality_gate",
        "cadence":     "daily",
        "depth":       "since dq.expectations_active enabled",
        "validation":  ["score_in_0_100"],
        "criticality": "OPTIONAL",
    },
    "intelligence_stock_features_daily": {
        "source":      "derived",
        "source_url":  "internal:intelligence_layer",
        "retrieval":   "derived",
        "ingester":    "intelligence_layer",
        "cadence":     "daily",
        "depth":       "regenerable",
        "validation":  ["beta_in_minus5_plus5"],
        "criticality": "OPTIONAL",
    },
    "intelligence_entity_links": {
        "source":      "derived",
        "source_url":  "internal:intelligence_layer",
        "retrieval":   "derived",
        "ingester":    "intelligence_layer",
        "cadence":     "monthly",
        "depth":       "current graph",
        "validation":  ["edge_weight_in_0_1"],
        "criticality": "OPTIONAL",
    },
    "intelligence_correlations": {
        "source":      "derived",
        "source_url":  "internal:intelligence_layer",
        "retrieval":   "derived",
        "ingester":    "intelligence_layer",
        "cadence":     "weekly",
        "depth":       "rolling window",
        "validation":  ["rho_in_minus1_plus1"],
        "criticality": "OPTIONAL",
    },
    "intelligence_normalized_events": {
        "source":      "derived",
        "source_url":  "internal:event_analyzer",
        "retrieval":   "derived",
        "ingester":    "event_analyzer",
        "cadence":     "event-driven",
        "depth":       "since events.normalized_events seeded",
        "validation":  ["event_type_in_taxonomy"],
        "criticality": "OPTIONAL",
    },
    "intelligence_market_snapshot": {
        "source":      "derived",
        "source_url":  "internal:market_intelligence",
        "retrieval":   "derived",
        "ingester":    "market_intelligence",
        "cadence":     "daily",
        "depth":       "regenerable",
        "validation":  ["regime_in_known_set"],
        "criticality": "OPTIONAL",
    },
    "intelligence_portfolio_snapshot": {
        "source":      "derived",
        "source_url":  "internal:portfolio_intelligence_sync",
        "retrieval":   "derived",
        "ingester":    "portfolio_intelligence_sync",
        "cadence":     "event-driven",
        "depth":       "per-user",
        "validation":  ["weights_sum_~1.0"],
        "criticality": "OPTIONAL",
    },
    "intelligence_portfolio_holdings": {
        "source":      "derived",
        "source_url":  "internal:portfolio_intelligence_sync",
        "retrieval":   "derived",
        "ingester":    "portfolio_intelligence_sync",
        "cadence":     "event-driven",
        "depth":       "per-user",
        "validation":  ["units_positive"],
        "criticality": "OPTIONAL",
    },
    # ── Mutual Funds ──────────────────────────────────────────────────
    "mf_scheme_master": {
        "source":      "AMFI",
        "source_url":  "https://www.amfiindia.com/spages/NAVAll.txt",
        "retrieval":   "api_text",
        "ingester":    "amfi_nav",
        "cadence":     "daily",
        "depth":       "current snapshot",
        "validation":  ["isin_format", "amc_in_master"],
        "criticality": "MANDATORY",
    },
    "mf_nav_daily": {
        "source":      "AMFI",
        "source_url":  "https://portal.amfiindia.com/NavHistoryReport_Po.aspx",
        "retrieval":   "api_text",
        "ingester":    "amfi_nav_history",
        "cadence":     "daily",
        "depth":       "10+ years",
        "validation":  ["nav_positive", "nav_date_in_past", "scheme_in_master"],
        "criticality": "MANDATORY",
        "notes":       "20-year AMFI history available; reliable backfill source.",
    },
    "mf_holdings_monthly": {
        "source":      "AMC SID PDFs",
        "source_url":  "internal:mf_holdings (scrapes each AMC's monthly SID)",
        "retrieval":   "scraper",
        "ingester":    "mf_holdings",
        "cadence":     "monthly",
        "depth":       "rolling 12 months for top-10 AMCs",
        "validation":  ["weight_in_0_100", "isin_format_or_OTHER"],
        "criticality": "RECOMMENDED",
    },
    "mf_scheme_events": {
        "source":      "derived",
        "source_url":  "internal:amfi_circulars + mf_disclosure_snapshot",
        "retrieval":   "derived",
        "ingester":    "mf_disclosure_snapshot",
        "cadence":     "event-driven",
        "depth":       "since circular sync enabled",
        "validation":  ["event_type_in_taxonomy"],
        "criticality": "OPTIONAL",
    },
    "mf_scheme_disclosure_snapshot": {
        "source":      "AMC SID pages",
        "source_url":  "internal:mf_disclosure_snapshot",
        "retrieval":   "scraper",
        "ingester":    "mf_disclosure_snapshot",
        "cadence":     "weekly",
        "depth":       "rolling snapshots",
        "validation":  ["ter_in_0_5_pct"],
        "criticality": "RECOMMENDED",
    },
    "mf_amfi_circulars": {
        "source":      "AMFI",
        "source_url":  "https://www.amfiindia.com/research-information/amfi-circulars",
        "retrieval":   "scraper",
        "ingester":    "amfi_circulars",
        "cadence":     "rolling",
        "depth":       "multi-year",
        "validation":  ["published_at_in_past"],
        "criticality": "OPTIONAL",
    },
}


def for_feed(name: str) -> Dict[str, Any]:
    """Returns provenance dict for `name`, or an UNKNOWN stub if not registered."""
    p = PROVENANCE.get(name)
    if p:
        return p
    return {
        "source":      "UNKNOWN",
        "source_url":  None,
        "retrieval":   "unknown",
        "ingester":    None,
        "cadence":     "unknown",
        "depth":       "unknown",
        "validation":  [],
        "criticality": "OPTIONAL",
        "notes":       "Not registered in provenance map.",
    }


def certify(coverage_pct: float | None) -> str:
    """Map a coverage percentage (0..1) to a certification tier."""
    if coverage_pct is None:
        return "UNKNOWN"
    if coverage_pct >= 0.95:
        return "GOLD"
    if coverage_pct >= 0.80:
        return "SILVER"
    if coverage_pct >= 0.50:
        return "PARTIAL"
    if coverage_pct > 0:
        return "GAPS"
    return "EMPTY"
