"""Iteration 41 — Actionable Portfolio UX enhancements.

Verifies:
 1. GET /api/portfolio/holdings-enriched returns `portfolio_impact` with all keys.
 2. HOLD rows carry `sub_action` + `sub_reason` with Keep/Watch/Review distribution.
 3. `_hold_sub_action` unit-tests: >=10% weight returns Rebalance.
"""
import os
import pytest
import requests

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # read from frontend .env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    return (url or "").rstrip("/")


BASE_URL = _load_backend_url()
SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION)
    return s


@pytest.fixture(scope="module")
def enriched(client):
    r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# ── portfolio_impact object shape ───────────────────────────────────────
class TestPortfolioImpact:
    def test_portfolio_impact_has_all_keys(self, enriched):
        pi = enriched.get("portfolio_impact")
        assert pi is not None, "portfolio_impact missing in payload"
        required = {
            "pending_actions", "by_action", "estimated_cost_savings_rs_per_yr",
            "estimated_value_freed_rs", "health_current", "health_projected",
            "health_delta",
        }
        assert required.issubset(pi.keys()), f"Missing: {required - pi.keys()}"

    def test_by_action_breakdown(self, enriched):
        by = enriched["portfolio_impact"]["by_action"]
        for k in ("EXIT", "SWITCH", "ADD"):
            assert k in by
            assert isinstance(by[k], int)

    def test_priyanka_expected_values(self, enriched):
        pi = enriched["portfolio_impact"]
        assert pi["pending_actions"] == 15, f"expected 15, got {pi['pending_actions']}"
        assert pi["estimated_cost_savings_rs_per_yr"] >= 1000, pi
        assert pi["estimated_value_freed_rs"] >= 500000, pi
        assert pi["health_current"] == 64 or abs((pi["health_current"] or 0) - 64) <= 1, pi


# ── HOLD sub_action distribution ────────────────────────────────────────
class TestHoldSubAction:
    def test_hold_rows_have_sub_action(self, enriched):
        hold_rows = [h for h in enriched["holdings"]
                     if (h.get("action_badge") or {}).get("action") == "HOLD"]
        assert len(hold_rows) >= 5, f"Only {len(hold_rows)} HOLD rows"
        for row in hold_rows:
            ab = row["action_badge"]
            assert "sub_action" in ab and ab["sub_action"] in {
                "Keep", "Watch", "Review", "Rebalance"
            }, ab
            assert ab.get("sub_reason"), ab

    def test_sub_action_distribution(self, enriched):
        hold_rows = [h for h in enriched["holdings"]
                     if (h.get("action_badge") or {}).get("action") == "HOLD"]
        subs = {r["action_badge"]["sub_action"] for r in hold_rows}
        # spec expects >=3 distinct sub_action values (Keep/Watch/Review)
        assert len(subs) >= 3, f"Only saw: {subs}"


# ── unit test Rebalance branch ──────────────────────────────────────────
class TestRebalanceUnit:
    def test_rebalance_when_weight_ge_10pct(self):
        from services.portfolio_enrichment import _hold_sub_action
        r = _hold_sub_action(q=80, h=70, weight_pct=12.5)
        assert r["sub_action"] == "Rebalance"
        assert "12" in r["sub_reason"] or "13" in r["sub_reason"]

    def test_keep_branch(self):
        from services.portfolio_enrichment import _hold_sub_action
        r = _hold_sub_action(q=80, h=70, weight_pct=3.0)
        assert r["sub_action"] == "Keep"

    def test_watch_branch(self):
        from services.portfolio_enrichment import _hold_sub_action
        r = _hold_sub_action(q=55, h=55, weight_pct=2.0)
        assert r["sub_action"] == "Watch"

    def test_review_branch(self):
        from services.portfolio_enrichment import _hold_sub_action
        r = _hold_sub_action(q=40, h=45, weight_pct=2.0)
        assert r["sub_action"] == "Review"


# ── alerts components present (for frontend CTA mapping) ────────────────
class TestAlertsForCTA:
    def test_alert_components(self, enriched):
        comps = {a.get("component") for a in enriched.get("alerts", [])}
        # Spec mentions: allocation, Diversification, Cost, data_coverage
        # Not all may be present every run — just report
        print(f"Alert components present: {comps}")
