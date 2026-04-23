"""Integration tests for Iteration 38.

Phase A — Unified Portfolio Health across Dashboard / Insights / Plan Board
Phase B — V3 Stock admin endpoints (weights + master catalogue)

Uses REACT_APP_BACKEND_URL from frontend/.env; tests against the public URL.
"""
from __future__ import annotations

import os
import re
import json
import copy
import pytest
import requests


# ── Config & credentials ───────────────────────────────────────────────
def _read_frontend_env() -> str:
    env_path = "/app/frontend/.env"
    with open(env_path) as f:
        for line in f:
            m = re.match(r"^\s*REACT_APP_BACKEND_URL\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _read_frontend_env().rstrip("/")

# Test users (from /app/memory/test_credentials.md & review_request)
PRIMARY_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"   # priyankamantri@gmail.com (admin, 64 holdings)
ADMIN_TOKEN = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"     # aporwal107@gmail.com (admin)


@pytest.fixture(scope="session")
def user_client():
    s = requests.Session()
    s.cookies.set("session_token", PRIMARY_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_client():
    s = requests.Session()
    s.cookies.set("session_token", ADMIN_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


# ════════════════════════════════════════════════════════════════════════
# Phase A — Unified Portfolio Health
# ════════════════════════════════════════════════════════════════════════
class TestAnalyticsHealth:
    """Dashboard /api/portfolio/analytics returns unified health_score block."""

    def test_analytics_returns_health_score_keys(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "health_score" in data, f"missing health_score in {list(data)}"
        hs = data["health_score"]
        expected = {
            "overall", "grade", "diversification", "risk",
            "cost_efficiency", "performance",
            "summary", "risk_drivers", "components", "low_confidence",
        }
        missing = expected - set(hs)
        assert not missing, f"missing keys in health_score: {missing} (got {list(hs)})"

        # Value sanity
        assert 0 <= hs["overall"] <= 100
        assert hs["grade"] in {"A+", "A", "B+", "B", "C", "D", "F"}
        for k in ("diversification", "risk", "cost_efficiency", "performance"):
            assert 0 <= float(hs[k]) <= 100, f"{k}={hs[k]} out of range"

    def test_analytics_preserves_legacy_dashboard_keys(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60)
        assert r.status_code == 200
        data = r.json()
        # Legacy/existing dashboard fields must still be present
        for key in ("total_invested", "current_value"):
            assert key in data, f"missing {key} in analytics payload"

    def test_grade_matches_score_threshold(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60)
        hs = r.json()["health_score"]
        overall = float(hs["overall"])
        grade = hs["grade"]
        thresholds = [(90, "A+"), (80, "A"), (70, "B+"), (60, "B"),
                      (50, "C"), (40, "D"), (0, "F")]
        expected_grade = next(label for t, label in thresholds if overall >= t)
        assert grade == expected_grade, (
            f"grade {grade} for overall {overall} — expected {expected_grade}"
        )


class TestInsightsHealthParity:
    """Insights /api/insights/analysis and /v3-portfolio must match analytics."""

    def test_insights_analysis_has_portfolio_health_block(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/insights/analysis", timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "portfolio_health" in data, f"missing portfolio_health in {list(data)}"
        ph = data["portfolio_health"]
        assert "health_score" in ph
        assert "grade" in ph
        assert "components" in ph
        assert "risk_drivers" in ph
        assert ph["grade"] in {"A+", "A", "B+", "B", "C", "D", "F"}

    def test_health_parity_analytics_vs_insights_analysis(self, user_client):
        a = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60).json()
        i = user_client.get(f"{BASE_URL}/api/insights/analysis", timeout=90).json()
        overall_a = float(a["health_score"]["overall"])
        overall_i = float(i["portfolio_health"]["health_score"])
        # ±1 because analytics rounds to int, insights keeps 2dp
        assert abs(overall_a - overall_i) <= 1.0, (
            f"Health parity breach: analytics={overall_a} vs insights={overall_i}"
        )

    def test_health_parity_v3_portfolio(self, user_client):
        a = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60).json()
        v = user_client.get(f"{BASE_URL}/api/insights/v3-portfolio", timeout=90)
        assert v.status_code == 200, v.text
        vdata = v.json()
        # v3-portfolio still returns its legacy keys
        assert "funds" in vdata
        assert "coverage_pct" in vdata
        assert "health" in vdata
        h_block = vdata["health"]
        # The unified score should be either top-level overall or nested
        v3_score = (
            h_block.get("health_score")
            or h_block.get("overall")
            or (h_block.get("portfolio_health") or {}).get("health_score")
        )
        if v3_score is not None:
            diff = abs(float(a["health_score"]["overall"]) - float(v3_score))
            assert diff <= 1.0, f"v3-portfolio health={v3_score} vs analytics={a['health_score']['overall']}"


class TestHealthProjection:
    """Plan Board /api/plans/active/health-projection."""

    def test_projection_shape_for_user_with_active_plan(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/plans/active/health-projection", timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "available" in data

        if not data["available"]:
            # No active plan — acceptable: flag for reviewer context.
            pytest.skip(f"user has no active plan: {data.get('message')}")

        for key in ("current", "projected", "delta_total", "delta_by_component",
                    "completed_count", "pending_count"):
            assert key in data, f"missing {key} in projection"

        current = data["current"]
        assert "health_score" in current
        assert 0 <= float(current["health_score"]) <= 100
        projected = data["projected"]
        assert "health_score" in projected
        assert 0 <= float(projected["health_score"]) <= 100
        # Delta plausibility per review_request: -10 to +15
        assert -10.0 <= float(data["delta_total"]) <= 15.0

    def test_projection_current_matches_analytics(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/plans/active/health-projection", timeout=90)
        if r.status_code != 200 or not r.json().get("available"):
            pytest.skip("no active plan")
        current_score = float(r.json()["current"]["health_score"])
        a = user_client.get(f"{BASE_URL}/api/portfolio/analytics", timeout=60).json()
        overall = float(a["health_score"]["overall"])
        assert abs(current_score - overall) <= 1.5, (
            f"projection.current={current_score} vs analytics={overall}"
        )


# ════════════════════════════════════════════════════════════════════════
# Phase B — V3 Stock admin endpoints
# ════════════════════════════════════════════════════════════════════════
class TestStockWeightsAdmin:
    """Admin endpoints for V3 Stock weights configuration."""

    def test_get_weights_requires_admin(self):
        # No auth
        r = requests.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30)
        assert r.status_code in (401, 403), f"expected auth error, got {r.status_code}"

    def test_get_weights_returns_four_dimensions(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # Payload may wrap weights under "weights" key — accept both
        weights = data.get("weights", data)
        for dim in ("quality", "health", "exit", "add"):
            assert dim in weights, f"missing dimension {dim} in {list(weights)}"

    def test_default_weight_values(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30)
        data = r.json()
        weights = data.get("weights", data)
        # User-approved defaults
        assert weights["quality"].get("roe") == 25, f"quality.roe={weights['quality'].get('roe')}"
        assert weights["health"].get("revenue_growth") == 25
        assert weights["exit"].get("pe_overvaluation") == 25
        assert weights["add"].get("sector_gap") == 30

    def test_put_weights_validates_sum_to_100(self, admin_client):
        # Contract: {"weights": {dim: {key: value, ...}, ...}}. Sum must be 100 per dim.
        bad = {"weights": {"quality": {
            "roe": 10, "debt_to_equity": 10, "eps_growth_3y": 10,
            "promoter_holding": 10, "market_cap_stability": 10,
            "earnings_consistency": 10,   # sum=60, not 100
        }}}
        r = admin_client.put(
            f"{BASE_URL}/api/admin/v3-stock-weights", json=bad, timeout=30,
        )
        assert r.status_code in (400, 422), f"expected 400/422 for bad sum, got {r.status_code}: {r.text}"

    def test_put_weights_persists_and_reset_restores(self, admin_client):
        # GET original full config
        orig_resp = admin_client.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30).json()
        orig_cfg = copy.deepcopy(orig_resp["weights"])
        orig_quality = copy.deepcopy(orig_cfg["quality"])

        # Build a mutated quality (swap two fields, sum still 100)
        new_q = dict(orig_quality)
        a, b = "roe", "eps_growth_3y"
        assert a in new_q and b in new_q
        new_q[a], new_q[b] = new_q[b], new_q[a]
        new_cfg = copy.deepcopy(orig_cfg)
        new_cfg["quality"] = new_q

        # PUT
        r = admin_client.put(
            f"{BASE_URL}/api/admin/v3-stock-weights",
            json={"weights": new_cfg}, timeout=30,
        )
        try:
            assert r.status_code in (200, 204), f"PUT failed: {r.status_code}: {r.text}"

            # Verify persisted
            check = admin_client.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30).json()
            check_q = check["weights"]["quality"]
            assert check_q[a] == new_q[a], f"persist failed: {check_q}"
        finally:
            # Always reset — teardown safety per review_request "always reset to defaults"
            r2 = admin_client.post(
                f"{BASE_URL}/api/admin/v3-stock-weights/reset", timeout=30,
            )
            assert r2.status_code in (200, 204), f"reset failed: {r2.status_code}"

        # Verify reset restored defaults
        after = admin_client.get(f"{BASE_URL}/api/admin/v3-stock-weights", timeout=30).json()
        after_q = after["weights"]["quality"]
        assert after_q.get("roe") == 25
        assert after_q.get("eps_growth_3y") == 20


class TestStockMaster:
    """Admin v3-stock-master endpoint.

    Postgres migration 008 is NOT applied in sandbox, so endpoint may return
    empty/error — that's expected; test shape only.
    """

    def test_master_endpoint_responds(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/admin/v3-stock-master?nifty_100_only=true",
            timeout=30,
        )
        # Accept 200 (with error field) OR 503 (PG unavailable). Reject 500.
        assert r.status_code in (200, 404, 503), f"got {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            data = r.json()
            # Shape: a list OR a dict containing list / error
            if isinstance(data, dict):
                assert "stocks" in data or "error" in data or "data" in data
            elif isinstance(data, list):
                # fine — empty list acceptable
                pass
            else:
                pytest.fail(f"unexpected master shape: {type(data)}")
