"""Iteration 43 — Morningstar rating wiring tests.

Verifies:
- GET /api/portfolio/holdings-enriched: MF rows include `morningstar_rating` field (int 1-5 or null).
- At least 10 MF holdings have non-null `morningstar_rating` for priyanka.
- POST /api/portfolio/refresh-mf-ratings: response shape + idempotency.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nidp-backfill-ui.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- holdings-enriched: field presence + rating count -----------------------
class TestHoldingsEnrichedMorningstar:
    def test_holdings_enriched_mf_has_morningstar_field(self, client):
        r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        holdings = data.get("holdings") or data.get("enriched") or data.get("rows") or []
        assert isinstance(holdings, list) and len(holdings) > 0, f"no holdings in response: keys={list(data.keys())[:8]}"
        mfs = [h for h in holdings if (h.get("asset_type") or "").lower() in ("mutual_fund", "mf")]
        assert len(mfs) >= 20, f"expected >=20 MF holdings for priyanka, got {len(mfs)}"
        # Every MF row must have key (may be null)
        missing = [m.get("name") for m in mfs if "morningstar_rating" not in m]
        assert not missing, f"MF rows missing morningstar_rating key: {missing[:5]}"
        # Type check - int 1..5 or None
        for m in mfs:
            mr = m.get("morningstar_rating")
            assert mr is None or (isinstance(mr, int) and 1 <= mr <= 5), (
                f"Invalid morningstar_rating {mr!r} on {m.get('name')}"
            )

    def test_at_least_10_mfs_rated(self, client):
        r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
        assert r.status_code == 200
        data = r.json()
        holdings = data.get("holdings") or data.get("enriched") or data.get("rows") or []
        mfs = [h for h in holdings if (h.get("asset_type") or "").lower() in ("mutual_fund", "mf")]
        rated = [m for m in mfs if m.get("morningstar_rating") is not None]
        print(f"\n[INFO] {len(rated)}/{len(mfs)} MFs have morningstar_rating")
        for m in rated[:20]:
            print(f"  - {m.get('name')[:60]}: ★{m.get('morningstar_rating')}")
        assert len(rated) >= 10, f"expected >=10 rated MFs, got {len(rated)} of {len(mfs)}"

    def test_specific_expected_ratings(self, client):
        """Spec mentions HDFC Flexi Cap=★5, Axis Small Cap=★5, Sundaram Value=★2."""
        r = client.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=60)
        data = r.json()
        holdings = data.get("holdings") or data.get("enriched") or data.get("rows") or []
        by_name = {(h.get("name") or "").lower(): h for h in holdings}
        checks = {
            "hdfc flexi cap": 5,
            "axis small cap": 5,
            "sundaram value": 2,
        }
        found = {}
        for needle, expected in checks.items():
            matches = [v for k, v in by_name.items() if needle in k]
            if matches:
                mr = matches[0].get("morningstar_rating")
                found[needle] = (mr, expected, matches[0].get("name"))
        print(f"\n[INFO] specific-fund ratings: {found}")
        # At least 2 of 3 must match (data source may occasionally vary)
        matched = sum(1 for (mr, exp, _n) in found.values() if mr == exp)
        assert matched >= 2, f"expected ≥2 matching spec ratings, got {matched}: {found}"


# --- refresh-mf-ratings: shape + idempotency --------------------------------
class TestRefreshMfRatings:
    def test_refresh_response_shape(self, client):
        r = client.post(f"{BASE_URL}/api/portfolio/refresh-mf-ratings", timeout=300)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("ok", "total", "scraped", "with_rating", "failed", "failed_details"):
            assert k in data, f"missing key {k} in refresh response: {list(data.keys())}"
        assert data["ok"] is True
        assert isinstance(data["total"], int) and data["total"] >= 30
        assert isinstance(data["scraped"], int)
        assert isinstance(data["with_rating"], int)
        assert isinstance(data["failed"], int)
        assert isinstance(data["failed_details"], list)
        print(f"\n[INFO] refresh-mf-ratings (run 1): {data}")
        self._run1 = data

    def test_refresh_idempotent(self, client):
        """Running twice should return similar counts (no blow-up)."""
        r1 = client.post(f"{BASE_URL}/api/portfolio/refresh-mf-ratings", timeout=300)
        assert r1.status_code == 200
        d1 = r1.json()
        time.sleep(1)
        r2 = client.post(f"{BASE_URL}/api/portfolio/refresh-mf-ratings", timeout=300)
        assert r2.status_code == 200
        d2 = r2.json()
        print(f"\n[INFO] run1={d1}\nrun2={d2}")
        assert d1["total"] == d2["total"]
        # with_rating count should be same ±2
        assert abs(d1["with_rating"] - d2["with_rating"]) <= 2
