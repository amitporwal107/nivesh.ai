"""Tests for the Cost-of-Switch framework overlay (PRD).

Validates the 3 threshold rules added on top of the engine:
  1. switch_cost_pct > 2% AND switch_score < 3 → WATCHLIST (block)
  2. switch_cost_pct < 1% → STRONG_SWITCH labelled "low-friction"
  3. tax_impact_pct > 2% → STAGGERED_SWITCH (STP)
Plus the structured cost breakdown in `compute_switch_costs()`.
"""
import pytest
from services import switch_decision_engine as sde


def _strong_alt():
    return sde.CandidateFund(
        name="Better Fund Direct",
        category="Flexi Cap",
        expense=0.006, return_5y=0.20, drawdown=0.18, consistency=85,
        aum_cr=50_000, track_record_years=8,
    )


def _base_inp(**kw):
    """Direct-plan holder with healthy gain — sets up clean cost math."""
    base = dict(
        quality=55, health=55, exit_s=45, add=55,
        invested_amount=500_000, current_value=600_000,
        holding_period_days=240,                       # STCG
        is_equity=True, exit_load_pct=0.01,            # 1% exit load
        expense_current=0.018, expense_direct=None,
        current_return_5y=0.13, current_drawdown=0.22, current_consistency=60,
        current_category="Flexi Cap", current_fund_name="Cur Fund",
        years_to_goal=5, direct_plan_available=False,
        candidate_funds=[_strong_alt()],
    )
    base.update(kw)
    return sde.DecisionInputs(**base)


# ── compute_switch_costs() ──────────────────────────────────────────────
def test_cost_breakdown_matches_user_example():
    """User's PRD example: invested=5L, current=6L, gain=1L, STCG, 1% exit load.
    Expected: exit=6k, tax=15k, slippage=1.2k → total cost ≈ 3.7%."""
    inp = sde.DecisionInputs(
        invested_amount=500_000, current_value=600_000,
        holding_period_days=240,                # STCG
        is_equity=True,
        exit_load_pct=0.01,                     # 1%
        slippage_pct=0.002,                     # 0.2%
    )
    c = sde.compute_switch_costs(inp)
    assert c["exit_cost"] == 6_000.0
    assert c["tax_cost"] == 15_000.0    # 1L gain × 15% STCG
    assert c["slippage_cost"] == 1_200.0
    assert c["total_cost"] == 22_200.0
    # Total cost % = 22,200 / 600,000 = 3.7%
    assert c["switch_cost_pct"] == pytest.approx(0.037, abs=1e-4)
    assert c["tax_impact_pct"] == pytest.approx(0.025, abs=1e-4)


def test_cost_breakdown_zero_gain_zero_tax():
    inp = sde.DecisionInputs(
        invested_amount=500_000, current_value=500_000,    # no gain
        holding_period_days=200, is_equity=True,
        exit_load_pct=0.01, slippage_pct=0.002,
    )
    c = sde.compute_switch_costs(inp)
    assert c["tax_cost"] == 0.0
    assert c["exit_cost"] == 5_000.0
    assert c["switch_cost_pct"] == pytest.approx(0.012, abs=1e-4)


# ── Rule 1: switch_cost > 2% AND signals weak → WATCHLIST ───────────────
def test_high_switch_cost_with_weak_signals_blocks_to_watchlist():
    """8% tax + 1% exit + 0.2% slip = ~9% friction. Score=1 (weak)."""
    r = sde.decide(_base_inp(
        quality=70, health=70, exit_s=55, add=55,    # A<65 so ADD doesn't fire
    ), plan_type="direct")
    assert r.action == sde.ACTION_WATCHLIST
    d = sde.result_to_dict(r)
    assert d["recommendation"] == "REVIEW"
    assert d["impact"]["switch_cost_pct"] > 2.0
    # Reason should cite the friction
    assert any("Switch cost" in r2 and "%" in r2 for r2 in d["reason"])


def test_high_switch_cost_with_strong_signals_passes_to_staggered():
    """Score=3 + tax>2% → not blocked, escalates to STAGGERED_SWITCH."""
    r = sde.decide(_base_inp(
        quality=45, health=45, exit_s=38, add=45,    # score=5
    ), plan_type="direct")
    # tax_impact ~ 2.5% > 2% threshold + score>=3 → STAGGERED
    assert r.action == sde.ACTION_STAGGERED_SWITCH


# ── Rule 2: switch_cost < 1% → low-friction tag ─────────────────────────
def test_low_friction_switch_uses_aggressive_path():
    """LTCG-eligible holding with tiny gain → tax = 0, total cost ~0.2%."""
    r = sde.decide(_base_inp(
        invested_amount=500_000, current_value=505_000,    # 5k gain only
        holding_period_days=400,                            # LTCG (gain<1L)
        exit_load_pct=0.0,                                  # exit window passed
        quality=45, health=45, exit_s=38, add=45,           # score=5
        years_to_goal=10,
    ), plan_type="direct")
    assert r.action == sde.ACTION_STRONG_SWITCH
    d = sde.result_to_dict(r)
    assert d["impact"]["switch_cost_pct"] < 1.0
    # Should mention "low-friction"
    assert any("low-friction" in r2 for r2 in d["reason"])


# ── Rule 3: tax_impact > 2% → STAGGERED ─────────────────────────────────
def test_high_tax_impact_routes_to_staggered_switch():
    """STCG ~₹15k on ₹6L = 2.5% > 2% threshold."""
    r = sde.decide(_base_inp(
        quality=48, health=55, exit_s=45, add=55,    # score=2
        exit_load_pct=0.0,                            # remove exit load
    ), plan_type="direct")
    assert r.action == sde.ACTION_STAGGERED_SWITCH
    d = sde.result_to_dict(r)
    assert d["recommendation"] == "SWITCH"
    assert d["action_strength"] == "MEDIUM"
    assert d["allocation_change"] == "25%"
    assert "STP" in d["reason"][1] or "Stagger" in d["reason"][1]
    assert d["impact"]["tax_impact_pct"] > 2.0


def test_low_tax_impact_does_not_trigger_staggered():
    """LTCG-eligible with gain just above ₹1L → tiny tax → no stagger."""
    r = sde.decide(_base_inp(
        invested_amount=500_000, current_value=605_000,  # 1.05L gain
        holding_period_days=400,                          # LTCG
        exit_load_pct=0.0,
        quality=45, health=45, exit_s=38, add=45,         # score=5 → strong
    ), plan_type="direct")
    # Tax = 5k × 10% = 500 → tax_impact_pct = 0.083% ≪ 2%
    # Score>=3, low cost → STRONG_SWITCH
    assert r.action == sde.ACTION_STRONG_SWITCH


# ── Output exposes the new cost fields ──────────────────────────────────
def test_impact_block_exposes_cost_breakdown():
    r = sde.decide(_base_inp(), plan_type="direct")
    d = sde.result_to_dict(r)
    impact = d["impact"]
    # All Cost-of-Switch fields present
    for k in ("switch_cost_pct", "tax_impact_pct", "exit_load_pct",
              "slippage_pct", "alpha_pct_annual", "slippage_cost"):
        assert k in impact, f"Missing field: {k}"


# ── SIP_REDIRECT bypasses cost-block (zero switch cost) ────────────────
def test_sip_redirect_not_blocked_by_high_switch_cost():
    """High tax + score=2 + negative net → SIP_REDIRECT (zero-cost path)."""
    r = sde.decide(_base_inp(
        quality=48, health=60, exit_s=50, add=60,        # score=2
        invested_amount=100_000, current_value=2_000_000,  # huge gain
        holding_period_days=400,                          # LTCG
        years_to_goal=1,                                  # small benefit horizon
        exit_load_pct=0.0,
        candidate_funds=[sde.CandidateFund(
            name="Modest Alt", category="Flexi Cap",
            expense=0.012, return_5y=0.151, drawdown=0.21, consistency=72,
            aum_cr=2000, track_record_years=5,
        )],
    ), plan_type="direct")
    # Even though switch_cost ~9.2%, SIP_REDIRECT runs first
    # (zero redemption cost) for net_benefit ≤ 0.
    assert r.action == sde.ACTION_SIP_REDIRECT


# ── Slippage default applied ────────────────────────────────────────────
def test_default_slippage_pct_is_0_2():
    inp = sde.DecisionInputs(
        invested_amount=100_000, current_value=100_000,
        is_equity=True, exit_load_pct=0.0,
    )
    c = sde.compute_switch_costs(inp)
    # 0.2% slippage default
    assert c["slippage_pct"] == pytest.approx(0.002, abs=1e-6)
    assert c["slippage_cost"] == pytest.approx(200.0, abs=0.5)
