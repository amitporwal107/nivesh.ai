"""Iteration 54 — MFD OS pivot from unit-delta SIP estimation to REAL CAS
transactions extracted from CAS Parser API / casparser.

Tests new/regression endpoints around:
  - GET  /api/portfolio/cas-snapshots                      (regression)
  - GET  /api/portfolio/cas-sip-summary                    (no fallback now)
  - GET  /api/portfolio/cas-sip-breakdown?month=YYYY-MM    (no fallback now)
  - GET  /api/portfolio/cas-top-transactions               (no holdings fallback)
  - POST /api/portfolio/cas-transactions/backfill          (NEW)
  - GET  /api/mfd/cas-uploads/{file_id}/parsed-response    (NEW)
  - GET  /api/mfd/cas-snapshots/{snapshot_date}/parsed-response (NEW)
  - POST /api/mfd/cas-uploads/{file_id}/reparse            (regression)
  - cas_parsed_responses unique index on file_id
"""
from __future__ import annotations

import os
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

PRIMARY_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"   # user_6a8206568b50 (aporwal107)
OTHER_TOKEN   = "370eff71-fda1-46d8-b506-b81b894d634f"   # user_f087c6332922 (priyankamantri)


# ── shared fixtures ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def s_primary():
    s = requests.Session()
    s.cookies.set("session_token", PRIMARY_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def s_other():
    s = requests.Session()
    s.cookies.set("session_token", OTHER_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def s_anon():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ── 1. cas-snapshots regression ────────────────────────────────────────
class TestCasSnapshotsList:
    def test_list_snapshots_ok(self, s_primary):
        r = s_primary.get(f"{API}/portfolio/cas-snapshots")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "snapshots" in body and isinstance(body["snapshots"], list)
        assert "count" in body and body["count"] == len(body["snapshots"])
        assert "current_snapshot_date" in body
        assert "is_default_latest" in body

    def test_requires_auth(self, s_anon):
        r = s_anon.get(f"{API}/portfolio/cas-snapshots")
        assert r.status_code in (401, 403)


# ── 2. SIP summary — REAL transactions only ────────────────────────────
class TestCasSipSummary:
    def test_returns_only_real_transactions_shape(self, s_primary):
        r = s_primary.get(f"{API}/portfolio/cas-sip-summary")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "months" in body and isinstance(body["months"], list)
        assert "total_invested" in body
        assert isinstance(body["total_invested"], (int, float))
        # No unit-delta fallback — every month row must come from cas_transactions
        for m in body["months"]:
            assert m.get("source") == "cas_transactions", (
                f"unit_delta fallback should be removed; got source={m.get('source')!r}"
            )
            assert "month" in m and "total" in m and "count" in m

    def test_empty_when_no_real_txns(self, s_other):
        # priyankamantri has 0 holdings (data wiped) — should be empty
        r = s_other.get(f"{API}/portfolio/cas-sip-summary")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["months"] == []
        assert body["total_invested"] == 0


# ── 3. SIP breakdown — REAL transactions only ──────────────────────────
class TestCasSipBreakdown:
    def test_breakdown_structure_no_unit_delta(self, s_primary):
        r = s_primary.get(f"{API}/portfolio/cas-sip-breakdown", params={"month": "2026-01"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("month") == "2026-01"
        assert "funds" in body and isinstance(body["funds"], list)
        assert "amcs" in body and isinstance(body["amcs"], list)
        assert "redemptions" in body and isinstance(body["redemptions"], list)
        # Top-level source must be cas_transactions, NEVER unit_delta
        assert body.get("source") == "cas_transactions", (
            f"breakdown must not use unit_delta fallback; got source={body.get('source')!r}"
        )
        # No fund row should claim source=unit_delta
        for f in body["funds"]:
            assert f.get("source") != "unit_delta"

    def test_breakdown_empty_for_other_user(self, s_other):
        r = s_other.get(f"{API}/portfolio/cas-sip-breakdown", params={"month": "2026-01"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["funds"] == []
        assert body["amcs"] == []

    def test_invalid_month_400(self, s_primary):
        r = s_primary.get(f"{API}/portfolio/cas-sip-breakdown", params={"month": "2026/01"})
        assert r.status_code == 400


# ── 4. Top transactions — REAL only, no HOLDING ────────────────────────
class TestCasTopTransactions:
    def test_no_holding_type_in_response(self, s_primary):
        r = s_primary.get(f"{API}/portfolio/cas-top-transactions", params={"n": 20})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "transactions" in body and isinstance(body["transactions"], list)
        assert "count" in body and body["count"] == len(body["transactions"])
        for t in body["transactions"]:
            # Must never expose holdings as fake transactions any more
            assert (t.get("type") or "").upper() != "HOLDING", (
                f"top-transactions must not return holdings fallback; got {t}"
            )

    def test_empty_for_other_user(self, s_other):
        r = s_other.get(f"{API}/portfolio/cas-top-transactions")
        assert r.status_code == 200
        body = r.json()
        assert body["transactions"] == []
        assert body["count"] == 0


# ── 5. Backfill endpoint ───────────────────────────────────────────────
class TestBackfillTransactions:
    def test_backfill_contract(self, s_primary):
        r = s_primary.post(f"{API}/portfolio/cas-transactions/backfill")
        assert r.status_code == 200, r.text
        body = r.json()
        # Per the request: contract test, not value test
        assert "snapshots_scanned" in body
        assert "transactions_inserted" in body
        assert "transactions_updated" in body
        assert isinstance(body["snapshots_scanned"], int)
        assert isinstance(body["transactions_inserted"], int)
        assert isinstance(body["transactions_updated"], int)

    def test_backfill_idempotent(self, s_primary):
        r1 = s_primary.post(f"{API}/portfolio/cas-transactions/backfill")
        r2 = s_primary.post(f"{API}/portfolio/cas-transactions/backfill")
        assert r1.status_code == 200 and r2.status_code == 200
        b2 = r2.json()
        # Second run should not insert anything new (existing snapshots have
        # transactions_count=0 anyway)
        assert b2["transactions_inserted"] == 0

    def test_backfill_requires_auth(self, s_anon):
        r = s_anon.post(f"{API}/portfolio/cas-transactions/backfill")
        assert r.status_code in (401, 403)


# ── 6. Parsed-response by file_id ──────────────────────────────────────
class TestParsedResponseByFileId:
    def test_unknown_file_id_404(self, s_primary):
        r = s_primary.get(f"{API}/mfd/cas-uploads/does-not-exist/parsed-response")
        # Owning workspace lookup fails first → 404
        assert r.status_code == 404

    def test_requires_auth(self, s_anon):
        r = s_anon.get(f"{API}/mfd/cas-uploads/anything/parsed-response")
        assert r.status_code in (401, 403)


# ── 7. Parsed-response by snapshot_date ────────────────────────────────
class TestParsedResponseBySnapshot:
    def test_no_snapshot_or_no_file_404(self, s_primary):
        r = s_primary.get(f"{API}/mfd/cas-snapshots/2099-12-31/parsed-response")
        assert r.status_code == 404

    def test_requires_auth(self, s_anon):
        r = s_anon.get(f"{API}/mfd/cas-snapshots/2026-01-31/parsed-response")
        assert r.status_code in (401, 403)


# ── 8. Reparse endpoint regression ─────────────────────────────────────
class TestReparseRegression:
    def test_reparse_unknown_file_404(self, s_primary):
        r = s_primary.post(
            f"{API}/mfd/cas-uploads/no-such-file/reparse",
            json={"password": "ABCDE1234F"},
        )
        assert r.status_code == 404

    def test_reparse_requires_auth(self, s_anon):
        r = s_anon.post(
            f"{API}/mfd/cas-uploads/whatever/reparse",
            json={"password": "ABCDE1234F"},
        )
        assert r.status_code in (401, 403)


# ── 9. MongoDB index verification ──────────────────────────────────────
class TestMongoIndex:
    def test_cas_parsed_responses_unique_index(self):
        # Use the same DB the backend uses
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name   = os.environ.get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL / DB_NAME must be set"

        async def _check():
            client = AsyncIOMotorClient(mongo_url)
            try:
                # Trigger ensure_indexes from the engine to be sure
                from services import cas_snapshot_engine as eng  # noqa: WPS433
                try:
                    await eng.ensure_indexes()
                except Exception:
                    pass
                idx = await client[db_name].cas_parsed_responses.index_information()
                return idx
            finally:
                client.close()

        # Run from backend dir so imports resolve
        import sys
        sys.path.insert(0, "/app/backend")
        idx = asyncio.run(_check())
        # Find an index that includes file_id and is unique
        found = False
        for name, info in idx.items():
            keys = info.get("key") or []
            field_names = [k[0] for k in keys]
            if "file_id" in field_names and info.get("unique"):
                found = True
                break
        assert found, f"cas_parsed_responses needs unique index on file_id. Got: {idx}"
