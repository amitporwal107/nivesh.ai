"""
nidp_suites — declarative DQ suites, schema-grounded against the real columns.

Each Suite carries:
  - asset / ingester           (-> validation_findings.ingester, v_feed_status)
  - fetch (FeedQuery)          (-> the FEED_QUERIES entry: how the runner pulls data)
  - rules                      (the reviewed list the gate executes)

The four schema-forced CORRECTIONS are marked  # CORRECTION  inline and each has
a regression test in test_nidp_dq.py:
  1. nse_financials uniqueness drops period_type  (real UNIQUE is symbol,period_end,consolidated)
  2. period_type: case-insensitive membership (pass) + canonical-casing (warn)
  3. shareholding uniqueness deliberately tighter than the PK (drops source)
  4. fii_dii domain corrected to {FII, DII}; band allows blank
Plus the mf_holdings grouped weight-sum is scoped to the latest as_of_month
(FeedQuery.scope='latest_period') so it sees the whole month, not a sampled limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .dq_primitives import TradingCalendar
from . import dq_rules as E
from . import dq_guards as G


# ---------------------------------------------------------------------------
# FEED_QUERIES entry — how the runner fetches a batch for an asset
# ---------------------------------------------------------------------------
@dataclass
class FeedQuery:
    table: str
    columns: list
    date_col: Optional[str] = None
    scope: str = "recent"            # "recent" | "latest_period" | "all"
    period_col: Optional[str] = None  # required for scope="latest_period"
    limit: int = 200_000

    def to_sql(self) -> str:
        cols = ", ".join(self.columns)
        if self.scope == "latest_period":
            # CRITICAL: grouped checks (weight-sum per scheme) need ALL rows of the
            # latest period, never a truncated LIMIT — otherwise the sum is partial
            # and the NIPPON guard silently passes.
            assert self.period_col, "latest_period scope requires period_col"
            return (f"SELECT {cols} FROM {self.table} "
                    f"WHERE {self.period_col} = (SELECT max({self.period_col}) FROM {self.table})")
        if self.scope == "all":
            return f"SELECT {cols} FROM {self.table}"
        order = f" ORDER BY {self.date_col} DESC" if self.date_col else ""
        return f"SELECT {cols} FROM {self.table}{order} LIMIT {self.limit}"


@dataclass
class Suite:
    asset: str
    ingester: str
    fetch: FeedQuery
    rules: list
    description: str = ""

    @property
    def required_columns(self) -> list:
        return list(self.fetch.columns)


# A small NSE holiday set; in production load from nidp.nse_holidays.
def trading_calendar(holidays=None) -> TradingCalendar:
    return TradingCalendar(holidays or set())


# ===========================================================================
# 1. nse_financials_quarterly
# ===========================================================================
def nse_financials_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "period_end", "period_type", "consolidated",
            "pat_cr", "eps_basic", "eps_diluted", "revenue_from_ops_cr"]
    return Suite(
        asset="nse_financials_quarterly", ingester="nse_financials",
        fetch=FeedQuery("nidp.nse_financials_quarterly", cols, date_col="period_end"),
        rules=[
            E.not_null("symbol", "period_end", "consolidated"),
            # CORRECTION 1: real UNIQUE is (symbol, period_end, consolidated) — NO period_type.
            E.compound_unique("symbol", "period_end", "consolidated",
                              note="tracks real UNIQUE; omits period_type so case-dupes surface"),
            # CORRECTION 2 (recalibrated): three LIVE literals confirmed in data
            # {annual, quarterly, QUARTERLY}. Membership allows all three as-is — the
            # view depends on 'QUARTERLY' (ILIKE leg) AND 'annual' (exact leg), so
            # upstream normalization is BLOCKED until the view is fixed too.
            E.in_set("period_type", {"annual", "quarterly", "QUARTERLY"}),
            E.canonical_casing("period_type", canonical="lower", severity="warn"),
            # CORRECTION (real-data): same-sign is WARN, NULLs excluded, ~1% legit
            # exceptions (22/2384 minority-interest cases). Do NOT hard-fail.
            E.same_sign("eps_basic", "pat_cr", severity="warn"),
            # PAT <= revenue is violated legitimately by banks/NBFCs/holdcos (revenue_from_ops
            # excludes interest/investment income) -> warn, not fail.
            E.pair_a_lte_b("pat_cr", "revenue_from_ops_cr", severity="warn"),
            E.not_in_future("period_end"),
            # QUARTERLY feed: latest filed quarter is normally 1-4 months old (next quarter-end
            # + ~45-day filing window). A daily-feed lag false-positives; allow a quarter +
            # filing slack (~110 trading days) before flagging genuinely stale.
            E.freshness("period_end", cal, max_lag_trading_days=110, severity="warn"),
            # doubled-PAT guard -> BLOCK action (must not propagate to scoring)
            E.q4_annual_contamination(
                ["pat_cr", "revenue_from_ops_cr"],
                period_type_col="period_type", consolidated_col="consolidated"),
        ],
        description="fundamentals; where the Q4-contamination + casing bugs live",
    )


# ===========================================================================
# 2. shareholding_pattern
# ===========================================================================
def shareholding_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "period_end", "source",
            "promoter_pct", "fii_pct", "dii_pct", "public_pct", "promoter_pledged_pct"]
    return Suite(
        asset="shareholding_pattern", ingester="nse_shareholding",
        fetch=FeedQuery("nidp.shareholding_pattern", cols, date_col="period_end"),
        rules=[
            E.not_null("symbol", "period_end"),
            # CORRECTION 3: real PK is (symbol, period_end, source) — source IS in the key,
            # which is exactly why NSE + Screener both land. This check is DELIBERATELY
            # tighter than the PK (drops source) to catch the multi-source dupe.
            E.compound_unique("symbol", "period_end",
                              note="INTENTIONALLY tighter than PK: drops 'source' to catch source-mixing dupes"),
            E.between("promoter_pct", min=0, max=100),
            E.between("fii_pct", min=0, max=100),
            E.between("dii_pct", min=0, max=100),
            E.between("public_pct", min=0, max=100),
            E.between("promoter_pledged_pct", min=0, max=100),
            E.pair_a_lte_b("promoter_pledged_pct", "promoter_pct"),  # pledge <= promoter
            # CONFIRMED 2-column: public_pct is the all-non-promoter aggregate; fii/dii
            # are SUBSETS of it. Clean rows show promoter+public = 99.96 (97.27–100.00).
            # public_pct is contaminated (max 9904) so this check IS the corruption
            # detector — it fires on exactly the violators. tol from clean-row range.
            E.columns_sum_to(["promoter_pct", "public_pct"], target=100, tol=3.0, severity="fail"),
            # Tripwire for v_shareholding_latest's nondeterministic pick: source is in
            # the table PK but NOT in the view's partition, so >1 source per
            # (symbol, period_end) makes "latest" a coin-flip. Durable fix is a
            # deterministic tiebreak IN THE VIEW; this surfaces how often we're rolling.
            G.single_source_per_key(["symbol", "period_end"], "source", severity="warn"),
            E.not_in_future("period_end"),
        ],
        description="shareholding; source-mixing dupes were the bug",
    )


# ===========================================================================
# 3. mf_holdings_monthly
# ===========================================================================
def mf_holdings_suite(cal: TradingCalendar) -> Suite:
    cols = ["scheme_code", "as_of_month", "security_isin", "security_name",
            "instrument_type", "weight_pct", "rating", "source"]
    return Suite(
        asset="mf_holdings_monthly", ingester="mf_holdings",
        # CORRECTION/FIX: grouped weight-sum needs the FULL latest month, not a LIMIT.
        fetch=FeedQuery("nidp.mf_holdings_monthly", cols,
                        scope="latest_period", period_col="as_of_month"),
        rules=[
            E.not_null("scheme_code", "as_of_month", "security_name"),
            # weight_pct is blank for a few legitimately-disclosed holdings (delisted
            # /written-off names like Manpasand Beverages, some InvIT lines) — flag as
            # coverage (WARN), not a hard failure. grouped_sum is the real weight gate.
            E.not_null("weight_pct", severity="warn"),
            # Uniqueness key matches migration 113: security_isin is part of the key
            # so distinct instruments sharing an issuer NAME (e.g. 4 Kotak Securities
            # CPs with 4 ISINs) are not flagged as duplicates.
            E.compound_unique("scheme_code", "as_of_month", "security_name",
                              "security_isin", "source", note="matches real uniqueness key"),
            # CORRECTION (real-data): 336 legit lines >100 (index-future/derivative
            # notionals, e.g. "Nifty Index" = 412.81; stale single-stock lines). A
            # per-line cap is WRONG. Lower bound admits the 5,179 legit shorts (min
            # -20.91). The per-SCHEME sum is the real guard. >100 is WARN-only signal.
            E.between("weight_pct", min=-25, max=None, severity="warn"),
            E.match_regex("security_isin", E.ISIN_REGEX, allow_blank=True),
            # instrument_type domain spans two writer vintages: the older AMFI codes
            # {STO,IDO,STF,IDF} and the current per-source XLSX labels {DEBT,CASH,REIT,
            # EQUITY} (verified live in staging: 4780 DEBT / 530 CASH / 495 REIT, ~95%
            # blank). All are legitimate asset classes — the prior set flagged 5,805
            # valid rows. Superset keeps both vintages so neither env false-positives.
            E.in_set("instrument_type",
                     {"STO", "IDO", "STF", "IDF", "DEBT", "CASH", "REIT", "EQUITY",
                      "DERIVATIVE", "OTHER"},
                     allow_blank=True),
            E.no_subtotal_rows("security_name", isin_col="security_isin"),  # exempt real securities
            # rating is 100% NULL (all 242,614 rows) — credit checks have nothing to
            # read. Surface as a coverage finding; max_rate=1.0 today, lower once built.
            G.null_rate_within("rating", max_rate=1.0, severity="info"),
            # The NIPPON guard: per-scheme weight-sum ~= 100 (full month via fetch scope).
            E.grouped_sum_between(["scheme_code"], "weight_pct", min=98, max=102),
            E.not_in_future("as_of_month"),
        ],
        description="MF holdings; NIPPON 224% weight-sum + subtotal rows were the bug",
    )


def build_suites(cal: Optional[TradingCalendar] = None) -> dict:
    cal = cal or trading_calendar()
    return {
        "nse_financials": nse_financials_suite(cal),
        "shareholding": shareholding_suite(cal),
        "mf_holdings": mf_holdings_suite(cal),
        # Group 1 — scoring / contamination chains
        "v3_stock_scores": v3_stock_scores_suite(cal),
        "v3_mf_scores": v3_mf_scores_suite(cal),
        "mf_derived_analytics": mf_derived_analytics_suite(cal),
        # Group 3-4 — baselines
        "nse_financials_cashflow": nse_financials_cashflow_suite(cal),
        "bank_metrics": bank_metrics_suite(cal),
        "bank_quality_scores": bank_quality_scores_suite(cal),
        "mf_category_rank": mf_category_rank_suite(cal),
        "mf_rolling_returns": mf_rolling_returns_suite(cal),
        "rbi_yields": rbi_yields_suite(cal),
        "fred_macro": fred_macro_suite(cal),
        "event_calendar": event_calendar_suite(cal),
        "documents": documents_suite(cal),
        "prices_eod_adjusted": prices_eod_adjusted_suite(cal),
        "fund_category_rank": fund_category_rank_suite(cal),
    }


# ===========================================================================
# Group 1 — scoring / contamination chains
# ===========================================================================
def v3_stock_scores_suite(cal: TradingCalendar) -> Suite:
    # PK (as_of_date, symbol); engine_version NOT in key.
    cols = ["as_of_date", "symbol", "final_score", "quality_score", "health_score",
            "technical_score", "quality_coverage_pct", "health_coverage_pct",
            "band", "status", "sector_profile", "market_cap_bucket"]
    return Suite(
        asset="v3_stock_scores_daily", ingester="v3_scores_engine",
        # scope to the latest as_of_date: validate TODAY's scores, not 90 days of history.
        # (A 'recent' limit reached back into pre-band runs and reported a misleading 90%
        #  null-band; current dates are ~0% null.)
        fetch=FeedQuery("nidp.v3_stock_scores_daily", cols,
                        scope="latest_period", period_col="as_of_date"),
        rules=[
            E.not_null("as_of_date", "symbol"),
            E.compound_unique("as_of_date", "symbol", note="PK; engine_version not in key"),
            # scores bounded [0,100]; ~11% NULL (gate-failure rows) -> nulls pass bound
            E.between("final_score", min=0, max=100),
            E.between("quality_score", min=0, max=100),
            E.between("health_score", min=0, max=100),
            E.between("quality_coverage_pct", min=0, max=100),
            E.between("health_coverage_pct", min=0, max=100),
            # NOTE: for STOCKS, quality_score and health_score are INTENTIONAL
            # backward-compat mirrors of final_score / technical_score (the v3 table is
            # shared with MF; the engine sets them deliberately —
            # v3_scores_engine/service.py:439-441,498-502). They are SUPPOSED to be
            # identical, so no columns_not_identical guard here — it was a false positive
            # flagging the documented alias as a defect. The real distinct stock metrics
            # are fundamental_score / technical_score / final_score.
            # band: blank is NULL (not ''). not_null is NOT asserted; in_set allows NULL.
            E.in_set("band", {"HOLD", "REDUCE", "BUY", "AVOID", "STRONG_BUY"}, allow_blank=True),
            E.in_set("status", {"gate_failed", "ranked", "low_confidence",
                                "insufficient_coverage"}, allow_blank=True),
            E.in_set("sector_profile", {"DEFAULT", "CYCLICAL", "NBFC", "CAPGOODS",
                                        "PHARMA", "FMCG", "IT", "BANK"}, allow_blank=True),
            E.in_set("market_cap_bucket", {"LARGE_CAP", "MID_CAP", "SMALL_CAP", "MICRO_CAP"},
                     allow_blank=True),
            # band NULL-rate baseline ~13%; a jump = engine emitting NULL en masse
            G.null_rate_within("band", max_rate=0.25, severity="warn"),
            E.freshness("as_of_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="V3 equity scores; funnel both buggy fundamental feeds pass through",
    )


def v3_mf_scores_suite(cal: TradingCalendar) -> Suite:
    # PK (as_of_date, isin); scheme_code is a NON-key attribute -> fan-out risk.
    # real columns: quality_coverage_pct / health_coverage_pct (no single coverage_pct).
    cols = ["as_of_date", "isin", "scheme_code", "fund_category",
            "quality_score", "health_score", "quality_coverage_pct", "health_coverage_pct"]
    return Suite(
        asset="v3_mf_scores_daily", ingester="v3_scores_engine",
        fetch=FeedQuery("nidp.v3_mf_scores_daily", cols, date_col="as_of_date"),
        rules=[
            E.not_null("as_of_date", "isin"),
            E.compound_unique("as_of_date", "isin", note="PK"),
            # DEFECT GUARD: one scheme_code per (isin, as_of_date), else the join to
            # holdings on scheme_code fans out silently.
            G.distinct_count_per_key(["isin", "as_of_date"], "scheme_code",
                                     max_distinct=1, severity="fail"),
            E.in_set("fund_category", {"equity", "debt", "liquid", "hybrid"}, allow_blank=True),
            E.between("quality_score", min=0, max=100),
            E.between("health_score", min=0, max=100),
            E.between("quality_coverage_pct", min=0, max=100),
            E.between("health_coverage_pct", min=0, max=100),
            E.freshness("as_of_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="V3 MF scores; isin-keyed with scheme_code fan-out risk",
    )


def mf_derived_analytics_suite(cal: TradingCalendar) -> Suite:
    # PK (scheme_code, as_of_date). The catalogue's named columns are 100% NULL on
    # dev AND staging -> data-gap, not access-gap. Completeness/freshness fire today;
    # validity bounds DEFERRED until the feed is built (depends on AMC holdings scrape).
    cols = ["scheme_code", "as_of_date", "credit_quality_score", "duration_risk_score",
            "consistency_score", "portfolio_ytm_pct", "modified_duration_years",
            "portfolio_turnover_pct"]
    return Suite(
        asset="mf_derived_analytics", ingester="mf_derived_refresh",
        fetch=FeedQuery("nidp.mf_derived_analytics", cols, date_col="as_of_date"),
        rules=[
            E.not_null("scheme_code", "as_of_date"),
            E.compound_unique("scheme_code", "as_of_date", note="PK"),
            # bounded where populated:
            E.between("duration_risk_score", min=1, max=10),      # 42% null
            E.between("consistency_score", min=0, max=10),        # 46% null
            E.between("portfolio_turnover_pct", min=0, max=2000, severity="warn"),  # tail to 18086
            # KNOWN-NULL coverage findings (max_rate=1.0 today; raise once feed built):
            G.null_rate_within("portfolio_ytm_pct", max_rate=1.0, severity="info"),
            G.null_rate_within("modified_duration_years", max_rate=1.0, severity="info"),
            G.null_rate_within("credit_quality_score", max_rate=1.0, severity="info"),
            E.freshness("as_of_date", cal, max_lag_trading_days=7, severity="warn"),
        ],
        description="MF debt analytics; named columns 100% NULL everywhere (feed not built)",
    )


# ===========================================================================
# Group 3-4 — baseline suites (completeness + validity + freshness)
# ===========================================================================
def nse_financials_cashflow_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "period_end", "consolidated", "cfo_cr", "capex_cr"]
    return Suite(
        asset="nse_financials_cashflow", ingester="nse_financials_backfill",
        fetch=FeedQuery("nidp.nse_financials_cashflow", cols, date_col="period_end"),
        rules=[
            E.not_null("symbol", "period_end", "consolidated"),
            E.compound_unique("symbol", "period_end", "consolidated", note="real UNIQUE"),
            E.between("cfo_cr", min=-80000, max=80000, severity="warn"),  # legit huge for banks
            G.null_rate_within("capex_cr", max_rate=1.0, severity="info"),  # 100% NULL today
            E.not_in_future("period_end"),
        ],
        description="cashflow baseline; capex_cr 100% NULL (coverage finding)",
    )


def bank_metrics_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "as_of_date", "gnpa_pct", "nnpa_pct", "coverage_pct", "gnpa_trend"]
    return Suite(
        asset="bank_metrics_daily", ingester="bank_scoring",
        fetch=FeedQuery("nidp.bank_metrics_daily", cols, date_col="as_of_date"),
        rules=[
            E.not_null("symbol", "as_of_date"),
            E.compound_unique("symbol", "as_of_date", note="real key"),
            E.between("gnpa_pct", min=0, max=100),
            E.between("nnpa_pct", min=0, max=100),
            E.between("coverage_pct", min=0, max=100),
            E.pair_a_lte_b("nnpa_pct", "gnpa_pct"),               # net <= gross NPA
            E.in_set("gnpa_trend", {"improving", "stable", "worsening"}, allow_blank=True),
            E.freshness("as_of_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="bank metrics baseline",
    )


def bank_quality_scores_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "as_of_date", "bank_quality_score"]
    return Suite(
        asset="bank_quality_scores_daily", ingester="bank_scoring",
        fetch=FeedQuery("nidp.bank_quality_scores_daily", cols, date_col="as_of_date"),
        rules=[
            E.not_null("symbol", "as_of_date"),
            E.compound_unique("symbol", "as_of_date", note="real key"),
            E.between("bank_quality_score", min=0, max=100),
            E.freshness("as_of_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="bank quality scores baseline",
    )


def mf_category_rank_suite(cal: TradingCalendar) -> Suite:
    # real columns: category_pct (not percentile); composite metric also present.
    cols = ["scheme_code", "rank_date", "sebi_category", "category_rank",
            "category_pct", "category_size", "status"]
    return Suite(
        asset="mf_category_rank_daily", ingester="mf_category_ranking",
        fetch=FeedQuery("nidp.mf_category_rank_daily", cols, date_col="rank_date"),
        rules=[
            E.not_null("scheme_code", "rank_date"),
            E.compound_unique("scheme_code", "rank_date", note="real key"),
            E.between("category_rank", min=1, max=None),
            E.between("category_pct", min=0, max=100),
            E.in_set("status", {"insufficient_history", "insufficient_coverage",
                                "ranked", "low_confidence"}, allow_blank=True),
            # ranks contiguous per (category, date) — grouped contiguity is a deeper
            # check; baseline keeps rank>=1 here and defers contiguity to Phase 3.
            E.freshness("rank_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="MF category rank baseline; sebi_category allow-set from dump (~35 values)",
    )


def mf_rolling_returns_suite(cal: TradingCalendar) -> Suite:
    # EMPTY on dev; populated on staging (95,403 rows). Calibrated from staging.
    cols = ["scheme_code", "as_of_date", "window_months", "positive_pct",
            "obs_count", "ret_p90", "ret_max"]
    return Suite(
        asset="mf_rolling_returns", ingester="mf_analytics_engine",
        fetch=FeedQuery("nidp.mf_rolling_returns", cols, date_col="as_of_date"),
        rules=[
            E.not_null("scheme_code", "as_of_date", "window_months"),
            E.compound_unique("scheme_code", "as_of_date", "window_months", note="real key"),
            E.in_set("window_months", {"12", "36", "60", 12, 36, 60}),
            E.between("positive_pct", min=0, max=100),
            E.between("obs_count", min=11, max=1439),
            # NAV-artifact tail: ret p99.9 ~900; treat > ~300 as corruption signal.
            E.between("ret_p90", min=-100, max=300, severity="warn"),
            E.between("ret_max", min=-100, max=300, severity="warn"),
            E.freshness("as_of_date", cal, max_lag_trading_days=7, severity="warn"),
        ],
        description="MF rolling returns; empty on dev, calibrated from staging NAV-artifact tail",
    )


def rbi_yields_suite(cal: TradingCalendar) -> Suite:
    cols = ["as_of_date", "tenor", "source", "yield_pct"]
    return Suite(
        asset="rbi_yields", ingester="rbi_yields",
        fetch=FeedQuery("nidp.rbi_yields", cols, date_col="as_of_date"),
        rules=[
            E.not_null("as_of_date", "tenor"),
            E.compound_unique("as_of_date", "tenor", "source", note="real key"),
            E.in_set("tenor", {"OVERNIGHT", "91D", "364D", "1Y", "10Y"}),
            E.between("yield_pct", min=0, max=20),
            # RBI yields publish ~weekly (not daily) -> allow ~2 weeks before flagging stale.
            E.freshness("as_of_date", cal, max_lag_trading_days=10, severity="warn"),
        ],
        description="RBI yields baseline (sparse, ~weekly)",
    )


def fred_macro_suite(cal: TradingCalendar) -> Suite:
    cols = ["as_of_date", "series_id", "source", "value"]
    return Suite(
        asset="fred_macro", ingester="fred_macro",
        fetch=FeedQuery("nidp.fred_macro", cols, date_col="as_of_date"),
        rules=[
            E.not_null("as_of_date", "series_id", "value"),
            E.compound_unique("as_of_date", "series_id", "source", note="real key"),
            # freshness intentionally lax: some FRED series legitimately lag months.
            E.freshness("as_of_date", cal, max_lag_trading_days=45, severity="warn"),
            E.not_in_future("as_of_date"),
        ],
        description="FRED macro baseline; some series lag legitimately",
    )


def event_calendar_suite(cal: TradingCalendar) -> Suite:
    cols = ["id", "symbol", "event_type", "event_date", "period", "source"]
    return Suite(
        asset="event_calendar", ingester="event_calendar",
        fetch=FeedQuery("nidp.event_calendar", cols, date_col="event_date"),
        rules=[
            E.not_null("symbol", "event_type", "event_date"),
            E.in_set("event_type", {"quarterly_results", "other", "dividend",
                                    "board_meeting", "buyback", "split", "bonus"}),
            E.in_set("source", {"nse"}),
        ],
        description="event calendar baseline",
    )


def documents_suite(cal: TradingCalendar) -> Suite:
    cols = ["doc_id", "source_url", "doc_type", "parse_status",
            "page_count", "text_size_chars"]
    return Suite(
        asset="documents", ingester="document_parser",
        fetch=FeedQuery("nidp.documents", cols),
        rules=[
            E.not_null("doc_id"),
            E.compound_unique("doc_id", note="PK"),
            E.in_set("doc_type", {"announcement_attachment"}),
            E.in_set("parse_status", {"failed", "parsed"}),
            # DEFECT: 99.99% parse failure. Floor fires permanently right now — the point.
            G.success_rate_floor("parse_status", {"parsed"}, min_rate=0.5, severity="warn"),
        ],
        description="documents; 99.99% parse-failure surfaced by the rate floor",
    )


def prices_eod_adjusted_suite(cal: TradingCalendar) -> Suite:
    cols = ["symbol", "as_of_date", "source", "adj_close", "adj_volume",
            "cumulative_adj_factor", "last_event_type"]
    return Suite(
        asset="prices_eod_adjusted", ingester="price_adjuster",
        fetch=FeedQuery("nidp.prices_eod_adjusted", cols, date_col="as_of_date"),
        rules=[
            E.not_null("symbol", "as_of_date", "adj_close"),
            E.compound_unique("symbol", "as_of_date", "source", note="real key"),
            E.between("adj_close", min=0, max=None, inclusive=False),  # >0; legit to 162k (MRF)
            E.between("adj_volume", min=0, max=None),                  # legit to 8.45B (index)
            E.between("cumulative_adj_factor", min=0, max=None, inclusive=False),
            E.in_set("last_event_type", {"DIVIDEND", "SPLIT", "BONUS"}, allow_blank=True),
            E.freshness("as_of_date", cal, max_lag_trading_days=2, severity="warn"),
        ],
        description="adjusted prices baseline; large values legit (MRF/index)",
    )


def fund_category_rank_suite(cal: TradingCalendar) -> Suite:
    cols = ["scheme_code", "rank_date", "return_1y", "sharpe_1y"]
    return Suite(
        asset="fund_category_rank", ingester="mf_category_ranking",
        fetch=FeedQuery("analytics.fund_category_rank", cols, date_col="rank_date"),
        rules=[
            E.not_null("scheme_code", "rank_date"),
            E.compound_unique("scheme_code", "rank_date", note="real key"),
            # right tail contaminated (return_1y to +900); flag the tail.
            E.between("return_1y", min=-100, max=300, severity="warn"),
            # DEFECT: sharpe_1y has a -99999.9999 sentinel. Exclude before bounding,
            # and flag the sentinel's presence (don't let it drag the min-bound).
            G.between_excluding_sentinels("sharpe_1y", min=-10, max=10,
                                          sentinels=(-99999.9999, -99999.99), severity="warn"),
            E.freshness("rank_date", cal, max_lag_trading_days=4, severity="warn"),
        ],
        description="analytics fund rank; sharpe_1y sentinel excluded before bounding",
    )
