"""V4 endpoint integration tests — Nivesh v4 Phase 3.

Uses:
- aporwal107@gmail.com session token (staging)
- sdk_real_nsdl_full.json fixture (NSDL ECAS)

All HTTP tests use requests.Session + session_token cookie.
Pure-Python tests run with no network and skip gracefully on 401/403.

Run:
    cd /app/backend
    pytest tests/test_v4_endpoints.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://nidp-backfill-ui.preview.emergentagent.com",
).rstrip("/")

# aporwal107@gmail.com — standard v4 test fixture user
SESSION_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"

FIXTURE_DIR = "/app/backend/portfolio_ingestion/tests/fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def nsdl_fixture():
    with open(f"{FIXTURE_DIR}/sdk_real_nsdl_full.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def skip_if_unauth(r):
    if r.status_code in (401, 403):
        pytest.skip(f"Auth required (status {r.status_code})")


# ===========================================================================
# 1. switch_score unit test (pure Python, no HTTP)
# ===========================================================================

def test_switch_score_unit():
    from services.switch_score import compute_switch_score

    # Basic formula: exit_score * (1 + replacement_advantage_pp / 100)
    # 60 * 1.20 = 72.0
    assert compute_switch_score(60, 20) == pytest.approx(72.0, abs=0.1)

    # Category mismatch -> None
    assert compute_switch_score(
        60, 20,
        source_category="Large Cap",
        target_category="Mid Cap",
    ) is None

    # Same fund guard (source_isin == target_isin) -> None
    assert compute_switch_score(
        60, 20,
        source_isin="INF123",
        target_isin="INF123",
    ) is None

    # Cost-leak guard: higher ER, lower return -> 0.0
    result = compute_switch_score(
        60, 20,
        source_expense_ratio=0.5,
        target_expense_ratio=1.0,
        source_return_3y_pct=15.0,
        target_return_3y_pct=12.0,
    )
    assert result == 0.0


# ===========================================================================
# 2. snapshot_action_writers module smoke test (pure Python, no HTTP)
# ===========================================================================

def test_snapshot_action_writers_module():
    mod = importlib.import_module("services.snapshot_action_writers")
    assert callable(mod.write_tax_actions)
    assert callable(mod.write_goals_actions)


# ===========================================================================
# 3. NSDL fixture loads and contains MF holdings (pure Python)
# ===========================================================================

def test_nsdl_fixture_loads(nsdl_fixture):
    assert "demat_accounts" in nsdl_fixture
    assert len(nsdl_fixture["demat_accounts"]) > 0

    all_mf = []
    for acct in nsdl_fixture["demat_accounts"]:
        all_mf.extend(acct.get("holdings", {}).get("demat_mutual_funds", []))
    assert len(all_mf) > 0, "NSDL fixture must have at least one MF holding"


# ===========================================================================
# 4. Dashboard concentration envelope (HTTP)
# ===========================================================================

def test_dashboard_concentration(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/dashboards/concentration")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("domain", "stat_tiles", "breakdown", "recommendations", "projection", "health"):
        assert key in data, f"Missing key: {key}"
    assert data["domain"] == "concentration"


# ===========================================================================
# 5. All 6 dashboard types return non-500 (HTTP)
# ===========================================================================

def test_dashboard_all_types(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    for dtype in ("concentration", "diversification", "risk", "performance", "goals", "tax"):
        r = client.get(f"{BASE_URL}/api/dashboards/{dtype}")
        skip_if_unauth(r)
        assert r.status_code != 500, f"{dtype} returned 500"


# ===========================================================================
# 6. Recommendations compliance_note (HTTP)
# ===========================================================================

def test_recommendations_compliance_note(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/recommendations/stocks")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    assert "compliance_note" in r.json()


# ===========================================================================
# 7. Fund performance period + benchmark params (HTTP)
# ===========================================================================

def test_fund_performance_period_param(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/portfolio/fund-performance?period=3y&benchmark=index")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("period") == "3y"
    assert data.get("benchmark") == "index"
    ratings = data.get("fund_ratings", [])
    if ratings:
        assert "benchmark_index" in ratings[0]


# ===========================================================================
# 8. SIPs v4 fields (HTTP)
# ===========================================================================

def test_sips_v4_fields(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/portfolio/sips")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    sips = r.json().get("sips", [])
    if sips:
        s = sips[0]
        for field in ("state", "mandate_id", "cycles_missed", "proposed_stepup_pct"):
            assert field in s, f"SIP missing v4 field: {field}"


# ===========================================================================
# 9. Insights v3-portfolio ETag (HTTP)
# ===========================================================================

def test_insights_v3_portfolio_etag(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/insights/v3-portfolio")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "etag" in data, "v3-portfolio response must include etag field"
    etag_header = r.headers.get("ETag") or r.headers.get("etag")
    assert etag_header, "v3-portfolio must set ETag response header"


# ===========================================================================
# 10. Plans active source_domain filter (HTTP)
# ===========================================================================

def test_plans_active_source_domain_filter(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.get(f"{BASE_URL}/api/plans/active?source_domain=tax")
    skip_if_unauth(r)
    assert r.status_code == 200, r.text
    actions = r.json().get("actions", [])
    for action in actions:
        assert action.get("source_domain") == "tax", (
            f"source_domain filter broken: got {action.get('source_domain')}"
        )


# ===========================================================================
# 11. Review pack scaffold (HTTP)
# ===========================================================================

def test_review_pack_scaffold(client):
    if not BASE_URL:
        pytest.skip("BASE_URL not set")
    r = client.post(
        f"{BASE_URL}/api/mfd/profiles/test_profile_v4/review-pack/generate",
        json={"format": "pdf", "sections": ["portfolio", "goals"]},
    )
    skip_if_unauth(r)
    assert r.status_code in (200, 404), f"review-pack returned {r.status_code}: {r.text}"
    if r.status_code == 200:
        data = r.json()
        assert "task_id" in data
        assert "status" in data
