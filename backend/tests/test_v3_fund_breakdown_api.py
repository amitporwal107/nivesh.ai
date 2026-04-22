"""Integration test: /api/insights/v3-portfolio — verifies per-fund V3
breakdown fields (scores, plan_type, cost_leak, recommendation, explanation)
and portfolio-level counts (n_exit_recs, n_switch_recs, n_review_recs)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com

VALID_ACTIONS = {"EXIT", "SWITCH", "REVIEW", "BUY", "HOLD"}
SORT_RANK = {"EXIT": 0, "SWITCH": 1, "REVIEW": 2, "HOLD": 3, "BUY": 4}


@pytest.fixture(scope="module")
def api():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    return s


@pytest.fixture(scope="module")
def payload(api):
    r = api.get(f"{BASE_URL}/api/insights/v3-portfolio", timeout=60)
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:400]}"
    return r.json()


def _funds(payload):
    return payload.get("funds") or payload.get("per_fund") or []


# ── Top-level portfolio counts ─────────────────────────────────────────
def test_portfolio_has_recommendation_counts(payload):
    p = payload.get("portfolio") or payload
    for k in ("n_exit_recs", "n_switch_recs", "n_review_recs"):
        assert k in p, f"missing {k}; keys={list(p)[:20]}"
        assert isinstance(p[k], int)


def test_portfolio_no_longer_exposes_danger_counts(payload):
    """Danger block was removed per product decision — must not reappear."""
    p = payload.get("portfolio") or payload
    assert "n_danger_critical" not in p
    assert "n_danger_warning" not in p


def test_portfolio_returns_funds(payload):
    funds = _funds(payload)
    assert len(funds) >= 1, f"expected >=1 funds, got {len(funds)}"


# ── Per-fund shape ─────────────────────────────────────────────────────
def test_each_fund_has_scores_block(payload):
    for f in _funds(payload):
        sc = f.get("scores")
        assert isinstance(sc, dict), f"fund missing scores dict: {f.get('scheme_name')}"
        for k in ("quality", "health", "exit", "add", "switch"):
            assert k in sc, f"scores missing {k} for {f.get('scheme_name')}"


def test_each_fund_has_plan_type(payload):
    for f in _funds(payload):
        pt = f.get("plan_type")
        assert pt in ("regular", "direct"), f"bad plan_type={pt} for {f.get('scheme_name')}"


def test_each_fund_has_cost_leak_field(payload):
    for f in _funds(payload):
        assert "cost_leak_rs_per_yr" in f
        cl = f["cost_leak_rs_per_yr"]
        assert cl is None or isinstance(cl, (int, float))


def test_each_fund_has_recommendation(payload):
    for f in _funds(payload):
        r = f.get("recommendation")
        assert isinstance(r, dict), f"recommendation missing for {f.get('scheme_name')}"
        assert r.get("action") in VALID_ACTIONS, f"bad action={r.get('action')}"
        assert isinstance(r.get("label"), str) and r["label"]
        assert isinstance(r.get("reason"), str)


def test_no_fund_has_danger_block(payload):
    """Danger block should no longer be emitted per product decision."""
    for f in _funds(payload):
        assert "danger" not in f, f"stale danger block present for {f.get('scheme_name')}"


def test_each_fund_has_deterministic_explanation(payload):
    for f in _funds(payload):
        exp = f.get("explanation")
        assert isinstance(exp, str)
        assert len(exp) > 0, f"empty explanation for {f.get('scheme_name')}"


# ── Business rules ─────────────────────────────────────────────────────
def test_switch_null_for_direct_numeric_for_regular_with_cost_leak(payload):
    for f in _funds(payload):
        pt = f["plan_type"]
        sw = f["scores"]["switch"]
        if pt == "direct":
            assert sw is None, f"direct plan has non-null switch for {f.get('scheme_name')}"
        else:
            cl = f.get("cost_leak_rs_per_yr") or 0
            if cl >= 1000:
                assert sw is not None, (
                    f"Regular plan with cost_leak ₹{cl:.0f} has null switch: "
                    f"{f.get('scheme_name')}"
                )


def test_funds_sorted_by_recommendation_priority(payload):
    """Funds should be ordered EXIT → SWITCH → REVIEW → HOLD → BUY."""
    funds = _funds(payload)
    prev_rank = -1
    for f in funds:
        action = (f.get("recommendation") or {}).get("action", "HOLD")
        rank = SORT_RANK.get(action, 3)
        assert rank >= prev_rank, (
            f"sort broken: fund '{f.get('scheme_name')}' with action "
            f"{action} (rank {rank}) appears after rank {prev_rank}"
        )
        prev_rank = rank


def test_recommendation_counts_consistent_with_funds(payload):
    funds = _funds(payload)
    p = payload.get("portfolio") or payload
    n_exit = sum(1 for f in funds if (f.get("recommendation") or {}).get("action") == "EXIT")
    n_switch = sum(1 for f in funds if (f.get("recommendation") or {}).get("action") == "SWITCH")
    n_review = sum(1 for f in funds if (f.get("recommendation") or {}).get("action") == "REVIEW")
    assert p["n_exit_recs"] == n_exit
    assert p["n_switch_recs"] == n_switch
    assert p["n_review_recs"] == n_review


def test_switch_action_only_on_regular_plans(payload):
    """SWITCH recommendation should only fire for Regular plans."""
    for f in _funds(payload):
        if (f.get("recommendation") or {}).get("action") == "SWITCH":
            assert f["plan_type"] == "regular", (
                f"SWITCH rec on non-regular plan: {f.get('scheme_name')}"
            )


def test_explanation_is_deterministic_no_llm_markers(payload):
    """Deterministic explanation should never contain LLM artefacts."""
    bad = ["As an AI", "I am an", "sorry,", "I cannot"]
    for f in _funds(payload):
        e = (f.get("explanation") or "").lower()
        for marker in bad:
            assert marker.lower() not in e, (
                f"LLM-like marker '{marker}' in explanation for {f.get('scheme_name')}"
            )


def test_expected_priyanka_has_actionable_recs(payload):
    """Priyanka's portfolio should surface at least some actionable recs."""
    p = payload.get("portfolio") or payload
    funds = _funds(payload)
    assert len(funds) >= 20, f"expected >=20 funds, got {len(funds)}"
    total_actionable = p["n_exit_recs"] + p["n_switch_recs"] + p["n_review_recs"]
    assert total_actionable > 0, "expected at least one actionable recommendation"
