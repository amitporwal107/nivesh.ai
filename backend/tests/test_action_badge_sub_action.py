"""Tests for the SWITCH sub-action differentiation in derive_action_badge.

Ensures the UI distinguishes:
  • "To Direct" — Regular plan with healthy scores (cost optimisation)
  • "To Peer"   — engine-flagged switch / unhealthy fund
  • "Reduce"    — high-overlap diversification trim
"""
from services.portfolio_enrichment import derive_action_badge


def _scores(q=70, h=70, e=40, a=70):
    return {"quality": q, "health": h, "exit": e, "add": a}


def test_regular_plan_with_healthy_scores_emits_to_direct():
    badge = derive_action_badge(
        _scores(q=71, h=80, e=41, a=77),
        recommendation="HOLD",
        is_regular_plan=True,
    )
    assert badge["action"] == "SWITCH"
    assert badge["sub_action"] == "To Direct"
    assert "Regular plan" in badge["reason"]


def test_regular_plan_with_weak_quality_emits_to_peer():
    badge = derive_action_badge(
        _scores(q=45, h=80, e=41, a=77),     # Q<60 → not healthy
        recommendation="HOLD",
        is_regular_plan=True,
    )
    assert badge["action"] == "SWITCH"
    assert badge["sub_action"] == "To Peer"


def test_engine_flagged_switch_on_direct_plan_emits_to_peer():
    badge = derive_action_badge(
        _scores(q=70, h=70, e=55, a=70),    # E<70 so EXIT branch doesn't fire
        recommendation="SWITCH",
        is_regular_plan=False,
    )
    assert badge["sub_action"] == "To Peer"


def test_high_overlap_emits_reduce():
    badge = derive_action_badge(
        _scores(),
        recommendation="HOLD",
        is_regular_plan=False,
        high_overlap=True,
    )
    assert badge["sub_action"] == "Reduce"


def test_regular_plan_high_exit_score_emits_to_peer():
    """E=65 → not healthy (e<60 fails) so even Regular goes to To Peer."""
    badge = derive_action_badge(
        _scores(q=70, h=70, e=65, a=70),    # E<70 to avoid EXIT branch
        recommendation="HOLD",
        is_regular_plan=True,
    )
    assert badge["sub_action"] == "To Peer"
