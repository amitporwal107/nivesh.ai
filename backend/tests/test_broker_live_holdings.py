"""Live broker holdings — `hub_reads.read_account_holdings` / `holdings_totals` and the two routes
GET /api/broker/accounts/{id}/holdings and GET /api/broker/holdings, plus what the all-accounts positions
route now says for an OpenAlgo account.

No broker, no Mongo: every broker read is a fake Fenix reader or a fake adapter and `db` is an in-memory
fake (harness from test_broker_hub_reads.py and test_broker_connect_native_routes.py). Nothing in this file
talks to a real broker.

A live read stores nothing: every test that reads asserts that `db.holdings` was not written, and that the
account row was written only when the broker refused the session (the session is then ended).
"""
from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timezone

import pytest

from tests.test_broker_hub_reads import (  # noqa: F401  (`sib`, `broker_rows_as_given` are fixtures)
    CLIENT_ID, GOLDBEES, INFY, REAL_MASTERDATA_FILL, SECRET, FakeDB, broker_rows_as_given, holding_row, hub,
    hub_position, native_account, sib,
)
from tests.test_broker_connect_native_routes import (  # noqa: F401  (`h`, `flag_off`, `flag_unreadable` are fixtures)
    _error, _no_secret, _utc, flag_off, flag_unreadable, h,
)

import routes.broker_connect as bc  # noqa: E402

ROW_KEYS = {"isin", "symbol", "name", "exchange", "asset_type", "sector", "quantity", "avg_price", "current_price",
            "price_source", "invested_rs", "value_rs", "pnl_rs", "pnl_pct", "source_id"}
TOTAL_KEYS = {"invested_rs", "value_rs", "pnl_rs", "pnl_pct"}
WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
          "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write")


def watch_writes(monkeypatch, collection) -> list:
    """Record every write method called on a fake collection (the call still goes through)."""
    calls: list = []
    for name in WRITES:
        original = getattr(collection, name, None)

        def recorder(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            if _original is None:
                raise AssertionError(f"{_name} called on a collection that has no such method")
            return _original(*args, **kwargs)
        monkeypatch.setattr(collection, name, recorder, raising=False)
    return calls


def _read(db, account_id):
    return asyncio.run(hub.read_account_holdings(db, db.broker_accounts.one(account_id=account_id)))


# ── hub_reads.read_account_holdings ──────────────────────────────────────
def test_live_rows_carry_the_brokers_figures_and_value_cost_and_pnl_worked_out_from_them(sib, monkeypatch):
    db = FakeDB([native_account("ba_z")], holdings=[holding_row("OLD-Z", source="broker_native", broker_account_id="ba_z")])
    holding_writes = watch_writes(monkeypatch, db.holdings)
    account_writes = watch_writes(monkeypatch, db.broker_accounts)
    sib.holdings["ba_z"] = [INFY, GOLDBEES]

    rows = _read(db, "ba_z")

    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z")]
    assert all(set(r) == ROW_KEYS for r in rows)
    infy, bees = rows
    # INFY: 10 × 1,400.50 = 14,005 invested; 10 × 1,525 = 15,250 value; +1,245; 1,245 / 14,005 = +8.89%
    assert infy == {
        "isin": "INE009A01021", "symbol": "INFY", "name": "Infosys Ltd", "exchange": "NSE", "asset_type": "equity",
        "sector": "IT", "quantity": 10.0, "avg_price": 1400.5, "current_price": 1525.0, "price_source": "broker",
        "invested_rs": 14005.0, "value_rs": 15250.0, "pnl_rs": 1245.0, "pnl_pct": 8.89, "source_id": "NSE:INFY"}
    # GOLDBEES: 100 × 52 = 5,200; 100 × 61.25 = 6,125; +925; +17.79%. Gaps the broker left get the sync's defaults.
    assert (bees["name"], bees["sector"], bees["source_id"], bees["asset_type"]) == ("GOLDBEES", "Other", None, "etf")
    assert (bees["invested_rs"], bees["value_rs"], bees["pnl_rs"], bees["pnl_pct"]) == (5200.0, 6125.0, 925.0, 17.79)

    # Read, never stored: the stored rows and the account row are untouched.
    assert holding_writes == [] and account_writes == []
    assert [r["holding_id"] for r in db.holdings.docs] == ["hold_OLD-Z"]
    assert db.broker_sync_snapshots.docs == [] and sib.cache_invalidations == [] and sib.reconciled == []


def test_a_missing_price_or_average_is_null_never_zero(sib):
    db = FakeDB([native_account("ba_z")])
    sib.holdings["ba_z"] = [
        dataclasses.replace(INFY, current_price=0.0),                                     # Groww sends no price
        dataclasses.replace(INFY, symbol="TCS", isin="INE467B01029", current_price=None),
        dataclasses.replace(INFY, symbol="HDFC", isin="INE040A01034", avg_price=0.0),     # no average
    ]
    infy, tcs, hdfc = _read(db, "ba_z")
    for row in (infy, tcs):
        assert (row["current_price"], row["price_source"], row["value_rs"], row["pnl_rs"], row["pnl_pct"]) == (
            None, None, None, None, None)
        assert (row["avg_price"], row["invested_rs"]) == (1400.5, 14005.0)     # what is known is still given
    assert (hdfc["avg_price"], hdfc["invested_rs"], hdfc["pnl_rs"], hdfc["pnl_pct"]) == (None, None, None, None)
    assert (hdfc["current_price"], hdfc["value_rs"]) == (1525.0, 15250.0)


def test_the_lines_are_the_ones_a_sync_would_store(sib):
    # ICICI lists sold-out instruments with every quantity at zero; a line sent twice is one holding; a second
    # lot of the same instrument at another cost is a real line and stays.
    db = FakeDB([native_account("ba_z")])
    sib.holdings["ba_z"] = [
        INFY, INFY,
        dataclasses.replace(INFY, quantity=5, avg_price=1300.0),
        dataclasses.replace(GOLDBEES, quantity=0.0),
        dataclasses.replace(INFY, symbol="TCS", isin="INE467B01029", quantity=None),
    ]
    rows = _read(db, "ba_z")
    assert [(r["symbol"], r["quantity"], r["avg_price"]) for r in rows] == [("INFY", 10.0, 1400.5), ("INFY", 5.0, 1300.0)]

    # The same reply through a sync stores the same lines.
    sync_db = FakeDB([native_account("ba_z")])
    asyncio.run(hub.sync_account(sync_db, sync_db.broker_accounts.one(account_id="ba_z")))
    stored = [(r["ticker"], r["quantity"], r["buy_price"]) for r in sync_db.holdings.docs]
    assert stored == [(r["symbol"], r["quantity"], r["avg_price"]) for r in rows]


def test_masterdata_fills_the_name_sector_and_a_missing_price_exactly_as_the_sync_does(sib, monkeypatch):
    from services import masterdata
    monkeypatch.setattr(hub, "_fill_from_masterdata", REAL_MASTERDATA_FILL)
    monkeypatch.setattr(masterdata, "lookup_isin", lambda isin: (
        {"name": "INFOSYS LIMITED", "price": 1500.0, "source": "nse"} if isin == "INE009A01021" else None))
    db = FakeDB([native_account("ba_z")])
    sib.holdings["ba_z"] = [
        dataclasses.replace(INFY, name="INFTEC", symbol="INFTEC", current_price=0.0, sector=None),   # ICICI-style
        dataclasses.replace(INFY, symbol="INFY2", source_id="NSE:INFY2", quantity=3),                  # broker price
        dataclasses.replace(INFY, symbol="NOMASTER", isin="INE000000000", current_price=0.0, source_id="NSE:NOMASTER"),
    ]
    filled, kept, unknown = _read(db, "ba_z")

    # The broker's own code becomes the company name; the stored close fills the price, and says so.
    assert (filled["name"], filled["current_price"], filled["price_source"]) == ("INFOSYS LIMITED", 1500.0, "masterdata")
    assert (filled["symbol"], filled["quantity"], filled["avg_price"], filled["isin"]) == ("INFTEC", 10.0, 1400.5, "INE009A01021")
    assert filled["sector"] not in (None, "")                       # classified, as the sync classifies it
    assert (filled["value_rs"], filled["pnl_rs"], filled["pnl_pct"]) == (15000.0, 995.0, 7.1)
    # A price the broker gave is never replaced.
    assert (kept["name"], kept["current_price"], kept["price_source"]) == ("Infosys Ltd", 1525.0, "broker")
    # Nothing anywhere: no price, and no figure that needs one.
    assert (unknown["current_price"], unknown["price_source"], unknown["value_rs"]) == (None, None, None)

    # The sync, given the same reply, stores the same name and price.
    sync_db = FakeDB([native_account("ba_z")])
    asyncio.run(hub.sync_account(sync_db, sync_db.broker_accounts.one(account_id="ba_z")))
    row = sync_db.holdings.one(ticker="INFTEC")
    assert (row["name"], row["current_price"], row["sector"]) == (filled["name"], filled["current_price"], filled["sector"])


def test_a_rejected_session_is_ended_and_nothing_else_is_written(sib, monkeypatch):
    db = FakeDB([native_account("ba_z")], holdings=[holding_row("OLD-Z", source="broker_native", broker_account_id="ba_z")])
    holding_writes = watch_writes(monkeypatch, db.holdings)
    sib.holdings["ba_z"] = hub.BrokerSessionExpired("token rejected")
    with pytest.raises(hub.BrokerSessionExpired):
        _read(db, "ba_z")
    assert sib.ended == [("ba_z", "broker_rejected")]
    assert db.broker_accounts.one(account_id="ba_z")["status"] == "expired"
    assert holding_writes == [] and db.holdings.one(name="OLD-Z")       # the stored rows stay for the fallback


def test_an_ended_session_is_not_read_and_not_ended_again(sib):
    db = FakeDB([native_account("ba_z", status="expired", session_ended_reason="logout")])
    with pytest.raises(hub.sessions.SessionEnded):
        _read(db, "ba_z")
    assert sib.reads() == [] and sib.ended == []
    assert db.broker_accounts.one(account_id="ba_z")["session_ended_reason"] == "logout"


def test_a_failed_read_writes_no_error_on_the_account_unlike_a_sync(sib, monkeypatch, caplog):
    db = FakeDB([native_account("ba_i", broker="icicidirect")])
    account_writes = watch_writes(monkeypatch, db.broker_accounts)
    sib.holdings["ba_i"] = RuntimeError(f"adapter broke {SECRET}")
    with caplog.at_level("DEBUG", logger="services.brokers.hub_reads"):
        with pytest.raises(hub.BrokerReadError):
            _read(db, "ba_i")
    assert account_writes == [] and db.broker_accounts.one(account_id="ba_i")["last_error"] is None
    assert "broker holdings read failed account=ba_i broker=icicidirect error=RuntimeError" in caplog.text
    assert SECRET not in caplog.text and CLIENT_ID not in caplog.text


def test_an_openalgo_row_is_never_read_as_a_broker_session(sib):
    db = FakeDB([native_account("ba_oa", native=False, openalgo_url="http://oa.local:5000")])
    with pytest.raises(hub.BrokerNotSupported):
        _read(db, "ba_oa")
    assert sib.calls == []


# ── hub_reads.holdings_totals ────────────────────────────────────────────
def _row(**over):
    row = {"invested_rs": 1000.0, "value_rs": 1100.0, "pnl_rs": 100.0}
    row.update(over)
    return row


def test_totals_add_up_the_rows():
    assert hub.holdings_totals([_row(), _row(invested_rs=500.0, value_rs=400.0, pnl_rs=-100.0)]) == {
        "invested_rs": 1500.0, "value_rs": 1500.0, "pnl_rs": 0.0, "pnl_pct": 0.0}
    assert hub.holdings_totals([_row(), _row(invested_rs=3000.0, value_rs=3300.0, pnl_rs=300.0)])["pnl_pct"] == 10.0


def test_a_total_is_null_when_any_row_lacks_its_input():
    unpriced = _row(value_rs=None, pnl_rs=None)
    assert hub.holdings_totals([_row(), unpriced]) == {"invested_rs": 2000.0, "value_rs": None, "pnl_rs": None, "pnl_pct": None}
    no_average = _row(invested_rs=None, pnl_rs=None)
    assert hub.holdings_totals([_row(), no_average]) == {"invested_rs": None, "value_rs": 2200.0, "pnl_rs": None, "pnl_pct": None}


def test_no_holdings_is_a_known_zero_with_no_percentage():
    assert hub.holdings_totals([]) == {"invested_rs": 0.0, "value_rs": 0.0, "pnl_rs": 0.0, "pnl_pct": None}


# ── GET /api/broker/accounts/{id}/holdings ───────────────────────────────
def test_one_accounts_holdings_are_read_live(h, sib, monkeypatch):
    holding_writes = watch_writes(monkeypatch, h.db.holdings)
    account_writes = watch_writes(monkeypatch, h.db.broker_accounts)
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    before = datetime.now(timezone.utc)
    res = h.get("/api/broker/accounts/ba_z/holdings")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"account_id", "broker", "broker_display", "label", "as_of", "holdings", "counts", "totals"}
    assert (body["account_id"], body["broker"], body["broker_display"], body["label"]) == ("ba_z", "zerodha", "Zerodha", "Zerodha")
    assert before <= _utc(body["as_of"]) <= datetime.now(timezone.utc)
    assert [r["symbol"] for r in body["holdings"]] == ["INFY", "GOLDBEES"] and all(set(r) == ROW_KEYS for r in body["holdings"])
    assert body["counts"] == {"total": 2}
    # 14,005 + 5,200 = 19,205 invested; 15,250 + 6,125 = 21,375 value; +2,170; 2,170 / 19,205 = +11.30%
    assert body["totals"] == {"invested_rs": 19205.0, "value_rs": 21375.0, "pnl_rs": 2170.0, "pnl_pct": 11.3}
    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z")]
    assert holding_writes == [] and account_writes == [] and h.audits == []
    _no_secret(res.text)


def test_one_accounts_holdings_for_an_openalgo_account_are_400(h, sib):
    res = h.get("/api/broker/accounts/ba_oa/holdings")
    _error(res, 400, "BROKER_READ_NOT_SUPPORTED",
           "Live holdings are available only for accounts connected by signing in on the broker's own page.",
           [{"broker": "upstox", "account_id": "ba_oa"}])
    assert sib.calls == []                          # the stored OpenAlgo key is never loaded as a broker token


def test_one_accounts_holdings_of_another_user_are_404(h, sib):
    _error(h.get("/api/broker/accounts/ba_u2/holdings", who="u1"), 404, "RES-001", "Broker account not found")
    assert h.get("/api/broker/accounts/ba_nope/holdings").status_code == 404
    assert sib.calls == []


def test_one_accounts_holdings_with_an_ended_session_are_409_without_a_broker_call(h, sib):
    h.db.broker_accounts.one(account_id="ba_z").update(status="expired", session_ended_reason="expired")
    _error(h.get("/api/broker/accounts/ba_z/holdings"), 409, "BROKER_SESSION_EXPIRED",
           "Your Zerodha session has ended. Reconnect the account to continue.",
           [{"broker": "zerodha", "account_id": "ba_z"}])
    assert sib.reads() == [] and sib.ended == []


def test_one_accounts_holdings_with_a_rejected_token_are_409_and_end_the_session(h, sib, monkeypatch):
    holding_writes = watch_writes(monkeypatch, h.db.holdings)
    sib.holdings["ba_z"] = hub.BrokerSessionExpired(f"rejected {SECRET}")
    res = h.get("/api/broker/accounts/ba_z/holdings")
    _error(res, 409, "BROKER_SESSION_EXPIRED", details=[{"broker": "zerodha", "account_id": "ba_z"}])
    assert sib.ended == [("ba_z", "broker_rejected")] and holding_writes == []
    _no_secret(res.text)


def test_one_accounts_holdings_broker_failure_is_424_with_no_secret(h, sib, caplog):
    sib.holdings["ba_i"] = RuntimeError(f'upstream 500 {{"token":"{SECRET}","client":"{CLIENT_ID}"}}')
    with caplog.at_level("DEBUG"):
        res = h.get("/api/broker/accounts/ba_i/holdings")
    _error(res, 424, "BROKER_READ_FAILED", "Could not read holdings from ICICI Direct. Please try again.",
           [{"broker": "icicidirect", "account_id": "ba_i"}])
    assert sib.ended == [] and h.db.broker_accounts.one(account_id="ba_i")["last_error"] is None
    _no_secret(res.text, caplog.text)


def test_one_accounts_holdings_for_a_broker_with_no_reader_are_400(h, sib):
    sib.adapter("icicidirect", "ICICI Direct", implemented=False)
    _error(h.get("/api/broker/accounts/ba_i/holdings"), 400, "BROKER_READ_NOT_SUPPORTED",
           "Reading holdings is not available for ICICI Direct.")


# ── GET /api/broker/holdings ─────────────────────────────────────────────
ENTRY_KEYS = {"account_id", "broker", "broker_display", "label", "ok", "error", "as_of", "holdings", "counts", "totals"}
UNKNOWN_TOTALS = {"invested_rs": None, "value_rs": None, "pnl_rs": None, "pnl_pct": None}


def test_every_account_is_reported_on_its_own(h, sib, monkeypatch):
    h.db.broker_accounts.docs.extend([
        native_account("ba_fail", broker="icicidirect", label="Failing", created_at="2026-10-13T03:00:00+00:00"),
        native_account("ba_ended", label="Ended", status="expired", created_at="2026-10-13T02:00:00+00:00"),
        native_account("ba_empty", label="Empty", created_at="2026-10-11T02:00:00+00:00"),
    ])
    holding_writes = watch_writes(monkeypatch, h.db.holdings)
    account_writes = watch_writes(monkeypatch, h.db.broker_accounts)
    sib.holdings["ba_z"] = [INFY, dataclasses.replace(GOLDBEES, current_price=0.0)]     # one row without a price
    sib.holdings["ba_i"] = [INFY]
    sib.holdings["ba_fail"] = RuntimeError(f"broker exploded {SECRET}")
    sib.holdings["ba_empty"] = []
    sib.holdings["ba_u2"] = [dataclasses.replace(INFY, symbol="SHOULD-NOT-APPEAR")]

    before = datetime.now(timezone.utc)
    res = h.get("/api/broker/holdings")
    assert res.status_code == 200                           # one account failing does not fail the request
    body = res.json()
    assert set(body) == {"as_of", "accounts"}
    accounts = body["accounts"]
    # Every account of the user, newest first — the OpenAlgo one included — and never another user's.
    assert [a["account_id"] for a in accounts] == ["ba_z", "ba_i", "ba_fail", "ba_ended", "ba_oa", "ba_empty"]
    assert all(set(a) == ENTRY_KEYS for a in accounts)
    z, i, fail, ended, oa, empty = accounts

    assert (z["ok"], z["error"], z["broker"], z["broker_display"], z["label"]) == (True, None, "zerodha", "Zerodha", "Zerodha")
    assert [r["symbol"] for r in z["holdings"]] == ["INFY", "GOLDBEES"] and z["counts"] == {"total": 2}
    # GOLDBEES has no price: value and P&L are not totalled; the cost still is (14,005 + 5,200).
    assert z["totals"] == {"invested_rs": 19205.0, "value_rs": None, "pnl_rs": None, "pnl_pct": None}
    assert (i["ok"], i["broker_display"], i["label"], i["counts"]) == (True, "ICICI Direct", "ICICI trading", {"total": 1})
    assert i["totals"] == {"invested_rs": 14005.0, "value_rs": 15250.0, "pnl_rs": 1245.0, "pnl_pct": 8.89}

    assert (fail["ok"], fail["holdings"], fail["counts"], fail["totals"]) == (False, [], {"total": None}, UNKNOWN_TOTALS)
    assert fail["error"] == {"code": "BROKER_READ_FAILED", "message": "Could not read holdings from ICICI Direct. Please try again."}
    # Needs a reconnect: listed, not dropped — and the broker is not called for it.
    assert (ended["ok"], ended["label"], ended["holdings"], ended["totals"]) == (False, "Ended", [], UNKNOWN_TOTALS)
    assert ended["error"] == {"code": "BROKER_SESSION_EXPIRED",
                              "message": "Your Zerodha session has ended. Reconnect the account to continue."}
    # An OpenAlgo account is listed, with why it is not read.
    assert (oa["ok"], oa["broker"], oa["broker_display"], oa["label"], oa["holdings"]) == (False, "upstox", "Upstox", "My Upstox", [])
    assert oa["error"] == {"code": "BROKER_READ_NOT_SUPPORTED",
                           "message": "Live holdings are available only for accounts connected by signing in on the broker's own page."}
    # Read, and nothing held: a known zero.
    assert (empty["ok"], empty["holdings"], empty["counts"]) == (True, [], {"total": 0})
    assert empty["totals"] == {"invested_rs": 0.0, "value_rs": 0.0, "pnl_rs": 0.0, "pnl_pct": None}

    assert {c[2] for c in sib.reads()} == {"ba_z", "ba_i", "ba_fail", "ba_empty"}
    stamps = [_utc(a["as_of"]) for a in accounts]
    assert all(before <= s <= _utc(body["as_of"]) for s in stamps)
    # Nothing stored, no account row touched, nothing audited.
    assert holding_writes == [] and account_writes == [] and h.audits == []
    _no_secret(res.text)


def test_a_session_the_broker_rejects_is_ended_and_the_others_are_still_read(h, sib):
    sib.holdings["ba_z"] = hub.BrokerSessionExpired("rejected")
    sib.holdings["ba_i"] = [INFY]
    body = h.get("/api/broker/holdings").json()
    by_id = {a["account_id"]: a for a in body["accounts"]}
    assert by_id["ba_z"]["error"]["code"] == "BROKER_SESSION_EXPIRED" and by_id["ba_z"]["ok"] is False
    assert sib.ended == [("ba_z", "broker_rejected")]
    assert h.db.broker_accounts.one(account_id="ba_z")["status"] == "expired"
    assert by_id["ba_i"]["ok"] is True and [r["symbol"] for r in by_id["ba_i"]["holdings"]] == ["INFY"]
    # The stored rows of the rejected account stay (the screen shows them as of the last sync).
    assert h.db.holdings.one(name="OLD-Z")


def test_accounts_are_read_a_few_at_a_time(h, sib):
    n = hub.LIVE_READ_CONCURRENCY * 3
    state = {"now": 0, "peak": 0}

    async def slow_read():
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return [INFY]

    h.db.broker_accounts.docs = [native_account(f"ba_{k}", created_at=f"2026-10-13T{k:02d}:00:00+00:00") for k in range(n)]
    for k in range(n):
        sib.holdings[f"ba_{k}"] = slow_read
    body = h.get("/api/broker/holdings").json()
    assert len(body["accounts"]) == n and all(a["ok"] for a in body["accounts"])
    assert 1 < state["peak"] <= hub.LIVE_READ_CONCURRENCY


def test_a_user_with_no_account_gets_an_empty_list(h, sib):
    h.db.broker_accounts.docs = [d for d in h.db.broker_accounts.docs if d["user_id"] != "u2"]
    res = h.get("/api/broker/holdings", who="u2")
    assert res.status_code == 200 and res.json()["accounts"] == []


def test_holdings_routes_require_a_signed_in_user(h, sib):
    assert h.http.get("/api/broker/holdings").status_code == 401
    assert h.http.get("/api/broker/accounts/ba_z/holdings").status_code == 401
    assert sib.calls == []


@pytest.mark.parametrize("path", ["/api/broker/holdings", "/api/broker/accounts/ba_z/holdings"])
def test_holdings_routes_are_refused_when_the_flag_is_off(h, sib, flag_off, path):
    sib.holdings["ba_z"] = [INFY]
    _error(h.get(path), 403, "AUTHZ-001", "feature_not_enabled", [])
    assert sib.calls == []


@pytest.mark.parametrize("path", ["/api/broker/holdings", "/api/broker/accounts/ba_z/holdings"])
def test_holdings_routes_fail_closed_when_the_flag_state_cannot_be_read(h, sib, flag_unreadable, path):
    sib.holdings["ba_z"] = [INFY]
    _error(h.get(path), 503, "INT-001", "feature_state_unavailable", [])
    assert sib.calls == []


# ── GET /api/broker/positions: OpenAlgo accounts are listed too ──────────
def test_all_accounts_positions_list_an_openalgo_account_as_not_readable(h, sib):
    sib.positions["ba_z"] = [hub_position()]
    sib.positions["ba_i"] = []
    body = h.get("/api/broker/positions").json()
    accounts = body["accounts"]
    assert [a["account_id"] for a in accounts] == ["ba_z", "ba_i", "ba_oa"]
    oa = accounts[2]
    assert (oa["ok"], oa["broker"], oa["broker_display"], oa["positions"]) == (False, "upstox", "Upstox", [])
    assert oa["counts"] == {"total": 0, "fno": 0, "intraday": 0}
    assert oa["error"] == {"code": "BROKER_READ_NOT_SUPPORTED",
                           "message": "Live positions are available only for accounts connected by signing in on the broker's own page."}
    assert [a["broker_display"] for a in accounts[:2]] == ["Zerodha", "ICICI Direct"]
    assert {c[2] for c in sib.reads()} == {"ba_z", "ba_i"}       # the OpenAlgo account is never read


def test_all_accounts_positions_are_read_a_few_at_a_time(h, sib):
    n = hub.LIVE_READ_CONCURRENCY * 3
    state = {"now": 0, "peak": 0}

    async def slow_book(kind):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return [hub_position(kind=kind)]

    h.db.broker_accounts.docs = [native_account(f"ba_{k}", created_at=f"2026-10-13T{k:02d}:00:00+00:00") for k in range(n)]
    for k in range(n):
        sib.positions[f"ba_{k}"] = slow_book
    body = h.get("/api/broker/positions").json()
    assert len(body["accounts"]) == n and all(a["ok"] for a in body["accounts"])
    assert 1 < state["peak"] <= hub.LIVE_READ_CONCURRENCY


def test_the_route_module_names_the_new_routes():
    paths = {(sorted(r.methods)[0], r.path) for r in bc.router.routes}
    assert ("GET", "/api/broker/holdings") in paths and ("GET", "/api/broker/accounts/{account_id}/holdings") in paths


# ── A broker whose full list would not answer (ICICI's /dematholdings, 31 Oct 2026) ──
PARTIAL_NOTE = ("ICICI Direct's demat holdings list is not answering, so these 1 holdings are from its NSE equity portfolio view. "
                "Holdings outside NSE equity (other exchanges, bonds, funds) and ISINs are missing.")


def _partial_view():
    from services.brokers.base import PartialHoldings
    return PartialHoldings([dataclasses.replace(INFY, isin=None)], PARTIAL_NOTE)


def test_a_partial_read_is_shown_live_with_its_note_on_both_live_routes(h, sib):
    sib.holdings["ba_z"] = _partial_view()
    one = h.get("/api/broker/accounts/ba_z/holdings")
    assert one.status_code == 200 and one.json()["partial"] == PARTIAL_NOTE and one.json()["counts"] == {"total": 1}
    assert [r["symbol"] for r in one.json()["holdings"]] == ["INFY"]
    every = h.get("/api/broker/holdings").json()["accounts"]
    mine = next(a for a in every if a["account_id"] == "ba_z")
    assert mine["ok"] is True and mine["partial"] == PARTIAL_NOTE
    # A complete read says nothing about being partial.
    sib.holdings["ba_z"] = [INFY]
    assert "partial" not in h.get("/api/broker/accounts/ba_z/holdings").json()


def test_a_partial_read_never_replaces_the_holdings_on_file(h, sib):
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    assert h.post("/api/broker/accounts/ba_z/sync").json()["count"] == 2
    on_file = sorted(r["holding_id"] for r in h.db.holdings.docs if r.get("broker_account_id") == "ba_z")
    snapshots = len(h.db.broker_sync_snapshots.docs)

    sib.holdings["ba_z"] = _partial_view()
    res = h.post("/api/broker/accounts/ba_z/sync")
    body = res.json()
    assert res.status_code == 200 and body["partial"] == PARTIAL_NOTE
    assert body["count"] == 2 and body["holdings"] == []                  # what is still on file, nothing new
    assert sorted(r["holding_id"] for r in h.db.holdings.docs if r.get("broker_account_id") == "ba_z") == on_file
    assert len(h.db.broker_sync_snapshots.docs) == snapshots              # a partial read is not a sync snapshot
    acct = h.db.broker_accounts.one(account_id="ba_z")
    assert (acct["last_sync_count"], acct["last_error"]) == (2, None)
    assert h.audits[-1]["outcome"] == "success" and h.audits[-1]["details"]["partial"] is True
