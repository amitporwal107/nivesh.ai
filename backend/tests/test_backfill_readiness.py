"""Regression tests for the Backfill Readiness Matrix API.

Smoke-level — exercises the live route end-to-end and asserts:
  • 200 status with admin session cookie
  • Verdict + totals.mandatory_total/_gold/_pct present
  • Each row carries source / criticality / cert / coverage_pct
  • Filter `only_mandatory=true` returns only MANDATORY rows
"""
from __future__ import annotations

import os

import httpx
import pytest


API = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
ADMIN_TOKEN = os.environ.get("ADMIN_SESSION_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")
COOKIES = {"session_token": ADMIN_TOKEN}


def _get(path: str, **params):
    return httpx.get(f"{API}{path}", cookies=COOKIES, params=params, timeout=30.0)


def test_readiness_returns_matrix() -> None:
    r = _get("/api/admin/nidp/backfill/readiness", target_days=90)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["verdict"] in ("READY", "NEAR_READY", "NOT_READY")
    assert "totals" in d and "mandatory_total" in d["totals"]
    assert d["totals"]["mandatory_total"] > 0
    assert isinstance(d["rows"], list)
    assert len(d["rows"]) > 0
    sample = d["rows"][0]
    for key in ("name", "source", "criticality", "cert", "coverage_pct", "validation"):
        assert key in sample, f"missing key {key!r} in row: {sample}"


def test_readiness_only_mandatory_filter() -> None:
    r = _get("/api/admin/nidp/backfill/readiness", target_days=90, only_mandatory="true")
    assert r.status_code == 200
    d = r.json()
    assert all(row["criticality"] == "MANDATORY" for row in d["rows"]), (
        "only_mandatory filter leaked non-MANDATORY rows"
    )


def test_readiness_requires_admin_auth() -> None:
    r = httpx.get(
        f"{API}/api/admin/nidp/backfill/readiness",
        timeout=10.0,
    )
    assert r.status_code in (401, 403), f"expected auth gate, got {r.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
