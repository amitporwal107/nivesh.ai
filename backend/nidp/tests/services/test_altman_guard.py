"""Altman Z must stay bounded when EPS or debt is a rounding artefact.

Live staging (2026-09-08) had altman_z_score up to 27,350: X4 = market cap /
total debt with no floor on either input.
"""
from nidp.services.fundamental_engine.calculator import compute_altman_z

BASE = {"total_equity_cr": 1000.0, "long_term_debt_cr": 200.0, "short_term_debt_cr": 100.0,
        "cash_and_equiv_cr": 50.0, "pat_cr": 50.0, "finance_costs_cr": 5.0,
        "depreciation_cr": 10.0, "revenue_ttm_cr": 2000.0, "eps_basic": 5.0}


def test_trivial_debt_scores_no_higher_than_debt_free():
    tiny = {**BASE, "long_term_debt_cr": 0.0, "short_term_debt_cr": 0.01}
    free = {**BASE, "long_term_debt_cr": 0.0, "short_term_debt_cr": 0.0}
    assert compute_altman_z(tiny, 500.0) <= compute_altman_z(free, 500.0) + 1e-9


def test_rounding_artefact_eps_does_not_explode():
    z = compute_altman_z({**BASE, "eps_basic": 0.001}, 500.0)
    assert z is not None and abs(z) < 100


def test_ordinary_company_scores_in_the_safe_zone():
    z = compute_altman_z(BASE, 500.0)
    assert 2.99 < z < 20
