"""Unit tests for switch_decision_engine — Cases A/B/C/D from the PRD.

Run: cd /app/backend && pytest tests/test_switch_decision_engine.py -v
"""
import pytest
from services import switch_decision_engine as sde


def _inp(**kw):
    """Factory that defaults to the HDFC BAF scenario user raised:
    good Q/H/A, Regular plan, > ₹14L value, holding > 1 year."""
    base = dict(
        quality=71, health=80, exit_s=41, add=77,
        invested_amount=1_100_000, current_value=1_470_000,
        holding_period_days=900, is_equity=True,
        exit_load_pct=0.0,
        expense_regular=0.0185, expense_direct=0.0074,   # diff 1.11%
        years_to_goal=10, alt_expected_alpha=0.0,
        better_alternative_exists=False,
    )
    base.update(kw)
    return sde.DecisionInputs(**base)


# ── Case A: STRONG_SWITCH_DIRECT (the user's HDFC scenario) ─────────────
def test_case_a_strong_switch_direct_when_tax_plus_exit_under_half_saving():
    r = sde.decide(_inp(), plan_type="regular")
    assert r.action == sde.ACTION_STRONG_SWITCH_DIRECT
    assert r.decision_case == "A_direct"
    # ~1.11% × ₹14.7L × 10y ≈ ₹163k saving; gain ₹3.7L, taxable ₹2.7L,
    # tax 10% = ₹27k. Exit 0. 27k < 81k (half saving) → STRONG.
    assert r.economics["annual_saving"] > 10_000
    assert r.economics["tax_cost"] < r.economics["total_cost_saving"] * 0.5


# ── Case A: PARTIAL_SWITCH when tax erodes > half but net still positive ─
def test_case_a_partial_when_tax_heavy_but_net_positive():
    r = sde.decide(_inp(
        invested_amount=100_000, current_value=2_000_000,   # huge gain
        holding_period_days=400,                             # LTCG just barely
    ), plan_type="regular")
    # gain ₹19L → LTCG on ₹18L × 10% = ₹1.8L tax
    # saving ≈ ₹2M × 1.11% × 10y = ₹222k; 1.8L > half of 222k
    # but net = 222k − 180k = +42k → PARTIAL
    assert r.action == sde.ACTION_PARTIAL_SWITCH
    assert r.economics["net_benefit"] > 0


# ── Case A: HOLD_DEFER when net benefit goes negative ───────────────────
def test_case_a_hold_defer_when_net_benefit_negative():
    r = sde.decide(_inp(
        invested_amount=100_000, current_value=2_000_000,
        holding_period_days=400,
        years_to_goal=1,   # slash horizon so saving is small
    ), plan_type="regular")
    # saving = 22k, tax = 1.8L → net heavily negative → HOLD_DEFER
    assert r.action == sde.ACTION_HOLD_DEFER
    assert r.economics["net_benefit"] < 0


# ── Case C: Tax Override when STCG drag > savings (inside 1 year) ────────
def test_case_c_tax_override_stcg_drag():
    r = sde.decide(_inp(
        holding_period_days=180,   # STCG
        invested_amount=1_000_000,
        current_value=1_500_000,   # ₹5L STCG gain → 75k tax
        years_to_goal=5,
    ), plan_type="regular")
    # 15% of 500k = 75k tax
    # saving = 1.5M × 1.11% × 5 = ₹83k
    # tax 75k > saving+alpha (83k+0)? Actually 75k < 83k — Case C won't trigger.
    # But total_cost_saving*0.5 = 41.5k; tax 75k > 41.5k → not STRONG → PARTIAL
    assert r.action == sde.ACTION_PARTIAL_SWITCH

    # Stronger case: force STCG > saving
    r2 = sde.decide(_inp(
        holding_period_days=180,
        invested_amount=100_000,
        current_value=1_000_000,   # ₹9L STCG gain → ₹1.35L tax
        years_to_goal=1,           # saving small
    ), plan_type="regular")
    # saving = 1M × 1.11% × 1y = 11k; tax 135k > 11k → Case C
    assert r2.action == sde.ACTION_HOLD_TAX


# ── Case D: Exit Load Protection ────────────────────────────────────────
def test_case_d_exit_load_beats_saving():
    r = sde.decide(_inp(
        exit_load_pct=0.01,        # 1% exit load
        years_to_goal=1,           # shrink saving
    ), plan_type="regular")
    # exit_cost = 1.47L × 0.01 = ₹14,700
    # saving = 1.47L × 1.11% × 1 = ₹16,317 — still slightly > exit
    # So this should go STRONG (tax+exit=14.7k+2.7k gain tax is 0 since LTCG
    # exempt… ah 900d holding, gain 370k → LTCG (370k-100k)*10% = 27k
    # tax+exit = 14.7k + 27k = 41.7k > 0.5*16.3k → not strong.
    # net = 16.3k - 41.7k - 0 = -25k negative → HOLD_DEFER.
    # To genuinely trigger Case D, need exit > saving:
    r2 = sde.decide(_inp(
        exit_load_pct=0.05,        # 5% — absurd but proves rule
        invested_amount=1_470_000, current_value=1_470_000,   # no gain, no tax
        years_to_goal=1,
    ), plan_type="regular")
    # exit = 73.5k; saving = 1.47L × 1.11% × 1 = 16.3k; 73k > 16k → HOLD_EXIT_LOAD
    assert r2.action == sde.ACTION_HOLD_EXIT_LOAD


# ── Case B: Fund-to-fund HOLD when no alt ───────────────────────────────
def test_case_b_hold_when_no_better_alt():
    # Direct plan — so Case A is skipped. No alt → HOLD.
    r = sde.decide(_inp(), plan_type="direct")
    assert r.action == sde.ACTION_HOLD


# ── Case B: STRONG_SWITCH_FUND when alt exists + signals ≥ 3 + net > 0 ──
def test_case_b_strong_switch_to_alt_fund():
    r = sde.decide(_inp(
        quality=30, health=30, exit_s=30, add=30,   # all weak → signals=4
        expense_regular=0.0, expense_direct=0.0,    # no direct saving
        better_alternative_exists=True,
        alt_expected_alpha=0.02,                    # 2% alpha justifies switch
        invested_amount=1_470_000, current_value=1_470_000,  # no tax
    ), plan_type="direct")
    assert r.action == sde.ACTION_STRONG_SWITCH_FUND
    assert r.switch_score >= 3


# ── Signals math ────────────────────────────────────────────────────────
def test_signals_exit_below_40_scores_2():
    s = sde.compute_signals(_inp(exit_s=35))
    assert s["exit_signal"] == 2


def test_signals_exit_between_40_and_60_scores_1():
    s = sde.compute_signals(_inp(exit_s=50))
    assert s["exit_signal"] == 1


def test_signals_exit_above_60_scores_0():
    s = sde.compute_signals(_inp(exit_s=80))
    assert s["exit_signal"] == 0


# ── Tax calculation ────────────────────────────────────────────────────
def test_tax_equity_stcg():
    t = sde.compute_tax_cost(_inp(
        holding_period_days=100, invested_amount=100_000, current_value=200_000,
    ))
    assert t == 15_000   # 15% of ₹100k STCG


def test_tax_equity_ltcg_with_exemption():
    t = sde.compute_tax_cost(_inp(
        holding_period_days=400, invested_amount=100_000, current_value=300_000,
    ))
    # gain 200k, taxable (200k-100k) = 100k, tax 10% = 10k
    assert t == 10_000


def test_tax_debt_slab():
    t = sde.compute_tax_cost(_inp(
        is_equity=False, invested_amount=100_000, current_value=150_000,
        debt_slab_rate=0.30,
    ))
    assert t == 15_000   # 30% slab on ₹50k gain
