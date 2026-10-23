"""Reconciliation test for the ScanX MF-holdings coverage extension (migration 184).

THE GAP THIS GUARDS
nidp.v_mf_holdings_canonical (migration 182) covers 11 of 56 AMCs in nidp.mf_amc_master. Validating
a real stock (Sundaram Finance, NSE SUNDARMFIN, ISIN INE660A01013) against Trendlyne's public
MF-holdings page found AlphaGrep, JioBlackRock, Zerodha and Navi holding it — real AMCs, real
holdings, invisible in our product because none of the four is one of the 11. nidp.scanx_mf_holdings
(migrations 179/180) already carries all four plus 47 more (51 AMCs total, re-verified here against
real staging data: `SELECT DISTINCT amc FROM nidp.scanx_mf_holdings` = 51, a strict superset of the
11), and migration 184 wires it into a new, additive `nidp.v_mf_holdings_canonical_ext` without
touching the existing 11-AMC view or anything that already reads it.

WHAT IS LOCKED IN AS A REGRESSION TEST, AND WHY
`backend/nidp/tests/fixtures/mf_holdings_scanx_sundaram_202609.json` holds the REAL
nidp.scanx_mf_holdings rows (read-only SELECT, staging, 2026-10-23) behind the Sundaram Finance
validation against the real Trendlyne screenshot: 7 of 8 comparable monthly deltas matched the
vendor's figures to the share. Those 7 deltas are asserted here literally, so this specific
real-world validation cannot silently regress if canonical.py's ScanX mirror or migration 184's SQL
drift apart. The one Trendlyne figure NOT reproduced (Navi, 2026-07) is asserted as a genuine
missing month, never backfilled with a guess — see the fixture's "known_gap_not_a_defect".

WHAT IS ASSERTED ABOUT DOUBLE-COUNTING
Two independent safeguards, both from the migration-182/183 playbook of reporting things
SEPARATELY rather than blending them into one number:
  * combine_extended_holdings() never sums an AMC's amc-file figure with its ScanX figure — an
    AMC present in BOTH sources is counted from the amc-file side ONLY (TC-S7).
  * amcs_amc_file / amcs_scanx / funds_scanx stay separate counts, never folded into a single
    "amcs" ratio that would hide which source produced a figure (TC-S8), the same way migration
    182/183 keep duplication and coverage as two numbers, never one blended ratio.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nidp.services.mf_holdings.canonical import (
    CanonicalHolding,
    ScanxCanonicalHolding,
    base_scheme_name,
    combine_extended_holdings,
    scanx_canonical_holdings,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mf_holdings_scanx_sundaram_202609.json"

# Measured against the real staging warehouse, read-only, 2026-10-23 (see test_reports/
# mf_holdings_scanx_coverage_20261023.md for the full queries and output). Not re-derivable from
# the single-stock fixture below, so recorded here as a committed constant, the same way
# test_mf_holdings_reconciliation.py's SQL_MEASURED records numbers the small fixture cannot
# reproduce at full scale.
AMC_FILE_AMCS = 11                 # SELECT DISTINCT amc_id FROM nidp.v_mf_holdings_canonical
SCANX_TOTAL_AMCS = 51              # SELECT DISTINCT amc FROM nidp.scanx_mf_holdings
NEW_AMCS_ADDED = 40                # scanx-only, i.e. SCANX_TOTAL_AMCS - overlap with the 11
NIFTY500_COVERAGE_BEFORE = (0.5598, 0.5340)   # (median, mean), n=408, 2026-09, amc-file-only panel
NIFTY500_COVERAGE_AFTER = (0.9473, 0.9181)    # (median, mean), n=408, 2026-09, extended panel
NIFTY500_WITHIN_BOUND_AFTER_PCT = 99.3        # of 408, coverage_ratio <= 1.05 on the extended panel


def test_new_amc_arithmetic_matches_the_real_measurement():
    """TC-S0: the headline counts this migration's docstring claims, pinned as a constant."""
    assert SCANX_TOTAL_AMCS - AMC_FILE_AMCS == NEW_AMCS_ADDED == 40


@pytest.fixture(scope="module")
def fixture_doc():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sundaram_rows(fixture_doc):
    return fixture_doc["rows"]


@pytest.fixture(scope="module")
def amc_id_map(fixture_doc):
    return fixture_doc["amc_id_map"]


# ── TC-S1/S2: the ScanX canonical rule ──────────────────────────────────────────────────────────

def test_equity_and_arbitrage_asset_classes_are_kept():
    """TC-S1: the two equity-like classes survive; shares is passed through, never summed (the
    primary key already guarantees one row per fund x ISIN x month on the real table)."""
    rows = [
        {"amc": "Zerodha Mutual Fund", "scheme_name": "Zerodha Arbitrage Fund Direct-Growth",
         "security_isin": "INE090A01021", "as_of_month": "2026-09-01", "shares": 5000.0,
         "weight_pct": 1.2, "asset_class": "Arbitrage"},
        {"amc": "Zerodha Mutual Fund", "scheme_name": "Zerodha Nifty 50 Index Fund Direct-Growth",
         "security_isin": "INE090A01021", "as_of_month": "2026-09-01", "shares": 10000.0,
         "weight_pct": 2.4, "asset_class": "Equity"},
    ]
    groups = scanx_canonical_holdings(rows, {"Zerodha Mutual Fund": "zerodha"})
    assert len(groups) == 2
    assert {g.shares for g in groups} == {5000.0, 10000.0}


@pytest.mark.parametrize("asset_class", [
    "Debenture", "Certificate of Deposit", "Bonds", "Commercial Paper",
    "Real Estate Investment Trusts", "Infrastructure Investment Trust", "Preference Shares",
])
def test_non_equity_asset_classes_are_excluded_not_zeroed(asset_class):
    """TC-S2: debt/REIT/InvIT/other instruments (real asset_class values observed in
    nidp.scanx_mf_holdings, 2026-10-23) are excluded entirely — never counted as a zero share
    position, which would be a fabricated number in the other direction."""
    rows = [{"amc": "HDFC Mutual Fund", "scheme_name": "HDFC Liquid Fund Direct-Growth",
             "security_isin": "INE999Z99999", "as_of_month": "2026-09-01", "shares": 100000.0,
             "weight_pct": 5.0, "asset_class": asset_class}]
    assert scanx_canonical_holdings(rows, {"HDFC Mutual Fund": "hdfc"}) == []


def test_rows_with_no_isin_or_unmapped_amc_are_dropped():
    """TC-S2b: absence of an ISIN, or an AMC name the map does not resolve, drops the row rather
    than guessing an amc_id."""
    rows = [
        {"amc": "HDFC Mutual Fund", "scheme_name": "X Fund Direct-Growth", "security_isin": "",
         "as_of_month": "2026-09-01", "shares": 1.0, "weight_pct": 0.1, "asset_class": "Equity"},
        {"amc": "Some New AMC Mutual Fund", "scheme_name": "Y Fund Direct-Growth",
         "security_isin": "INE999Z99999", "as_of_month": "2026-09-01", "shares": 1.0,
         "weight_pct": 0.1, "asset_class": "Equity"},
    ]
    assert scanx_canonical_holdings(rows, {"HDFC Mutual Fund": "hdfc"}) == []


def test_a_disclosed_zero_is_kept_not_dropped():
    """TC-S3: shares=0 is a real disclosed holding (migration 184's 'zero row' finding — a stable
    27-31% of all scanx_mf_holdings rows every month, not an artefact), and must survive exactly
    like a zero-quantity equity_cash row survives on the AMC-file side."""
    rows = [{"amc": "AlphaGrep Mutual Fund", "scheme_name": "AlphaGrep Flexi Cap Fund Direct-Growth",
             "security_isin": "INE660A01013", "as_of_month": "2026-08-01", "shares": 0,
             "weight_pct": 0.0, "asset_class": "Equity"}]
    [g] = scanx_canonical_holdings(rows, {"AlphaGrep Mutual Fund": "alphagrep"})
    assert g.shares == 0.0


# ── TC-S4..S6: the Sundaram Finance real-world validation, locked in ───────────────────────────

def _shares_by_fund_month(rows, amc_id_map):
    out = {}
    for g in scanx_canonical_holdings(rows, amc_id_map):
        out[(g.canonical_fund_key, g.as_of_month)] = g.shares
    return out


def test_alphagrep_fresh_buy_892_reproduces_trendlyne(sundaram_rows, amc_id_map):
    """TC-S4: the one disclosed-zero case. 2026-08 shares=0 -> 2026-09 shares=892, matching
    Trendlyne's 'Fresh Buy 892' for AlphaGrep Flexi Cap Fund on SUNDARMFIN."""
    shares = _shares_by_fund_month(sundaram_rows, amc_id_map)
    key = "alphagrep|" + base_scheme_name("AlphaGrep Flexi Cap Fund Direct-Growth")
    assert shares[(key, "2026-08-01")] == 0.0
    assert shares[(key, "2026-09-01")] == 892.0
    assert shares[(key, "2026-09-01")] - shares[(key, "2026-08-01")] == 892.0


def test_jioblackrock_midcap150_delta_minus_106(sundaram_rows, amc_id_map):
    """TC-S5: JioBlackRock Nifty Midcap 150, 2026-08=4636 -> 2026-09=4530, matching Trendlyne's -106."""
    shares = _shares_by_fund_month(sundaram_rows, amc_id_map)
    key = "jio_blackrock|" + base_scheme_name("JioBlackRock Nifty Midcap 150 Index Fund Direct-Growth")
    assert shares[(key, "2026-09-01")] - shares[(key, "2026-08-01")] == -106.0


@pytest.mark.parametrize("scheme_name,prev_month,cur_month,expected_delta", [
    ("Zerodha Life Cycle Fund 2036 Direct-Growth", "2026-08-01", "2026-09-01", 12.0),
    ("Zerodha Life Cycle Fund 2041 Direct-Growth", "2026-08-01", "2026-09-01", -1.0),
    ("Zerodha Nifty MidSmallcap400 50:50 Index Fund Direct-Growth", "2026-08-01", "2026-09-01", 18.0),
    ("Zerodha Nifty LargeMidcap250 Plus 8-13 Yr G-Sec 70:30 Index Fund Direct-Growth",
     "2026-08-01", "2026-09-01", 1.0),
])
def test_zerodha_deltas_reproduce_trendlyne(sundaram_rows, amc_id_map, scheme_name, prev_month,
                                             cur_month, expected_delta):
    """TC-S6: four of Zerodha's five validated SUNDARMFIN deltas (+12, -1, +18, +1)."""
    shares = _shares_by_fund_month(sundaram_rows, amc_id_map)
    key = "zerodha|" + base_scheme_name(scheme_name)
    assert shares[(key, cur_month)] - shares[(key, prev_month)] == expected_delta


def test_zerodha_life_cycle_2031_is_a_fresh_buy_of_43(sundaram_rows, amc_id_map):
    """TC-S6b: Zerodha Life Cycle Fund 2031 has NO 2026-08 row at all, so this is panel_entry /
    'unknown direction' by the existing deltas-service rule, not a computable delta — but the
    2026-09 holding itself (43 shares) matches Trendlyne's 'Fresh Buy 43'."""
    shares = _shares_by_fund_month(sundaram_rows, amc_id_map)
    key = "zerodha|" + base_scheme_name("Zerodha Life Cycle Fund 2031 Direct-Growth")
    assert (key, "2026-08-01") not in shares        # genuinely absent, not a zero
    assert shares[(key, "2026-09-01")] == 43.0


def test_navi_july_gap_is_a_real_absence_not_backfilled(sundaram_rows, amc_id_map):
    """TC-S6c: the one Trendlyne figure this source does NOT reproduce (Navi, 2026-07) is a
    genuinely missing month here, never invented to force a match. 2026-06 and 2026-08 both exist;
    2026-07 does not."""
    shares = _shares_by_fund_month(sundaram_rows, amc_id_map)
    key = "navi|" + base_scheme_name("Navi Nifty MidSmallcap 400 Index Fund Direct-Growth")
    assert (key, "2026-06-01") in shares
    assert (key, "2026-08-01") in shares
    assert (key, "2026-07-01") not in shares


# ── TC-S7/S8: no double-counting, sources reported separately ──────────────────────────────────

def test_overlapping_amc_is_counted_from_amc_file_only_never_summed():
    """TC-S7: an AMC present on BOTH sides (e.g. 'sbi') must be counted from amc_file_groups
    ONLY. If this ever summed both sides, mf_shares below would be 300 instead of 100."""
    amc_file = [CanonicalHolding(amc_id="sbi", base_scheme="sbi bluechip fund",
                                  security_isin="INEXXX", shares=100.0,
                                  naive_sum_quantity=400.0, variant_rows=4)]
    scanx = [ScanxCanonicalHolding(amc_id="sbi", base_scheme="sbi bluechip fund",
                                    security_isin="INEXXX", as_of_month="2026-09-01", shares=200.0),
             ScanxCanonicalHolding(amc_id="alphagrep", base_scheme="alphagrep flexi cap fund",
                                    security_isin="INEXXX", as_of_month="2026-09-01", shares=50.0)]
    combined = combine_extended_holdings(amc_file, scanx)
    acc = combined["INEXXX"]
    assert acc.mf_shares == 150.0                 # 100 (sbi, amc-file) + 50 (alphagrep, scanx only)
    assert acc.amcs_amc_file == {"sbi"}
    assert acc.amcs_scanx == {"alphagrep"}
    assert acc.funds == 2
    assert acc.funds_scanx == 1
    assert acc.amcs == 2                            # union, not a sum that would double-count sbi


def test_sources_are_reported_separately_never_blended():
    """TC-S8: amcs_amc_file / amcs_scanx / funds_scanx stay distinct fields on the result, the
    same separation migration 182/183 keep between duplication and coverage. There is no single
    'amcs' input field a caller could mistake for the whole picture without the breakdown."""
    amc_file = [CanonicalHolding(amc_id="kotak", base_scheme="kotak arbitrage fund",
                                  security_isin="INEYYY", shares=10.0)]
    scanx = [ScanxCanonicalHolding(amc_id="navi", base_scheme="navi flexi cap fund",
                                    security_isin="INEYYY", as_of_month="2026-09-01", shares=5.0)]
    acc = combine_extended_holdings(amc_file, scanx)["INEYYY"]
    assert acc.amcs_amc_file == {"kotak"}
    assert acc.amcs_scanx == {"navi"}
    assert acc.funds_scanx == 1
    # Both counts are independently recoverable from the object; neither is lost in a blend.
    assert len(acc.amcs_amc_file) + len(acc.amcs_scanx) == acc.amcs


def test_empty_scanx_groups_reduce_to_the_amc_file_figure():
    """TC-S9: with no ScanX input at all, combine_extended_holdings() must reproduce the amc-file
    figure exactly — the extension must be a strict superset, never a different number for the
    11 AMCs it already had."""
    amc_file = [CanonicalHolding(amc_id="uti", base_scheme="uti flexi cap fund",
                                  security_isin="INEZZZ", shares=42.0, naive_sum_quantity=42.0)]
    acc = combine_extended_holdings(amc_file, [])["INEZZZ"]
    assert acc.mf_shares == 42.0
    assert acc.amcs_scanx == set()
    assert acc.funds_scanx == 0
