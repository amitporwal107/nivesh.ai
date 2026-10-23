"""Reconciliation test for the MF holdings canonical dedupe (migrations 182/183).

THE DEFECT THIS GUARDS
nidp.mf_holdings_monthly stores a scheme's holding once per plan/option scheme_code, each row
carrying the same quantity, so summing `quantity` multiplies the holding. Measured on staging
2026-09-01: 156,683 equity-leg rows collapse to 38,318 canonical fund-ISIN rows (4.09x), and the
summed figure came to 2.07x (median, Nifty 500 n=408) of the mutual-fund holding the companies
themselves disclosed. After dedupe the same measure is 0.56x — the honest number for a book that
indexes 11 of the 56 AMCs in nidp.mf_amc_master.

WHAT IS ASSERTED, AND WHY IT IS ONE-SIDED
With 11 of 56 AMCs, our share count must NOT exceed what the company disclosed, and must NOT be
expected to equal it. So the bound is `ratio <= 1.05` (5% headroom for the mismatch between a
month-end portfolio and a quarter-end filing) for at least 90% of names, plus a coverage band
that would fail if anyone "fixed" coverage by inflating the numerator. Asserting ratio ~= 1 would
be asserting the bug back into existence.

THE FIXTURE IS REAL DATA
backend/nidp/tests/fixtures/mf_holdings_recon_202609.json holds 3,183 real holdings rows for 15
Nifty 500 names (chosen by ntile over the per-stock fund count, 12 to 147 funds) together with
each company's own NSE shareholding filing. Nothing in it is synthetic. The per-stock canonical
totals below were measured by the SQL view on staging; asserting the Python mirror reproduces
them exactly is what keeps migration 182 and canonical.py from drifting apart.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from nidp.services.mf_holdings.canonical import (
    LEG_DERIVATIVE,
    LEG_EQUITY,
    LEG_NO_QUANTITY,
    base_scheme_name,
    canonical_holdings,
    leg_class,
    reconcile,
    source_amc_map,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mf_holdings_recon_202609.json"

# Per-stock canonical/naive share counts and fund counts as nidp.v_mf_stock_shares_monthly
# measured them on staging for 2026-09-01 (read-only query, 2026-10-23). The Python mirror must
# reproduce them to the share.
SQL_MEASURED = {
    #  isin            canonical      naive          funds
    "INE930P01018": (92229.0, 366689.0, 12),
    "INE552Z01027": (8683048.0, 43247193.0, 18),
    "INE208C01025": (9963358.0, 48656144.0, 22),
    "INE885A01032": (6002299.0, 21761450.0, 24),
    "INE216P01012": (6942121.0, 27606533.0, 26),
    "INE769A01020": (24346315.0, 105499750.0, 28),
    "INE404A01024": (18498160.0, 107633867.0, 35),
    "INE791I01019": (52410060.0, 190790513.0, 44),
    "INE371P01015": (1686692.0, 7167277.0, 54),
    "INE674K01013": (45821589.0, 126070634.0, 60),
    "INE372A01015": (4947648.0, 22087472.0, 71),
    "INE466L01038": (43994920.0, 192712141.0, 76),
    "INE117A01022": (6067113.0, 27672955.0, 91),
    "INE423A01024": (69490290.0, 250429057.0, 113),
    "INE437A01024": (14951630.0, 50596366.0, 147),
}

# The tolerance, stated once (see the module docstring for why it is one-sided).
MAX_RATIO = 1.05
MIN_PASS_FRACTION = 0.90
COVERAGE_BAND = (0.40, 0.75)


@pytest.fixture(scope="module")
def fixture_doc():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(fixture_doc):
    """Re-expand the compact fixture into holdings rows."""
    schemes = fixture_doc["schemes"]
    isins = fixture_doc["securities"]
    names = fixture_doc["security_names"]
    out = []
    for s_idx, i_idx, n_idx, qty in fixture_doc["rows"]:
        code, source, scheme_name, amc_id = schemes[s_idx]
        out.append({"scheme_code": code, "source": source, "scheme_name": scheme_name,
                    "amc_id": amc_id, "security_isin": isins[i_idx],
                    "security_name": names[n_idx], "quantity": qty})
    return out


@pytest.fixture(scope="module")
def expected(fixture_doc):
    return {e["isin"]: e for e in fixture_doc["expected"]}


@pytest.fixture(scope="module")
def source_amc(fixture_doc):
    """source -> amc_id as the warehouse derives it over the WHOLE table.

    It cannot be derived from a 15-stock extract: none of the QUANT_MF_PORTFOLIO_XLSX rows in
    this fixture carries a scheme code that resolves to nidp.mf_scheme_master, so deriving the
    map locally splits quant in two and silently restores part of the duplication.
    """
    return fixture_doc["source_amc"]


def test_every_source_belongs_to_exactly_one_amc(fixture_doc):
    """TC-6 guard: the source fallback is only safe while this holds."""
    assert fixture_doc["source_amc_distinct_counts"]
    assert all(n == 1 for n in fixture_doc["source_amc_distinct_counts"].values()), \
        fixture_doc["source_amc_distinct_counts"]


# ── TC-1..TC-5: the canonical name rule ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Axis Children's Fund - Direct Plan - Growth Option",
    "Axis Children's Fund - Direct Plan - IDCW Option",
    "Axis Children's Fund - Regular Plan - Growth Option",
    "Axis Children's Fund - Regular Plan - IDCW Option",
])
def test_plan_and_option_variants_share_one_key(name):
    """TC-1: the 8 rows behind one Axis Children's Fund holding are one fund."""
    assert base_scheme_name(name) == "axis children's fund"


def test_trailing_plan_without_option(name="Axis Nifty Capital Markets Index Fund - Direct Plan"):
    """TC-2: 31 of 3,000 staging names end at the plan, with no option suffix."""
    assert base_scheme_name(name) == "axis nifty capital markets index fund"
    assert base_scheme_name("Axis Nifty Capital Markets Index Fund - Regular Plan") \
        == base_scheme_name(name)


@pytest.mark.parametrize("name", [
    "Axis Liquid Fund - Growth Option",
    "Axis Liquid Fund - Daily IDCW Option",
    "Axis Liquid Fund - Weekly IDCW Option",
    "Axis Liquid Fund - Direct Plan - Bonus Option",
])
def test_option_only_names_collapse(name):
    """TC-3: 226 staging names carry no plan word at all, only an option."""
    assert base_scheme_name(name) == "axis liquid fund"


def test_case_only_difference_is_one_fund():
    """TC-4: the feed writes the same fund in two cases."""
    a = base_scheme_name("ADITYA BIRLA SUN LIFE ARBITRAGE FUND - Direct Plan - GROWTH")
    b = base_scheme_name("Aditya Birla Sun Life Arbitrage Fund - Regular Plan - IDCW-Re-investment")
    assert a == b == "aditya birla sun life arbitrage fund"


def test_stacked_suffixes_are_all_removed():
    """A real staging name with the option BEFORE the plan, and no space before the dash."""
    assert base_scheme_name("Nippon India Nifty 1D Rate Liquid ETF- Growth - Direct Plan") \
        == "nippon india nifty 1d rate liquid etf"
    assert base_scheme_name(
        "Kotak Arbitrage Fund - Regular Plan - IDCW - Payout & Re-investment of Income "
        "Distribution cum capital withdrawal option") == "kotak arbitrage fund"


@pytest.mark.parametrize("name,expected_key", [
    # TC-5: the plan/option words appear mid-name and must NOT truncate it.
    ("ICICI Prudential Regular Savings Fund - Direct Plan - Growth",
     "icici prudential regular savings fund"),
    ("Aditya Birla Sun Life Regular Savings Fund - Regular Plan - IDCW",
     "aditya birla sun life regular savings fund"),
    ("HDFC Growth Opportunities Fund", "hdfc growth opportunities fund"),
    ("quant Dividend Yield Fund - Direct Plan - Growth", "quant dividend yield fund"),
    ("ADITYA BIRLA SUN LIFE NIFTY BANK ETF", "aditya birla sun life nifty bank etf"),
])
def test_no_over_merge(name, expected_key):
    assert base_scheme_name(name) == expected_key


# ── TC-7: instrument legs ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sec_name,qty,expect", [
    ("ICICI Bank Ltd.-OCT2026", -22519700.0, LEG_DERIVATIVE),      # short future
    ("Ultratech Cement Ltd.-NOV2026", -51650.0, LEG_DERIVATIVE),
    ("JIO FINANCIAL SERVICES LTD-OCT2026", 75200.0, LEG_DERIVATIVE),  # LONG future, still not shares
    ("Kotak Mahindra Bank Ltd. (CALL Option)", -10208000.0, LEG_DERIVATIVE),
    ("Vodafone Idea Ltd.", -10006500.0, LEG_DERIVATIVE),            # unmarked short leg
    ("ICICI BANK LTD.", 23751000.0, LEG_EQUITY),
    ("Net Receivables / (Payables)", None, LEG_NO_QUANTITY),
])
def test_leg_classification(sec_name, qty, expect):
    assert leg_class(sec_name, qty) == expect


def test_derivative_legs_are_excluded_and_reported():
    """A short future must neither count as ownership nor net against the cash leg."""
    rows = [
        {"scheme_code": "105967", "source": "KOTAK_DISCLOSURE_ADVISORKHOJ", "amc_id": "kotak",
         "scheme_name": "Kotak Arbitrage Fund - Regular Plan - Growth",
         "security_isin": "INE090A01021", "security_name": "ICICI BANK LTD.",
         "quantity": 23751000.0},
        {"scheme_code": "119771", "source": "KOTAK_DISCLOSURE_ADVISORKHOJ", "amc_id": "kotak",
         "scheme_name": "Kotak Arbitrage Fund - Direct Plan - Growth",
         "security_isin": "INE090A01021", "security_name": "ICICI BANK LTD.",
         "quantity": 23751000.0},
        {"scheme_code": "105967", "source": "KOTAK_DISCLOSURE_ADVISORKHOJ", "amc_id": "kotak",
         "scheme_name": "Kotak Arbitrage Fund - Regular Plan - Growth",
         "security_isin": "INE090A01021", "security_name": "ICICI Bank Ltd.-OCT2026",
         "quantity": -22519700.0},
    ]
    [g] = canonical_holdings(rows)
    assert g.shares == 23751000.0            # not 47.5m (summed), not 1.23m (netted)
    assert g.variant_rows == 2
    assert g.derivative_rows == 1
    assert g.derivative_net_quantity == -22519700.0


# ── TC-6: two sources for one AMC-month ─────────────────────────────────────────────────────

def test_source_derived_amc_merges_the_two_quant_feeds(source_amc):
    """QUANT_MF_PORTFOLIO_XLSX keys rows by scheme NAME and resolves to no master row.

    Without deriving its amc from the source, quant's book is counted twice — once from the
    AMC's own file and once from the third-party index.
    """
    rows = [
        {"scheme_code": "151788", "source": "QUANT_DISCLOSURE_ADVISORKHOJ", "amc_id": "quant",
         "scheme_name": "quant BFSI Fund - Direct Plan - Growth Option",
         "security_isin": "INE522D01027", "security_name": "Manappuram Finance Ltd",
         "quantity": 2453969.0},
        {"scheme_code": "151789", "source": "QUANT_DISCLOSURE_ADVISORKHOJ", "amc_id": "quant",
         "scheme_name": "quant BFSI Fund - Regular Plan - Growth Option",
         "security_isin": "INE522D01027", "security_name": "Manappuram Finance Ltd",
         "quantity": 2453969.0},
        {"scheme_code": "quant BFSI Fund", "source": "QUANT_MF_PORTFOLIO_XLSX", "amc_id": None,
         "scheme_name": None, "security_isin": "INE522D01027",
         "security_name": "Manappuram Finance Ltd", "quantity": 2453969.0},
    ]
    groups = canonical_holdings(rows, source_amc)
    assert len(groups) == 1, [g.canonical_fund_key for g in groups]
    g = groups[0]
    assert g.canonical_fund_key == "quant|quant bfsi fund"
    assert g.shares == 2453969.0
    assert sorted(g.sources) == ["QUANT_DISCLOSURE_ADVISORKHOJ", "QUANT_MF_PORTFOLIO_XLSX"]


def test_source_mapping_fails_loudly_if_a_source_carries_two_amcs():
    rows = [
        {"scheme_code": "1", "source": "X", "amc_id": "sbi", "scheme_name": "A - Direct Plan",
         "security_isin": "I", "security_name": "N", "quantity": 1.0},
        {"scheme_code": "2", "source": "X", "amc_id": "axis", "scheme_name": "B - Direct Plan",
         "security_isin": "I", "security_name": "N", "quantity": 1.0},
    ]
    with pytest.raises(ValueError, match="maps to several amc_ids"):
        source_amc_map(rows)


# ── TC-13 / TC-14: the reconciliation itself ────────────────────────────────────────────────

def test_python_mirror_reproduces_the_sql_measurement(rows, source_amc):
    """The Python rule and migration 182's SQL must agree to the share."""
    recon = {r.security_isin: r for r in reconcile(rows, {}, source_amc)}
    assert set(recon) == set(SQL_MEASURED)
    mismatches = []
    for isin, (shares, naive, funds) in SQL_MEASURED.items():
        got = recon[isin]
        if (round(got.canonical_shares, 4) != shares or round(got.naive_shares, 4) != naive
                or got.funds != funds):
            mismatches.append((isin, (got.canonical_shares, got.naive_shares, got.funds),
                               (shares, naive, funds)))
    assert not mismatches, mismatches


def test_dedupe_removes_the_fourfold_duplication(rows, source_amc):
    groups = canonical_holdings(rows, source_amc)
    source_rows = sum(g.variant_rows for g in groups)
    factor = source_rows / len(groups)
    assert 3.0 <= factor <= 6.0, f"duplication factor {factor:.3f} outside the measured range"
    naive_total = sum(g.naive_sum_quantity for g in groups)
    canonical_total = sum(g.shares for g in groups)
    assert naive_total / canonical_total > 3.0, "the naive sum is no longer inflated — rule drift?"


def test_variants_agree_on_the_quantity(rows, source_amc):
    """99.906% of staging groups carry ONE distinct quantity: the duplicates are pure copies."""
    groups = canonical_holdings(rows, source_amc)
    conflicted = [g for g in groups if g.qty_variants > 1]
    assert len(conflicted) / len(groups) < 0.01, \
        f"{len(conflicted)} of {len(groups)} groups disagree on quantity"


def test_canonical_never_exceeds_the_disclosed_holding(rows, expected, source_amc):
    """TC-13, the deliverable: deduped-vs-disclosed within tolerance for a stated fraction."""
    recon = [r for r in reconcile(rows, expected, source_amc) if r.coverage_ratio is not None]
    assert len(recon) == 15
    within = [r for r in recon if r.coverage_ratio <= MAX_RATIO]
    fraction = len(within) / len(recon)
    assert fraction >= MIN_PASS_FRACTION, (
        f"only {len(within)}/{len(recon)} names within {MAX_RATIO}x of the disclosed MF "
        f"holding: " + ", ".join(f"{r.symbol}={r.coverage_ratio:.2f}"
                                 for r in recon if r.coverage_ratio > MAX_RATIO))


def test_naive_sum_fails_the_same_assertion(rows, expected, source_amc):
    """TC-14: the pre-fix figure must FAIL, or this test is proving nothing."""
    recon = [r for r in reconcile(rows, expected, source_amc) if r.naive_ratio is not None]
    within = [r for r in recon if r.naive_ratio <= MAX_RATIO]
    assert len(within) / len(recon) < MIN_PASS_FRACTION, \
        "the naive summed figure now passes the bound — the fixture or the rule has changed"
    assert statistics.median(r.naive_ratio for r in recon) > 1.5


def test_measured_coverage_is_the_real_number_not_a_constant(rows, expected, source_amc):
    """TC-10: coverage is ~0.56 because we index 11 of 56 AMCs. It is not 1.00 and not 100.00."""
    ratios = [r.coverage_ratio
              for r in reconcile(rows, expected, source_amc) if r.coverage_ratio is not None]
    median = statistics.median(ratios)
    lo, hi = COVERAGE_BAND
    assert lo <= median <= hi, (
        f"median coverage {median:.3f} outside the measured band {COVERAGE_BAND}; either AMC "
        "coverage really changed (update the band and say so) or the numerator is being inflated")
    assert all(r > 0 for r in ratios)


def test_undisclosed_expected_side_is_none_not_zero(rows, source_amc):
    """TC-11: absence is reported as unknown, never as 0 and never as full coverage."""
    recon = reconcile(rows, {}, source_amc)
    assert recon and all(r.expected_shares is None for r in recon)
    assert all(r.coverage_ratio is None and r.naive_ratio is None for r in recon)


def test_rows_without_isin_are_dropped_not_guessed():
    rows = [{"scheme_code": "1", "source": "S", "amc_id": "sbi",
             "scheme_name": "X Fund - Direct Plan - Growth", "security_isin": "",
             "security_name": "TREPS", "quantity": 100.0}]
    assert canonical_holdings(rows) == []
