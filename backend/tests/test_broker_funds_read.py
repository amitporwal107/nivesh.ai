"""Read-only broker funds — `hub_reads.read_account_funds` and GET /api/broker/funds (PRD §8.3 cash balance, §8.7, §14.2).

No broker, no Mongo: the broker adapters are fakes from the hub-reads harness (test_broker_hub_reads.py) with a
`fetch_funds`, and `db` is its in-memory fake. Every adapter here is wrapped so that touching any order, transfer or
other write method fails the test: the funds read may call `fetch_funds` and nothing else.

MOCK — not real data: the cash figures are made up.
"""
from __future__ import annotations

import asyncio

import pytest

from services.brokers.base import Funds
from tests.test_broker_hub_reads import FakeAdapter, FakeDB, hub, native_account, sib  # noqa: F401  (`sib` is a fixture)
from tests.test_broker_connect_native_routes import _Harness, _db, _error, _no_secret, flag_off, h  # noqa: F401
from tests.test_broker_live_holdings import watch_writes

WRITE_WORDS = ("order", "place", "modify", "cancel", "transfer", "withdraw", "payout", "exit", "convert", "square")


class FundsAdapter(FakeAdapter):
    """A fake adapter with `fetch_funds`; any attribute that sounds like a write raises."""

    def __init__(self, harness, slug, display, funds):
        super().__init__(harness, slug, display)
        self._funds = funds
        self.touched = []

    def __getattribute__(self, name):
        if any(w in name.lower() for w in WRITE_WORDS):
            object.__getattribute__(self, "touched").append(name)
            raise AssertionError(f"the funds read touched a write method: {name}")
        return object.__getattribute__(self, name)

    async def fetch_funds(self, token):
        self._h.calls.append(("adapter.fetch_funds", self.SLUG, self._h.account_of(token)))
        value = self._funds.get(self._h.account_of(token))
        if isinstance(value, BaseException):
            raise value
        return value


def _install(sib, table):
    for slug, display in (("zerodha", "Zerodha"), ("icicidirect", "ICICI Direct")):
        sib.adapters[slug] = FundsAdapter(sib, slug, display, table)
    return sib.adapters


def test_funds_come_from_fetch_funds_only_and_nothing_is_written(sib, monkeypatch):
    adapters = _install(sib, {"ba_i": Funds(available_cash=125000.5, collateral=40000.0, used_margin=10000.0)})
    db = FakeDB([native_account("ba_i", broker="icicidirect")])
    account_writes = watch_writes(monkeypatch, db.broker_accounts)
    holding_writes = watch_writes(monkeypatch, db.holdings)

    out = asyncio.run(hub.read_account_funds(db, db.broker_accounts.one(account_id="ba_i")))

    assert out == {"available_cash_rs": 125000.5, "collateral_rs": 40000.0, "used_margin_rs": 10000.0}
    assert sib.reads() == [("adapter.fetch_funds", "icicidirect", "ba_i")]
    assert adapters["icicidirect"].touched == [] and account_writes == [] and holding_writes == []


def test_fenix_never_serves_funds_even_where_it_serves_holdings(sib):
    _install(sib, {"ba_z": Funds(available_cash=1.0)})
    db = FakeDB([native_account("ba_z")])
    asyncio.run(hub.read_account_funds(db, db.broker_accounts.one(account_id="ba_z")))
    assert sib.reads() == [("adapter.fetch_funds", "zerodha", "ba_z")]


def test_a_refused_session_is_ended_and_no_other_write_happens(sib, monkeypatch):
    import httpx
    request = httpx.Request("GET", "https://broker.example/funds")
    _install(sib, {"ba_i": httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request))})
    db = FakeDB([native_account("ba_i", broker="icicidirect")])
    holding_writes = watch_writes(monkeypatch, db.holdings)
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.read_account_funds(db, db.broker_accounts.one(account_id="ba_i")))
    assert sib.ended == [("ba_i", "broker_rejected")] and holding_writes == []


def test_an_ended_session_is_not_read(sib):
    _install(sib, {"ba_i": Funds(available_cash=1.0)})
    db = FakeDB([native_account("ba_i", broker="icicidirect", status="expired")])
    with pytest.raises(hub.sessions.SessionEnded):
        asyncio.run(hub.read_account_funds(db, db.broker_accounts.one(account_id="ba_i")))
    assert sib.reads() == []


def test_an_adapter_without_a_funds_reader_is_not_supported(sib):
    db = FakeDB([native_account("ba_i", broker="icicidirect")])          # the plain FakeAdapter has no fetch_funds
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_account_funds(db, db.broker_accounts.one(account_id="ba_i")))


# ── GET /api/broker/funds ────────────────────────────────────────────────────
def test_route_lists_every_account_with_its_own_outcome(h, sib, monkeypatch):
    import httpx
    request = httpx.Request("GET", "https://broker.example/funds")
    _install(sib, {"ba_z": Funds(available_cash=50000.0, collateral=0.0, used_margin=2500.0),
                   "ba_i": httpx.HTTPStatusError("500", request=request, response=httpx.Response(500, request=request))})
    holding_writes = watch_writes(monkeypatch, h.db.holdings)
    r = h.get("/api/broker/funds")
    assert r.status_code == 200, r.text
    body = r.json()
    _no_secret(body)
    by_id = {a["account_id"]: a for a in body["accounts"]}
    assert set(by_id) == {"ba_z", "ba_i", "ba_oa"}                      # u2's account is not listed
    z = by_id["ba_z"]
    assert (z["ok"], z["broker_display"], z["funds"]) == (True, "Zerodha", {"available_cash_rs": 50000.0, "collateral_rs": 0.0,
                                                                           "used_margin_rs": 2500.0})
    i = by_id["ba_i"]
    assert (i["ok"], i["funds"], i["error"]["code"]) == (False, None, "BROKER_READ_FAILED")
    assert i["error"]["message"] == "Could not read funds from ICICI Direct. Please try again."
    oa = by_id["ba_oa"]
    assert (oa["ok"], oa["error"]["code"]) == (False, "BROKER_READ_NOT_SUPPORTED")
    assert body["basis"] and "never stored" in body["basis"]
    assert holding_writes == []
    assert sorted(c for c in sib.reads()) == [("adapter.fetch_funds", "icicidirect", "ba_i"), ("adapter.fetch_funds", "zerodha", "ba_z")]


def test_route_needs_a_user_and_the_broker_hub_flag(h, sib, flag_off):
    _install(sib, {})
    assert h.get("/api/broker/funds", who="nobody").status_code == 401
    _error(h.get("/api/broker/funds"), 403, "AUTHZ-001", "feature_not_enabled", [])
    assert sib.reads() == []
