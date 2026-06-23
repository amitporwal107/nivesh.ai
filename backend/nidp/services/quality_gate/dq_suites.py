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
            E.not_null("symbol", "period_end", "period_type", "consolidated"),
            # CORRECTION 1: real UNIQUE is (symbol, period_end, consolidated) — NO period_type.
            # Keeping period_type in the key would mask the quarterly/QUARTERLY case-dupe.
            E.compound_unique("symbol", "period_end", "consolidated",
                              note="tracks real UNIQUE; omits period_type so case-dupes surface"),
            # CORRECTION 2: casing split is systemic (~15k rows). Membership is
            # case-insensitive (data is semantically valid -> pass); canonical
            # casing is a separate WARN (early warning for the view's defensive ILIKE).
            E.in_set("period_type", {"annual", "quarterly"}, case_insensitive=True),
            E.canonical_casing("period_type", canonical="lower", severity="warn"),
            E.same_sign("eps_basic", "pat_cr"),                  # EPS & PAT same sign
            E.pair_a_lte_b("pat_cr", "revenue_from_ops_cr"),     # PAT <= revenue
            E.not_in_future("period_end"),
            E.freshness("period_end", cal, max_lag_trading_days=2, severity="warn"),
            # The doubled-PAT guard; flow metrics only, case-insensitive period_type.
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
            # NOTE: in Indian filings fii/dii are typically WITHIN public, so the safe
            # identity is promoter + public ~= 100. If your schema treats fii/dii as
            # disjoint, switch to [promoter,public,fii,dii]. WARN-level pending that check.
            E.columns_sum_to(["promoter_pct", "public_pct"], target=100, tol=1.5, severity="warn"),
            E.not_in_future("period_end"),
        ],
        description="shareholding; source-mixing dupes were the bug",
    )


# ===========================================================================
# 3. mf_holdings_monthly
# ===========================================================================
def mf_holdings_suite(cal: TradingCalendar) -> Suite:
    cols = ["scheme_code", "as_of_month", "security_isin", "security_name",
            "instrument_type", "weight_pct", "source"]
    return Suite(
        asset="mf_holdings_monthly", ingester="mf_holdings",
        # CORRECTION/FIX: grouped weight-sum needs the FULL latest month, not a LIMIT.
        fetch=FeedQuery("nidp.mf_holdings_monthly", cols,
                        scope="latest_period", period_col="as_of_month"),
        rules=[
            E.not_null("scheme_code", "as_of_month", "security_name", "weight_pct"),
            E.compound_unique("scheme_code", "as_of_month", "security_name", "source",
                              note="matches real PK"),
            # weight_pct real range is -20.9..412.8: lower bound ADMITS shorts (negative),
            # upper bound flags the 412 NIPPON single-row corruption.
            E.between("weight_pct", min=-25, max=100),
            E.match_regex("security_isin", E.ISIN_REGEX, allow_blank=True),
            # instrument_type is 94% blank -> allow_blank; enum only on the non-blank tail.
            E.in_set("instrument_type", {"DEBT", "CASH", "OTHER", "REIT", "DERIVATIVE"},
                     allow_blank=True),
            E.no_subtotal_rows("security_name"),                 # NIPPON/SBI subtotal rows
            # The NIPPON guard: per-scheme weight-sum ~= 100 (sees full month via fetch scope).
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
    }
