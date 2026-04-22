"""Integration tests for the Goal-Based Investment Planning API (/api/goals/*).

Covers:
  * Auth gating (401 without cookie)
  * Snapshot GET/PUT round-trip
  * Fund shortlist for equity/debt/hybrid buckets
  * Goal create → list → get → simulate → what-if → patch → delete
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"   # priyankamantri@gmail.com


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def created_goal_id(client):
    """Create a throwaway goal for mutation-style tests, clean up at module end."""
    payload = {
        "goal_type": "wealth",
        "goal_name": f"TEST_GoalAPI_{uuid.uuid4().hex[:6]}",
        "target_amount_rs": 5000000,
        "horizon_years": 12,
        "priority": "medium",
        "inflation_pct": 6.0,
        "current_corpus_rs": 100000,
        "monthly_sip_rs": 8000,
    }
    r = client.post(f"{BASE_URL}/api/goals", json=payload)
    assert r.status_code == 200, r.text
    gid = r.json()["goal_id"]
    yield gid
    client.delete(f"{BASE_URL}/api/goals/{gid}")


# ── Auth ─────────────────────────────────────────────────────────────
class TestAuth:
    def test_snapshot_unauth(self):
        r = requests.get(f"{BASE_URL}/api/goals/snapshot")
        assert r.status_code == 401

    def test_list_goals_unauth(self):
        r = requests.get(f"{BASE_URL}/api/goals")
        assert r.status_code == 401

    def test_fund_shortlist_unauth(self):
        r = requests.get(f"{BASE_URL}/api/goals/fund-shortlist/equity")
        assert r.status_code == 401

    def test_post_goal_unauth(self):
        r = requests.post(f"{BASE_URL}/api/goals", json={"goal_type": "wealth", "goal_name": "x",
                                                          "target_amount_rs": 1, "horizon_years": 1})
        assert r.status_code == 401


# ── Snapshot ─────────────────────────────────────────────────────────
class TestSnapshot:
    def test_get_snapshot(self, client):
        r = client.get(f"{BASE_URL}/api/goals/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert "snapshot" in body
        # Priyanka already has snapshot per main-agent note
        snap = body["snapshot"]
        assert snap is not None
        assert "risk_profile" in snap

    def test_put_snapshot_idempotent(self, client):
        # Save current, then re-PUT identical payload
        r0 = client.get(f"{BASE_URL}/api/goals/snapshot")
        cur = r0.json()["snapshot"] or {}
        payload = {
            "age": cur.get("age") or 35,
            "dependents": cur.get("dependents") or 0,
            "monthly_income_rs": cur.get("monthly_income_rs") or 200000,
            "income_growth_pct": cur.get("income_growth_pct") or 8.0,
            "monthly_expenses_rs": cur.get("monthly_expenses_rs") or 80000,
            "inflation_pct": cur.get("inflation_pct") or 6.0,
            "current_corpus_rs": cur.get("current_corpus_rs") or 500000,
            "total_liabilities_rs": cur.get("total_liabilities_rs") or 0,
            "risk_profile": cur.get("risk_profile") or "moderate",
        }
        r1 = client.put(f"{BASE_URL}/api/goals/snapshot", json=payload)
        assert r1.status_code == 200, r1.text
        snap1 = r1.json()["snapshot"]
        # Sanity-check persisted values
        assert snap1["age"] == payload["age"]
        assert float(snap1["monthly_income_rs"]) == payload["monthly_income_rs"]
        assert snap1["risk_profile"] == payload["risk_profile"]

        # PUT again — idempotent (same values)
        r2 = client.put(f"{BASE_URL}/api/goals/snapshot", json=payload)
        assert r2.status_code == 200
        snap2 = r2.json()["snapshot"]
        assert snap2["age"] == snap1["age"]
        assert snap2["risk_profile"] == snap1["risk_profile"]


# ── Fund shortlist ────────────────────────────────────────────────────
class TestFundShortlist:
    @pytest.mark.parametrize("bucket", ["equity", "debt", "hybrid"])
    def test_shortlist_returns_quality_funds(self, client, bucket):
        r = client.get(f"{BASE_URL}/api/goals/fund-shortlist/{bucket}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["bucket"] == bucket
        funds = body["funds"]
        assert isinstance(funds, list)
        assert len(funds) >= 3, f"expected ≥3 {bucket} funds, got {len(funds)}"
        # Sorted by quality_score DESC
        qs = [f.get("quality_score") for f in funds if f.get("quality_score") is not None]
        assert qs == sorted(qs, reverse=True)
        # Min quality filter ≥ 55
        for f in funds:
            if f.get("quality_score") is not None:
                assert f["quality_score"] >= 55


# ── Goal CRUD + simulation ───────────────────────────────────────────
class TestGoalLifecycle:
    def test_create_goal_returns_full_simulation(self, client, created_goal_id):
        r = client.get(f"{BASE_URL}/api/goals/{created_goal_id}")
        assert r.status_code == 200
        g = r.json()
        assert g["goal_id"] == created_goal_id
        assert g["goal_name"].startswith("TEST_GoalAPI_")
        assert g["status"] == "active"
        # Allocation set
        assert isinstance(g["allocation"], dict) and sum(g["allocation"].values()) == pytest.approx(100, abs=1)
        # Selected funds dict keyed by bucket
        assert isinstance(g["selected_funds"], dict)
        # last_simulation payload is complete
        sim = g["last_simulation"]
        assert set(["scenarios", "monte_carlo", "actions", "on_track_pct"]).issubset(sim.keys())
        assert set(sim["scenarios"].keys()) == {"base", "bull", "bear", "stress"}
        assert 0 <= sim["monte_carlo"]["prob_success_pct"] <= 100
        assert sim["actions"], "Expected at least 1 action recommendation"

    def test_list_goals_contains_created(self, client, created_goal_id):
        r = client.get(f"{BASE_URL}/api/goals")
        assert r.status_code == 200
        ids = [g["goal_id"] for g in r.json()["goals"]]
        assert created_goal_id in ids
        # Priority ordering: high before medium before low
        order = {"high": 0, "medium": 1, "low": 2}
        goals = r.json()["goals"]
        prios = [order.get(g["priority"], 1) for g in goals]
        assert prios == sorted(prios)

    def test_simulate_persists(self, client, created_goal_id):
        r = client.post(f"{BASE_URL}/api/goals/{created_goal_id}/simulate")
        assert r.status_code == 200
        ev = r.json()
        assert ev["goal_id"] == created_goal_id
        assert "scenarios" in ev and "monte_carlo" in ev
        # Verify the on_track_pct was persisted
        g = client.get(f"{BASE_URL}/api/goals/{created_goal_id}").json()
        assert g["on_track_pct"] == ev["on_track_pct"]

    def test_what_if_does_not_persist(self, client, created_goal_id):
        before = client.get(f"{BASE_URL}/api/goals/{created_goal_id}").json()
        r = client.post(
            f"{BASE_URL}/api/goals/{created_goal_id}/what-if",
            json={"monthly_sip_rs": 50000, "horizon_years": before["horizon_years"]},
        )
        assert r.status_code == 200
        preview = r.json()
        assert preview["preview"] is True
        assert "scenarios" in preview and "monte_carlo" in preview
        # Higher SIP → higher on-track vs. baseline
        assert preview["on_track_pct"] >= before["on_track_pct"]
        # Persistence check: monthly_sip_rs unchanged
        after = client.get(f"{BASE_URL}/api/goals/{created_goal_id}").json()
        assert after["monthly_sip_rs"] == before["monthly_sip_rs"]

    def test_patch_persists(self, client, created_goal_id):
        r = client.patch(
            f"{BASE_URL}/api/goals/{created_goal_id}",
            json={"monthly_sip_rs": 15000, "goal_name": "TEST_GoalAPI_renamed"},
        )
        assert r.status_code == 200
        assert float(r.json()["monthly_sip_rs"]) == 15000
        # Re-GET to confirm persistence
        g = client.get(f"{BASE_URL}/api/goals/{created_goal_id}").json()
        assert g["goal_name"] == "TEST_GoalAPI_renamed"
        assert float(g["monthly_sip_rs"]) == 15000

    def test_delete_soft_abandons(self, client):
        # Create a throwaway goal to delete
        payload = {"goal_type": "wealth", "goal_name": "TEST_DeleteMe",
                   "target_amount_rs": 100000, "horizon_years": 5, "monthly_sip_rs": 1000}
        gid = client.post(f"{BASE_URL}/api/goals", json=payload).json()["goal_id"]
        r = client.delete(f"{BASE_URL}/api/goals/{gid}")
        assert r.status_code == 200
        assert r.json()["status"] == "abandoned"
        # Still fetchable but status=abandoned
        g = client.get(f"{BASE_URL}/api/goals/{gid}").json()
        assert g["status"] == "abandoned"
