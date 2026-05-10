"""Great-Expectations suites — one per feed (per the user-supplied spec
NIDP_Sample_Feed_Expectation_Rules.docx).

Each builder takes the optional `expected_date` kwarg used by the
freshness expectation. Suites execute against rows fetched from the
NIDP TimescaleDB, mapping our snake_case column names to the GE-spec
camelCase / TitleCase names where needed.
"""
from __future__ import annotations

from typing import Optional

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
    "amfi_nav":     amfi_nav_suite,
    "fii_dii":      fii_dii_suite,
    "bhavcopy":     nse_bhavcopy_suite,
    "index_close":  nse_index_close_suite,
}
