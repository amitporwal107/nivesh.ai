"""Unit tests for v3_explainer — purely deterministic, no DB/LLM."""
from services import v3_explainer


def _bundle(quality=None, health=None, exit_s=None, add=None, switch=None,
            q_comps=None, h_comps=None, primitives=None,
            blocked=False, reasons=None):
    return {
        "quality_score": quality,
        "health_score": health,
        "exit_score": exit_s,
        "add_score": add,
        "switch_score": switch,
        "quality_components": q_comps or {},
        "health_components": h_comps or {},
        "v3_primitives": primitives or {},
        "guardrail_blocked": blocked,
        "guardrail_reasons": reasons or [],
    }


# ── classify_danger ──────────────────────────────────────────────────────
def test_classify_danger_critical_on_very_low_quality():
    d = v3_explainer.classify_danger(_bundle(quality=30, health=70))
    assert d["level"] == "critical"
    assert d["is_danger"] is True
    assert any(r["code"] == "very_low_quality" for r in d["reasons"])


def test_classify_danger_critical_on_high_exit():
    d = v3_explainer.classify_danger(_bundle(quality=60, health=60, exit_s=80))
    assert d["level"] == "critical"
    assert any(r["code"] == "high_exit" for r in d["reasons"])


def test_classify_danger_warning_only_on_borderline():
    d = v3_explainer.classify_danger(_bundle(quality=50, health=70))
    assert d["level"] == "warning"
    assert d["is_danger"] is True


def test_classify_danger_ok_on_healthy():
    d = v3_explainer.classify_danger(_bundle(quality=80, health=75, exit_s=25))
    assert d["level"] == "ok"
    assert d["is_danger"] is False
    assert d["reasons"] == []


def test_classify_danger_flags_strong_switch_score():
    d = v3_explainer.classify_danger(_bundle(quality=70, health=70, switch=2.5))
    assert d["level"] == "warning"
    assert any(r["code"] == "strong_switch" for r in d["reasons"])


def test_classify_danger_surfaces_tax_lockout():
    d = v3_explainer.classify_danger(_bundle(
        quality=60, health=60, blocked=True,
        reasons=["tax_exceeds_benefit"],
    ))
    assert any(r["code"] == "tax_exceeds_benefit" for r in d["reasons"])


def test_classify_danger_ignores_high_quality_protection():
    # high_quality_protection is a POSITIVE guardrail (block exit to keep a
    # strong fund) — should NOT bump the danger level
    d = v3_explainer.classify_danger(_bundle(
        quality=80, health=75, blocked=True,
        reasons=["high_quality_protection"],
    ))
    assert d["level"] == "ok"


# ── build_explanation ────────────────────────────────────────────────────
def test_explanation_includes_scores_and_weak_components():
    b = _bundle(
        quality=40, health=60,
        q_comps={"performance": 2.0, "risk_adjusted": 1.5, "consistency": 8.0,
                 "drawdown": 7.0, "cost": 9.0, "aum_age": 8.0},
        h_comps={"manager_tenure": 2.0, "aum_stability": 7.0},
        primitives={"max_drawdown_pct": 28.5, "manager_tenure_years": 1.2},
    )
    e = v3_explainer.build_explanation(b)
    assert "40" in e and "60" in e  # headline scores
    assert "performance" in e.lower() or "risk-adjusted" in e.lower()
    assert "manager tenure" in e.lower() or "1.2y" in e.lower()


def test_explanation_cites_drawdown_primitive():
    b = _bundle(
        quality=45, health=70,
        q_comps={"drawdown": 2.0, "performance": 7.0, "cost": 8.0},
        primitives={"max_drawdown_pct": 35.7},
    )
    e = v3_explainer.build_explanation(b)
    assert "35.7%" in e  # primitive surfaced


def test_explanation_adds_switch_note_for_regular_plan():
    b = _bundle(quality=70, health=70, switch=2.8)
    e = v3_explainer.build_explanation(b, plan_type="regular", cost_leak_rs=12345)
    assert "switch" in e.lower()
    assert "12,345" in e or "2.8" in e


def test_explanation_no_switch_note_for_direct_plan():
    b = _bundle(quality=70, health=70, switch=None)
    e = v3_explainer.build_explanation(b, plan_type="direct")
    assert "switch" not in e.lower() or "switch score" not in e.lower()


def test_explanation_mentions_exit_when_elevated():
    b = _bundle(quality=55, health=55, exit_s=72)
    e = v3_explainer.build_explanation(b)
    assert "exit" in e.lower() and "72" in e


def test_explanation_handles_missing_primitives_gracefully():
    b = _bundle(quality=None, health=None)
    e = v3_explainer.build_explanation(b)
    # Should not raise; returns empty or minimal string
    assert isinstance(e, str)
