"""backend/routes/broker_connect.py — the native (broker-session) branch of /sync, the two live positions
routes, the account list with session state, and the legacy OpenAlgo rows, which can still be listed and
disconnected but no longer synced (the OpenAlgo connect, provisioning and proxy paths were removed 2026-10-24).

The route and `services.brokers.hub_reads` both run for real; only what sits below them is faked — the
Fenix reader, the adapters, the sessions module, `db`, the signed-in user and the audit writer (harness from test_broker_hub_reads.py). Nothing here talks to a real broker.

The test app registers the real `core.error_handlers`, exactly as server.py does, so every error body
asserted here is the envelope a client actually receives. The `broker_hub` flag gate (`feature_gate`) runs
for real too; only its re-read of the persisted flags is stubbed.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from tests.test_broker_hub_reads import (  # noqa: F401  (`sib` is a fixture)
    broker_rows_as_given,  # autouse: rows stored as the broker gave them
    CLIENT_ID, GOLDBEES, INFY, SECRET, ZERO_DUPLICATES, FakeDB, holding_row, hub, hub_position, native_account, sib,
)

import feature_flags as ff  # noqa: E402
import feature_gate  # noqa: E402
import routes.broker_connect as bc  # noqa: E402  (after the harness has ensured the sibling modules exist)
from core.error_handlers import register_error_handlers  # noqa: E402
from services.brokers.base import Position  # noqa: E402

USERS = {"u1": {"user_id": "u1", "email": "one@example.com"},
         "u2": {"user_id": "u2", "email": "two@example.com"}}

EXISTING_ACCOUNT_KEYS = {"account_id", "broker", "broker_display", "label", "openalgo_url", "openalgo_hosted",
                         "api_key_masked", "status", "last_sync_at", "last_sync_count", "last_error", "created_at"}
SESSION_KEYS = {"native", "broker_user_masked", "session_expires_at", "session_ended_reason", "needs_reconnect"}


def openalgo_account(account_id: str, user_id: str = "u1", broker: str = "upstox", **over) -> dict:
    doc = {
        "account_id": account_id, "user_id": user_id, "broker": broker, "label": "My Upstox",
        "openalgo_url": "http://oa.local:5000", "openalgo_hosted": False,
        "api_key_encrypted": "enc(openalgo-key)", "api_key_masked": "oa12••••••9z",
        "status": "active", "created_at": "2026-10-12T04:00:00+00:00", "updated_at": "2026-10-12T04:00:00+00:00",
        "last_sync_at": None, "last_sync_count": 0, "last_error": None,
    }
    doc.update(over)
    return doc


class _Harness:
    def __init__(self, monkeypatch, db):
        self.db, self.audits = db, []
        monkeypatch.setattr(bc, "db", db)

        async def current_user(request: Request):
            who = request.headers.get("X-Test-User")
            if who not in USERS:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return dict(USERS[who])
        monkeypatch.setattr(bc, "get_current_user", current_user)

        async def record(**kw):
            self.audits.append(kw)
            return "aud_test"
        monkeypatch.setattr(bc._audit, "record", record)

        # The flag gate re-reads persisted flags from the database; keep this worker's copy,
        # with `broker_hub` on for everyone (its default) unless a test says otherwise.
        async def flags_fresh(_db, now=None):
            return False
        monkeypatch.setattr(feature_gate, "refresh_if_stale", flags_fresh)
        ff._ensure_defaults()
        monkeypatch.setitem(ff._flags, bc.FLAG, {"mode": "everyone", "allowlist": []})

        app = FastAPI()
        register_error_handlers(app)
        app.include_router(bc.router)
        self.http = TestClient(app)

    def get(self, path, who="u1"):
        return self.http.get(path, headers={"X-Test-User": who})

    def post(self, path, who="u1"):
        return self.http.post(path, headers={"X-Test-User": who})

    def delete(self, path, who="u1"):
        return self.http.delete(path, headers={"X-Test-User": who})


def _db():
    return FakeDB(
        accounts=[
            native_account("ba_z", created_at="2026-10-13T05:00:00+00:00"),
            native_account("ba_i", broker="icicidirect", label="ICICI trading", created_at="2026-10-13T04:00:00+00:00"),
            openalgo_account("ba_oa", created_at="2026-10-12T04:00:00+00:00"),
            native_account("ba_u2", user_id="u2"),
        ],
        holdings=[
            holding_row("CAS-FUND", source="cas", asset_type="mutual_fund"),
            holding_row("OLD-Z", source="broker_native", broker="zerodha", broker_account_id="ba_z"),
            holding_row("OLD-OA", source="openalgo", broker="upstox", broker_account_id="ba_oa"),
            holding_row("U2-ROW", user_id="u2", source="broker_native", broker="zerodha", broker_account_id="ba_u2"),
        ],
    )


@pytest.fixture
def h(monkeypatch, sib):
    return _Harness(monkeypatch, _db())


def _no_secret(*texts):
    for text in texts:
        text = text if isinstance(text, str) else json.dumps(text, default=str)
        assert SECRET not in text and CLIENT_ID not in text and "enc(" not in text


def _utc(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    return parsed


def _error(res, status: int, code: str, message: str | None = None, details: list | None = None) -> dict:
    """Assert the standard error envelope `core.error_handlers` sends, and return it."""
    body = res.json()
    assert {"timestamp", "status", "error", "code", "message", "details", "correlationId", "path"} == set(body)
    assert (res.status_code, body["status"], body["code"]) == (status, status, code)
    if message is not None:
        assert body["message"] == message
    if details is not None:
        assert body["details"] == details
    return body


# ── _public_account / GET /accounts ──────────────────────────────────────
def test_public_account_keeps_every_existing_key_and_adds_session_state(sib):
    for doc in (native_account("ba_z"), openalgo_account("ba_oa")):
        out = bc._public_account(doc)
        assert set(out) == EXISTING_ACCOUNT_KEYS | SESSION_KEYS
        for key in ("account_id", "broker", "label", "status", "last_sync_at", "last_sync_count", "last_error",
                    "created_at", "openalgo_url", "api_key_masked"):
            assert out[key] == doc[key]
        _no_secret(out)
        assert "api_key_encrypted" not in out and "extras_encrypted" not in out

    native = bc._public_account(native_account("ba_z", status="expired", session_ended_reason="logout"))
    assert (native["native"], native["needs_reconnect"], native["session_ended_reason"]) == (True, True, "logout")
    assert (native["status"], native["broker_user_masked"]) == ("expired", "ZX••71")
    oa = bc._public_account(openalgo_account("ba_oa"))
    assert (oa["native"], oa["needs_reconnect"]) == (False, False)


def test_session_fields_can_never_displace_an_existing_key(sib, monkeypatch):
    monkeypatch.setattr(bc._sessions, "public_fields",
                        lambda doc, now=None: {"status": "HIJACKED", "account_id": "x", "needs_reconnect": False})
    out = bc._public_account(native_account("ba_z"))
    assert (out["status"], out["account_id"]) == ("active", "ba_z")


def test_broker_display_comes_from_the_registry_for_native_rows(sib):
    # "icicidirect" is not in the OpenAlgo-only map, so only the adapter registry can name it.
    assert "icicidirect" not in bc.SUPPORTED_BROKERS
    assert bc._public_account(native_account("ba_i", broker="icicidirect"))["broker_display"] == "ICICI Direct"
    assert bc._public_account(native_account("ba_x", broker="nosuchbroker"))["broker_display"] == "nosuchbroker"
    # OpenAlgo rows keep reading the OpenAlgo map.
    sib.adapter("upstox", "REGISTRY NAME")
    assert bc._public_account(openalgo_account("ba_oa"))["broker_display"] == bc.SUPPORTED_BROKERS["upstox"] == "Upstox"


def test_list_accounts_expires_due_sessions_first_and_reports_them(h, sib):
    h.db.broker_accounts.one(account_id="ba_i").update(_due=True)
    res = h.get("/api/broker/accounts")
    assert res.status_code == 200
    assert ("sessions.expire_due_sessions", "u1") in sib.calls              # scoped to the caller
    accounts = res.json()["accounts"]
    assert [a["account_id"] for a in accounts] == ["ba_z", "ba_i", "ba_oa"]  # newest first, never u2's
    by_id = {a["account_id"]: a for a in accounts}
    assert (by_id["ba_i"]["status"], by_id["ba_i"]["needs_reconnect"]) == ("expired", True)
    assert (by_id["ba_z"]["status"], by_id["ba_z"]["needs_reconnect"]) == ("active", False)
    assert all(set(a) == EXISTING_ACCOUNT_KEYS | SESSION_KEYS for a in accounts)
    _no_secret(res.text)


# ── POST /accounts/{id}/sync — native ────────────────────────────────────
def test_the_openalgo_connect_routes_are_gone(h, sib):
    # OA-2: removed on purpose (live execution goes through Kite Connect; OpenAlgo had no caller in the app).
    for name in ("_client_from", "_hosted_base_url", "_persist_broker_holdings", "_instance_mgr", "ConnectRequest"):
        assert not hasattr(bc, name), name
    paths = {getattr(r, "path", None) for r in bc.router.routes}
    assert not paths & {"/api/broker/connect", "/api/broker/connect-hosted", "/api/broker/openalgo-config"}
    before = [dict(a) for a in h.db.broker_accounts.docs]
    assert h.post("/api/broker/connect").status_code in (404, 405)
    assert h.post("/api/broker/connect-hosted").status_code in (404, 405)
    assert h.get("/api/broker/openalgo-config").status_code in (404, 405)
    assert h.db.broker_accounts.docs == before and h.audits == []


def test_native_sync_goes_through_the_hub_and_never_builds_an_openalgo_client(h, sib):
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    assert h.db.broker_accounts.one(account_id="ba_z")["openalgo_url"] == ""
    res = h.post("/api/broker/accounts/ba_z/sync")
    assert res.status_code == 200
    body = res.json()
    # Every key the response had before, plus the snapshot of this sync and its duplicate check.
    assert set(body) == {"ok", "count", "holdings", "snapshot_id", "duplicates"}
    assert body["ok"] is True and body["count"] == 2 and body["duplicates"] == ZERO_DUPLICATES
    assert [set(r) for r in body["holdings"]] == [{"holding_id", "name", "ticker", "asset_type", "quantity"}] * 2
    assert [(r["name"], r["ticker"], r["asset_type"], r["quantity"]) for r in body["holdings"]] == [
        ("Infosys Ltd", "INFY", "equity", 10.0), ("GOLDBEES", "GOLDBEES", "etf", 100.0)]
    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z")]
    (snap,) = h.db.broker_sync_snapshots.docs
    assert (snap["snapshot_id"], snap["trigger"], snap["broker_account_id"], snap["broker"], snap["count"]) == (
        body["snapshot_id"], "manual", "ba_z", "zerodha", 2)

    written = [r for r in h.db.holdings.docs if r.get("broker_account_id") == "ba_z"]
    assert sorted(r["ticker"] for r in written) == ["GOLDBEES", "INFY"]
    # The frontend filters GET /api/portfolio/holdings on these two fields.
    assert all(r["broker"] == "zerodha" and r["broker_account_id"] == "ba_z" and r["user_id"] == "u1"
               and r["source"] == "broker_native" for r in written)
    assert sorted(r["isin"] for r in written) == ["INE009A01021", "INF204KB17I5"]
    assert [(c["broker"], c["live"], len(c["rows"])) for c in sib.reconciled] == [("zerodha", True, 2)]
    # CAS rows, the OpenAlgo account's rows and another user's rows are untouched.
    assert sorted(r["name"] for r in h.db.holdings.docs if r.get("broker_account_id") != "ba_z") == [
        "CAS-FUND", "OLD-OA", "U2-ROW"]

    acct = h.db.broker_accounts.one(account_id="ba_z")
    assert (acct["status"], acct["last_sync_count"], acct["last_error"]) == ("active", 2, None)
    assert h.audits == [{"user_id": "u1", "action": "broker_sync", "resource": "ba_z", "outcome": "success",
                         "ip": "testclient", "ua": "testclient",
                         "details": {"broker": "zerodha", "native": True, "count": 2}}]


def test_native_sync_with_a_rejected_token_is_409_and_ends_the_session(h, sib):
    sib.holdings["ba_z"] = hub.BrokerSessionExpired(f"rejected {SECRET}")
    res = h.post("/api/broker/accounts/ba_z/sync")
    _error(res, 409, "BROKER_SESSION_EXPIRED",
           "Your Zerodha session has ended. Reconnect the account to continue.",
           [{"broker": "zerodha", "account_id": "ba_z"}])
    assert sib.ended == [("ba_z", "broker_rejected")]
    assert h.db.holdings.one(name="OLD-Z")                    # last known holdings stay
    assert h.audits[0]["outcome"] == "error" and h.audits[0]["details"]["code"] == "BROKER_SESSION_EXPIRED"
    _no_secret(res.text, h.audits)

    # The row now needs a reconnect, and the next attempt is refused without calling the broker again.
    again = h.post("/api/broker/accounts/ba_z/sync")
    assert again.status_code == 409 and len(sib.reads()) == 1 and sib.ended == [("ba_z", "broker_rejected")]


def test_native_sync_for_a_broker_with_no_reader_is_400(h, sib):
    sib.adapter("groww", "Groww", implemented=False)
    h.db.broker_accounts.docs.append(native_account("ba_g", broker="groww"))
    res = h.post("/api/broker/accounts/ba_g/sync")
    _error(res, 400, "BROKER_READ_NOT_SUPPORTED", "Reading holdings is not available for Groww.",
           [{"broker": "groww", "account_id": "ba_g"}])
    assert h.audits[0]["outcome"] == "error"


def test_native_sync_broker_failure_is_424_with_no_secret_anywhere(h, sib, caplog):
    sib.holdings["ba_i"] = RuntimeError(f'broker payload {{"token":"{SECRET}","client":"{CLIENT_ID}"}}')
    with caplog.at_level("DEBUG"):
        res = h.post("/api/broker/accounts/ba_i/sync")
    _error(res, 424, "BROKER_READ_FAILED", "Could not read holdings from ICICI Direct. Please try again.",
           [{"broker": "icicidirect", "account_id": "ba_i"}])
    # A 424 is logged by the global handler as a warning with no traceback: the broker's own error must not ride along.
    assert "Client error: Could not read holdings from ICICI Direct" in caplog.text
    acct = h.db.broker_accounts.one(account_id="ba_i")
    assert acct["last_error"] == "Could not read holdings from ICICI Direct. Please try again."
    assert h.audits == [{"user_id": "u1", "action": "broker_sync", "resource": "ba_i", "outcome": "error",
                         "ip": "testclient", "ua": "testclient",
                         "details": {"broker": "icicidirect", "native": True, "code": "BROKER_READ_FAILED",
                                     "reason": "Could not read holdings from ICICI Direct. Please try again."}}]
    _no_secret(res.text, h.audits, acct["last_error"], caplog.text)


def test_sync_of_another_users_account_is_404_and_reads_nothing(h, sib):
    res = h.post("/api/broker/accounts/ba_u2/sync", who="u1")
    _error(res, 404, "RES-001", "Broker account not found")
    assert sib.reads() == [] and h.audits == []
    assert h.db.holdings.one(name="U2-ROW")


# ── POST /accounts/{id}/sync — a legacy OpenAlgo row is refused ─────────
def _hub_must_not_run(h, monkeypatch):
    async def hub_must_not_run(*a, **kw):
        raise AssertionError("an OpenAlgo account must not go through hub_reads")
    monkeypatch.setattr(bc._hub, "sync_account", hub_must_not_run)


def test_an_openalgo_row_cannot_be_synced_and_nothing_is_written(h, sib, monkeypatch):
    # OA-3: the OpenAlgo client path is gone; the row and its earlier holdings stay as they were.
    _hub_must_not_run(h, monkeypatch)
    before = ([dict(r) for r in h.db.holdings.docs], [dict(a) for a in h.db.broker_accounts.docs])
    res = h.post("/api/broker/accounts/ba_oa/sync")
    _error(res, 400, "BROKER_READ_NOT_SUPPORTED",
           "Syncing holdings is available only for accounts connected by signing in on the broker's own page.",
           [{"broker": "upstox", "account_id": "ba_oa"}])
    assert (h.db.holdings.docs, h.db.broker_accounts.docs) == before
    assert h.audits == [] and sib.reads() == [] and sib.cache_invalidations == []


# ── GET /accounts/{id}/positions ─────────────────────────────────────────
def _book(kind="net"):
    return [
        hub_position("NIFTY26OCTFUT", kind=kind),                                                    # F&O, carried
        hub_position("BANKNIFTY26OCT52000CE", kind=kind, product="intraday", product_raw="MIS",
                     is_intraday=True, instrument_type="CE", strike=52000.0, name=None),              # F&O, intraday
        hub_position("INFY", kind=kind, exchange="NSE", segment="equity", product="intraday", product_raw="MIS",
                     is_intraday=True, instrument_type=None, expiry=None, name="Infosys Ltd"),         # equity, intraday
        hub_position("CRUDEOIL26NOVFUT", kind=kind, exchange="MCX", segment="commodity", name=None),  # neither
    ]


def test_positions_default_to_net_and_all(h, sib):
    sib.positions["ba_z"] = _book
    before = datetime.now(timezone.utc)
    res = h.get("/api/broker/accounts/ba_z/positions")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"account_id", "broker", "kind", "segment", "as_of", "positions", "counts"}
    assert (body["account_id"], body["broker"], body["kind"], body["segment"]) == ("ba_z", "zerodha", "net", "all")
    assert before <= _utc(body["as_of"]) <= datetime.now(timezone.utc)
    assert [p["symbol"] for p in body["positions"]] == [
        "NIFTY26OCTFUT", "BANKNIFTY26OCT52000CE", "INFY", "CRUDEOIL26NOVFUT"]
    assert body["counts"] == {"total": 4, "fno": 2, "intraday": 2}
    assert {"symbol", "exchange", "quantity", "avg_price", "last_price", "pnl", "product", "product_raw", "segment",
            "is_intraday", "instrument_type", "expiry", "strike", "kind", "name"} <= set(body["positions"][0])
    assert [p["name"] for p in body["positions"]] == ["Nifty 50 Oct Fut", None, "Infosys Ltd", None]
    assert sib.reads() == [("fenix.read_positions", "zerodha", "ba_z", "net")]
    _no_secret(res.text)


@pytest.mark.parametrize("segment,symbols", [
    ("all", ["NIFTY26OCTFUT", "BANKNIFTY26OCT52000CE", "INFY", "CRUDEOIL26NOVFUT"]),
    ("fno", ["NIFTY26OCTFUT", "BANKNIFTY26OCT52000CE"]),
    ("intraday", ["BANKNIFTY26OCT52000CE", "INFY"]),
])
def test_segment_narrows_positions_but_counts_describe_the_whole_read(h, sib, segment, symbols):
    sib.positions["ba_z"] = _book
    body = h.get(f"/api/broker/accounts/ba_z/positions?segment={segment}").json()
    assert body["segment"] == segment
    assert [p["symbol"] for p in body["positions"]] == symbols
    assert body["counts"] == {"total": 4, "fno": 2, "intraday": 2}


def test_day_positions_ask_the_reader_for_the_day_book(h, sib):
    sib.positions["ba_z"] = _book
    body = h.get("/api/broker/accounts/ba_z/positions?kind=day&segment=fno").json()
    assert sib.reads() == [("fenix.read_positions", "zerodha", "ba_z", "day")]
    assert body["kind"] == "day" and {p["kind"] for p in body["positions"]} == {"day"}


def test_net_positions_through_an_adapter_only_broker(h, sib):
    sib.positions["ba_i"] = [
        Position(symbol="NIFTY26OCT25000PE", exchange="NFO", quantity=75, avg_price=90.0, pnl=300.0, product="NRML"),
        Position(symbol="TCS", exchange="NSE", quantity=4, avg_price=4100.0, pnl=-20.0, product="MIS")]
    body = h.get("/api/broker/accounts/ba_i/positions").json()
    assert body["counts"] == {"total": 2, "fno": 1, "intraday": 1}
    assert [(p["symbol"], p["segment"], p["is_intraday"], p["kind"], p["last_price"], p["name"])
            for p in body["positions"]] == [("NIFTY26OCT25000PE", "fno", False, "net", None, None),
                                            ("TCS", "equity", True, "net", None, None)]


def test_day_positions_from_a_net_only_adapter_are_400_not_relabelled_net_rows(h, sib):
    sib.positions["ba_i"] = [Position(symbol="TCS", exchange="NSE", quantity=4, avg_price=4100.0, product="MIS")]
    res = h.get("/api/broker/accounts/ba_i/positions?kind=day")
    _error(res, 400, "BROKER_READ_NOT_SUPPORTED", "Reading day positions is not available for ICICI Direct.",
           [{"broker": "icicidirect", "account_id": "ba_i"}])
    assert sib.reads() == []


def test_positions_with_an_ended_session_are_409_without_a_broker_call(h, sib):
    h.db.broker_accounts.one(account_id="ba_z").update(status="expired", session_ended_reason="expired")
    res = h.get("/api/broker/accounts/ba_z/positions")
    _error(res, 409, "BROKER_SESSION_EXPIRED",
           "Your Zerodha session has ended. Reconnect the account to continue.",
           [{"broker": "zerodha", "account_id": "ba_z"}])
    assert sib.reads() == [] and sib.ended == []


def test_positions_with_a_rejected_token_are_409_and_end_the_session(h, sib):
    sib.positions["ba_z"] = hub.BrokerSessionExpired(f"rejected {SECRET}")
    res = h.get("/api/broker/accounts/ba_z/positions")
    _error(res, 409, "BROKER_SESSION_EXPIRED", details=[{"broker": "zerodha", "account_id": "ba_z"}])
    assert sib.ended == [("ba_z", "broker_rejected")]
    assert h.db.broker_accounts.one(account_id="ba_z")["status"] == "expired"
    _no_secret(res.text)


def test_positions_broker_failure_is_424_with_no_secret_in_the_body(h, sib, caplog):
    sib.positions["ba_z"] = hub.BrokerReadError(f'upstream 500 {{"token":"{SECRET}"}}')
    with caplog.at_level("DEBUG"):
        res = h.get("/api/broker/accounts/ba_z/positions")
    _error(res, 424, "BROKER_READ_FAILED", "Could not read net positions from Zerodha. Please try again.",
           [{"broker": "zerodha", "account_id": "ba_z"}])
    assert "Client error: Could not read net positions from Zerodha" in caplog.text
    assert h.db.broker_accounts.one(account_id="ba_z")["status"] == "active" and sib.ended == []
    _no_secret(res.text, caplog.text)


def test_an_unexpected_failure_while_reading_positions_is_also_424(h, sib, caplog):
    sib.positions["ba_z"] = ZeroDivisionError(f"bug with {SECRET}")
    with caplog.at_level("DEBUG"):
        res = h.get("/api/broker/accounts/ba_z/positions")
    _error(res, 424, "BROKER_READ_FAILED", "Could not read net positions from Zerodha. Please try again.")
    _no_secret(res.text, caplog.text)


def test_positions_for_an_openalgo_account_are_400(h, sib):
    res = h.get("/api/broker/accounts/ba_oa/positions")
    _error(res, 400, "BROKER_READ_NOT_SUPPORTED",
           "Live positions are available only for accounts connected by signing in on the broker's own page.",
           [{"broker": "upstox", "account_id": "ba_oa"}])
    assert sib.calls == []                          # the stored OpenAlgo key is never loaded as a broker token


def test_positions_of_another_users_account_are_404(h, sib):
    res = h.get("/api/broker/accounts/ba_u2/positions", who="u1")
    _error(res, 404, "RES-001", "Broker account not found")
    assert sib.calls == []
    assert h.get("/api/broker/accounts/ba_nope/positions").status_code == 404


@pytest.mark.parametrize("query", ["kind=weekly", "segment=options", "kind=", "segment=FNO"])
def test_positions_reject_unknown_kind_or_segment(h, sib, query):
    assert h.get(f"/api/broker/accounts/ba_z/positions?{query}").status_code == 422
    assert h.get(f"/api/broker/positions?{query}").status_code == 422
    assert sib.reads() == []


def test_positions_require_a_signed_in_user(h, sib):
    assert h.http.get("/api/broker/accounts/ba_z/positions").status_code == 401
    assert h.http.get("/api/broker/positions").status_code == 401


# ── GET /positions (all accounts) ────────────────────────────────────────
def test_all_accounts_positions_report_each_account_on_its_own(h, sib):
    h.db.broker_accounts.docs.extend([
        native_account("ba_fail", broker="icicidirect", label="Failing", created_at="2026-10-13T03:00:00+00:00"),
        native_account("ba_ended", label="Ended", status="expired", created_at="2026-10-13T02:00:00+00:00"),
    ])
    sib.positions["ba_z"] = _book
    sib.positions["ba_i"] = [Position(symbol="TCS", exchange="NSE", quantity=4, avg_price=4100.0, product="MIS")]
    sib.positions["ba_fail"] = RuntimeError(f"broker exploded {SECRET}")
    sib.positions["ba_u2"] = [hub_position("SHOULD-NOT-APPEAR")]

    before = datetime.now(timezone.utc)
    res = h.get("/api/broker/positions?segment=fno")
    assert res.status_code == 200                               # one account failing does not fail the request
    body = res.json()
    assert set(body) == {"as_of", "kind", "segment", "accounts"}
    assert (body["kind"], body["segment"]) == ("net", "fno")

    accounts = body["accounts"]
    # Every account of the user (the OpenAlgo one is listed as not readable), never u2's.
    assert [a["account_id"] for a in accounts] == ["ba_z", "ba_i", "ba_fail", "ba_ended", "ba_oa"]
    assert all(set(a) == {"account_id", "broker", "broker_display", "label", "ok", "error", "as_of", "positions",
                          "counts"} for a in accounts)
    z, i, fail, ended, oa = accounts
    assert (oa["ok"], oa["positions"], oa["error"]["code"]) == (False, [], "BROKER_READ_NOT_SUPPORTED")

    assert (z["ok"], z["error"], z["broker"], z["label"]) == (True, None, "zerodha", "Zerodha")
    assert [p["symbol"] for p in z["positions"]] == ["NIFTY26OCTFUT", "BANKNIFTY26OCT52000CE"]
    assert z["counts"] == {"total": 4, "fno": 2, "intraday": 2}

    assert (i["ok"], i["positions"], i["counts"]) == (True, [], {"total": 1, "fno": 0, "intraday": 1})

    assert (fail["ok"], fail["positions"], fail["counts"]) == (False, [], {"total": 0, "fno": 0, "intraday": 0})
    assert fail["error"] == {"code": "BROKER_READ_FAILED",
                             "message": "Could not read net positions from ICICI Direct. Please try again."}

    # Needs a reconnect: listed, not dropped — and the broker is not called for it.
    assert (ended["ok"], ended["label"], ended["positions"]) == (False, "Ended", [])
    assert ended["error"] == {"code": "BROKER_SESSION_EXPIRED",
                              "message": "Your Zerodha session has ended. Reconnect the account to continue."}
    assert {c[2] for c in sib.reads()} == {"ba_z", "ba_i", "ba_fail"}

    # Every entry says when that account was read; the response says when it was assembled.
    stamps = [_utc(a["as_of"]) for a in accounts]
    assert all(before <= s <= _utc(body["as_of"]) for s in stamps)
    _no_secret(res.text)


def test_all_accounts_positions_end_a_session_the_broker_rejects(h, sib):
    sib.positions["ba_z"] = hub.BrokerSessionExpired("rejected")
    body = h.get("/api/broker/positions?kind=day").json()
    by_id = {a["account_id"]: a for a in body["accounts"]}
    assert by_id["ba_z"]["error"]["code"] == "BROKER_SESSION_EXPIRED" and sib.ended == [("ba_z", "broker_rejected")]
    # The adapter-only broker cannot serve the day book: reported per account, not as net rows.
    assert by_id["ba_i"]["ok"] is False and by_id["ba_i"]["error"]["code"] == "BROKER_READ_NOT_SUPPORTED"
    assert body["kind"] == "day"


def test_all_accounts_positions_with_no_native_account(h, sib):
    body = h.get("/api/broker/positions", who="u2").json()
    assert [a["account_id"] for a in body["accounts"]] == ["ba_u2"]
    h.db.broker_accounts.docs = [d for d in h.db.broker_accounts.docs if d["account_id"] != "ba_u2"]
    empty = h.get("/api/broker/positions", who="u2")
    assert empty.status_code == 200 and empty.json()["accounts"] == []


# ── DELETE /accounts/{id} — native rows ──────────────────────────────────
def test_disconnecting_a_native_account_removes_only_its_row_and_holdings(h, sib):
    res = h.delete("/api/broker/accounts/ba_z")
    assert res.status_code == 200 and res.json() == {"ok": True}
    assert [a["account_id"] for a in h.db.broker_accounts.docs] == ["ba_i", "ba_oa", "ba_u2"]
    assert sorted(r["name"] for r in h.db.holdings.docs) == ["CAS-FUND", "OLD-OA", "U2-ROW"]
    assert h.audits[0]["action"] == "broker_disconnect" and h.audits[0]["details"] == {"broker": "zerodha"}
    assert h.delete("/api/broker/accounts/ba_u2", who="u1").status_code == 404


def test_disconnecting_an_account_removes_its_sync_snapshots_too(h, sib):
    mine = _seed_snapshots(h.db, "ba_z", n=3)
    other = _seed_snapshots(h.db, "ba_i", n=2, broker="icicidirect")
    theirs = _seed_snapshots(h.db, "ba_u2", user="u2", n=1)

    assert h.delete("/api/broker/accounts/ba_z").json() == {"ok": True}
    assert [s["snapshot_id"] for s in h.db.broker_sync_snapshots.docs] == other + theirs
    _error(h.get(f"/api/broker/snapshots/{mine[0]}"), 404, "RES-001", "Broker sync snapshot not found")
    _error(h.get("/api/broker/accounts/ba_z/snapshots"), 404, "RES-001", "Broker account not found")


# ── POST /accounts/{id}/sync — the duplicate check and the snapshot ───────
def test_sync_response_shows_what_the_duplicate_check_found(h, sib):
    h.db.holdings.docs.append(holding_row("Z2-INFY", source="broker_native", broker="zerodha",
                                          broker_account_id="ba_z2", ticker="INFY", isin="INE009A01021"))
    sib.reconcile_result = {"statement_rows_removed": 4, "export_rows_removed": 3}
    sib.holdings["ba_z"] = [INFY, INFY, GOLDBEES, dataclasses.replace(GOLDBEES, quantity=40)]
    body = h.post("/api/broker/accounts/ba_z/sync").json()

    assert body["duplicates"] == {"repeated_in_broker_reply": 1, "same_instrument_lines": 1,
                                  "broker_file_rows_replaced": 3, "statement_rows_replaced": 4,
                                  "also_in_other_accounts": 1}
    assert body["count"] == 3 and [r["ticker"] for r in body["holdings"]] == ["INFY", "GOLDBEES", "GOLDBEES"]
    assert h.db.holdings.one(name="Z2-INFY")                   # the other login's row is only counted
    snap = h.db.broker_sync_snapshots.one(snapshot_id=body["snapshot_id"])
    assert snap["duplicates"] == body["duplicates"] and snap["count"] == 3


def test_sync_still_succeeds_with_a_null_snapshot_id_when_the_snapshot_cannot_be_written(h, sib, monkeypatch):
    async def write_fails(_doc):
        raise RuntimeError(f"mongo write failed {SECRET}")
    monkeypatch.setattr(h.db.broker_sync_snapshots, "insert_one", write_fails)
    sib.holdings["ba_z"] = [INFY]
    res = h.post("/api/broker/accounts/ba_z/sync")

    assert res.status_code == 200
    body = res.json()
    assert body["snapshot_id"] is None and body["ok"] is True and body["count"] == 1
    assert body["duplicates"] == ZERO_DUPLICATES
    assert h.db.holdings.one(ticker="INFY")["broker_account_id"] == "ba_z"
    assert h.audits[0]["outcome"] == "success"
    _no_secret(res.text)


# ── GET /accounts/{id}/snapshots · GET /snapshots/{id} ───────────────────
SNAPSHOT_SUMMARY_KEYS = {"snapshot_id", "synced_at", "trigger", "count", "total_value_rs", "total_invested_rs",
                         "priced", "duplicates"}


def _seed_snapshots(db, account, n, user="u1", broker="zerodha", trigger="daily"):
    """`n` snapshots of one account, a minute apart; returns their ids oldest first."""
    rows = [{"name": "Infosys Ltd", "ticker": "INFY", "isin": "INE009A01021", "asset_type": "equity",
             "quantity": 10.0, "buy_price": 1400.5, "current_price": 1525.0, "sector": "IT", "source_id": "NSE:INFY",
             "holding_id": "hold_x", "user_id": user}]
    return [
        asyncio.run(bc._snapshots.record(
            db, native_account(account, user_id=user, broker=broker), rows, trigger=trigger,
            duplicates=ZERO_DUPLICATES, synced_at=f"2026-10-14T04:{i:02d}:00+00:00", broker_display=broker.title()))
        for i in range(n)
    ]


def test_snapshots_of_an_account_are_listed_newest_first_without_their_holdings(h, sib):
    ids = _seed_snapshots(h.db, "ba_z", n=3)
    _seed_snapshots(h.db, "ba_i", n=2, broker="icicidirect")
    _seed_snapshots(h.db, "ba_u2", n=1, user="u2")

    res = h.get("/api/broker/accounts/ba_z/snapshots")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"account_id", "broker", "snapshots"}
    assert (body["account_id"], body["broker"]) == ("ba_z", "zerodha")
    assert [s["snapshot_id"] for s in body["snapshots"]] == ids[::-1]
    assert all(set(s) == SNAPSHOT_SUMMARY_KEYS for s in body["snapshots"])           # no holdings, no user id
    assert body["snapshots"][0] == {
        "snapshot_id": ids[2], "synced_at": "2026-10-14T04:02:00+00:00", "trigger": "daily", "count": 1,
        "total_value_rs": 15250.0, "total_invested_rs": 14005.0, "priced": 1, "duplicates": ZERO_DUPLICATES}
    _no_secret(res.text)


def test_a_sync_shows_up_in_the_accounts_snapshot_list(h, sib):
    sib.holdings["ba_i"] = [INFY, GOLDBEES]
    synced = h.post("/api/broker/accounts/ba_i/sync").json()
    listed = h.get("/api/broker/accounts/ba_i/snapshots").json()
    assert (listed["broker"], [s["snapshot_id"] for s in listed["snapshots"]]) == ("icicidirect", [synced["snapshot_id"]])
    assert (listed["snapshots"][0]["trigger"], listed["snapshots"][0]["count"]) == ("manual", 2)


def test_snapshot_list_limit_defaults_to_30_and_is_bounded_at_90(h, sib):
    ids = _seed_snapshots(h.db, "ba_z", n=35)
    assert [s["snapshot_id"] for s in h.get("/api/broker/accounts/ba_z/snapshots").json()["snapshots"]] == ids[:4:-1]
    assert len(h.get("/api/broker/accounts/ba_z/snapshots?limit=1").json()["snapshots"]) == 1
    assert len(h.get("/api/broker/accounts/ba_z/snapshots?limit=90").json()["snapshots"]) == 35
    for bad in ("0", "91", "-1", "many"):
        assert h.get(f"/api/broker/accounts/ba_z/snapshots?limit={bad}").status_code == 422


def test_snapshot_list_is_for_the_owner_of_the_account(h, sib):
    _seed_snapshots(h.db, "ba_u2", n=2, user="u2")
    _error(h.get("/api/broker/accounts/ba_u2/snapshots", who="u1"), 404, "RES-001", "Broker account not found")
    _error(h.get("/api/broker/accounts/ba_nope/snapshots"), 404, "RES-001", "Broker account not found")
    assert h.http.get("/api/broker/accounts/ba_z/snapshots").status_code == 401
    assert len(h.get("/api/broker/accounts/ba_u2/snapshots", who="u2").json()["snapshots"]) == 2
    # An OpenAlgo account is never snapshotted: an empty history, not an error.
    assert h.get("/api/broker/accounts/ba_oa/snapshots").json() == {
        "account_id": "ba_oa", "broker": "upstox", "snapshots": []}


def test_one_snapshot_is_returned_in_full_to_its_owner_only(h, sib):
    (mine,) = _seed_snapshots(h.db, "ba_z", n=1, trigger="connect")
    (theirs,) = _seed_snapshots(h.db, "ba_u2", n=1, user="u2")

    res = h.get(f"/api/broker/snapshots/{mine}")
    assert res.status_code == 200
    snap = res.json()
    assert set(snap) == SNAPSHOT_SUMMARY_KEYS | {"broker_account_id", "broker", "broker_display",
                                                  "broker_user_masked", "holdings"}
    assert (snap["snapshot_id"], snap["broker_account_id"], snap["broker"], snap["broker_display"],
            snap["broker_user_masked"], snap["trigger"]) == (mine, "ba_z", "zerodha", "Zerodha", "••••71", "connect")
    assert snap["holdings"] == [{"name": "Infosys Ltd", "ticker": "INFY", "isin": "INE009A01021",
                                 "asset_type": "equity", "quantity": 10.0, "buy_price": 1400.5,
                                 "current_price": 1525.0, "sector": "IT", "source_id": "NSE:INFY"}]
    _no_secret(res.text)

    _error(h.get(f"/api/broker/snapshots/{theirs}", who="u1"), 404, "RES-001", "Broker sync snapshot not found")
    _error(h.get("/api/broker/snapshots/bsnap_000000000000"), 404, "RES-001", "Broker sync snapshot not found")
    assert h.http.get(f"/api/broker/snapshots/{mine}").status_code == 401
    assert h.get(f"/api/broker/snapshots/{theirs}", who="u2").status_code == 200


@pytest.mark.parametrize("state", ["flag_off", "flag_unreadable"])
def test_reading_snapshots_does_not_depend_on_the_flag(h, sib, request, state):
    (mine,) = _seed_snapshots(h.db, "ba_z", n=1)
    request.getfixturevalue(state)                  # off, or unreadable: a gated route would answer 403 / 503
    listed = h.get("/api/broker/accounts/ba_z/snapshots")
    assert listed.status_code == 200 and [s["snapshot_id"] for s in listed.json()["snapshots"]] == [mine]
    assert h.get(f"/api/broker/snapshots/{mine}").json()["snapshot_id"] == mine


# ── broker_hub feature flag ──────────────────────────────────────────────
GATED = [("post", "/api/broker/accounts/ba_z/sync"),
         ("get", "/api/broker/accounts/ba_z/positions"),
         ("get", "/api/broker/positions")]


@pytest.fixture
def flag_off(h, monkeypatch):
    monkeypatch.setitem(ff._flags, bc.FLAG, {"mode": "off", "allowlist": []})


@pytest.fixture
def flag_unreadable(h, monkeypatch):
    async def unreadable(_db, now=None):
        raise RuntimeError("mongo unavailable")
    monkeypatch.setattr(feature_gate, "refresh_if_stale", unreadable)


def test_the_gate_uses_the_broker_hub_flag_which_is_on_for_everyone_by_default():
    assert bc.FLAG == "broker_hub" and ff.KNOWN_FEATURES[bc.FLAG]["default_mode"] == "everyone"


@pytest.mark.parametrize("method,path", GATED)
def test_native_reads_are_refused_when_the_flag_is_off(h, sib, flag_off, method, path):
    sib.holdings["ba_z"], sib.positions["ba_z"] = [INFY], _book
    before = ([dict(r) for r in h.db.holdings.docs], [dict(a) for a in h.db.broker_accounts.docs])
    res = getattr(h, method)(path)
    _error(res, 403, "AUTHZ-001", "feature_not_enabled", [])
    assert sib.calls == []                          # no token loaded, no broker read, nothing reconciled
    assert (h.db.holdings.docs, h.db.broker_accounts.docs) == before and h.audits == []


@pytest.mark.parametrize("method,path", GATED)
def test_native_reads_fail_closed_when_the_flag_state_cannot_be_read(h, sib, flag_unreadable, method, path):
    sib.holdings["ba_z"], sib.positions["ba_z"] = [INFY], _book
    res = getattr(h, method)(path)
    _error(res, 503, "INT-001", "feature_state_unavailable", [])
    assert sib.calls == [] and h.audits == []


def test_the_flag_allowlist_is_checked_per_user(h, sib, monkeypatch):
    monkeypatch.setitem(ff._flags, bc.FLAG, {"mode": "allowlist", "allowlist": ["one@example.com"]})
    assert h.get("/api/broker/positions", who="u1").status_code == 200
    _error(h.get("/api/broker/positions", who="u2"), 403, "AUTHZ-001", "feature_not_enabled")


def test_the_flag_is_checked_after_ownership_on_sync(h, sib, flag_off):
    # Someone else's account stays a 404 — the gate must not reveal that it exists.
    _error(h.post("/api/broker/accounts/ba_u2/sync", who="u1"), 404, "RES-001", "Broker account not found")


@pytest.mark.parametrize("state", ["flag_off", "flag_unreadable"])
def test_list_delete_and_the_openalgo_refusal_do_not_depend_on_the_flag(h, sib, monkeypatch, request, state):
    request.getfixturevalue(state)                  # off, or unreadable: a route that consulted it would 403 / 503
    listed = h.get("/api/broker/accounts")
    assert listed.status_code == 200
    assert [a["account_id"] for a in listed.json()["accounts"]] == ["ba_z", "ba_i", "ba_oa"]

    # OA-7: an OpenAlgo row is refused the same way whatever the flag says.
    _hub_must_not_run(h, monkeypatch)
    _error(h.post("/api/broker/accounts/ba_oa/sync"), 400, "BROKER_READ_NOT_SUPPORTED")

    assert h.delete("/api/broker/accounts/ba_z").json() == {"ok": True}     # a native row can still be removed
    assert h.delete("/api/broker/accounts/ba_oa").json() == {"ok": True}
    assert [a["account_id"] for a in h.db.broker_accounts.docs] == ["ba_i", "ba_u2"]
    assert h.get("/api/broker/supported").status_code == 200
    assert sib.reads() == []


def test_a_failed_broker_read_is_never_answered_as_a_5xx(h, sib):
    """Cloudflare fronts staging and production and replaces an origin 502 with its own page, which has no CORS headers: the
    browser then drops the answer and the screen said "The request didn't reach the server" (owner, 31 Oct, when ICICI Direct's
    /dematholdings answered API status 500 and every sync failed). The failure must reach the screen as a 4xx with its code."""
    sib.holdings["ba_i"] = RuntimeError("the broker said no")
    res = h.post("/api/broker/accounts/ba_i/sync")
    assert res.status_code == 424 and res.json()["code"] == "BROKER_READ_FAILED"
