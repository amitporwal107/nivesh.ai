"""Tests for V3.1 category-aware weight config + classification."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"


@pytest.fixture(scope="module")
def api():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    s = requests.Session()
    s.cookies.set("session_token", ADMIN_TOKEN)
    return s


# ── Classifier (unit) ────────────────────────────────────────────────────
def test_classifier_equity():
    from services.v3_weights import classify_fund_category
    assert classify_fund_category({"category": "Large Cap Fund"}) == "equity"
    assert classify_fund_category({"category": "Flexi Cap"}) == "equity"
    assert classify_fund_category({"category": "Small Cap Fund"}) == "equity"


def test_classifier_debt():
    from services.v3_weights import classify_fund_category
    assert classify_fund_category({"category": "Corporate Bond"}) == "debt"
    assert classify_fund_category({"category": "Short Duration"}) == "debt"
    assert classify_fund_category({"category": "Gilt Fund"}) == "debt"


def test_classifier_hybrid():
    from services.v3_weights import classify_fund_category
    assert classify_fund_category({"category": "Aggressive Hybrid"}) == "hybrid"
    assert classify_fund_category({"category": "Balanced Advantage"}) == "hybrid"
    assert classify_fund_category({"category": "Multi Asset Allocation"}) == "hybrid"


def test_classifier_liquid():
    from services.v3_weights import classify_fund_category
    assert classify_fund_category({"category": "Liquid"}) == "liquid"
    assert classify_fund_category({"category": "Overnight Fund"}) == "liquid"


def test_classifier_default():
    from services.v3_weights import classify_fund_category
    assert classify_fund_category({}) == "equity"
    assert classify_fund_category({"category": ""}) == "equity"


def test_default_weights_sum_to_100():
    from services.v3_weights import DEFAULT_WEIGHTS
    for cat, dims in DEFAULT_WEIGHTS.items():
        for dim, wmap in dims.items():
            total = sum(wmap.values())
            assert total == 100, f"{cat}.{dim} sums to {total}, not 100"


# ── Admin API ────────────────────────────────────────────────────────────
def test_get_weights(api):
    r = api.get(f"{BASE_URL}/api/admin/v3-weights", timeout=10)
    assert r.status_code == 200
    d = r.json()
    for k in ("weights", "defaults", "summary"):
        assert k in d
    for cat in ("equity", "hybrid", "debt"):
        assert cat in d["weights"], f"missing category {cat}"
        for dim in ("quality", "health"):
            assert dim in d["weights"][cat]


def test_put_weights_validates_sum(api):
    bad = {
        "equity": {
            "quality": {
                "performance": 50, "risk_adjusted": 30, "consistency": 30,
                "drawdown": 30, "cost": 10, "aum_age": 10,  # sums to 160
            },
            "health": {
                "manager_tenure": 25, "aum_stability": 20, "turnover": 15,
                "concentration": 15, "downside_protection": 15, "expense_trend": 10,
            },
        }
    }
    r = api.put(f"{BASE_URL}/api/admin/v3-weights",
                json={"weights": bad}, timeout=10)
    assert r.status_code == 422
    assert "issues" in r.json().get("detail", {})


def test_put_weights_accepts_valid(api):
    """Round-trip: tweak equity.quality.performance and restore after."""
    r = api.get(f"{BASE_URL}/api/admin/v3-weights", timeout=10)
    current = r.json()["weights"]
    orig_perf = current["equity"]["quality"]["performance"]
    # Shift 5 points from performance → cost
    current["equity"]["quality"]["performance"] = orig_perf - 5
    current["equity"]["quality"]["cost"] = current["equity"]["quality"]["cost"] + 5
    r = api.put(f"{BASE_URL}/api/admin/v3-weights",
                json={"weights": current}, timeout=10)
    assert r.status_code == 200, r.text
    got = r.json()["weights"]
    assert got["equity"]["quality"]["performance"] == orig_perf - 5
    # Restore
    r = api.post(f"{BASE_URL}/api/admin/v3-weights/reset", timeout=10)
    assert r.status_code == 200


def test_reset_restores_defaults(api):
    r = api.post(f"{BASE_URL}/api/admin/v3-weights/reset", timeout=10)
    assert r.status_code == 200
    got = r.json()["weights"]
    from services.v3_weights import DEFAULT_WEIGHTS
    for cat in DEFAULT_WEIGHTS:
        assert got[cat] == DEFAULT_WEIGHTS[cat]


def test_non_admin_blocked():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    r = requests.get(f"{BASE_URL}/api/admin/v3-weights", timeout=10)
    assert r.status_code in (401, 403)


# ── Master funds endpoint applies per-category weights ───────────────────
def test_master_funds_applies_category_weights(api):
    r = api.get(f"{BASE_URL}/api/admin/v3-master-funds", timeout=60)
    assert r.status_code == 200
    d = r.json()
    # Find at least one debt, hybrid, equity fund
    by_cat = {}
    for f in d["funds"]:
        cat = f["quality_breakdown"].get("category")
        if cat and cat not in by_cat:
            by_cat[cat] = f
    assert "equity" in by_cat
    assert "debt" in by_cat
    # Verify each uses its own weight profile
    debt_weights = by_cat["debt"]["quality_breakdown"]["weight_profile"]
    equity_weights = by_cat["equity"]["quality_breakdown"]["weight_profile"]
    assert "credit_quality" in debt_weights, (
        f"debt fund missing credit_quality in weight_profile: {debt_weights}"
    )
    assert "credit_quality" not in equity_weights, (
        f"equity fund has credit_quality in weight_profile: {equity_weights}"
    )
    assert "performance" in equity_weights
