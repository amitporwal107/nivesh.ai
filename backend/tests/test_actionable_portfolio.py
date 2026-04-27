"""Backend regression tests for Actionable Portfolio (iteration 39)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://advisor-timeline.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    return s


# --- Holdings Enriched ---
def test_holdings_enriched_structure(client):
    r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "holdings" in data and isinstance(data["holdings"], list)
    assert len(data["holdings"]) >= 64, f"expected >=64 holdings, got {len(data['holdings'])}"
    assert "totals" in data
    assert data["totals"].get("xirr_pct") is not None, "totals.xirr_pct missing"
    assert "alerts" in data and len(data["alerts"]) >= 1
    assert "coverage_pct" in data


def test_holdings_enriched_badges_and_scores(client):
    r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
    data = r.json()
    badge_actions = set()
    has_score = False
    for h in data["holdings"]:
        assert "holding_id" in h and "name" in h
        if h.get("action_badge"):
            badge_actions.add(h["action_badge"].get("action"))
        if h.get("composite_score") is not None:
            has_score = True
    # At minimum, expect at least one non-trivial action and some scores
    assert badge_actions, "no action_badges on any holding"
    assert has_score, "no composite_score on any holding"


# --- Switch Candidates ---
def test_switch_candidates_hdfc(client):
    hid = "hold_6b028a43430c"
    r = client.get(f"{BASE_URL}/api/portfolio/switch-candidates",
                   params={"holding_id": hid}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "category" in data
    assert "source_fund" in data
    assert "candidates" in data
    assert len(data["candidates"]) >= 1, f"expected >=1 candidates, got {len(data['candidates'])}"
    c0 = data["candidates"][0]
    assert "name" in c0
    assert "switch_score" in c0


def test_switch_candidates_invalid_holding(client):
    r = client.get(f"{BASE_URL}/api/portfolio/switch-candidates",
                   params={"holding_id": "hold_does_not_exist"}, timeout=30)
    assert r.status_code == 404


def test_unauthenticated_blocked():
    r = requests.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=30)
    assert r.status_code in (401, 403)
