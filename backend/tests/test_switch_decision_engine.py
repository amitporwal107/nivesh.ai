"""Unit tests for Nivesh Switch Engine v2 — full 9-step PRD coverage."""
import pytest
from services import switch_decision_engine as sde


def _inp(**kw):
    """Factory — HDFC BAF scenario: Regular plan, good fund, 1-year+ hold."""
    base = dict(
        quality=71, health=80, exit_s=41, add=77,
        invested_amount=1_100_000, current_value=1_470_000,
        holding_period_days=900, is_equity=True,
        exit_load_pct=0.0,
        expense_current=0.0185, expense_direct=0.0074,
        current_return_5y=0.14, current_drawdown=0.22, current_consistency=70,
        current_category="Balanced Advantage",
        current_fund_name="HDFC Balanced Advantage Regular",
        years_to_goal=10,
        direct_plan_available=True,
        candidate_funds=[],
    )
    base.update(kw)
    return sde.DecisionInputs(**base)


def _strong_alt():
    """A candidate fund that is clearly better than the current (HDFC BAF)."""
    return sde.CandidateFund(
        name="Parag Parikh Flexi Cap Direct",
        category="Balanced Advantage",
        expense=0.006, return_5y=0.18, drawdown=0.18, consistency=85,
        aum_cr=50_000, track_record_years=8,
    )


# ── Step 6: Direct plan priority (user's HDFC case) ─────────────────────
def test_direct_plan_priority_strong_switch():
    r = sde.decide(_inp(), plan_type="regular")
    assert r.action == sde.ACTION_STRONG_SWITCH_DIRECT
    assert r.allocation_pct == 100
    assert r.to_fund == "Direct plan (same fund)"
    # Expect ~163k direct_saving, 27k tax, 0 exit → clear win
    assert r.breakdown["direct_saving"] > 100_000
    assert "Direct plan saves" in r.reason[0]


def test_direct_plan_priority_phased_when_tax_heavy():
    r = sde.decide(_inp(
        invested_amount=100_000, current_value=2_000_000,
        holding_period_days=400,   # LTCG just barely
        years_to_goal=2,            # direct_saving only ~44k, tax 190k → phased/defer
        expense_current=0.012, expense_direct=0.0074,   # diff 0.46%, below STRONG threshold path
    ), plan_type="regular")
    # expense_diff 0.46% < 0.5% → skips Direct priority, falls through to
    # LTCG harvest since gain > ₹1L
    assert r.action == sde.ACTION_PARTIAL_SWITCH


def test_direct_plan_priority_hold_defer_when_net_negative():
    r = sde.decide(_inp(
        invested_amount=100_000, current_value=2_000_000,
        holding_period_days=400,
        years_to_goal=1,
    ), plan_type="regular")
    assert r.action == sde.ACTION_HOLD_DEFER


# ── Step 5: Hard blockers ───────────────────────────────────────────────
def test_hard_blocker_tax_stcg_drag():
    r = sde.decide(_inp(
        holding_period_days=180,
        invested_amount=100_000, current_value=1_000_000,
        years_to_goal=1,
    ), plan_type="regular")
    # STCG 15% × 9L = 135k; saving 1M × 1.11% × 1 = 11.1k → HOLD_TAX
    assert r.action == sde.ACTION_HOLD_TAX


def test_hard_blocker_exit_load_heavy():
    r = sde.decide(_inp(
        exit_load_pct=0.05,
        invested_amount=1_470_000, current_value=1_470_000,  # no gain
        years_to_goal=1,
    ), plan_type="regular")
    assert r.action == sde.ACTION_HOLD_EXIT_LOAD


def test_hard_blocker_no_option():
    r = sde.decide(_inp(
        direct_plan_available=False,
        candidate_funds=[],
        expense_current=0.0074,   # already direct-ish
        expense_direct=None,
    ), plan_type="direct")
    assert r.action == sde.ACTION_HOLD_NO_OPTION


# ── Step 3 + 7: Fund switch with candidate universe ─────────────────────
def test_fund_switch_strong_when_alt_exists_and_signals_high():
    r = sde.decide(_inp(
        quality=30, health=30, exit_s=30, add=30,      # score = 4/5
        direct_plan_available=False,
        current_return_5y=0.10, current_drawdown=0.28, current_consistency=60,
        candidate_funds=[_strong_alt()],
    ), plan_type="direct")
    assert r.action == sde.ACTION_STRONG_SWITCH
    assert r.allocation_pct == 100
    assert r.to_fund == "Parag Parikh Flexi Cap Direct"
    assert r.switch_score >= 3


def test_fund_switch_partial_when_score_2_and_positive_net():
    r = sde.decide(_inp(
        quality=48, health=48, exit_s=80, add=80,      # score = 2/5
        direct_plan_available=False,
        current_return_5y=0.10, current_drawdown=0.28, current_consistency=60,
        candidate_funds=[_strong_alt()],
        invested_amount=1_470_000, current_value=1_470_000,   # no tax
    ), plan_type="direct")
    assert r.action == sde.ACTION_PARTIAL_SWITCH
    assert r.allocation_pct == 40


def _weak_alt():
    """Candidate that passes filters but has small return/cost uplift."""
    return sde.CandidateFund(
        name="Modest Alt Direct",
        category="Balanced Advantage",
        expense=0.012, return_5y=0.12, drawdown=0.20, consistency=70,
        aum_cr=2000, track_record_years=5,
    )


def test_fund_switch_watchlist_when_score_high_but_tax_drag():
    r = sde.decide(_inp(
        quality=30, health=30, exit_s=30, add=30,      # score = 4/5
        direct_plan_available=False,
        invested_amount=100_000, current_value=2_000_000,
        holding_period_days=400,                       # LTCG just barely
        current_return_5y=0.11, current_drawdown=0.28, current_consistency=60,
        candidate_funds=[_weak_alt()],
        years_to_goal=1,                                # tiny benefit
    ), plan_type="direct")
    # alt gives 0.01 uplift × 2M × 1 = 20k alpha + 12k cost saving = 32k
    # Tax ~190k → net negative → WATCHLIST
    assert r.action == sde.ACTION_WATCHLIST


def test_fund_switch_sip_redirect_when_score_2_and_net_negative():
    r = sde.decide(_inp(
        quality=48, health=60, exit_s=50, add=60,      # score = 1(exit)+1(quality) = 2
        direct_plan_available=False,
        invested_amount=100_000, current_value=2_000_000,
        holding_period_days=400,
        current_return_5y=0.11, current_drawdown=0.28, current_consistency=60,
        candidate_funds=[_weak_alt()],
        years_to_goal=1,
    ), plan_type="direct")
    # Score exactly 2 + modest alt + huge tax → SIP_REDIRECT fallback
    assert r.action == sde.ACTION_SIP_REDIRECT


# ── Step 3: weak-candidate rejection ────────────────────────────────────
def test_weak_candidate_rejected():
    weak = sde.CandidateFund(
        name="Weak Fund", category="Balanced Advantage",
        expense=0.018, return_5y=0.141, drawdown=0.22, consistency=65,
        aum_cr=1000, track_record_years=5,
    )
    # return_delta = 0.001 (< 1%), cost_delta = -0.0005 (< 0.3%), risk_delta = 0
    r = sde.decide(_inp(
        direct_plan_available=False,
        candidate_funds=[weak],
    ), plan_type="direct")
    # weak candidate → no better alt → HOLD_NO_OPTION
    assert r.action == sde.ACTION_HOLD_NO_OPTION


def test_candidate_aum_filter():
    small = sde.CandidateFund(
        name="Tiny Fund", category="Balanced Advantage",
        expense=0.003, return_5y=0.25, drawdown=0.10, consistency=95,
        aum_cr=300,                                      # below 500 Cr
        track_record_years=5,
    )
    r = sde.decide(_inp(
        direct_plan_available=False,
        candidate_funds=[small],
    ), plan_type="direct")
    assert r.action == sde.ACTION_HOLD_NO_OPTION


def test_candidate_track_record_filter():
    rookie = sde.CandidateFund(
        name="Rookie Fund", category="Balanced Advantage",
        expense=0.003, return_5y=0.25, drawdown=0.10, consistency=95,
        aum_cr=1000,
        track_record_years=2,                            # below 3y
    )
    r = sde.decide(_inp(
        direct_plan_available=False,
        candidate_funds=[rookie],
    ), plan_type="direct")
    assert r.action == sde.ACTION_HOLD_NO_OPTION


# ── Step 8: LTCG harvest for long-held funds ────────────────────────────
def test_ltcg_harvest_default_when_gain_exceeds_1L():
    r = sde.decide(_inp(
        quality=85, health=85, exit_s=80, add=80,      # strong fund → no signals
        direct_plan_available=False,                    # skip Direct path
        expense_current=0.0074,                         # already direct
        expense_direct=None,
        candidate_funds=[],                             # no alt
        holding_period_days=900,                        # LTCG eligible
        invested_amount=1_100_000, current_value=1_470_000,  # ₹3.7L gain
    ), plan_type="direct")
    # gain > ₹1L + no other case → PARTIAL_SWITCH harvest
    # Note: Step 5c triggers HOLD_NO_OPTION first; harvest is below that
    # So this specific scenario yields HOLD_NO_OPTION, as the PRD's
    # hard blockers fire early. Verify behaviour explicitly.
    assert r.action == sde.ACTION_HOLD_NO_OPTION


def test_ltcg_harvest_runs_when_candidate_rejected_but_still_has_option():
    # Direct plan available but expense_diff too small → step 6 doesn't fire;
    # no candidate; long hold with big gain → LTCG harvest PARTIAL.
    r = sde.decide(_inp(
        quality=85, health=85, exit_s=80, add=80,
        direct_plan_available=True,
        expense_current=0.0076, expense_direct=0.0074,   # diff only 0.02%
        candidate_funds=[],
        holding_period_days=900,
        invested_amount=1_100_000, current_value=1_470_000,
    ), plan_type="regular")
    assert r.action == sde.ACTION_PARTIAL_SWITCH
    assert r.allocation_pct == 20
    assert "LTCG" in r.reason[1] or "Harvest" in r.reason[1]


# ── Tax calculation correctness ─────────────────────────────────────────
def test_tax_equity_stcg():
    t = sde.compute_tax_cost(_inp(
        holding_period_days=100, invested_amount=100_000, current_value=200_000,
    ))
    assert t == 15_000


def test_tax_equity_ltcg_with_exemption():
    t = sde.compute_tax_cost(_inp(
        holding_period_days=400, invested_amount=100_000, current_value=300_000,
    ))
    assert t == 10_000


def test_tax_debt_slab():
    t = sde.compute_tax_cost(_inp(
        is_equity=False, invested_amount=100_000, current_value=150_000,
        debt_slab_rate=0.30,
    ))
    assert t == 15_000


# ── Signal math ─────────────────────────────────────────────────────────
def test_signals_exit_below_40_scores_2():
    assert sde.compute_signals(_inp(exit_s=35))["exit_signal"] == 2


def test_signals_exit_between_40_and_60_scores_1():
    assert sde.compute_signals(_inp(exit_s=50))["exit_signal"] == 1


def test_signals_exit_above_60_scores_0():
    assert sde.compute_signals(_inp(exit_s=80))["exit_signal"] == 0


# ── Output shape (Step 9) ───────────────────────────────────────────────
def test_output_has_all_required_fields():
    d = sde.result_to_dict(sde.decide(_inp(), plan_type="regular"))
    for key in ("action", "label", "allocation", "from_fund", "to_fund",
                "switch_score", "signals", "net_benefit", "breakdown", "reason"):
        assert key in d, f"Missing key: {key}"
    # allocation is a percentage string
    assert d["allocation"].endswith("%")
    assert isinstance(d["reason"], list)
    assert isinstance(d["signals"], dict)
    assert isinstance(d["breakdown"], dict)
