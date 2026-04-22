"""Unit tests for services.holding_action_score.

Covers all 3 derived scores (OIS, ADS, TFS), the HAS composite, category
weight profiles, guardrails, action mapping, reason generation, and the
single-shot entry point.
"""
from __future__ import annotations
import pytest

from services import holding_action_score as has_mod


# ── 1. Overlap Impact Score ────────────────────────────────────────────
def test_ois_clamps_and_rounds():
    assert has_mod.compute_ois(None) is None
    assert has_mod.compute_ois(0) == 0.0
    assert has_mod.compute_ois(45.123) == 45.12
    assert has_mod.compute_ois(150) == 100.0
    assert has_mod.compute_ois(-10) == 0.0


# ── 2. Allocation Deviation Score ──────────────────────────────────────
def test_ads_none_when_inputs_missing():
    out = has_mod.compute_ads(None, 10.0)
    assert out == {"deviation_pp": None, "penalty": None, "score": None, "stance": None}


def test_ads_overweight():
    out = has_mod.compute_ads(15.0, 10.0)
    assert out["deviation_pp"] == 5.0
    assert out["penalty"] == 25.0  # |5| × 5
    assert out["score"] == 75.0
    assert out["stance"] == "overweight"


def test_ads_underweight():
    out = has_mod.compute_ads(6.0, 10.0)
    assert out["deviation_pp"] == -4.0
    assert out["penalty"] == 20.0
    assert out["score"] == 80.0
    assert out["stance"] == "underweight"


def test_ads_on_target():
    out = has_mod.compute_ads(10.2, 10.0)
    assert out["stance"] == "on_target"


def test_ads_clamps_at_zero():
    # Extreme overweight: 100% position vs 10% target → penalty 450 → clamp 0
    out = has_mod.compute_ads(100.0, 10.0)
    assert out["score"] == 0.0


# ── 3. Tax Friction Score ──────────────────────────────────────────────
def test_tfs_none_when_inputs_missing():
    out = has_mod.compute_tfs(None, 100000, is_stcg=False)
    assert out["penalty"] is None


def test_tfs_zero_when_no_tax():
    out = has_mod.compute_tfs(0, 100000, is_stcg=False)
    assert out["penalty"] == 0.0


def test_tfs_high_gain_stcg_heavy_penalty():
    # 15% tax ratio + STCG bump → 15%*200 + 20 = 50
    out = has_mod.compute_tfs(15000, 100000, is_stcg=True)
    assert out["penalty"] == 50.0
    assert out["is_stcg"] is True


def test_tfs_low_gain_ltcg_light_penalty():
    # 5% tax ratio, no bump → 10
    out = has_mod.compute_tfs(5000, 100000, is_stcg=False)
    assert out["penalty"] == 10.0


def test_tfs_caps_at_100():
    out = has_mod.compute_tfs(60000, 100000, is_stcg=True)  # 120 + 20 = 140 → 100
    assert out["penalty"] == 100.0


def test_tfs_zero_holding_value_returns_none():
    out = has_mod.compute_tfs(1000, 0, is_stcg=False)
    assert out["penalty"] is None


# ── 4. HAS composite ───────────────────────────────────────────────────
def test_has_equity_full_inputs():
    """All 7 inputs provided → composite uses full equity profile."""
    r = has_mod.compute_has(
        category="equity",
        quality=80.0, health=70.0,
        exit_score=30.0, add_score=60.0,
        ois_score=20.0, ads_score=90.0, tfs_penalty=15.0,
    )
    assert r["category"] == "equity"
    # Expected: 0.30*80 + 0.20*70 + 0.15*(100-30) + 0.15*60 + 0.10*(100-20) + 0.05*90 + 0.05*(100-15)
    # = 24 + 14 + 10.5 + 9 + 8 + 4.5 + 4.25 = 74.25
    assert r["score"] == pytest.approx(74.25, rel=1e-3)
    assert r["missing"] == []


def test_has_partial_inputs_renormalise():
    """Only Q + H available → weights renormalise over those two."""
    r = has_mod.compute_has(category="equity", quality=80.0, health=60.0)
    # 0.30*80 + 0.20*60 → divided by 0.50 → (24 + 12) / 0.5 = 72
    assert r["score"] == 72.0
    assert set(r["missing"]) >= {"exit_inv", "add", "ois_inv", "ads", "tfs_inv"}


def test_has_all_missing_returns_none():
    r = has_mod.compute_has(category="equity", quality=None, health=None)
    assert r["score"] is None


def test_has_debt_routes_to_debt_profile():
    r = has_mod.compute_has(
        category="debt", quality=70, health=80,
        exit_score=40, add_score=50, ois_score=10, ads_score=95, tfs_penalty=5,
    )
    assert r["category"] == "debt"
    # Debt: Q=30 H=25 EX=15 ADD=15 OIS=5 ADS=5 TFS=5 → adjusted from equity
    # 0.30*70 + 0.25*80 + 0.15*(100-40) + 0.15*50 + 0.05*(100-10) + 0.05*95 + 0.05*(100-5)
    expected = 0.30*70 + 0.25*80 + 0.15*60 + 0.15*50 + 0.05*90 + 0.05*95 + 0.05*95
    assert r["score"] == pytest.approx(expected, rel=1e-3)


def test_has_liquid_ignores_overlap_exit():
    """Liquid profile drops Exit + OIS weights — passing values there shouldn't move HAS."""
    base = has_mod.compute_has(category="liquid", quality=80, health=80,
                               ads_score=90, tfs_penalty=10)
    with_overlap = has_mod.compute_has(category="liquid", quality=80, health=80,
                                       ads_score=90, tfs_penalty=10,
                                       ois_score=90, exit_score=90)
    # Liquid profile weights for OIS/Exit are 0 so adding them should NOT change HAS.
    assert base["score"] == with_overlap["score"]


def test_has_unknown_category_falls_back_to_equity():
    r = has_mod.compute_has(category="bogus", quality=80, health=60)
    assert r["category"] == "equity"


# ── 5. Guardrails ──────────────────────────────────────────────────────
def test_guardrail_high_quality_blocks_exit():
    g = has_mod.evaluate_guardrails(quality=80, health=75)
    assert g["block_exit"] is True
    assert "high_quality_protection" in g["blocks"]


def test_guardrail_tax_cost_exceeds_benefit():
    g = has_mod.evaluate_guardrails(
        quality=40, health=40, tax_cost_rs=10000, tax_benefit_rs=5000,
    )
    assert g["block_exit"] is True
    assert "tax_cost_exceeds_benefit" in g["blocks"]


def test_guardrail_recent_investment_blocks():
    g = has_mod.evaluate_guardrails(quality=40, health=40, holding_age_days=90)
    assert "recent_investment" in g["blocks"]


def test_guardrail_overlap_override_allows_exit():
    """Overlap > 80% overrides other blocks."""
    g = has_mod.evaluate_guardrails(
        quality=80, health=75,  # high-quality protection would normally block
        overlap_pct=85,
    )
    assert g["block_exit"] is False
    assert g["allow_exit_override"] is True
    # blocks list still populated for transparency
    assert "high_quality_protection" in g["blocks"]


def test_guardrail_low_confidence():
    g = has_mod.evaluate_guardrails(quality=40, health=40, confidence=35)
    assert g["confidence_ok"] is False


def test_guardrail_no_blocks_when_healthy():
    g = has_mod.evaluate_guardrails(quality=70, health=65, holding_age_days=500,
                                    tax_cost_rs=5000, tax_benefit_rs=30000)
    assert g["block_exit"] is False
    assert g["blocks"] == []


# ── 6. Action mapping ──────────────────────────────────────────────────
@pytest.mark.parametrize("has,expected", [
    (90, "HOLD"),        # ≥75 but no add_score
    (60.5, "HOLD"),      # 60-75
    (50, "TRIM"),        # 45-60
    (40, "SWITCH"),      # 30-45
    (20, "EXIT"),        # <30
    (None, "UNKNOWN"),
])
def test_map_has_action_basic(has, expected):
    g = has_mod.evaluate_guardrails(quality=50, health=50)
    assert has_mod.map_has_to_action(has, g) == expected


def test_map_has_to_add_when_add_score_high():
    g = has_mod.evaluate_guardrails(quality=50, health=50)
    assert has_mod.map_has_to_action(85, g, add_score=80) == "ADD"
    assert has_mod.map_has_to_action(85, g, add_score=40) == "HOLD"


def test_map_exit_downgrades_when_blocked():
    g = has_mod.evaluate_guardrails(quality=80, health=80)  # high-Q blocks exit
    assert has_mod.map_has_to_action(20, g) == "REVIEW"


def test_map_respects_overlap_override():
    g = has_mod.evaluate_guardrails(quality=80, health=80, overlap_pct=85)
    # Override sets block_exit=False, so EXIT stays EXIT
    assert has_mod.map_has_to_action(20, g) == "EXIT"


def test_map_low_confidence_downgrades_exit_and_switch():
    g = has_mod.evaluate_guardrails(quality=40, health=40, confidence=30)
    assert has_mod.map_has_to_action(20, g) == "REVIEW"
    assert has_mod.map_has_to_action(40, g) == "REVIEW"
    # TRIM still fine under low confidence
    assert has_mod.map_has_to_action(50, g) == "TRIM"


# ── 7. Reason string ───────────────────────────────────────────────────
def test_reason_cites_weakest_driver_for_exit():
    has_res = has_mod.compute_has(
        category="equity", quality=20, health=30,
        exit_score=80, add_score=20, ois_score=70,
        ads_score=40, tfs_penalty=50,
    )
    ads_res = has_mod.compute_ads(15, 10)
    g = has_mod.evaluate_guardrails(quality=20, health=30)
    reason = has_mod.build_holding_reason(has_res, ads_res, g, "EXIT")
    assert reason.startswith("Exit")
    # The weakest driver in an all-bad fund should be one of the low-score inputs
    assert "/100" in reason


def test_reason_cites_strongest_driver_for_hold():
    has_res = has_mod.compute_has(category="equity", quality=85, health=80,
                                  exit_score=10, add_score=75,
                                  ois_score=15, ads_score=95, tfs_penalty=10)
    ads_res = has_mod.compute_ads(10.5, 10.0)
    g = has_mod.evaluate_guardrails(quality=85, health=80)
    reason = has_mod.build_holding_reason(has_res, ads_res, g, "HOLD")
    assert reason.startswith("Hold")


def test_reason_mentions_overweight_stance():
    has_res = has_mod.compute_has(category="equity", quality=50, health=50,
                                  ois_score=10, ads_score=50, tfs_penalty=10)
    ads_res = has_mod.compute_ads(20, 10)
    g = has_mod.evaluate_guardrails(quality=50, health=50)
    reason = has_mod.build_holding_reason(has_res, ads_res, g, "TRIM")
    assert "overweight" in reason


def test_reason_mentions_blocked_guardrail_on_review():
    has_res = has_mod.compute_has(category="equity", quality=80, health=75,
                                  exit_score=80, add_score=20, ois_score=50,
                                  ads_score=50, tfs_penalty=20)
    ads_res = has_mod.compute_ads(10, 10)
    g = has_mod.evaluate_guardrails(quality=80, health=75)
    # Simulate downgrade EXIT → REVIEW by low has; guardrail should surface.
    reason = has_mod.build_holding_reason(has_res, ads_res, g, "REVIEW")
    assert "blocked by guardrail" in reason


# ── 8. Single entry-point ──────────────────────────────────────────────
def test_build_holding_action_happy_path():
    r = has_mod.build_holding_action(
        category="equity",
        quality=80, health=70,
        exit_score=30, add_score=60,
        portfolio_overlap_pct=25,
        current_weight_pct=9, target_weight_pct=10,
        tax_cost_rs=3000, tax_benefit_rs=15000,
        holding_value_rs=100000,
        is_stcg=False, holding_age_days=700,
    )
    assert isinstance(r, has_mod.HasResult)
    assert r.action in ("HOLD", "ADD", "TRIM")
    assert 60 <= r.has <= 95
    assert r.ois_score == 25.0
    assert r.ads_score == 95.0  # |9-10|*5 = 5 penalty, score = 95
    assert r.tfs_penalty == 6.0  # 3000/100000 = 0.03 → 6.0 penalty, no STCG bump
    assert r.category == "equity"
    assert r.reason


def test_build_holding_action_high_quality_protected_from_exit():
    r = has_mod.build_holding_action(
        category="equity",
        quality=90, health=75,
        exit_score=95, add_score=20,  # would normally trigger EXIT
        portfolio_overlap_pct=20,
        current_weight_pct=50, target_weight_pct=10,   # very overweight
        tax_cost_rs=20000, tax_benefit_rs=5000,
        holding_value_rs=500000,
        is_stcg=True, holding_age_days=30,
    )
    # Guardrails should prevent an EXIT here — should land on REVIEW/TRIM.
    assert r.action != "EXIT"
    assert r.guardrails["block_exit"] is True
    assert r.to_dict()["action"] == r.action


def test_build_holding_action_accepts_none_partial_inputs():
    r = has_mod.build_holding_action(
        category="equity",
        quality=70, health=60,
        exit_score=None, add_score=None,
        portfolio_overlap_pct=None,
        current_weight_pct=None, target_weight_pct=None,
        tax_cost_rs=None, tax_benefit_rs=None,
        holding_value_rs=None,
        is_stcg=False, holding_age_days=None,
    )
    assert r.has is not None  # Q + H alone is enough
    assert r.action in ("HOLD", "TRIM", "SWITCH", "EXIT")
