"""Regression tests for scheme-name → AMFI-code resolution (2026-06-25).

The old "split at first '(' or '-'" base extractor collapsed distinct funds that
share a prefix before a parenthetical — every "SBI Fixed Maturity Plan (FMP) -
Series N" became base "sbi fixed maturity plan", so 20 FMP series' holdings were
written to ALL FMP codes (per-scheme weight summed to >1000%). The resolver now
strips only the plan suffix and matches in precision order, collision-free.
"""
from nidp.services.mf_holdings.amc_dispatch import (
    _build_scheme_index,
    _resolve_scheme_codes,
    _scheme_identity,
)


def _row(code, name):
    return {"scheme_code": code, "scheme_name": name}


# Two FMP series + a normal fund, each with Regular/Direct × Growth/IDCW variants.
DB = [
    _row("F1G", "SBI Fixed Maturity Plan (FMP) - Series 1 (3668 Days) - Regular Plan - Growth"),
    _row("F1I", "SBI Fixed Maturity Plan (FMP) - Series 1 (3668 Days) - Direct Plan - Income Distribution cum Capital Withdrawal Option (IDCW)"),
    _row("F14G", "SBI Fixed Maturity Plan (FMP) - Series 14 (1100 Days) - Regular Plan - Growth"),
    _row("CONG", "SBI CONTRA FUND - REGULAR PLAN - GROWTH"),
    _row("COND", "SBI Contra Fund - Direct Plan - Income Distribution cum Capital Withdrawal Option (IDCW)"),
    _row("BANK", "SBI Banking & Financial Services Fund - Regular Plan - Growth"),
    _row("GILT", "SBI Gilt Fund - Regular Plan - Growth"),
]


def test_identity_strips_plan_suffix_and_keeps_series():
    assert _scheme_identity(DB[0]["scheme_name"]) == "sbi fixed maturity plan (fmp)-series 1 (3668 days)"
    assert _scheme_identity("SBI Contra Fund - Direct Plan - Growth") == "sbi contra fund"


def test_fmp_series_do_not_collide():
    idx = _build_scheme_index(DB)
    s1 = set(_resolve_scheme_codes("SBI Fixed Maturity Plan (FMP)- Series 1", idx))
    s14 = set(_resolve_scheme_codes("SBI Fixed Maturity Plan (FMP)- Series 14", idx))
    assert s1 == {"F1G", "F1I"}          # boundary-prefix: only Series 1's variants
    assert s14 == {"F14G"}               # Series 1 must NOT leak into Series 14
    assert s1.isdisjoint(s14)            # no cross-contamination


def test_normal_fund_resolves_all_plan_variants():
    idx = _build_scheme_index(DB)
    assert set(_resolve_scheme_codes("SBI Contra Fund", idx)) == {"CONG", "COND"}


def test_ampersand_and_erstwhile_normalisation():
    idx = _build_scheme_index(DB)
    assert set(_resolve_scheme_codes("SBI Banking And Financial Services Fund", idx)) == {"BANK"}
    assert set(_resolve_scheme_codes(
        "SBI Gilt Fund (Erstwhile known as SBI Magnum Gilt Fund)", idx)) == {"GILT"}


def test_no_fund_claims_another_funds_codes():
    idx = _build_scheme_index(DB)
    code_to_funds = {}
    for fund in ["SBI Fixed Maturity Plan (FMP)- Series 1",
                 "SBI Fixed Maturity Plan (FMP)- Series 14",
                 "SBI Contra Fund", "SBI Banking And Financial Services Fund", "SBI Gilt Fund"]:
        for c in _resolve_scheme_codes(fund, idx):
            code_to_funds.setdefault(c, set()).add(fund)
    collisions = {c: f for c, f in code_to_funds.items() if len(f) > 1}
    assert collisions == {}
