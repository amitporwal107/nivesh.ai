"""Phase 1 Time-Machine / Portfolio Snapshot Engine tests.

Covers:
  - POST /api/portfolio/snapshot (manual trigger, upsert idempotency)
  - GET  /api/portfolio/snapshots (list dates, newest first)
  - GET  /api/portfolio/snapshot (latest + by date + fallback earlier)
  - GET  /api/portfolio/trend (sparkline series)
  - GET  /api/portfolio/compare (diff new vs old)
  - 401 on every endpoint when unauthenticated
  - diff_snapshots() pure helper
  - get_snapshot_on_or_before() fallback
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ADMIN_TOKEN = os.environ.get("NIVESH_TEST_ADMIN_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")
COOKIES = {"session_token": ADMIN_TOKEN}


# ── Auth: 401 on every endpoint ────────────────────────────────────────
class TestAuth:
    def test_snapshots_list_401(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/snapshots")
        assert r.status_code == 401

    def test_snapshot_get_401(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/snapshot")
        assert r.status_code == 401

    def test_trend_401(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/trend?days=7")
        assert r.status_code == 401

    def test_compare_401(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/compare")
        assert r.status_code == 401

    def test_manual_snapshot_401(self):
        r = requests.post(f"{BASE_URL}/api/portfolio/snapshot", json={"trigger": "manual"})
        assert r.status_code == 401


# ── Manual snapshot endpoint ───────────────────────────────────────────
class TestManualSnapshot:
    def test_post_manual_returns_shape(self):
        r = requests.post(
            f"{BASE_URL}/api/portfolio/snapshot",
            json={"trigger": "manual"}, cookies=COOKIES,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "snapshot" in body and "persisted" in body
        s = body["snapshot"]
        for k in ["user_id", "snapshot_date", "total_value", "allocation",
                  "holdings_count", "top_holdings", "scores", "health_score", "grade"]:
            assert k in s, f"missing key {k}"
        assert body["persisted"] is True
        # Priyanka impersonates AMIT PORWAL (110 holdings). Total value ≈ ₹1.02 Cr.
        assert s["holdings_count"] >= 50
        assert s["total_value"] > 1_000_000
        assert s["grade"] in ("A", "B", "C", "D", "F")

    def test_upsert_idempotency(self):
        # list → POST (same day) → list again; count must not increase.
        r1 = requests.get(f"{BASE_URL}/api/portfolio/snapshots", cookies=COOKIES)
        assert r1.status_code == 200
        count_before = r1.json()["count"]

        r2 = requests.post(
            f"{BASE_URL}/api/portfolio/snapshot",
            json={"trigger": "manual"}, cookies=COOKIES,
        )
        assert r2.status_code == 200

        r3 = requests.get(f"{BASE_URL}/api/portfolio/snapshots", cookies=COOKIES)
        assert r3.status_code == 200
        count_after = r3.json()["count"]
        assert count_after == count_before, "upsert created duplicate same-day snapshot"


# ── List snapshot dates ────────────────────────────────────────────────
class TestListDates:
    def test_list_newest_first(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/snapshots", cookies=COOKIES)
        assert r.status_code == 200
        body = r.json()
        assert "count" in body and "dates" in body
        dates = body["dates"]
        assert body["count"] == len(dates)
        assert dates == sorted(dates, reverse=True), "dates should be newest-first"
        # Seeded dates include 2026-04-18..24
        assert len(dates) >= 5


# ── Get snapshot (latest + by date + fallback) ─────────────────────────
class TestGetSnapshot:
    def test_latest_no_date(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/snapshot", cookies=COOKIES)
        assert r.status_code == 200
        body = r.json()
        assert "snapshot_date" in body and "total_value" in body

    def test_by_exact_date(self):
        r = requests.get(
            f"{BASE_URL}/api/portfolio/snapshot?date=2026-04-23", cookies=COOKIES,
        )
        assert r.status_code == 200
        assert r.json()["snapshot_date"] == "2026-04-23"

    def test_fallback_earlier_when_missing(self):
        # 2026-04-01 has no snapshot; fallback to closest earlier or same.
        r = requests.get(
            f"{BASE_URL}/api/portfolio/snapshot?date=2026-04-20", cookies=COOKIES,
        )
        assert r.status_code == 200
        d = r.json()["snapshot_date"]
        # seeded 18,19,22,23,24 — on 20 fallback picks 19.
        assert d <= "2026-04-20"


# ── Trend series ──────────────────────────────────────────────────────
class TestTrend:
    def test_trend_shape(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/trend?days=30", cookies=COOKIES)
        assert r.status_code == 200
        body = r.json()
        assert body["days"] == 30
        series = body["series"]
        assert isinstance(series, list) and len(series) >= 2
        # ascending by date
        dates = [s["snapshot_date"] for s in series]
        assert dates == sorted(dates), "trend must be ascending by date"
        for s in series:
            assert "total_value" in s
            assert "health_score" in s
            assert "allocation" in s


# ── Compare (diff) ────────────────────────────────────────────────────
class TestCompare:
    def test_compare_default(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/compare", cookies=COOKIES)
        assert r.status_code == 200
        body = r.json()
        for k in ["new", "old", "diff"]:
            assert k in body
        diff = body["diff"]
        for k in ["value_delta", "value_pct_change", "health_delta",
                  "allocation_delta_pp", "holdings_added", "holdings_removed",
                  "from_date", "to_date"]:
            assert k in diff, f"missing diff key {k}"

    def test_compare_explicit_dates(self):
        r = requests.get(
            f"{BASE_URL}/api/portfolio/compare?from=2026-04-18&to=2026-04-24",
            cookies=COOKIES,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["new"]["snapshot_date"] == "2026-04-24"
        assert body["old"]["snapshot_date"] == "2026-04-18"
        assert body["diff"]["from_date"] == "2026-04-18"
        assert body["diff"]["to_date"] == "2026-04-24"


# ── Pure helpers (no DB) ───────────────────────────────────────────────
class TestPureHelpers:
    def test_diff_snapshots_first_snapshot(self):
        from services.portfolio_snapshot import diff_snapshots
        new = {"snapshot_date": "2026-04-24", "total_value": 100.0,
               "health_score": 70, "allocation": {"equity": 60}, "top_holdings": []}
        out = diff_snapshots(new, None)
        assert out["to_date"] == "2026-04-24"
        assert out["from_date"] is None
        assert out["value_delta"] is None

    def test_diff_snapshots_with_old(self):
        from services.portfolio_snapshot import diff_snapshots
        old = {"snapshot_date": "2026-04-18", "total_value": 100.0,
               "health_score": 70, "allocation": {"equity": 60, "mf": 40},
               "top_holdings": [{"name": "A"}, {"name": "B"}]}
        new = {"snapshot_date": "2026-04-24", "total_value": 110.0,
               "health_score": 72, "allocation": {"equity": 55, "mf": 45},
               "top_holdings": [{"name": "B"}, {"name": "C"}]}
        out = diff_snapshots(new, old)
        assert out["value_delta"] == 10.0
        assert out["value_pct_change"] == 10.0
        assert out["health_delta"] == 2
        assert out["allocation_delta_pp"] == {"equity": -5.0, "mf": 5.0}
        added = [h["name"] for h in out["holdings_added"]]
        removed = [h["name"] for h in out["holdings_removed"]]
        assert "C" in added and "A" in removed
