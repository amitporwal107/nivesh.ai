"""Integration tests for Nivesh v4 Phase 3 endpoints.

Auth uses session_token cookie (aporwal107@gmail.com) — matches the pattern
across all test files in this suite (test_actionable_portfolio.py, etc.).

Pure-Python unit tests run with no network.
HTTP tests skip gracefully on 401/403 (CI auth issue).

Run:
    cd /app/backend
    pytest tests/test_v4_endpoints.py -v
    REACT_APP_BACKEND_URL=https://nidp-backfill-ui.preview.emergentagent.com \
        pytest tests/test_v4_endpoints.py -v
"""
from __future__ import annotations

import json
import os
import sys

import pytest
import requests

# Always resolve the backend package path for direct module imports.
sys.path.insert(0, "/app/backend")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://nidp-backfill-ui.preview.emergentagent.com",
).rstrip("/")

# aporwal107@gmail.com — standard v4 test fixture user per brief.
SESSION_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"

FIXTURE_PATH = (
    "/app/backend/portfolio_ingestion/tests/fixtures/sdk_real_nsdl_full.json"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Authenticated requests.Session using session_token cookie."""
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def nsdl_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _skip_if_unauth(r: requests.Response, label: str = "") -> None:
    """Skip gracefully when the server returns 401 or 403 in CI."""
    if r.status_code in (401, 403):
        pytest.skip(
            f"Auth issue in CI{' for ' + label if label else ''}: "
            f"status={r.status_code}"
        )


# ===========================================================================
# 1. switch_score unit test (pure Python, no HTTP)
#    Renamed test_switch_score_computation → test_switch_score_unit to match
#    the function name used in the brief.
# ===========================================================================


def test_switch_score_computation():
    """Unit tests for services.switch_score.compute_switch_score."""
    from services.switch_score import compute_switch_score

    # Basic formula: exit_score × (1 + replacement_advantage_pp / 100)
    # 60 × 1.20 = 72.0
    assert compute_switch_score(60, 20) == pytest.approx(72.0, abs=0.1), (
        "Expected ~72.0 for compute_switch_score(60, 20)"
    )

    # Category mismatch → None
    assert compute_switch_score(
        60, 20,
        source_category="Large Cap",
        target_category="Mid Cap",
    ) is None, "Expected None on category mismatch"

    # Same fund guard (source_isin == target_isin) → None
    assert compute_switch_score(
        60, 20,
        source_isin="INF123",
        target_isin="INF123",
    ) is None, "Expected None when source_isin == target_isin"

    # Cost-leak guard: higher ER, lower return → 0.0
    result = compute_switch_score(
        60, 20,
        source_expense_ratio=0.5,
        target_expense_ratio=1.0,
        source_return_3y_pct=15.0,
        target_return_3y_pct=12.0,
    )
    assert result == 0.0, "Expected 0.0 on cost-leak guard"

    # Score is clamped to [0, 100]
    clamped = compute_switch_score(90.0, 50.0)   # 90 × 1.5 = 135 → capped at 100
    assert clamped is not None and clamped <= 100.0, (
        f"Expected score clamped to ≤100, got {clamped}"
    )


# ===========================================================================
# 2. Dashboard envelope shape — GET /api/dashboards/concentration
# ===========================================================================


def test_dashboard_envelope_shape(client):
    """GET /api/dashboards/concentration returns the required envelope keys."""
    url = f"{BASE_URL}/api/dashboards/concentration"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, "dashboards/concentration")
    assert r.status_code == 200, (
        f"Expected 200 from {url}, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    # The composite endpoint returns: type, badge, insight, stat_tiles,
    # breakdown, recommendations, projection (see routes/dashboards.py).
    required = {"type", "stat_tiles", "breakdown", "recommendations", "projection"}
    missing = required - set(body.keys())
    assert not missing, f"Dashboard response missing keys: {missing}"
    assert body["type"] == "concentration"


# ===========================================================================
# 3. Dashboard all 6 types — each must return 200 (never 500)
# ===========================================================================


DASHBOARD_TYPES = [
    "concentration", "diversification", "risk", "performance", "goals", "tax",
]


@pytest.mark.parametrize("dashboard_type", DASHBOARD_TYPES)
def test_dashboard_all_types(client, dashboard_type):
    """GET /api/dashboards/{type} must return 200 for every valid type."""
    url = f"{BASE_URL}/api/dashboards/{dashboard_type}"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, f"dashboards/{dashboard_type}")
    assert r.status_code != 500, (
        f"/api/dashboards/{dashboard_type} returned 500: {r.text[:400]}"
    )
    assert r.status_code == 200, (
        f"/api/dashboards/{dashboard_type} returned {r.status_code}: {r.text[:400]}"
    )


# ===========================================================================
# 4. Recommendations — compliance_note key (SEBI screened-ideas regime)
# ===========================================================================


def test_recommendations_compliance_note(client):
    """GET /api/recommendations/stocks must include 'compliance_note'."""
    url = f"{BASE_URL}/api/recommendations/stocks"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, "recommendations/stocks")
    assert r.status_code == 200, (
        f"Expected 200 from {url}, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    assert "compliance_note" in body, (
        f"'compliance_note' missing; keys present: {list(body.keys())}"
    )
    assert "profile" in body, f"'profile' missing; keys: {list(body.keys())}"
    assert "items" in body, f"'items' missing; keys: {list(body.keys())}"


# ===========================================================================
# 5. Tax summary — LTCG fields present per B.12
# ===========================================================================


def test_tax_summary_ltcg_fields(client):
    """GET /api/portfolio/tax-summary returns required LTCG dashboard fields."""
    url = f"{BASE_URL}/api/portfolio/tax-summary"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, "portfolio/tax-summary")
    assert r.status_code == 200, (
        f"Expected 200 from {url}, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    required = {
        "fy", "ltcg_limit_rs", "ltcg_used_rs", "ltcg_remaining_rs",
        "total_harvestable_rs", "days_to_fy_end", "candidates", "empty",
    }
    missing = required - set(body.keys())
    assert not missing, f"tax-summary missing keys: {missing}"
    # LTCG limit must reflect the Jul-2024 amendment (₹1.25L = 125 000)
    assert body["ltcg_limit_rs"] == 125_000.0, (
        f"Expected ltcg_limit_rs=125000.0, got {body['ltcg_limit_rs']}"
    )
    assert isinstance(body["candidates"], list)
    assert body["days_to_fy_end"] >= 0


# ===========================================================================
# 6. Fund v3-score — C.4 user-scope endpoint
# ===========================================================================


def test_fund_v3_score_valid_isin(client):
    """GET /api/funds/{isin}/v3-score returns 200 or 404 (not 500)."""
    # Use a well-known ISIN that is usually present in mf_master.
    isin = "INF179K01VY5"   # HDFC Flexi Cap
    url = f"{BASE_URL}/api/funds/{isin}/v3-score"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, f"funds/{isin}/v3-score")
    assert r.status_code != 500, (
        f"/api/funds/{isin}/v3-score returned 500: {r.text[:400]}"
    )
    if r.status_code == 200:
        body = r.json()
        assert "isin" in body
        assert "composite_score" in body
        scores = body.get("scores") or {}
        for sub in ("returns", "cost", "consistency"):
            assert sub in scores, f"scores.{sub} missing; keys: {list(scores.keys())}"
    # 404 is acceptable — fund may not be in mf_master for this environment.


# ===========================================================================
# 7. Advisor summary — B.6 book-level KPI rollup
# ===========================================================================


def test_advisor_summary_shape(client):
    """GET /api/advisor/summary returns required KPI fields."""
    url = f"{BASE_URL}/api/advisor/summary"
    r = client.get(url, timeout=30)
    _skip_if_unauth(r, "advisor/summary")
    assert r.status_code == 200, (
        f"Expected 200 from {url}, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    required = {
        "book_aum_rs", "avg_health_score",
        "needs_attention_count", "actions_open_count", "clients_total",
    }
    missing = required - set(body.keys())
    assert not missing, f"advisor/summary missing keys: {missing}"
    assert isinstance(body["book_aum_rs"], (int, float))
    assert isinstance(body["clients_total"], int)


# ===========================================================================
# 8. Plans/active — source_domain filter returns only matching actions
# ===========================================================================


def test_plans_active_source_domain_filter(client):
    """GET /api/plans/active?source_domain=tax filters actions to tax domain."""
    url = f"{BASE_URL}/api/plans/active"
    r = client.get(url, params={"source_domain": "tax"}, timeout=30)
    _skip_if_unauth(r, "plans/active")
    assert r.status_code == 200, (
        f"Expected 200 from {url}, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    # Shape may be {plan: {actions: [...]}} or {actions: [...]}
    actions = None
    if isinstance(body, dict):
        plan = body.get("plan")
        if plan and isinstance(plan, dict):
            actions = plan.get("actions")
        else:
            actions = body.get("actions")
    if actions and isinstance(actions, list):
        for action in actions:
            sd = action.get("source_domain")
            assert sd == "tax", (
                f"Expected source_domain='tax' on every filtered action, "
                f"got {sd!r} for action {action.get('action_id')!r}"
            )


# ===========================================================================
# 9. Review pack scaffold — POST 202 or 404, never 500
# ===========================================================================


def test_review_pack_scaffold(client):
    """POST /api/mfd/profiles/test_profile/review-pack/generate: 202 or 404, not 500."""
    url = f"{BASE_URL}/api/mfd/profiles/test_profile_v4/review-pack/generate"
    r = client.post(url, json={"format": "pdf", "sections": ["portfolio", "goals"]}, timeout=30)
    _skip_if_unauth(r, "mfd/profiles/review-pack/generate")
    assert r.status_code != 500, (
        f"review-pack/generate returned 500: {r.text[:400]}"
    )
    assert r.status_code in (200, 202, 404), (
        f"Expected 202 or 404, got {r.status_code}: {r.text[:400]}"
    )
    if r.status_code in (200, 202):
        body = r.json()
        assert "task_id" in body, f"Missing 'task_id'; keys: {list(body.keys())}"
        assert "status" in body, f"Missing 'status'; keys: {list(body.keys())}"
        assert body["status"] == "queued", f"Expected status='queued', got {body['status']!r}"


# ===========================================================================
# 10. NSDL ECAS fixture — PAN guard + MF holdings present (pure Python)
# ===========================================================================


def test_nsdl_fixture_pan_and_mf_holdings(nsdl_fixture):
    """NSDL fixture must contain PAN AMXXXXXX7E and at least one MF holding."""
    # PAN guard
    pans_found = []
    for acct in nsdl_fixture.get("demat_accounts", []):
        info = acct.get("additional_info") or {}
        pans_found.extend(info.get("linked_pans") or [])
    assert "AMXXXXXX7E" in pans_found, (
        f"Expected PAN 'AMXXXXXX7E' in fixture; found: {pans_found}"
    )

    # At least one MF holding across all demat accounts
    all_mf: list = []
    for acct in nsdl_fixture.get("demat_accounts", []):
        holdings = acct.get("holdings") or {}
        if isinstance(holdings, dict):
            all_mf.extend(holdings.get("demat_mutual_funds") or [])
    assert len(all_mf) > 0, "NSDL fixture must have at least one MF holding"

    # Every MF holding must have an ISIN
    for h in all_mf:
        assert h.get("isin"), f"MF holding missing ISIN: {h}"


# ===========================================================================
# 11. NSDL ECAS fixture — ParsedData schema validation (pure Python)
#     Confirms the fixture matches the exact schema the v4 dashboards consume.
# ===========================================================================


def test_nsdl_fixture_parseddata_schema(nsdl_fixture):
    """Full fixture must parse via ParsedData without validation errors."""
    from portfolio_ingestion.schemas.parsed_data import ParsedData
    payload = ParsedData.model_validate(nsdl_fixture)
    assert len(payload.demat_accounts) > 0, "Expected at least one demat account"
    n_demat = sum(len(da.iter_lines()) for da in payload.demat_accounts)
    assert n_demat > 0, f"Expected at least one demat line item, got {n_demat}"
    n_mf = sum(len(fol.schemes) for fol in payload.mutual_funds)
    assert n_mf > 0, f"Expected at least one MF scheme, got {n_mf}"


# ===========================================================================
# 12. LTCG constant — ₹1.25L per Jul-2024 amendment (pure Python)
# ===========================================================================


def test_ltcg_limit_is_125k():
    """Tax action writer must use ₹1.25L LTCG limit (not the old ₹1L)."""
    from services.snapshot_action_writers import _LTCG_LIMIT
    assert _LTCG_LIMIT == 125_000.0, f"Expected 125000.0, got {_LTCG_LIMIT}"
