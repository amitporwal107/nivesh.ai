"""services/brokers/sync_snapshots.py — the snapshot document, its retention, who may read one, and
its removal when the account is erased.

In-memory db only (the fake from test_broker_hub_reads.py); nothing here talks to Mongo or a broker.
That a sync writes a snapshot, and what the duplicate check puts in it, is tested with the sync in
test_broker_hub_reads.py; the routes are tested in test_broker_connect_native_routes.py.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_broker_hub_reads import CLIENT_ID, SECRET, FakeCollection, FakeDB, ZERO_DUPLICATES, native_account

from services.brokers import sync_snapshots as snaps  # noqa: E402

T0 = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def _stored_row(ticker: str, quantity: float, buy_price: float, current_price: float, **over) -> dict:
    """A holdings row as hub_reads stores it — with the ids and bookkeeping a snapshot leaves out."""
    row = {
        "_id": object(), "holding_id": f"hold_{ticker}", "user_id": "u1", "portfolio_id": "",
        "name": f"{ticker} Ltd", "ticker": ticker, "asset_type": "equity", "quantity": quantity,
        "buy_price": buy_price, "current_price": current_price, "sector": "IT", "buy_date": None,
        "source": "broker_native", "source_id": f"NSE:{ticker}", "broker": "zerodha", "broker_account_id": "ba_z",
        "uploaded_at": _at(0), "created_at": _at(0), "isin": f"INE{ticker:0<9}"[:12],
    }
    row.update(over)
    return row


ROWS = [_stored_row("INFY", 10.0, 1400.5, 1525.0), _stored_row("TCS", 2.0, 4000.0, 0.0)]


def _record(db, account="ba_z", user="u1", minutes=0, rows=ROWS, trigger="manual", **account_over):
    doc = native_account(account, user_id=user, **account_over)
    return asyncio.run(snaps.record(db, doc, rows, trigger=trigger, duplicates=ZERO_DUPLICATES,
                                    synced_at=_at(minutes), broker_display="Zerodha"))


# ── The document ─────────────────────────────────────────────────────────
def test_build_names_the_broker_and_the_login_and_copies_only_named_fields():
    row_without_isin = _stored_row("NOISIN", 1.0, 10.0, 12.0, plan="Direct")
    del row_without_isin["isin"]
    snap = snaps.build(native_account("ba_z"), ROWS + [row_without_isin], trigger="connect",
                       duplicates={**ZERO_DUPLICATES, "repeated_in_broker_reply": 2},
                       synced_at=_at(5), broker_display="Zerodha")

    assert re.fullmatch(r"bsnap_[0-9a-f]{12}", snap["snapshot_id"])
    assert {k: v for k, v in snap.items() if k not in ("snapshot_id", "holdings")} == {
        "user_id": "u1", "broker_account_id": "ba_z", "broker": "zerodha", "broker_display": "Zerodha",
        "broker_user_masked": "••••71", "trigger": "connect", "synced_at": "2026-10-14T04:05:00+00:00",
        "count": 3, "priced": 2,
        "total_value_rs": 15262.0,                      # 10 × 1525 + 1 × 12; TCS has no price and adds nothing
        "total_invested_rs": 22015.0,                   # 10 × 1400.5 + 2 × 4000 + 1 × 10
        "duplicates": {**ZERO_DUPLICATES, "repeated_in_broker_reply": 2},
    }
    assert snap["holdings"][0] == {
        "name": "INFY Ltd", "ticker": "INFY", "isin": "INEINFY00000", "asset_type": "equity", "quantity": 10.0,
        "buy_price": 1400.5, "current_price": 1525.0, "sector": "IT", "source_id": "NSE:INFY"}
    assert "isin" not in snap["holdings"][2]            # a row stored without an ISIN stays without one
    assert all(set(h) <= {"name", "ticker", "isin", "asset_type", "quantity", "buy_price", "current_price",
                          "sector", "source_id"} for h in snap["holdings"])


def test_a_snapshot_never_carries_the_token_or_the_client_id():
    account = native_account("ba_z", session_expires_at=_at(600), broker_user_key="sha256-of-client-id")
    snap = snaps.build(account, ROWS, trigger="manual", duplicates=ZERO_DUPLICATES, synced_at=_at(0),
                       broker_display="Zerodha")
    dumped = json.dumps(snap, ensure_ascii=False)
    assert SECRET not in dumped and CLIENT_ID not in dumped and "enc(" not in dumped
    assert "sha256-of-client-id" not in dumped and "api_key" not in dumped and "extras" not in dumped


def test_an_empty_sync_builds_an_empty_snapshot():
    snap = snaps.build(native_account("ba_z"), [], trigger="daily", duplicates=ZERO_DUPLICATES, synced_at=_at(0),
                       broker_display="Zerodha")
    assert (snap["count"], snap["priced"], snap["holdings"]) == (0, 0, [])
    assert (snap["total_value_rs"], snap["total_invested_rs"]) == (0.0, 0.0)
    assert isinstance(snap["total_value_rs"], float) and isinstance(snap["total_invested_rs"], float)


def test_the_duplicate_counters_are_copied_not_shared():
    counters = dict(ZERO_DUPLICATES)
    snap = snaps.build(native_account("ba_z"), ROWS, trigger="manual", duplicates=counters, synced_at=_at(0),
                       broker_display="Zerodha")
    counters["repeated_in_broker_reply"] = 99
    assert snap["duplicates"] == ZERO_DUPLICATES


@pytest.mark.parametrize("trigger", ["", "cron", "MANUAL", None])
def test_an_unknown_trigger_is_refused_and_nothing_is_written(trigger):
    db = FakeDB()
    with pytest.raises(ValueError):
        asyncio.run(snaps.record(db, native_account("ba_z"), ROWS, trigger=trigger, duplicates=ZERO_DUPLICATES,
                                 synced_at=_at(0), broker_display="Zerodha"))
    assert db.broker_sync_snapshots.docs == []


# ── Writing and retention ────────────────────────────────────────────────
def test_record_writes_one_document_and_returns_its_id():
    db = FakeDB()
    snapshot_id = _record(db)
    (stored,) = db.broker_sync_snapshots.docs
    assert stored["snapshot_id"] == snapshot_id and stored["count"] == 2
    assert _record(db, minutes=1) != snapshot_id and len(db.broker_sync_snapshots.docs) == 2


def test_at_most_ninety_snapshots_are_kept_per_account():
    assert snaps.MAX_PER_ACCOUNT == 90
    db = FakeDB()
    other = [_record(db, account="ba_other", minutes=-10 - i) for i in range(3)]     # older than all of ba_z's
    ids = [_record(db, minutes=i) for i in range(95)]

    mine = [s for s in db.broker_sync_snapshots.docs if s["broker_account_id"] == "ba_z"]
    assert len(mine) == 90
    assert {s["snapshot_id"] for s in mine} == set(ids[5:])                          # the five oldest went
    assert [s["snapshot_id"] for s in db.broker_sync_snapshots.docs
            if s["broker_account_id"] == "ba_other"] == other                        # another account is not pruned


def test_prune_reports_how_many_it_removed():
    db = FakeDB()
    for i in range(4):
        _record(db, minutes=i)
    assert asyncio.run(snaps.prune(db, "u1", "ba_z", keep=3)) == 1
    assert asyncio.run(snaps.prune(db, "u1", "ba_z", keep=3)) == 0
    assert [s["synced_at"] for s in db.broker_sync_snapshots.docs] == [_at(1), _at(2), _at(3)]


def test_a_failed_prune_does_not_lose_the_snapshot(monkeypatch, caplog):
    db = FakeDB()

    async def boom(*_a, **_k):
        raise RuntimeError("mongo delete failed")
    monkeypatch.setattr(snaps, "prune", boom)
    with caplog.at_level("ERROR", logger="services.brokers.sync_snapshots"):
        snapshot_id = _record(db)
    assert [s["snapshot_id"] for s in db.broker_sync_snapshots.docs] == [snapshot_id]
    assert "prune failed account=ba_z" in caplog.text


# ── Reading ──────────────────────────────────────────────────────────────
def test_list_is_newest_first_without_holdings_and_only_that_account():
    db = FakeDB()
    ids = [_record(db, minutes=i, trigger=t) for i, t in enumerate(["connect", "daily", "manual"])]
    _record(db, account="ba_other", minutes=9)
    _record(db, account="ba_u2", user="u2", minutes=9)

    listed = asyncio.run(snaps.list_for_account(db, "u1", "ba_z"))
    assert [s["snapshot_id"] for s in listed] == ids[::-1]
    assert [s["trigger"] for s in listed] == ["manual", "daily", "connect"]
    assert all(set(s) == {"snapshot_id", "synced_at", "trigger", "count", "total_value_rs", "total_invested_rs",
                          "priced", "duplicates"} for s in listed)                    # no holdings, no user id

    assert [s["snapshot_id"] for s in asyncio.run(snaps.list_for_account(db, "u1", "ba_z", limit=2))] == ids[:0:-1]
    assert asyncio.run(snaps.list_for_account(db, "u2", "ba_z")) == []                # someone else's account
    assert asyncio.run(snaps.list_for_account(db, "u1", "ba_none")) == []


def test_get_returns_the_full_snapshot_to_its_owner_only():
    db = FakeDB()
    snapshot_id = _record(db)
    snap = asyncio.run(snaps.get_for_owner(db, "u1", snapshot_id))
    assert snap["snapshot_id"] == snapshot_id and [h["ticker"] for h in snap["holdings"]] == ["INFY", "TCS"]
    assert "user_id" not in snap and "_id" not in snap
    assert asyncio.run(snaps.get_for_owner(db, "u2", snapshot_id)) is None
    assert asyncio.run(snaps.get_for_owner(db, "u1", "bsnap_000000000000")) is None


# ── Removal ──────────────────────────────────────────────────────────────
def _three_owners():
    db = FakeDB()
    _record(db, minutes=0)
    _record(db, minutes=1)
    _record(db, account="ba_other", minutes=2)
    _record(db, account="ba_u2", user="u2", minutes=3)
    return db


def test_delete_for_account_removes_only_that_accounts_snapshots():
    db = _three_owners()
    assert asyncio.run(snaps.delete_for_account(db, "u1", "ba_z")) == 2
    assert [s["broker_account_id"] for s in db.broker_sync_snapshots.docs] == ["ba_other", "ba_u2"]
    assert asyncio.run(snaps.delete_for_account(db, "u1", "ba_u2")) == 0              # not this user's account


def test_delete_for_user_removes_only_that_users_snapshots():
    db = _three_owners()
    assert asyncio.run(snaps.delete_for_user(db, "u1")) == 3
    assert [s["user_id"] for s in db.broker_sync_snapshots.docs] == ["u2"]


def test_account_erasure_removes_the_users_snapshots(monkeypatch):
    import routes.compliance as compliance

    db = _three_owners()
    db.holdings = FakeCollection([{"user_id": "u1", "name": "INFY"}, {"user_id": "u2", "name": "TCS"}])
    db.action_plans = FakeCollection([{"user_id": "u1"}])
    db.users = FakeCollection([{"user_id": "u1"}, {"user_id": "u2"}])
    audits = []

    async def current_user(_request):
        return {"user_id": "u1", "email": "one@example.com"}

    async def record(**kw):
        audits.append(kw)
        return "aud_test"

    monkeypatch.setattr(compliance, "db", db)
    monkeypatch.setattr(compliance, "get_current_user", current_user)
    monkeypatch.setattr(compliance.audit, "record", record)
    app = FastAPI()
    app.include_router(compliance.router)

    res = TestClient(app).delete("/api/compliance/account")
    assert res.status_code == 200 and res.json() == {"ok": True, "holdings_deleted": 1, "plans_deleted": 1}
    assert [s["user_id"] for s in db.broker_sync_snapshots.docs] == ["u2"]            # only the erased user's
    assert [h["user_id"] for h in db.holdings.docs] == ["u2"]
    assert db.users.one(user_id="u1")["is_deleted"] is True and audits[0]["action"] == "data_delete"
