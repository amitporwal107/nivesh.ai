"""Unit tests for services.goal_engine — pure-logic coverage.

Verifies:
  - Future value / SIP / lump sum math (PRD §7)
  - Allocation profiles + horizon guardrail (§8, §15)
  - Blended return/vol from allocation
  - Scenario matrix produces 4 named scenarios with monotone ordering
  - Monte-Carlo returns a plausible distribution
  - Action recommender picks the right signal per state
  - Single-shot evaluate_goal wires everything up
"""
from __future__ import annotations
import pytest
from services import goal_engine as ge


# ── Core math ──────────────────────────────────────────────────────────
def test_inflate_target_matches_formula():
    # ₹1 Cr × (1.06)^10 ≈ ₹1.791 Cr
    assert ge.inflate_target(10000000, 10, 6) == pytest.approx(17908476.97, rel=1e-3)


def test_required_sip_zero_pv_matches_formula():
    # FV=10L in 10y @ 12% annual → SIP around ₹4,347
    sip = ge.required_sip(1000000, 10, 12.0, starting_corpus_rs=0)
    assert 4200 < sip < 4600


def test_required_sip_with_pv_reduces_sip():
    sip_no_pv = ge.required_sip(1000000, 10, 12.0)
    sip_with_pv = ge.required_sip(1000000, 10, 12.0, starting_corpus_rs=200000)
    assert sip_with_pv < sip_no_pv


def test_required_sip_pv_exceeds_target_returns_zero():
    sip = ge.required_sip(future_value_rs=500000, years=10, annual_return_pct=10,
                          starting_corpus_rs=2000000)
    assert sip == 0.0


def test_required_lumpsum_inverse_of_fv():
    # If lumpsum grows @ 10% for 10y → FV = PV × 1.1^10
    pv = ge.required_lumpsum(future_value_rs=1000000, years=10, annual_return_pct=10)
    assert pv == pytest.approx(385543.29, rel=1e-3)


def test_project_corpus_matches_sip_math():
    # ₹10K/mo, 20y @ 12% → around ₹91-99L (range allows for monthly-equivalent vs arithmetic monthly rate convention)
    fv = ge.project_corpus_fixed(0, 10000, 20, 12)
    assert 8800000 < fv < 10500000


def test_project_corpus_with_starting():
    a = ge.project_corpus_fixed(100000, 10000, 10, 10)
    b = ge.project_corpus_fixed(0, 10000, 10, 10)
    assert a > b


# ── Allocation & horizon guardrail ─────────────────────────────────────
def test_allocation_for_moderate_profile():
    alloc = ge.allocation_for_profile("moderate", 10)
    assert alloc == {"equity": 60, "debt": 30, "hybrid": 10}


def test_allocation_for_aggressive_profile():
    alloc = ge.allocation_for_profile("aggressive", 10)
    assert alloc["equity"] == 80


def test_allocation_caps_equity_for_short_horizon():
    # Aggressive user but 3y horizon → equity must be capped at 40
    alloc = ge.allocation_for_profile("aggressive", 3)
    assert alloc["equity"] == 40
    assert alloc["equity"] + alloc["debt"] + alloc["hybrid"] == 100


def test_allocation_unknown_profile_falls_back_to_moderate():
    alloc = ge.allocation_for_profile("bogus", 10)
    assert alloc["equity"] == 60


# ── Blended return / vol ───────────────────────────────────────────────
def test_blend_return_vol_matches_weighted_avg():
    # 60/30/10 Moderate: 0.6*12 + 0.3*6.5 + 0.1*9 = 10.05
    stats = ge.blend_return_vol({"equity": 60, "debt": 30, "hybrid": 10})
    assert stats["annual_return_pct"] == 10.05


def test_blend_100_debt_gives_debt_stats():
    stats = ge.blend_return_vol({"equity": 0, "debt": 100, "hybrid": 0})
    assert stats["annual_return_pct"] == 6.5


# ── Scenario matrix ────────────────────────────────────────────────────
def test_scenario_matrix_orders_corpus():
    sc = ge.scenario_matrix(
        starting_corpus_rs=0, monthly_sip_rs=10000, years=10,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=5000000,
    )
    assert set(sc.keys()) == {"base", "bull", "bear", "stress"}
    # Corpus ordering: stress < bear < base < bull
    assert sc["stress"]["corpus_rs"] <= sc["bear"]["corpus_rs"] <= sc["base"]["corpus_rs"] <= sc["bull"]["corpus_rs"]


def test_scenario_matrix_never_goes_negative():
    """Even for extreme allocations, bear/stress returns are floored at 0.5%."""
    sc = ge.scenario_matrix(
        starting_corpus_rs=0, monthly_sip_rs=5000, years=5,
        allocation={"equity": 100, "debt": 0, "hybrid": 0},
        future_target_rs=500000,
    )
    for k, v in sc.items():
        assert v["return_pct"] >= 0.5


# ── Monte-Carlo ────────────────────────────────────────────────────────
def test_mc_deterministic_with_seed():
    mc1 = ge.monte_carlo_success(
        starting_corpus_rs=100000, monthly_sip_rs=10000, years=10,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=2500000, n_runs=500, seed=7,
    )
    mc2 = ge.monte_carlo_success(
        starting_corpus_rs=100000, monthly_sip_rs=10000, years=10,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=2500000, n_runs=500, seed=7,
    )
    assert mc1 == mc2


def test_mc_probability_in_range():
    mc = ge.monte_carlo_success(
        starting_corpus_rs=0, monthly_sip_rs=20000, years=15,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=10000000, n_runs=500, seed=42,
    )
    assert 0 <= mc["prob_success_pct"] <= 100
    assert mc["p5_corpus_rs"] <= mc["median_corpus_rs"] <= mc["p95_corpus_rs"]
    assert mc["n_runs"] == 500


def test_mc_huge_sip_high_success():
    mc = ge.monte_carlo_success(
        starting_corpus_rs=1000000, monthly_sip_rs=100000, years=20,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=5000000, n_runs=500, seed=99,
    )
    # Well-funded plan should hit target almost always
    assert mc["prob_success_pct"] >= 95


def test_mc_underfunded_low_success():
    mc = ge.monte_carlo_success(
        starting_corpus_rs=0, monthly_sip_rs=1000, years=5,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        future_target_rs=10000000, n_runs=500, seed=42,
    )
    assert mc["prob_success_pct"] < 10


# ── Action recommender ────────────────────────────────────────────────
def test_actions_recommend_sip_increase_on_shortfall():
    actions = ge.recommend_actions(
        on_track_pct=45, required_sip_rs=30000, actual_sip_rs=10000,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        risk_profile="moderate", horizon_years=10,
    )
    kinds = [a.kind for a in actions]
    assert "increase_sip" in kinds


def test_actions_recommend_risk_reduction_for_short_horizon():
    actions = ge.recommend_actions(
        on_track_pct=70, required_sip_rs=10000, actual_sip_rs=10000,
        allocation={"equity": 80, "debt": 10, "hybrid": 10},
        risk_profile="aggressive", horizon_years=3,
    )
    assert any(a.kind == "reduce_risk" for a in actions)


def test_actions_on_track_signal_when_healthy():
    actions = ge.recommend_actions(
        on_track_pct=95, required_sip_rs=10000, actual_sip_rs=10000,
        allocation={"equity": 60, "debt": 30, "hybrid": 10},
        risk_profile="moderate", horizon_years=15,
    )
    assert any(a.kind == "on_track" for a in actions)


# ── evaluate_goal wiring ──────────────────────────────────────────────
def test_evaluate_goal_full_plan():
    ev = ge.evaluate_goal(
        target_today_rs=10000000, horizon_years=15,
        starting_corpus_rs=200000, monthly_sip_rs=15000,
        risk_profile="moderate",
    )
    assert ev.future_target_rs > 10000000         # inflation-adjusted upward
    assert ev.expected_return_pct == 10.05        # moderate blend
    assert 0 <= ev.on_track_pct <= 100
    assert ev.required_sip_rs > 0
    assert set(ev.scenarios.keys()) == {"base", "bull", "bear", "stress"}
    assert "prob_success_pct" in ev.monte_carlo
    assert ev.actions
    # Dict round-trip works
    d = ev.to_dict()
    assert "future_target_rs" in d and "monte_carlo" in d


def test_evaluate_goal_allocation_override_respected():
    ev = ge.evaluate_goal(
        target_today_rs=5000000, horizon_years=10,
        starting_corpus_rs=0, monthly_sip_rs=10000,
        risk_profile="moderate",
        allocation_override={"equity": 0, "debt": 100, "hybrid": 0},
    )
    # 100% debt should produce the debt-only return
    assert ev.expected_return_pct == 6.5
