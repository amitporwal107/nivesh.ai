"""API-level integration tests for /api/insights/v3-portfolio Health block.

Validates:
- new top-level `health` block shape
- components weights (0.30/0.25/0.20/0.25)
- risk_drivers sorted desc, ≤5
- `?refresh_stocks=1` still 200
- equity-only / zero-holdings edge cases
- no regression on portfolio.avg_has_score, portfolio.has_action_counts, funds
"""
import os
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PRIMARY_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"
PRIMARY_EMAIL = "priyankamantri@gmail.com"
SECONDARY_TOKEN = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"  # aporwal107 (0 holdings)

HEADERS_PRIMARY = {"Cookie": f"session_token={PRIMARY_TOKEN}"}
HEADERS_SECONDARY = {"Cookie": f"session_token={SECONDARY_TOKEN}"}

URL = f"{BASE_URL}/api/insights/v3-portfolio"


# ── Primary user (26 MF + 15 equity + 3 ETF) ──────────────────────────
@pytest.fixture(scope="module")
def primary_resp():
    r = requests.get(URL, headers=HEADERS_PRIMARY, timeout=120)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
    return r.json()


def test_primary_has_health_block(primary_resp):
    assert "health" in primary_resp, "health top-level key missing"
    h = primary_resp["health"]
    for k in ("health_score", "summary", "low_confidence", "components", "risk_drivers"):
        assert k in h, f"missing key {k}"


def test_primary_health_score_in_range(primary_resp):
    score = primary_resp["health"]["health_score"]
    assert isinstance(score, (int, float))
    assert 40 <= score <= 85, f"expected 40..85, got {score}"


def test_primary_components_shape_and_weights(primary_resp):
    comps = primary_resp["health"]["components"]
    expected = {"diversification": 0.30, "risk": 0.25, "cost": 0.20, "performance": 0.25}
    for key, weight in expected.items():
        assert key in comps, f"missing component {key}"
        c = comps[key]
        for sub in ("name", "score", "weight", "sub_scores", "drivers", "low_confidence"):
            assert sub in c, f"{key} missing field {sub}"
        assert c["weight"] == weight, f"{key} weight={c['weight']} want {weight}"
        assert 0 <= c["score"] <= 100


def test_primary_diversification_low_and_performance_high(primary_resp):
    comps = primary_resp["health"]["components"]
    d_score = comps["diversification"]["score"]
    p_score = comps["performance"]["score"]
    assert d_score <= 50, f"Diversification should be ≤50 (low effective-N), got {d_score}"
    assert p_score >= 70, f"Performance should be ≥70 (strong 1y), got {p_score}"


def test_risk_drivers_sorted_and_capped(primary_resp):
    drivers = primary_resp["health"]["risk_drivers"]
    assert isinstance(drivers, list)
    assert len(drivers) <= 5
    for d in drivers:
        for k in ("label", "detail", "impact_points", "component"):
            assert k in d, f"driver missing {k}: {d}"
    impacts = [d.get("impact_points", 0) for d in drivers]
    assert impacts == sorted(impacts, reverse=True), "risk_drivers not sorted desc"


def test_primary_no_regression_legacy_fields(primary_resp):
    portfolio = primary_resp.get("portfolio") or {}
    # avg_has_score and has_action_counts should still exist
    assert "avg_has_score" in portfolio, "portfolio.avg_has_score missing (regression)"
    assert "has_action_counts" in portfolio, "portfolio.has_action_counts missing (regression)"
    # funds list
    assert "funds" in primary_resp and isinstance(primary_resp["funds"], list), \
        "funds list missing"


# ── refresh_stocks=1 ──────────────────────────────────────────────────
def test_refresh_stocks_still_200():
    r = requests.get(URL, headers=HEADERS_PRIMARY,
                     params={"refresh_stocks": 1}, timeout=180)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
    body = r.json()
    assert "health" in body
    # risk block should still exist & valid
    risk_c = body["health"]["components"]["risk"]
    assert 0 <= risk_c["score"] <= 100
    assert isinstance(risk_c.get("low_confidence"), bool)


# ── Secondary user: 0 holdings ────────────────────────────────────────
def test_secondary_user_zero_holdings_seeded():
    """Seed a synthetic user with truly 0 holdings and verify zero-state."""
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    from deps import db  # noqa

    uid = f"TEST_zero_{uuid.uuid4().hex[:8]}"
    tok = f"TEST_{uuid.uuid4().hex}"

    async def _seed():
        await db.users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local",
            "is_admin": False, "risk_profile": "moderate",
        })
        await db.user_sessions.insert_one({
            "session_token": tok, "user_id": uid,
            "expires_at": "2030-01-01T00:00:00+00:00",
        })

    async def _cleanup():
        await db.users.delete_many({"user_id": uid})
        await db.user_sessions.delete_many({"session_token": tok})
        await db.holdings.delete_many({"user_id": uid})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_seed())
        r = requests.get(URL, headers={"Cookie": f"session_token={tok}"}, timeout=60)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
        body = r.json()
        assert "health" in body
        h = body["health"]
        assert h.get("health_score", -1) == 0, f"expected 0, got {h.get('health_score')}"
        assert "no holdings" in (h.get("summary") or "").lower(), \
            f"summary={h.get('summary')!r}"
    finally:
        loop.run_until_complete(_cleanup())
        loop.close()


# ── Equity-only user: create synthetic temp user with only equities ────
def test_equity_only_user_returns_health():
    """Seed with pymongo (sync) to avoid motor event-loop coupling issues."""
    import pymongo
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "test_database"
    client = pymongo.MongoClient(mongo_url)
    sdb = client[db_name]

    uid = f"TEST_eq_{uuid.uuid4().hex[:8]}"
    tok = f"TEST_{uuid.uuid4().hex}"
    try:
        sdb.users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local",
            "is_admin": False, "risk_profile": "moderate",
        })
        sdb.user_sessions.insert_one({
            "session_token": tok, "user_id": uid,
            "expires_at": "2030-01-01T00:00:00+00:00",
        })
        sdb.holdings.insert_many([
            {"user_id": uid, "asset_type": "equity", "nse_symbol": "RELIANCE",
             "name": "Reliance", "quantity": 10, "current_price": 2500, "buy_price": 2000},
            {"user_id": uid, "asset_type": "equity", "nse_symbol": "TCS",
             "name": "TCS", "quantity": 5, "current_price": 3500, "buy_price": 3000},
            {"user_id": uid, "asset_type": "equity", "nse_symbol": "INFY",
             "name": "Infosys", "quantity": 20, "current_price": 1500, "buy_price": 1400},
        ])
        r = requests.get(URL, headers={"Cookie": f"session_token={tok}"}, timeout=120)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
        body = r.json()
        assert body.get("health") is not None, "health should not be null for equity-only"
        h = body["health"]
        assert "components" in h and h["components"], "components empty for equity-only"
        assert 0 <= h["health_score"] <= 100
    finally:
        sdb.users.delete_many({"user_id": uid})
        sdb.user_sessions.delete_many({"session_token": tok})
        sdb.holdings.delete_many({"user_id": uid})
        client.close()
