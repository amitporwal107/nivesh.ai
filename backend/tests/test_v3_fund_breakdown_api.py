"""Integration test: /api/insights/v3-portfolio — verifies per-fund V3
breakdown fields (scores, plan_type, cost_leak, danger, explanation) and
portfolio-level counts (n_danger_critical, n_danger_warning)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


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


# ── Top-level portfolio counts ─────────────────────────────────────────
def test_portfolio_has_danger_counts(payload):
    p = payload.get("portfolio") or payload
    assert "n_danger_critical" in p, f"missing n_danger_critical; keys={list(p)[:20]}"
    assert "n_danger_warning" in p
    assert isinstance(p["n_danger_critical"], int)
    assert isinstance(p["n_danger_warning"], int)


def test_portfolio_returns_funds(payload):
    funds = payload.get("funds") or payload.get("per_fund") or []
    assert len(funds) >= 1, f"expected >=1 funds, got {len(funds)}"


# ── Per-fund shape ─────────────────────────────────────────────────────
def _funds(payload):
    return payload.get("funds") or payload.get("per_fund") or []


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


def test_each_fund_has_danger_block(payload):
    for f in _funds(payload):
        d = f.get("danger")
        assert isinstance(d, dict), f"danger block missing for {f.get('scheme_name')}"
        assert d.get("level") in ("critical", "warning", "ok")
        assert isinstance(d.get("reasons"), list)
        assert isinstance(d.get("is_danger"), bool)


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
            # Regular: switch may be numeric or None (if no meaningful cost leak)
            cl = f.get("cost_leak_rs_per_yr") or 0
            if cl >= 1000:
                assert sw is not None, (
                    f"Regular plan with cost_leak ₹{cl:.0f} has null switch: "
                    f"{f.get('scheme_name')}"
                )


def test_danger_funds_sorted_first(payload):
    funds = _funds(payload)
    # Find first OK fund; no danger fund should appear after it.
    first_ok_idx = None
    for i, f in enumerate(funds):
        if f["danger"]["level"] == "ok":
            first_ok_idx = i
            break
    if first_ok_idx is not None:
        for f in funds[first_ok_idx:]:
            assert f["danger"]["level"] == "ok", (
                f"danger fund '{f.get('scheme_name')}' "
                f"appears after OK funds — sort broken"
            )


def test_danger_counts_consistent_with_funds(payload):
    funds = _funds(payload)
    crit = sum(1 for f in funds if f["danger"]["level"] == "critical")
    warn = sum(1 for f in funds if f["danger"]["level"] == "warning")
    p = payload.get("portfolio") or payload
    assert p["n_danger_critical"] == crit, (
        f"n_danger_critical={p['n_danger_critical']} but funds show {crit}"
    )
    assert p["n_danger_warning"] == warn, (
        f"n_danger_warning={p['n_danger_warning']} but funds show {warn}"
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


def test_expected_priyanka_counts(payload):
    """Main agent confirmed: 2 critical + 8 warning for priyankamantri."""
    p = payload.get("portfolio") or payload
    funds = _funds(payload)
    # Informational — but assert fund count reasonable
    assert len(funds) >= 20, f"expected >=20 funds, got {len(funds)}"
    # Counts should be >0 for this portfolio
    assert p["n_danger_critical"] + p["n_danger_warning"] > 0
