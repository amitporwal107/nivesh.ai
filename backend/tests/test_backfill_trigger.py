"""Tests for the Backfill VM trigger endpoints.

Smoke-level: verifies validation, auth gating, and that the /trigger/health
endpoint gracefully reports SSH unavailability when the SA key is missing
(the expected state until the user uploads `/app/backend/.secrets/nidp_vm_sa.json`).
"""
from __future__ import annotations

import os

import httpx
import pytest


API = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
ADMIN_TOKEN = os.environ.get("ADMIN_SESSION_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")
COOKIES = {"session_token": ADMIN_TOKEN}


def test_trigger_health_reports_when_sa_missing() -> None:
    """When the SA key is loaded, /trigger/health returns ok:true with VM echo.
    When missing, returns ok:false with a clear reason."""
    r = httpx.get(f"{API}/api/admin/nidp/backfill/trigger/health",
                  cookies=COOKIES, timeout=30.0)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "ok" in d
    if d["ok"]:
        # SA key is loaded — echo should include hostname
        assert "nidp-stack-vm" in d.get("vm_echo", "")
    else:
        # Expected when SA key isn't uploaded yet
        assert "service-account" in d["reason"].lower() or "ssh" in d["reason"].lower() \
            or "gcloud" in d["reason"].lower()


def test_trigger_daily_rejects_unknown_ingester() -> None:
    r = httpx.post(
        f"{API}/api/admin/nidp/backfill/trigger/daily",
        cookies=COOKIES, timeout=10.0,
        json={
            "start_date":   "2026-02-11",
            "end_date":     "2026-05-11",
            "ingesters":    ["bhavcopy", "nonexistent_feed"],
        },
    )
    assert r.status_code == 422, r.text
    assert "nonexistent_feed" in r.text or "unknown" in r.text.lower()


def test_trigger_rolling_rejects_unknown_service() -> None:
    r = httpx.post(
        f"{API}/api/admin/nidp/backfill/trigger/rolling",
        cookies=COOKIES, timeout=10.0,
        json={
            "start_date":   "2026-02-11",
            "end_date":     "2026-05-11",
            "services":     ["bulk_deals", "totally_made_up"],
        },
    )
    assert r.status_code == 422
    assert "totally_made_up" in r.text or "unknown" in r.text.lower()


def test_trigger_daily_rejects_inverted_dates() -> None:
    r = httpx.post(
        f"{API}/api/admin/nidp/backfill/trigger/daily",
        cookies=COOKIES, timeout=10.0,
        json={
            "start_date":   "2026-05-11",
            "end_date":     "2026-02-11",
            "ingesters":    ["fno_bhavcopy"],
        },
    )
    assert r.status_code == 422


def test_trigger_requires_admin_auth() -> None:
    r = httpx.post(
        f"{API}/api/admin/nidp/backfill/trigger/daily",
        json={"start_date": "2026-02-11", "end_date": "2026-05-11", "ingesters": ["fno_bhavcopy"]},
        timeout=10.0,
    )
    assert r.status_code in (401, 403)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
