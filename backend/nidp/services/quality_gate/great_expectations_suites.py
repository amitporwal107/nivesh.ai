"""Great-Expectations suites — one per NIDP feed.

The first 4 (amfi_nav, fii_dii, bhavcopy, index_close) come straight
from the user-supplied spec NIDP_Sample_Feed_Expectation_Rules.docx.

The remaining ~14 are pragmatic, domain-aware defaults (primary-key
uniqueness, date sanity, value bounds, format regex, enum guards) that
match what a production data-quality engineer would write at minimum.
They live in this file so they're reviewable as a single artifact and
can be exposed verbatim in the NIDP Console's Quality Gate page.
"""
from __future__ import annotations

from typing import Optional, Dict, Callable

from nidp.shared.expectations import Suite, expect


# ─────────────────────────────────────────────────────────────────
# 1. AMFI NAV Daily (NAVAll.txt)
# ─────────────────────────────────────────────────────────────────
def amfi_nav_suite(expected_date: Optional[str] = None) -> Suite:
    """Spec § 1 — `Scheme Code`, `Scheme Name`, `Net Asset Value`,
    `ISIN Div Payout/ISIN Growth`, `ISIN Div Reinvestment`, `Date`.

    Mapping to nidp.amfi_nav schema:
        Scheme Code                 → scheme_code
        Scheme Name                 → scheme_name
        Net Asset Value             → nav
        ISIN Div Payout/ISIN Growth → isin_payout
        ISIN Div Reinvestment       → isin_reinvest
        Date                        → as_of_date
    """
    s = Suite("amfi_nav.daily", feed="amfi_nav")
    s.add(expect.column_values_to_match_regex("scheme_code", r"^\d+$"))
    s.add(expect.column_values_to_be_not_null("scheme_code"))
    s.add(expect.column_values_to_be_not_null("scheme_name"))
    s.add(expect.column_values_to_be_between("nav", min_value=0, strict=True))
    s.add(expect.column_values_to_be_not_in_future("as_of_date"))
    s.add(expect.column_values_to_match_regex(
        "isin_payout",  r"^(-|INF[A-Z0-9]{9})$"))
    s.add(expect.column_values_to_match_regex(
        "isin_reinvest", r"^(-|INF[A-Z0-9]{9})$"))
    s.add(expect.compound_columns_to_be_unique(["scheme_code", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


# ─────────────────────────────────────────────────────────────────
# 2. FII / DII Flows (fii_dii.json)
# ─────────────────────────────────────────────────────────────────
def fii_dii_suite(expected_date: Optional[str] = None) -> Suite:
    """Spec § 2.

    Mapping to nidp.fii_dii schema:
        category   → category
        date       → as_of_date
        buyValue   → buy_value
        sellValue  → sell_value
        netValue   → net_value
    """
    s = Suite("fii_dii.daily", feed="fii_dii")
    s.add(expect.column_values_to_be_in_set("category", ["DII", "FII/FPI"]))
    s.add(expect.column_values_to_be_between("buy_value",  min_value=0, strict=False))
    s.add(expect.column_values_to_be_between("sell_value", min_value=0, strict=False))
    s.add(expect.column_pair_diff_equals_column(
        "buy_value", "sell_value", "net_value", tolerance=0.01))
    s.add(expect.column_values_to_be_not_in_future("as_of_date"))
    s.add(expect.compound_columns_to_be_unique(["category", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


# ─────────────────────────────────────────────────────────────────
# 3. NSE Equity Bhav Copy
# ─────────────────────────────────────────────────────────────────
def nse_bhavcopy_suite(expected_date: Optional[str] = None) -> Suite:
    """Spec § 3.

    Mapping to nidp.bhavcopy schema:
        SYMBOL      → symbol
        SERIES      → series
        TRADE_DATE  → as_of_date
        OPEN/HIGH/LOW/CLOSE  → open_price / high_price / low_price / close_price
        VOLUME      → volume
        ISIN        → isin
    """
    s = Suite("bhavcopy.daily", feed="bhavcopy")
    for c in ("open_price", "high_price", "low_price", "close_price"):
        s.add(expect.column_values_to_be_between(c, min_value=0, strict=False))
    # HIGH >= max(OPEN, LOW, CLOSE)
    s.add(expect.column_values_to_be_greater_than_or_equal_to_column(
        "high_price", "open_price"))
    s.add(expect.column_values_to_be_greater_than_or_equal_to_column(
        "high_price", "low_price"))
    s.add(expect.column_values_to_be_greater_than_or_equal_to_column(
        "high_price", "close_price"))
    # LOW <= min(OPEN, HIGH, CLOSE)
    s.add(expect.column_values_to_be_less_than_or_equal_to_column(
        "low_price", "open_price"))
    s.add(expect.column_values_to_be_less_than_or_equal_to_column(
        "low_price", "high_price"))
    s.add(expect.column_values_to_be_less_than_or_equal_to_column(
        "low_price", "close_price"))
    s.add(expect.column_values_to_be_between("volume", min_value=0, strict=False))
    s.add(expect.column_values_to_match_regex("isin", r"^IN[A-Z]{1}[0-9]{9}$"))
    s.add(expect.compound_columns_to_be_unique(["symbol", "series", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


# ─────────────────────────────────────────────────────────────────
# 4. NSE Index Close
# ─────────────────────────────────────────────────────────────────
def nse_index_close_suite(expected_date: Optional[str] = None) -> Suite:
    """Spec § 4.

    Mapping to nidp.index_close schema:
        INDEX_NAME  → index_name
        TRADE_DATE  → as_of_date
        OPEN/HIGH/LOW/CLOSE → open_price / high_price / low_price / close_price
    """
    s = Suite("index_close.daily", feed="index_close")
    for c in ("open_price", "high_price", "low_price", "close_price"):
        s.add(expect.column_values_to_be_not_null(c))
    s.add(expect.column_values_to_be_between(
        "close_price", min_value=0, strict=True))
    s.add(expect.compound_columns_to_be_unique(["index_name", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


SUITES = {
    # User-supplied spec
    "amfi_nav":     amfi_nav_suite,
    "fii_dii":      fii_dii_suite,
    "bhavcopy":     nse_bhavcopy_suite,
    "index_close":  nse_index_close_suite,
    # Auto-rules (see _OTHER_SUITES below)
}


# ─────────────────────────────────────────────────────────────────
# 5+ Other feeds — pragmatic domain defaults
# ─────────────────────────────────────────────────────────────────
def delivery_suite(expected_date: Optional[str] = None) -> Suite:
    """NSE delivery positions. Deliverable qty must be ≤ traded qty
    (else it's a parser bug — a position can't be 'delivered' more
    than it was traded)."""
    s = Suite("delivery.daily", feed="delivery")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_between("traded_quantity",      min_value=0))
    s.add(expect.column_values_to_be_between("deliverable_quantity", min_value=0))
    s.add(expect.column_values_to_be_between(
        "deliverable_pct", min_value=0, max_value=100))
    s.add(expect.column_values_to_be_less_than_or_equal_to_column(
        "deliverable_quantity", "traded_quantity"))
    s.add(expect.compound_columns_to_be_unique(["symbol", "series", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def fno_bhavcopy_suite(expected_date: Optional[str] = None) -> Suite:
    """NSE F&O bhavcopy. New-stack codes (post-2024) IDO/IDF/STO/STF +
    legacy OPTIDX/FUTIDX/OPTSTK/FUTSTK accepted."""
    s = Suite("fno_bhavcopy.daily", feed="fno_bhavcopy")
    s.add(expect.column_values_to_be_not_null("ticker_symbol"))
    s.add(expect.column_values_to_be_in_set("instrument_type", [
        "IDO", "IDF", "STO", "STF",
        "OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK",
    ]))
    s.add(expect.column_values_to_be_between("open_interest", min_value=0))
    s.add(expect.column_values_to_be_between("traded_volume", min_value=0))
    s.add(expect.column_values_to_be_between("close_price",   min_value=0))
    s.add(expect.compound_columns_to_be_unique([
        "ticker_symbol", "instrument_type", "expiry_date",
        "strike_price",  "option_type",     "as_of_date",
    ]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def bulk_deals_suite(expected_date: Optional[str] = None) -> Suite:
    s = Suite("bulk_deals.daily", feed="bulk_deals")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("client_name"))
    s.add(expect.column_values_to_be_in_set("deal_type", ["BUY", "SELL"]))
    s.add(expect.column_values_to_be_between("quantity",  min_value=0, strict=True))
    s.add(expect.column_values_to_be_between("avg_price", min_value=0, strict=True))
    s.add(expect.compound_columns_to_be_unique([
        "as_of_date", "symbol", "client_name", "deal_type", "deal_seq"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def block_deals_suite(expected_date: Optional[str] = None) -> Suite:
    s = Suite("block_deals.daily", feed="block_deals")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("client_name"))
    s.add(expect.column_values_to_be_in_set("deal_type", ["BUY", "SELL"]))
    s.add(expect.column_values_to_be_between("quantity",  min_value=0, strict=True))
    s.add(expect.column_values_to_be_between("avg_price", min_value=0, strict=True))
    s.add(expect.compound_columns_to_be_unique([
        "as_of_date", "symbol", "client_name", "deal_type", "deal_seq"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def corporate_actions_suite(expected_date: Optional[str] = None) -> Suite:
    """ex_date must not be in the past beyond a reasonable window —
    NSE only publishes upcoming + most-recent CAs."""
    s = Suite("corporate_actions.event", feed="corporate_actions")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("ex_date"))
    s.add(expect.column_values_to_be_in_set("action_type", [
        "DIVIDEND", "BONUS", "SPLIT", "RIGHTS", "BUYBACK", "AGM",
        "ANNUAL_GENERAL_MEETING", "EGM", "MERGER", "DEMERGER",
        "FACE_VALUE_CHANGE", "AMALGAMATION", "OTHER",
    ]))
    s.add(expect.compound_columns_to_be_unique([
        "symbol", "action_type", "ex_date"]))
    return s


def rbi_yields_suite(expected_date: Optional[str] = None) -> Suite:
    """RBI G-Sec yields — % bounds 0–30 (10Y has been 5–9% historically)."""
    s = Suite("rbi_yields.daily", feed="rbi_yields")
    s.add(expect.column_values_to_be_not_null("series_name"))
    s.add(expect.column_values_to_be_between(
        "yield_pct", min_value=0, max_value=30))
    s.add(expect.column_values_to_be_not_in_future("as_of_date"))
    s.add(expect.compound_columns_to_be_unique(["series_name", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def fred_macro_suite(expected_date: Optional[str] = None) -> Suite:
    """FRED time-series. PK on (series_id, observation_date)."""
    s = Suite("fred_macro.daily", feed="fred_macro")
    s.add(expect.column_values_to_be_not_null("series_id"))
    s.add(expect.column_values_to_be_not_null("observation_date"))
    s.add(expect.column_values_to_be_not_in_future("observation_date"))
    s.add(expect.compound_columns_to_be_unique(["series_id", "observation_date"]))
    return s


def nse_calendar_suite(expected_date: Optional[str] = None) -> Suite:
    """Holiday calendar. Segment must be one of the four NSE segments."""
    s = Suite("nse_calendar.monthly", feed="nse_calendar")
    s.add(expect.column_values_to_be_not_null("holiday_date"))
    s.add(expect.column_values_to_be_in_set("segment", [
        "CM", "FO", "DEBT", "CD", "CBM", "MF", "SLBS",
    ]))
    s.add(expect.compound_columns_to_be_unique(["holiday_date", "segment"]))
    return s


def nse_equity_master_suite(expected_date: Optional[str] = None) -> Suite:
    """Symbol master. ISIN must match Indian format. PK on symbol."""
    s = Suite("nse_equity_master.monthly", feed="nse_equity_master")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_match_regex("isin", r"^IN[A-Z]{1}[0-9]{9}$"))
    s.add(expect.compound_columns_to_be_unique(["symbol"]))
    return s


def nse_shareholding_suite(expected_date: Optional[str] = None) -> Suite:
    """Quarterly shareholding pattern (nidp.shareholding_pattern).

    Fixes the column name (period_end, not quarter_end) and adds checks that would have
    caught the 2026-06-23 issues: NSE is the single golden source, so a row must be
    unique on (symbol, period_end) — a second Screener row for the same period breaks
    this (it's how the 1,323 duplicates surfaced); pledge ≤ promoter on the
    total-shares basis; pcts in 0–100.
    """
    s = Suite("nse_shareholding.quarterly", feed="nse_shareholding")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("period_end"))
    s.add(expect.column_values_to_be_not_in_future("period_end"))
    for c in ("promoter_pct", "public_pct", "dii_pct", "fii_pct",
              "promoter_pledged_pct", "promoter_pledged_to_total_pct"):
        s.add(expect.column_values_to_be_between(c, min_value=0, max_value=100))
    # Same basis, or the comparison is meaningless: promoter_pledged_pct is
    # pledged/promoter-holding while promoter_pct is promoter/total-shares, so the
    # pair check belongs on promoter_pledged_to_total_pct (see dq_suites.py).
    s.add(expect.column_pair_a_lte_b("promoter_pledged_to_total_pct", "promoter_pct"))
    s.add(expect.compound_columns_to_be_unique(["symbol", "period_end"]))  # single golden source
    return s


def nse_financials_suite(expected_date: Optional[str] = None) -> Suite:
    """Quarterly results (nidp.nse_financials_quarterly).

    Beyond PK/null: encodes the data-correctness checks added 2026-06-23 after the
    Screener backfill introduced bad rows —
      • period_type canonical-cased (lowercase 'quarterly' is the case-inconsistency
        that hid contaminated rows from migration 089's QUARTERLY-only CTE);
      • EPS and PAT must share sign (caught SADBHAV/RPSGVENT parse errors);
      • PAT ≤ revenue for ≥95% of rows (PAT>revenue is legit only for banks/holdcos);
      • (symbol, period_end, period_type, consolidated) unique.
    """
    s = Suite("nse_financials.quarterly", feed="nse_financials")
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("period_end"))
    s.add(expect.column_values_to_be_not_in_future("period_end"))
    s.add(expect.column_values_to_be_in_set("period_type", [
        "Q", "H", "9M", "Y", "QUARTERLY", "HALF_YEARLY", "ANNUAL",
    ]))  # lowercase 'quarterly'/'annual' fail here by design — flags case-inconsistency
    s.add(expect.column_pair_same_sign("eps_basic", "pat_cr"))
    s.add(expect.column_pair_a_lte_b("pat_cr", "revenue_from_ops_cr"))  # mostly via runner
    s.add(expect.compound_columns_to_be_unique([
        "symbol", "period_end", "period_type", "consolidated"]))
    return s


def index_constituents_suite(expected_date: Optional[str] = None) -> Suite:
    """Index membership. weight_pct in 0..100; PK on (index_name, symbol, effective_date)."""
    s = Suite("index_constituents.monthly", feed="index_constituents")
    s.add(expect.column_values_to_be_not_null("index_name"))
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_between(
        "weight_pct", min_value=0, max_value=100))
    s.add(expect.compound_columns_to_be_unique([
        "index_name", "symbol", "effective_date"]))
    return s


def amfi_circulars_suite(expected_date: Optional[str] = None) -> Suite:
    """AMFI circulars. PK on circular_no; pub_date not in future."""
    s = Suite("amfi_circulars.daily", feed="amfi_circulars")
    s.add(expect.column_values_to_be_not_null("circular_no"))
    s.add(expect.column_values_to_be_not_null("pub_date"))
    s.add(expect.column_values_to_be_not_in_future("pub_date"))
    s.add(expect.compound_columns_to_be_unique(["circular_no"]))
    return s


def mf_holdings_suite(expected_date: Optional[str] = None) -> Suite:
    """AMC monthly disclosed holdings (nidp.mf_holdings_monthly).

    Fixes the column names (the old suite checked amc_id/isin/snapshot_date, none of
    which exist) and adds THE check that would have caught the 2026-06-23 corruption:
    a scheme's weight_pct must sum to ~100 per month. The NIPPON/SBI parsers ingested
    subtotal + grand-total rows as holdings, pushing the sum to ~224% (only 9% of
    schemes were sane). Also: weight per row ≤ 100, valid ISIN where present.
    """
    s = Suite("mf_holdings.monthly", feed="mf_holdings")
    s.add(expect.column_values_to_be_not_null("scheme_code"))
    s.add(expect.column_values_to_be_not_null("security_name"))
    s.add(expect.column_values_to_be_between("weight_pct", min_value=-5, max_value=100))
    s.add(expect.column_values_to_match_regex(
        "security_isin", r"^(|IN[EF][A-Z0-9]{9})$"))  # valid ISIN or blank (cash/TREPS)
    s.add(expect.column_grouped_sum_to_be_between(
        "weight_pct", ["scheme_code", "as_of_month"],
        min_value=95, max_value=105, mostly=0.90))
    s.add(expect.compound_columns_to_be_unique([
        "scheme_code", "as_of_month", "security_name", "source"]))
    return s


def mf_disclosure_snapshot_suite(expected_date: Optional[str] = None) -> Suite:
    """Monthly factsheet snapshots. PK (amc_id, scheme_code, snapshot_date)."""
    s = Suite("mf_disclosure_snapshot.monthly", feed="mf_disclosure_snapshot")
    s.add(expect.column_values_to_be_not_null("amc_id"))
    s.add(expect.column_values_to_be_not_null("scheme_code"))
    s.add(expect.compound_columns_to_be_unique([
        "amc_id", "scheme_code", "snapshot_date"]))
    return s


def announcement_classifier_suite(expected_date: Optional[str] = None) -> Suite:
    """Classifier output validity. event_category, impact_score, sentiment
    must be in their canonical enums."""
    s = Suite("announcement_classifier.event", feed="announcement_classifier")
    s.add(expect.column_values_to_be_in_set("event_category", [
        "orders", "mna", "earnings", "capex", "regulatory", "management",
        "dividend", "buyback", "qip", "rating", "litigation", "other",
    ]))
    s.add(expect.column_values_to_be_in_set("impact_score",
                                            ["high", "medium", "low"]))
    s.add(expect.column_values_to_be_in_set("sentiment",
                                            ["positive", "neutral", "negative"]))
    s.add(expect.column_values_to_be_not_null("classifier_version"))
    return s


def corporate_announcements_suite(
    feed: str, expected_date: Optional[str] = None,
) -> Suite:
    """Used for both nse + bse high-freq announcement pollers. Same
    columns; suite name varies."""
    s = Suite(f"{feed}.high_freq", feed=feed)
    s.add(expect.column_values_to_be_not_null("symbol"))
    s.add(expect.column_values_to_be_not_null("subject"))
    s.add(expect.column_values_to_be_not_null("disclosure_at"))
    s.add(expect.column_values_to_be_not_in_future("disclosure_at"))
    s.add(expect.compound_columns_to_be_unique([
        "symbol", "subject_hash", "disclosure_at"]))
    return s


def prices_eod_suite(expected_date: Optional[str] = None) -> Suite:
    """Daily EOD prices (nidp.prices_eod). OHLC internal consistency, positive
    prices, non-negative volume, delivery 0–100, PK, freshness."""
    s = Suite("prices_eod.daily", feed="prices_eod")
    for c in ("open_price", "high_price", "low_price", "close_price"):
        s.add(expect.column_values_to_be_between(c, min_value=0, strict=True))
    s.add(expect.column_pair_a_lte_b("low_price", "high_price"))
    s.add(expect.column_pair_a_lte_b("low_price", "close_price"))
    s.add(expect.column_pair_a_lte_b("close_price", "high_price"))
    s.add(expect.column_values_to_be_between("volume", min_value=0))
    s.add(expect.column_values_to_be_between("deliv_pct", min_value=0, max_value=100))
    s.add(expect.column_values_to_be_not_in_future("as_of_date"))
    s.add(expect.compound_columns_to_be_unique(["symbol", "as_of_date", "series"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def stock_features_suite(expected_date: Optional[str] = None) -> Suite:
    """Technical features (nidp.stock_features_daily). Bounded indicators +
    accumulation_score presence (it was silently 0/2274 before SD-12 went live)
    + freshness (features lagged prices by 4 days on 2026-06-23)."""
    s = Suite("stock_features.daily", feed="technical_indicator_engine")
    s.add(expect.column_values_to_be_between("rsi14", min_value=0, max_value=100))
    s.add(expect.column_values_to_be_between("accumulation_score", min_value=0, max_value=100))
    s.add(expect.column_values_to_be_between("volatility_1y_pct", min_value=0))
    s.add(expect.column_values_to_be_between("beta_1y", min_value=-5, max_value=10))
    s.add(expect.column_values_to_be_between("close", min_value=0, strict=True))
    s.add(expect.compound_columns_to_be_unique(["symbol", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def v3_stock_scores_suite(expected_date: Optional[str] = None) -> Suite:
    """V3 composite scores (nidp.v3_stock_scores_daily). Scores 0–100, band enum,
    coverage 0–100, PK, freshness."""
    s = Suite("v3_stock_scores.daily", feed="v3_scores_engine")
    for c in ("fundamental_score", "technical_score", "final_score"):
        s.add(expect.column_values_to_be_between(c, min_value=0, max_value=100))
    for c in ("quality_coverage_pct", "health_coverage_pct"):
        s.add(expect.column_values_to_be_between(c, min_value=0, max_value=100))
    s.add(expect.column_values_to_be_in_set(
        "band", ["STRONG_BUY", "BUY", "HOLD", "REDUCE", "AVOID"]))
    s.add(expect.compound_columns_to_be_unique(["symbol", "as_of_date"]))
    if expected_date:
        s.add(expect.freshness_max_date_equals("as_of_date", expected_date))
    return s


def stock_fundamentals_latest_suite(expected_date: Optional[str] = None) -> Suite:
    """Derived fundamentals (nidp.v_stock_fundamentals_latest) — the layer feeding
    scoring. Plausibility bounds + the correctness checks from 2026-06-23:
    EPS/PAT same sign, PAT ≤ revenue (mostly; banks/holdcos exempt), one row/symbol."""
    s = Suite("stock_fundamentals.latest", feed="fundamental_engine")
    s.add(expect.column_values_to_be_between("roe_annualised_pct", min_value=-150, max_value=150))
    s.add(expect.column_values_to_be_between("debt_to_equity", min_value=0, max_value=50))
    s.add(expect.column_values_to_be_between("current_ratio", min_value=0, max_value=50))
    s.add(expect.column_pair_same_sign("eps_ttm", "pat_ttm_cr"))
    s.add(expect.column_pair_a_lte_b("pat_ttm_cr", "revenue_ttm_cr"))
    s.add(expect.compound_columns_to_be_unique(["symbol"]))
    return s


# Register all of the additional suites
SUITES.update({
    "prices_eod":                prices_eod_suite,
    "technical_indicator_engine": stock_features_suite,
    "v3_scores_engine":          v3_stock_scores_suite,
    "fundamental_engine":        stock_fundamentals_latest_suite,
    "delivery":                  delivery_suite,
    "fno_bhavcopy":              fno_bhavcopy_suite,
    "bulk_deals":                bulk_deals_suite,
    "block_deals":               block_deals_suite,
    "corporate_actions":         corporate_actions_suite,
    "rbi_yields":                rbi_yields_suite,
    "fred_macro":                fred_macro_suite,
    "nse_calendar":              nse_calendar_suite,
    "nse_equity_master":         nse_equity_master_suite,
    "nse_shareholding":          nse_shareholding_suite,
    "nse_financials":            nse_financials_suite,
    "index_constituents":        index_constituents_suite,
    "amfi_circulars":            amfi_circulars_suite,
    "mf_holdings":               mf_holdings_suite,
    "mf_disclosure_snapshot":    mf_disclosure_snapshot_suite,
    "announcement_classifier":   announcement_classifier_suite,
    "corporate_announcements_nse": lambda exp=None: corporate_announcements_suite(
        "corporate_announcements_nse", exp),
    "corporate_announcements_bse": lambda exp=None: corporate_announcements_suite(
        "corporate_announcements_bse", exp),
})


# ─────────────────────────────────────────────────────────────────
# Documentation surface — used by the NIDP Console
# ─────────────────────────────────────────────────────────────────
def documentation() -> Dict[str, dict]:
    """Return a JSON-serialisable spec of every suite, for display in
    the admin console's Data Quality page. Each entry has:

        feed:          str
        suite_name:    str
        expectations:  list[{type, kwargs}]
    """
    out: Dict[str, dict] = {}
    for feed, builder in SUITES.items():
        # Build a sample run to introspect expectations. Pass the same
        # signature as the runner uses (expected_date kwarg). Failing
        # builds (e.g. lambda glue) fall back gracefully.
        try:
            suite = builder(expected_date=None)
        except TypeError:
            suite = builder()
        exps = []
        for fn in suite._expectations:                  # noqa: SLF001 — internal access acceptable here
            # Run the closure on an empty list to obtain the
            # ExpectationResult shell — its `kwargs` + `expectation_type`
            # are populated even with 0 rows.
            try:
                shell = fn([])
                exps.append({
                    "type":   shell.expectation_type,
                    "column": shell.column,
                    "columns": shell.columns,
                    "kwargs": shell.kwargs,
                })
            except Exception as e:                            # noqa: BLE001
                exps.append({"type": "<introspection_error>",
                             "kwargs": {"error": str(e)}})
        out[feed] = {
            "feed":         feed,
            "suite_name":   suite.name,
            "expectations": exps,
        }
    return out
