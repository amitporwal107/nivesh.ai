"""services/brokers/hub_reads.py — reader choice, native holdings sync, live positions, the daily job.

No broker, no Mongo, no Redis: every broker read is a fake Fenix reader or a fake adapter, and `db` is
an in-memory fake. Nothing in this file talks to a real broker.

`services/brokers/sessions.py`, `services/brokers/fenix_reader.py` and `base.HubPosition` are written in
parallel with `hub_reads`. Where one is not on disk yet, a stand-in built from the agreed contract is
installed BEFORE `hub_reads` is imported (`SIBLINGS` records which). Real or stand-in, every function
`hub_reads` calls on them is replaced per test by the `Siblings` harness below, so these tests pin what
`hub_reads` does with the contract and not how the sibling modules implement it. The same goes for
`helpers.holdings_reconcile.apply_broker_wins`, except in the one end-to-end test that runs the real one.

The harness (`FakeDB`, `Siblings`, `native_account`, …) is shared with
test_broker_connect_native_routes.py.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib
import inspect
import logging
import sys
import types
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import pytest

import services.brokers.base as _base
from services.brokers.base import AccessToken, Holding, Position

# A broker session token and a broker client id. Neither may ever reach a log line, a stored error,
# an audit record or a response body.
SECRET = "tok-SECRET-9f3a71"
CLIENT_ID = "ZX4471"

SIBLINGS: dict[str, str] = {}


# ── Stand-ins for modules that may not be on disk yet ────────────────────
@dataclass
class _StandInHubPosition:
    symbol: str
    exchange: str
    quantity: float
    avg_price: float
    last_price: Optional[float]
    pnl: float
    product: Optional[str]
    product_raw: Optional[str]
    segment: str
    is_intraday: bool
    instrument_type: Optional[str]
    expiry: Optional[str]
    strike: Optional[float]
    kind: str
    name: Optional[str] = None


def _stand_in_sessions() -> types.ModuleType:
    m = types.ModuleType("services.brokers.sessions")
    m.STATUS_ACTIVE = "active"
    m.STATUS_EXPIRED = "expired"

    class SessionEnded(RuntimeError):
        pass

    def is_live(doc, now=None):
        raise NotImplementedError("stand-in: replaced per test")

    def load_token(doc):
        raise NotImplementedError("stand-in: replaced per test")

    def public_fields(doc, now=None):
        raise NotImplementedError("stand-in: replaced per test")

    async def end_session(db, account_id, reason, *, error=None):
        raise NotImplementedError("stand-in: replaced per test")

    async def expire_due_sessions(db, *, user_id=None, now=None):
        raise NotImplementedError("stand-in: replaced per test")

    m.SessionEnded = SessionEnded
    m.is_live, m.load_token, m.public_fields = is_live, load_token, public_fields
    m.end_session, m.expire_due_sessions = end_session, expire_due_sessions
    return m


def _stand_in_fenix_reader() -> types.ModuleType:
    m = types.ModuleType("services.brokers.fenix_reader")

    class BrokerReadError(RuntimeError):
        pass

    class BrokerSessionExpired(BrokerReadError):
        pass

    class BrokerNotSupported(BrokerReadError):
        pass

    def supports(slug):
        raise NotImplementedError("stand-in: replaced per test")

    async def read_holdings(slug, token):
        raise NotImplementedError("stand-in: replaced per test")

    async def read_positions(slug, token, kind="net"):
        raise NotImplementedError("stand-in: replaced per test")

    m.BrokerReadError, m.BrokerSessionExpired, m.BrokerNotSupported = (
        BrokerReadError, BrokerSessionExpired, BrokerNotSupported,
    )
    m.supports, m.read_holdings, m.read_positions = supports, read_holdings, read_positions
    return m


def _ensure_sibling_modules() -> None:
    import services.brokers as pkg

    if hasattr(_base, "HubPosition"):
        SIBLINGS["base.HubPosition"] = "real"
    else:
        _base.HubPosition = _StandInHubPosition
        SIBLINGS["base.HubPosition"] = "stand-in"
    for name, build in (("sessions", _stand_in_sessions), ("fenix_reader", _stand_in_fenix_reader)):
        full = f"services.brokers.{name}"
        try:
            importlib.import_module(full)
            SIBLINGS[name] = "real"
        except ModuleNotFoundError as e:
            if e.name != full:
                raise  # the module exists but one of ITS imports is missing — a real failure
            module = build()
            sys.modules[full] = module
            setattr(pkg, name, module)
            SIBLINGS[name] = "stand-in"


_ensure_sibling_modules()

from services.brokers import hub_reads as hub  # noqa: E402

# The masterdata fill reads the real masterdata files; tests state what they give a row themselves.
REAL_MASTERDATA_FILL = hub._fill_from_masterdata


@pytest.fixture(autouse=True)
def broker_rows_as_given(monkeypatch):
    """Rows are stored as the broker gave them unless a test puts the real fill back."""
    monkeypatch.setattr(hub, "_fill_from_masterdata", lambda row: None)

# helpers/holdings_reconcile.py (the "broker wins" rule) is on disk and imported for real by hub_reads;
# `Siblings` replaces its `apply_broker_wins` per test, and one test below puts the real one back.
SIBLINGS["helpers.holdings_reconcile"] = "real"
REAL_APPLY_BROKER_WINS = hub.holdings_reconcile.apply_broker_wins


# ── In-memory db ─────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        return self._docs if length is None else self._docs[:length]


class FakeCollection:
    def __init__(self, docs=()):
        self.docs = [dict(d) for d in docs]

    _OPS = {"$ne": lambda have, arg: have != arg,
            "$in": lambda have, arg: have in arg,           # like Mongo, None also matches a missing field
            "$nin": lambda have, arg: have not in arg}

    @classmethod
    def _matches(cls, doc, query):
        for key, want in (query or {}).items():
            if key == "$or":
                if not any(cls._matches(doc, q) for q in want):
                    return False
                continue
            have = doc.get(key)
            if isinstance(want, dict) and want and all(k.startswith("$") for k in want):
                if not all(cls._OPS[op](have, arg) for op, arg in want.items()):
                    return False
            elif have != want:
                return False
        return True

    def find(self, query=None, proj=None):
        return _Cursor([dict(d) for d in self.docs if self._matches(d, query)])

    async def find_one(self, query, proj=None, **_kw):
        for d in self.docs:
            if self._matches(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                d.update(update["$set"])
                return 1
        return 0

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._matches(d, query):
                del self.docs[i]
                return 1
        return 0

    async def delete_many(self, query):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not self._matches(d, query)]
        return types.SimpleNamespace(deleted_count=before - len(self.docs))

    def one(self, **query):
        """Test accessor: the single stored doc matching `query`."""
        (doc,) = [d for d in self.docs if self._matches(d, query)]
        return doc


class FakeDB:
    def __init__(self, accounts=(), holdings=()):
        self.broker_accounts = FakeCollection(accounts)
        self.holdings = FakeCollection(holdings)
        self.mfd_profile_signal_cache = FakeCollection([{"user_id": "u1", "signal": "stale"}])


def native_account(account_id: str, user_id: str = "u1", broker: str = "zerodha", **over) -> dict:
    """A `broker_accounts` row as routes/broker_native.py writes it after the redirect flow."""
    doc = {
        "account_id": account_id, "user_id": user_id, "broker": broker, "label": broker.title(),
        "openalgo_url": "", "openalgo_hosted": False, "openalgo_per_account_instance": False,
        "native": True,
        "api_key_encrypted": f"enc({SECRET})", "api_key_masked": "tok-••••••3a71",
        "extras_encrypted": f"enc({CLIENT_ID})",
        "status": "active",
        "created_at": "2026-10-13T04:00:00+00:00", "updated_at": "2026-10-13T04:00:00+00:00",
        "last_sync_at": None, "last_sync_count": 0, "last_error": None,
    }
    doc.update(over)
    return doc


def holding_row(name: str, user_id: str = "u1", **over) -> dict:
    row = {"holding_id": f"hold_{name}", "user_id": user_id, "portfolio_id": "", "name": name,
           "ticker": name, "asset_type": "equity", "quantity": 1.0, "source": "cas"}
    row.update(over)
    return row


def http_error(status: int, text: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://broker.example/portfolio")
    return httpx.HTTPStatusError(
        text or f"status {status}", request=request,
        response=httpx.Response(status, request=request, text=text),
    )


# ── Fakes for everything hub_reads calls outside itself ──────────────────
class FakeAdapter:
    """A broker adapter as `registry.get(slug)` returns it. Results come from the harness tables,
    keyed by the account the token belongs to."""

    def __init__(self, harness: "Siblings", slug: str, display: str, implemented: bool = True):
        self.SLUG, self.DISPLAY, self.AUTH_STYLE = slug, display, "oauth"
        if not implemented:
            self.IMPLEMENTED = False
        self._h = harness

    async def fetch_holdings(self, token):
        self._h.calls.append(("adapter.fetch_holdings", self.SLUG, self._h.account_of(token)))
        return await self._h.result(self._h.holdings, token)

    async def fetch_positions(self, token):
        self._h.calls.append(("adapter.fetch_positions", self.SLUG, self._h.account_of(token)))
        return await self._h.result(self._h.positions, token, "net")


class RichFakeAdapter(FakeAdapter):
    """An adapter that also has the optional `fetch_hub_positions(token, kind)`."""

    async def fetch_hub_positions(self, token, kind):
        self._h.calls.append(("adapter.fetch_hub_positions", self.SLUG, self._h.account_of(token), kind))
        return await self._h.result(self._h.positions, token, kind)


class Siblings:
    """Replaces sessions / fenix_reader / registry / dashboard cache as `hub_reads` sees them.

    Conventions: an account row with `status == "expired"` has no live session; a row with
    `_due: True` is past its broker expiry and gets expired by the next sweep. `holdings` and
    `positions` map account_id -> rows | an exception to raise | a (sync or async) callable; a
    `positions` callable receives the requested kind.
    """

    def __init__(self):
        self.fenix_supports: dict[str, dict] = {}
        self.adapters: dict[str, Any] = {}
        self.holdings: dict[str, Any] = {}
        self.positions: dict[str, Any] = {}
        self.calls: list[tuple] = []
        self.ended: list[tuple] = []
        self.cache_invalidations: list[str] = []
        self.reconciled: list[dict] = []
        self.reconcile_error: Optional[BaseException] = None

    # tokens ---------------------------------------------------------------
    @staticmethod
    def account_of(token: AccessToken) -> str:
        return token.token.rsplit(":", 1)[1]

    async def result(self, table, token, kind=None):
        value = table.get(self.account_of(token), [])
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = value(kind) if kind is not None else value()
            if inspect.isawaitable(value):
                value = await value
        return value

    def adapter(self, slug, display, *, rich=False, implemented=True):
        cls = RichFakeAdapter if rich else FakeAdapter
        self.adapters[slug] = cls(self, slug, display, implemented)
        return self.adapters[slug]

    def reads(self) -> list[tuple]:
        return [c for c in self.calls if c[0].startswith(("fenix.", "adapter."))]

    # sessions ---------------------------------------------------------------
    def is_live(self, doc, now=None):
        return doc.get("status") != "expired"

    def load_token(self, doc):
        if not self.is_live(doc):
            raise hub.sessions.SessionEnded("no usable token")
        self.calls.append(("sessions.load_token", doc["account_id"]))
        return AccessToken(token=f"{SECRET}:{doc['account_id']}", extras={"client_id": CLIENT_ID})

    def public_fields(self, doc, now=None):
        native = bool(doc.get("native"))
        return {
            "native": native,
            "broker_user_masked": "ZX••71" if native else None,
            "session_expires_at": doc.get("session_expires_at"),
            "session_ended_reason": doc.get("session_ended_reason"),
            "needs_reconnect": native and not self.is_live(doc),
        }

    async def end_session(self, db, account_id, reason, *, error=None):
        self.ended.append((account_id, reason))
        await db.broker_accounts.update_one(
            {"account_id": account_id},
            {"$set": {"status": "expired", "session_ended_reason": reason}},
        )

    async def expire_due_sessions(self, db, *, user_id=None, now=None):
        self.calls.append(("sessions.expire_due_sessions", user_id))
        n = 0
        for d in db.broker_accounts.docs:
            if d.get("_due") and d.get("status") != "expired" and user_id in (None, d["user_id"]):
                d.update(status="expired", session_ended_reason="expired")
                n += 1
        return n

    # fenix ------------------------------------------------------------------
    def supports(self, slug):
        return dict(self.fenix_supports.get(slug, {"holdings": False, "positions": False}))

    async def read_holdings(self, slug, token):
        self.calls.append(("fenix.read_holdings", slug, self.account_of(token)))
        return await self.result(self.holdings, token)

    async def read_positions(self, slug, token, kind="net"):
        self.calls.append(("fenix.read_positions", slug, self.account_of(token), kind))
        return await self.result(self.positions, token, kind)

    # registry / caches --------------------------------------------------------
    def registry_get(self, slug):
        if slug not in self.adapters:
            raise KeyError(f"Unknown broker '{slug}'")
        return self.adapters[slug]

    async def invalidate_dashboards(self, user_id):
        self.calls.append(("dashboard_cache.invalidate", user_id))
        self.cache_invalidations.append(user_id)

    async def apply_broker_wins(self, db, user_id, rows, *, broker, live):
        self.calls.append(("holdings_reconcile.apply_broker_wins", user_id, broker, live))
        self.reconciled.append({"user_id": user_id, "rows": rows, "broker": broker, "live": live,
                                "in_db": [h["holding_id"] for h in db.holdings.docs]})
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return {"statement_rows_removed": 0, "export_rows_removed": 0}

    def install(self, monkeypatch) -> "Siblings":
        for name in ("is_live", "load_token", "public_fields", "end_session", "expire_due_sessions"):
            monkeypatch.setattr(hub.sessions, name, getattr(self, name))
        for name in ("supports", "read_holdings", "read_positions"):
            monkeypatch.setattr(hub.fenix_reader, name, getattr(self, name))
        monkeypatch.setattr(hub.registry, "get", self.registry_get)
        monkeypatch.setattr(hub.dashboard_cache, "invalidate", self.invalidate_dashboards)
        monkeypatch.setattr(hub.holdings_reconcile, "apply_broker_wins", self.apply_broker_wins)
        return self


@pytest.fixture
def sib(monkeypatch) -> Siblings:
    s = Siblings().install(monkeypatch)
    s.fenix_supports["zerodha"] = {"holdings": True, "positions": True}
    s.adapter("zerodha", "Zerodha")
    s.adapter("icicidirect", "ICICI Direct")          # adapter-only broker: Fenix does not support it
    return s


def hub_position(symbol="NIFTY26OCTFUT", **over):
    fields = dict(symbol=symbol, exchange="NFO", quantity=50.0, avg_price=25000.0, last_price=25100.0,
                  pnl=5000.0, product="carryforward", product_raw="NRML", segment="fno", is_intraday=False,
                  instrument_type="FUT", expiry="2026-10-29", strike=None, kind="net", name="Nifty 50 Oct Fut")
    fields.update(over)
    return hub.HubPosition(**fields)


INFY = Holding(isin="INE009A01021", symbol="INFY", asset_type="equity", quantity=10, avg_price=1400.5,
               current_price=1525.0, name="Infosys Ltd", sector="IT", exchange="NSE", source_id="NSE:INFY")
GOLDBEES = Holding(isin="INF204KB17I5", symbol="GOLDBEES", asset_type="etf", quantity=100, avg_price=52.0,
                   current_price=61.25, name=None, sector=None, exchange="NSE", source_id=None)


# ── Reader choice ────────────────────────────────────────────────────────
def test_holdings_use_fenix_when_fenix_supports_the_broker(sib):
    sib.holdings["ba_z"] = [INFY]
    got = asyncio.run(hub.read_holdings_for(native_account("ba_z", broker="zerodha")))
    assert got == [INFY]
    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z")]       # the adapter was never asked


def test_holdings_use_the_adapter_when_fenix_does_not_support_the_broker(sib):
    sib.holdings["ba_i"] = [INFY]
    got = asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))
    assert got == [INFY]
    assert sib.reads() == [("adapter.fetch_holdings", "icicidirect", "ba_i")]


def test_reader_choice_is_per_read_not_per_broker(sib):
    # Fenix serves this broker's holdings but not its positions: each read picks its own reader.
    sib.fenix_supports["zerodha"] = {"holdings": True, "positions": False}
    sib.holdings["ba_z"] = [INFY]
    sib.positions["ba_z"] = [Position(symbol="INFY", exchange="NSE", quantity=5, avg_price=1500.0)]
    doc = native_account("ba_z")
    asyncio.run(hub.read_holdings_for(doc))
    asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))
    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z"),
                           ("adapter.fetch_positions", "zerodha", "ba_z")]


def test_a_fenix_error_surfaces_and_never_falls_back_to_the_adapter(sib):
    sib.holdings["ba_z"] = hub.BrokerReadError("fenix: upstream 500")
    with pytest.raises(hub.BrokerReadError):
        asyncio.run(hub.read_holdings_for(native_account("ba_z")))
    assert sib.reads() == [("fenix.read_holdings", "zerodha", "ba_z")]


def test_an_adapter_error_surfaces_and_never_falls_back_to_fenix(sib):
    sib.holdings["ba_i"] = RuntimeError("adapter broke")
    with pytest.raises(hub.BrokerReadError):
        asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))
    assert sib.reads() == [("adapter.fetch_holdings", "icicidirect", "ba_i")]


def test_an_account_without_a_live_session_is_not_read_at_all(sib):
    with pytest.raises(hub.sessions.SessionEnded):
        asyncio.run(hub.read_holdings_for(native_account("ba_z", status="expired")))
    assert sib.reads() == []


def test_an_openalgo_row_is_never_read_as_a_broker_session(sib):
    # Its stored key is an OpenAlgo API key, not a broker token: it must not even be loaded.
    doc = native_account("ba_oa", native=False, openalgo_url="http://oa.local:5000")
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_holdings_for(doc))
    assert sib.calls == []


# ── Adapter path: error mapping ──────────────────────────────────────────
class TokenException(Exception):                      # the name kiteconnect / SmartApi use
    pass


class IciciSessionExpired(Exception):                 # an adapter's own "session expired"
    pass


class DayBookNotSupported(Exception):                 # an adapter's own "not supported"
    pass


@pytest.mark.parametrize("raised", [
    http_error(401), http_error(403), TokenException("Incorrect `api_key` or `access_token`."),
    IciciSessionExpired("session timed out"),
], ids=["http-401", "http-403", "TokenException", "name-ends-SessionExpired"])
def test_adapter_token_rejection_becomes_broker_session_expired(sib, raised):
    sib.holdings["ba_i"] = raised
    with pytest.raises(hub.BrokerSessionExpired) as e:
        asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))
    assert e.value.__cause__ is raised


def test_kiteconnect_token_exception_becomes_broker_session_expired(sib):
    kite_exceptions = pytest.importorskip("kiteconnect.exceptions")
    sib.holdings["ba_i"] = kite_exceptions.TokenException("Token is invalid or has expired.", code=403)
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))


@pytest.mark.parametrize("raised", [
    http_error(500), http_error(429), httpx.ReadTimeout("timed out"), RuntimeError("kiteconnect SDK not installed"),
], ids=["http-500", "http-429", "timeout", "runtime-error"])
def test_other_adapter_failures_are_read_errors_not_session_expiry(sib, raised):
    sib.holdings["ba_i"] = raised
    with pytest.raises(hub.BrokerReadError) as e:
        asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))
    assert not isinstance(e.value, (hub.BrokerSessionExpired, hub.BrokerNotSupported))


@pytest.mark.parametrize("raised", [DayBookNotSupported("no day book"), NotImplementedError()],
                         ids=["name-ends-NotSupported", "NotImplementedError"])
def test_adapter_not_supported_becomes_broker_not_supported(sib, raised):
    sib.holdings["ba_i"] = raised
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_holdings_for(native_account("ba_i", broker="icicidirect")))


def test_a_placeholder_adapter_is_not_supported_and_is_never_called(sib):
    sib.adapter("groww", "Groww", implemented=False)
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_holdings_for(native_account("ba_g", broker="groww")))
    assert sib.reads() == []


def test_a_broker_with_no_adapter_is_not_supported(sib):
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_holdings_for(native_account("ba_x", broker="nosuchbroker")))


def test_a_mapped_adapter_error_carries_no_broker_text(sib, caplog):
    sib.holdings["ba_i"] = http_error(500, text=f'{{"error":"bad token {SECRET}","client":"{CLIENT_ID}"}}')
    db = FakeDB([native_account("ba_i", broker="icicidirect")])
    with caplog.at_level(logging.DEBUG, logger="services.brokers.hub_reads"):
        with pytest.raises(hub.BrokerReadError) as e:
            asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_i")))
    stored = db.broker_accounts.one(account_id="ba_i")["last_error"]
    code, message = hub.describe_failure(e.value, "icicidirect", "holdings")
    assert code == "BROKER_READ_FAILED"
    assert stored == message == "Could not read holdings from ICICI Direct. Please try again."
    for text in (str(e.value), stored, caplog.text):
        assert SECRET not in text and CLIENT_ID not in text
    assert "HTTP 500" in caplog.text                    # the log still says what failed


# ── sync_account ─────────────────────────────────────────────────────────
def _seeded_db():
    return FakeDB(
        accounts=[native_account("ba_z"), native_account("ba_other", broker="icicidirect"),
                  native_account("ba_u2", user_id="u2")],
        holdings=[
            holding_row("CAS-FUND", source="cas", asset_type="mutual_fund"),
            holding_row("MANUAL", source="manual"),
            holding_row("OLD-Z-1", source="broker_native", broker="zerodha", broker_account_id="ba_z"),
            holding_row("OLD-Z-2", source="broker_native", broker="zerodha", broker_account_id="ba_z"),
            holding_row("OTHER-ACCT", source="broker_native", broker="icicidirect", broker_account_id="ba_other"),
            holding_row("OA-ROW", source="openalgo", broker="upstox", broker_account_id="ba_oa"),
            holding_row("U2-ROW", user_id="u2", source="broker_native", broker="zerodha", broker_account_id="ba_u2"),
        ],
    )


def test_native_sync_replaces_only_that_accounts_rows(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    names = sorted(h["name"] for h in db.holdings.docs)
    assert names == sorted(["CAS-FUND", "MANUAL", "OTHER-ACCT", "OA-ROW", "U2-ROW", "Infosys Ltd", "GOLDBEES"])
    mine = [h for h in db.holdings.docs if h.get("broker_account_id") == "ba_z"]
    assert len(mine) == 2 and all(h["user_id"] == "u1" for h in mine)

    assert result["count"] == 2
    assert [set(r) for r in result["holdings"]] == [{"holding_id", "name", "ticker", "asset_type", "quantity"}] * 2
    assert [(r["name"], r["ticker"], r["asset_type"], r["quantity"]) for r in result["holdings"]] == [
        ("Infosys Ltd", "INFY", "equity", 10.0), ("GOLDBEES", "GOLDBEES", "etf", 100.0)]


def test_native_sync_writes_the_stored_row_faithfully(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    infy = db.holdings.one(ticker="INFY")
    assert {k: infy[k] for k in ("user_id", "portfolio_id", "name", "ticker", "asset_type", "quantity", "buy_price",
                                 "current_price", "sector", "buy_date", "source", "source_id", "broker",
                                 "broker_account_id")} == {
        "user_id": "u1", "portfolio_id": "", "name": "Infosys Ltd", "ticker": "INFY", "asset_type": "equity",
        "quantity": 10.0, "buy_price": 1400.5, "current_price": 1525.0, "sector": "IT", "buy_date": None,
        "source": "broker_native", "source_id": "NSE:INFY", "broker": "zerodha", "broker_account_id": "ba_z"}
    assert infy["holding_id"].startswith("hold_") and infy["uploaded_at"] == infy["created_at"]
    assert infy["isin"] == "INE009A01021"           # the ISIN rides alongside; `ticker` stays the trading symbol

    bees = db.holdings.one(ticker="GOLDBEES")       # gaps in the broker's row get the collection's defaults
    assert (bees["name"], bees["sector"], bees["source_id"], bees["asset_type"]) == ("GOLDBEES", "Other", "", "etf")

    # The frontend lists a broker's holdings by these two fields: every native row must carry both.
    for row in db.holdings.docs:
        if row.get("source") == "broker_native" and row.get("broker_account_id") == "ba_z":
            assert row["broker"] == "zerodha" and row["broker_account_id"] == "ba_z"


def test_native_rows_carry_the_isin_upper_cased_and_omit_the_key_when_the_broker_gave_none(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [
        INFY,
        dataclasses.replace(GOLDBEES, isin=" inf204kb17i5 "),
        dataclasses.replace(INFY, symbol="NOISIN", isin=None),
        dataclasses.replace(INFY, symbol="BLANKISIN", isin="  "),
    ]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert db.holdings.one(ticker="INFY")["isin"] == "INE009A01021"
    assert db.holdings.one(ticker="GOLDBEES")["isin"] == "INF204KB17I5"
    assert "isin" not in db.holdings.one(ticker="NOISIN")          # left out, not stored as None or ""
    assert "isin" not in db.holdings.one(ticker="BLANKISIN")
    for row in (h for h in db.holdings.docs if h.get("broker_account_id") == "ba_z"):
        assert {"broker_account_id", "broker", "ticker", "source", "source_id"} <= set(row)


def test_a_holding_the_broker_gives_no_last_price_for_is_stored_at_zero_not_at_an_invented_price(sib):
    # The Groww adapter returns `current_price=0.0`: its holdings payload has no last price.
    db = _seeded_db()
    sib.holdings["ba_z"] = [dataclasses.replace(INFY, current_price=0.0),
                            dataclasses.replace(INFY, symbol="TCS", isin="INE467B01029", current_price=None)]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    for ticker in ("INFY", "TCS"):
        row = db.holdings.one(ticker=ticker)
        assert row["current_price"] == 0.0 and row["buy_price"] == 1400.5    # not filled from the buy price
    assert all("current_price" not in r and "buy_price" not in r for r in result["holdings"])


# ── sync_account: empty rows, and what masterdata fills in ───────────────
def test_instruments_with_no_quantity_are_not_stored_as_holdings(sib):
    # ICICI's demat list keeps sold-out instruments, with every quantity field at zero.
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY, dataclasses.replace(GOLDBEES, quantity=0.0),
                            dataclasses.replace(INFY, symbol="TCS", isin="INE467B01029", quantity=None)]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    assert result["count"] == 1 and [h["ticker"] for h in result["holdings"]] == ["INFY"]
    assert [h["ticker"] for h in db.holdings.docs if h.get("broker_account_id") == "ba_z"] == ["INFY"]
    assert db.broker_accounts.one(account_id="ba_z")["last_sync_count"] == 1


def test_a_row_named_by_the_brokers_own_code_gets_the_company_name_and_a_missing_price(sib, monkeypatch):
    from services import masterdata
    monkeypatch.setattr(hub, "_fill_from_masterdata", REAL_MASTERDATA_FILL)
    monkeypatch.setattr(masterdata, "lookup_isin", lambda isin: (
        {"name": "INFOSYS LIMITED", "price": 1500.0, "source": "nse"} if isin == "INE009A01021" else None))
    db = _seeded_db()
    sib.holdings["ba_z"] = [dataclasses.replace(INFY, name="INFTEC", symbol="INFTEC", current_price=0.0)]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    row = db.holdings.one(ticker="INFTEC")
    assert (row["name"], row["current_price"]) == ("INFOSYS LIMITED", 1500.0)
    # What the broker did give is never touched.
    assert (row["ticker"], row["quantity"], row["buy_price"], row["isin"]) == ("INFTEC", 10.0, 1400.5, "INE009A01021")


def test_a_real_name_and_price_from_the_broker_are_kept(sib, monkeypatch):
    from services import masterdata
    monkeypatch.setattr(hub, "_fill_from_masterdata", REAL_MASTERDATA_FILL)
    monkeypatch.setattr(masterdata, "lookup_isin", lambda isin: {"name": "INFOSYS LIMITED", "price": 9999.0, "source": "nse"})
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    row = db.holdings.one(ticker="INFY")
    assert (row["name"], row["current_price"], row["sector"]) == ("Infosys Ltd", 1525.0, "IT")


def test_a_failed_masterdata_lookup_leaves_the_row_as_the_broker_gave_it(sib, monkeypatch):
    from services import masterdata

    def boom(_isin):
        raise OSError("masterdata volume not mounted")

    monkeypatch.setattr(hub, "_fill_from_masterdata", REAL_MASTERDATA_FILL)
    monkeypatch.setattr(masterdata, "lookup_isin", boom)
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    assert result["count"] == 1 and db.holdings.one(ticker="INFY")["name"] == "Infosys Ltd"


# ── sync_account: the broker wins (helpers.holdings_reconcile) ───────────
def test_native_sync_hands_the_stored_rows_to_the_reconcile(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    (call,) = sib.reconciled                                        # once per sync
    assert (call["user_id"], call["broker"], call["live"]) == ("u1", "zerodha", True)
    stored = [h for h in db.holdings.docs if h.get("broker_account_id") == "ba_z"]
    assert call["rows"] == stored                                   # the row dicts exactly as stored
    assert [(r["isin"], r["ticker"]) for r in call["rows"]] == [("INE009A01021", "INFY"), ("INF204KB17I5", "GOLDBEES")]
    assert [r["holding_id"] for r in call["rows"]] == [r["holding_id"] for r in result["holdings"]]
    # After the rows are in the collection (and the old ones gone), before the caches are cleared.
    assert {r["holding_id"] for r in call["rows"]} <= set(call["in_db"])
    assert "hold_OLD-Z-1" not in call["in_db"]
    tail = [c[0] for c in sib.calls if c[0] in ("holdings_reconcile.apply_broker_wins", "dashboard_cache.invalidate")]
    assert tail == ["holdings_reconcile.apply_broker_wins", "dashboard_cache.invalidate"]


def test_a_reconcile_failure_does_not_fail_the_sync(sib, caplog):
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    sib.reconcile_error = RuntimeError("reconcile exploded")
    with caplog.at_level(logging.DEBUG, logger="services.brokers.hub_reads"):
        result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    assert result["count"] == 2 and len(sib.reconciled) == 1
    assert sorted(h["ticker"] for h in db.holdings.docs if h.get("broker_account_id") == "ba_z") == ["GOLDBEES", "INFY"]
    acct = db.broker_accounts.one(account_id="ba_z")
    assert (acct["status"], acct["last_sync_count"], acct["last_error"]) == ("active", 2, None)
    assert sib.cache_invalidations == ["u1"]                        # carried on past the failure
    assert "reconcile failed account=ba_z broker=zerodha" in caplog.text
    assert SECRET not in caplog.text and CLIENT_ID not in caplog.text


def test_broker_wins_end_to_end_with_the_real_reconcile(sib, monkeypatch):
    # Not a test of holdings_reconcile itself: it checks the rows this sync stores are rows its
    # matcher recognises (ISIN in `isin`; statement rows keep theirs in `ticker`).
    monkeypatch.setattr(hub.holdings_reconcile, "apply_broker_wins", REAL_APPLY_BROKER_WINS)
    db = FakeDB(accounts=[native_account("ba_z")], holdings=[
        holding_row("CAS-INFY", source="cas", ticker="INE009A01021"),                  # the statement's copy of INFY
        holding_row("CAS-OTHER", source="cas", ticker="INE002A01018"),                 # an ISIN the broker lacks
        holding_row("EXPORT-INFY", source="broker_export", broker="zerodha", ticker="INFY", isin="INE009A01021"),
        holding_row("OTHER-ACCT-INFY", source="broker_native", broker="icicidirect", broker_account_id="ba_other",
                    ticker="INFY", isin="INE009A01021"),                               # another connection's row
        holding_row("U2-CAS-INFY", user_id="u2", source="cas", ticker="INE009A01021"),  # another user's statement
    ])
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    assert result["count"] == 2
    assert sorted(h["name"] for h in db.holdings.docs) == sorted([
        "Infosys Ltd", "GOLDBEES",                      # the broker's rows
        "CAS-OTHER", "OTHER-ACCT-INFY", "U2-CAS-INFY",  # untouched
    ])                                                  # CAS-INFY and this broker's export copy are gone


def test_native_sync_never_writes_openalgo_as_the_source(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [INFY]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert db.holdings.one(ticker="INFY")["source"] == hub.NATIVE_SOURCE == "broker_native"
    assert db.holdings.one(name="OA-ROW")["source"] == "openalgo"          # OpenAlgo rows are left as they are


def test_an_unknown_asset_type_falls_back_to_equity_like_the_openalgo_sync(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = [dataclasses.replace(INFY, asset_type="warrant")]
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert result["holdings"][0]["asset_type"] == "equity"


def test_native_sync_updates_the_account_and_clears_caches(sib):
    db = _seeded_db()
    db.broker_accounts.one(account_id="ba_z").update(last_error="Could not read holdings from Zerodha.")
    sib.holdings["ba_z"] = [INFY, GOLDBEES]
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))

    acct = db.broker_accounts.one(account_id="ba_z")
    assert (acct["status"], acct["last_sync_count"], acct["last_error"]) == ("active", 2, None)
    assert acct["last_sync_at"] == acct["updated_at"] and acct["last_sync_at"].endswith("+00:00")
    assert db.broker_accounts.one(account_id="ba_other")["last_sync_at"] is None      # other accounts untouched

    assert db.mfd_profile_signal_cache.docs == []
    assert sib.cache_invalidations == ["u1"]


def test_an_empty_portfolio_clears_the_accounts_rows_and_counts_zero(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = []
    result = asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert result == {"count": 0, "holdings": []}
    assert [h for h in db.holdings.docs if h.get("broker_account_id") == "ba_z"] == []
    assert len(db.holdings.docs) == 5
    assert [c["rows"] for c in sib.reconciled] == [[]]


def test_broker_rejecting_the_token_ends_the_session_and_keeps_stored_holdings(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = hub.BrokerSessionExpired("token rejected")
    before = [dict(h) for h in db.holdings.docs]
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert sib.ended == [("ba_z", "broker_rejected")]
    assert db.holdings.docs == before
    assert sib.cache_invalidations == [] and sib.reconciled == []


def test_an_ended_session_is_not_synced_and_not_ended_twice(sib):
    db = _seeded_db()
    db.broker_accounts.one(account_id="ba_z").update(status="expired", session_ended_reason="logout")
    before = [dict(h) for h in db.holdings.docs]
    with pytest.raises(hub.sessions.SessionEnded):
        asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    assert sib.ended == [] and sib.reads() == []
    assert db.holdings.docs == before
    assert db.broker_accounts.one(account_id="ba_z")["session_ended_reason"] == "logout"


def test_a_failed_read_keeps_stored_holdings_and_records_the_error(sib):
    db = _seeded_db()
    sib.holdings["ba_z"] = hub.BrokerReadError("fenix: upstream timeout")
    before = [dict(h) for h in db.holdings.docs]
    with pytest.raises(hub.BrokerReadError):
        asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    acct = db.broker_accounts.one(account_id="ba_z")
    assert acct["last_error"] == "Could not read holdings from Zerodha. Please try again."
    assert acct["status"] == "active"               # a failed read does not end, or relabel, the session
    assert acct["last_sync_at"] is None and sib.ended == []
    assert db.holdings.docs == before
    assert sib.reconciled == []                     # nothing was stored, so nothing is reconciled


def test_a_sync_that_finishes_after_the_session_was_ended_does_not_reactivate_it(sib):
    db = _seeded_db()

    async def logged_out_mid_read():
        await sib.end_session(db, "ba_z", "logout")
        return [INFY]

    sib.holdings["ba_z"] = logged_out_mid_read
    asyncio.run(hub.sync_account(db, db.broker_accounts.one(account_id="ba_z")))
    acct = db.broker_accounts.one(account_id="ba_z")
    assert (acct["status"], acct["session_ended_reason"]) == ("expired", "logout")


# ── Positions ────────────────────────────────────────────────────────────
POSITION_KEYS = {f.name for f in dataclasses.fields(hub.HubPosition)}


def test_position_shape_includes_name():
    assert {"symbol", "exchange", "quantity", "avg_price", "last_price", "pnl", "product", "product_raw", "segment",
            "is_intraday", "instrument_type", "expiry", "strike", "kind", "name"} <= POSITION_KEYS


@pytest.mark.parametrize("kind", ["net", "day"])
def test_fenix_positions_pass_the_kind_and_come_back_as_dicts(sib, kind):
    sib.positions["ba_z"] = lambda k: [hub_position(kind=k)]
    doc = native_account("ba_z")
    rows = asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, kind))
    assert sib.reads() == [("fenix.read_positions", "zerodha", "ba_z", kind)]
    assert rows == [dataclasses.asdict(hub_position(kind=kind))]
    assert rows[0]["name"] == "Nifty 50 Oct Fut" and set(rows[0]) == POSITION_KEYS


def test_positions_default_to_the_net_book(sib):
    doc = native_account("ba_z")
    asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))
    assert sib.reads() == [("fenix.read_positions", "zerodha", "ba_z", "net")]


@pytest.mark.parametrize("kind", ["net", "day"])
def test_adapter_with_fetch_hub_positions_serves_both_books_itself(sib, kind):
    sib.adapter("icicidirect", "ICICI Direct", rich=True)
    sib.positions["ba_i"] = lambda k: [hub_position("RELIANCE", exchange="NSE", segment="equity", kind=k,
                                                    instrument_type=None, expiry=None, name="Reliance Industries")]
    doc = native_account("ba_i", broker="icicidirect")
    rows = asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, kind))
    assert sib.reads() == [("adapter.fetch_hub_positions", "icicidirect", "ba_i", kind)]     # not fetch_positions
    assert rows[0]["kind"] == kind and rows[0]["name"] == "Reliance Industries" and set(rows[0]) == POSITION_KEYS


@pytest.mark.parametrize("raised", [DayBookNotSupported("no day book"), NotImplementedError()],
                         ids=["name-ends-NotSupported", "NotImplementedError"])
def test_fetch_hub_positions_saying_not_supported_becomes_broker_not_supported(sib, raised):
    sib.adapter("icicidirect", "ICICI Direct", rich=True)
    sib.positions["ba_i"] = raised
    doc = native_account("ba_i", broker="icicidirect")
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, "day"))
    assert sib.reads() == [("adapter.fetch_hub_positions", "icicidirect", "ba_i", "day")]   # no fallback to net


def test_fetch_hub_positions_session_expiry_ends_the_session(sib):
    sib.adapter("icicidirect", "ICICI Direct", rich=True)
    sib.positions["ba_i"] = IciciSessionExpired("session timed out")
    doc = native_account("ba_i", broker="icicidirect")
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))
    assert sib.ended == [("ba_i", "broker_rejected")]


def test_adapter_without_fetch_hub_positions_serves_net_through_fetch_positions(sib):
    sib.positions["ba_i"] = [
        Position(symbol="NIFTY26OCT25000CE", exchange="NFO", quantity=-75, avg_price=120.5, pnl=-1500.0, product="NRML"),
        Position(symbol="INFY", exchange="NSE", quantity=20, avg_price=1500.0, pnl=250.0, product="MIS"),
    ]
    doc = native_account("ba_i", broker="icicidirect")
    rows = asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, "net"))
    assert sib.reads() == [("adapter.fetch_positions", "icicidirect", "ba_i")]
    assert all(set(r) == POSITION_KEYS for r in rows)
    assert rows[0] == {
        "symbol": "NIFTY26OCT25000CE", "exchange": "NFO", "quantity": -75.0, "avg_price": 120.5, "last_price": None,
        "pnl": -1500.0, "product": "carryforward", "product_raw": "NRML", "segment": "fno", "is_intraday": False,
        "instrument_type": None, "expiry": None, "strike": None, "kind": "net", "name": None}
    assert (rows[1]["segment"], rows[1]["product"], rows[1]["is_intraday"]) == ("equity", "intraday", True)


def test_adapter_without_fetch_hub_positions_cannot_serve_the_day_book(sib):
    # Net rows must never be returned labelled as day rows.
    sib.positions["ba_i"] = [Position(symbol="INFY", exchange="NSE", quantity=20, avg_price=1500.0)]
    doc = native_account("ba_i", broker="icicidirect")
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, "day"))
    assert sib.reads() == []


@pytest.mark.parametrize("exchange,segment", [
    ("NFO", "fno"), ("BFO", "fno"), ("MCX", "commodity"), ("CDS", "currency"), ("BCD", "currency"),
    ("NSE", "equity"), ("BSE", "equity"), ("nfo", "fno"), ("", "equity")])
def test_adapter_position_segment_comes_from_the_exchange(sib, exchange, segment):
    sib.positions["ba_i"] = [Position(symbol="X", exchange=exchange, quantity=1, avg_price=1.0)]
    doc = native_account("ba_i", broker="icicidirect")
    assert asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))[0]["segment"] == segment


@pytest.mark.parametrize("code,product,intraday", [
    ("MIS", "intraday", True), ("I", "intraday", True), ("INTRADAY", "intraday", True), ("BO", "intraday", True),
    ("CO", "intraday", True), ("mis", "intraday", True),
    ("CNC", "delivery", False), ("D", "delivery", False), ("DELIVERY", "delivery", False),
    ("NRML", "carryforward", False), ("CARRYFORWARD", "carryforward", False),
    ("MTF", "margin", False), ("MARGIN", "margin", False),
    ("SOMETHING_NEW", None, False), (None, None, False), ("", None, False)])
def test_adapter_position_product_and_intraday_come_from_the_product_code(sib, code, product, intraday):
    sib.positions["ba_i"] = [Position(symbol="X", exchange="NSE", quantity=1, avg_price=1.0, product=code)]
    doc = native_account("ba_i", broker="icicidirect")
    row = asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))[0]
    assert (row["product"], row["is_intraday"]) == (product, intraday)
    assert row["product_raw"] == (code or None)         # the broker's own code is kept, an unknown one is not guessed


def test_adapter_position_name_is_passed_through_only_when_the_adapter_has_one(sib):
    @dataclass
    class NamedPosition(Position):
        name: Optional[str] = None

    sib.positions["ba_i"] = [NamedPosition(symbol="INFY", exchange="NSE", quantity=1, avg_price=1.0, name="Infosys Ltd"),
                             Position(symbol="TCS", exchange="NSE", quantity=1, avg_price=1.0)]
    doc = native_account("ba_i", broker="icicidirect")
    rows = asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))
    assert [r["name"] for r in rows] == ["Infosys Ltd", None]


def test_positions_are_read_live_and_never_stored(sib):
    db = _seeded_db()
    before = ([dict(h) for h in db.holdings.docs], [dict(a) for a in db.broker_accounts.docs])
    sib.positions["ba_z"] = [hub_position()]
    asyncio.run(hub.read_account_positions(db, db.broker_accounts.one(account_id="ba_z")))
    assert (db.holdings.docs, db.broker_accounts.docs) == before
    assert not hasattr(db, "positions") and sib.cache_invalidations == []


def test_positions_token_rejection_ends_the_session(sib):
    sib.positions["ba_z"] = hub.BrokerSessionExpired("token rejected")
    db = FakeDB([native_account("ba_z")])
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.read_account_positions(db, db.broker_accounts.one(account_id="ba_z")))
    assert sib.ended == [("ba_z", "broker_rejected")]


def test_positions_for_an_ended_session_raise_without_a_broker_call(sib):
    doc = native_account("ba_z", status="expired")
    with pytest.raises(hub.sessions.SessionEnded):
        asyncio.run(hub.read_account_positions(FakeDB([doc]), doc))
    assert sib.reads() == [] and sib.ended == []


def test_positions_reject_an_unknown_kind(sib):
    doc = native_account("ba_z")
    with pytest.raises(ValueError):
        asyncio.run(hub.read_account_positions(FakeDB([doc]), doc, "weekly"))
    assert sib.calls == []


# ── describe_failure ─────────────────────────────────────────────────────
def test_describe_failure_codes(sib):
    raw = f"RAW-BROKER-TEXT {SECRET}"
    cases = [
        (hub.sessions.SessionEnded(raw), "BROKER_SESSION_EXPIRED"),
        (hub.BrokerSessionExpired(raw), "BROKER_SESSION_EXPIRED"),
        (hub.BrokerNotSupported(raw), "BROKER_READ_NOT_SUPPORTED"),
        (hub.BrokerReadError(raw), "BROKER_READ_FAILED"),
        (KeyError(raw), "BROKER_READ_FAILED"),
    ]
    for exc, code in cases:
        got, message = hub.describe_failure(exc, "zerodha", "holdings")
        assert got == code and "Zerodha" in message
        assert "RAW-BROKER-TEXT" not in message and SECRET not in message   # never the exception's own text


# ── daily_sync ───────────────────────────────────────────────────────────
def test_daily_sync_counts_a_mix_of_live_expired_and_failing_accounts(sib, caplog):
    db = FakeDB(accounts=[
        native_account("ba_ok1", user_id="u1"),
        native_account("ba_ok2", user_id="u2", broker="icicidirect"),
        native_account("ba_due", user_id="u3", _due=True),                    # expired by the sweep
        native_account("ba_gone", user_id="u4", status="expired"),            # ended before this run
        native_account("ba_rejected", user_id="u5"),                          # broker refuses the token
        native_account("ba_fail", user_id="u6"),                              # broker read fails
        native_account("ba_crash", user_id="u7", broker="icicidirect"),       # adapter blows up
        native_account("ba_oa", user_id="u8", native=False, openalgo_url="http://oa.local:5000"),
    ], holdings=[holding_row("KEEP-FAIL", user_id="u6", source="broker_native", broker_account_id="ba_fail")])
    sib.holdings.update({
        "ba_ok1": [INFY, GOLDBEES], "ba_ok2": [INFY],
        "ba_rejected": hub.BrokerSessionExpired("token rejected"),
        "ba_fail": hub.BrokerReadError(f"upstream said {SECRET}"),
        "ba_crash": RuntimeError(f"payload for {CLIENT_ID}"),
    })

    with caplog.at_level(logging.DEBUG, logger="services.brokers.hub_reads"):
        summary = asyncio.run(hub.daily_sync(db))

    assert summary == {"accounts": 7, "synced": 2, "expired": 3, "failed": 2}
    assert summary["accounts"] == summary["synced"] + summary["expired"] + summary["failed"]

    assert sib.calls[0] == ("sessions.expire_due_sessions", None)             # the sweep runs first, for everyone
    read = {c[2] for c in sib.reads()}
    assert read == {"ba_ok1", "ba_ok2", "ba_rejected", "ba_fail", "ba_crash"}  # never due / gone / the OpenAlgo row
    assert sib.ended == [("ba_rejected", "broker_rejected")]

    assert db.broker_accounts.one(account_id="ba_ok1")["last_sync_count"] == 2
    assert db.broker_accounts.one(account_id="ba_ok2")["last_sync_count"] == 1
    assert db.broker_accounts.one(account_id="ba_due")["status"] == "expired"
    assert db.broker_accounts.one(account_id="ba_fail")["last_error"].startswith("Could not read holdings")
    assert db.broker_accounts.one(account_id="ba_oa")["last_sync_at"] is None
    assert db.holdings.one(name="KEEP-FAIL")                                   # a failed account keeps its rows
    assert len([h for h in db.holdings.docs if h.get("broker_account_id") in ("ba_ok1", "ba_ok2")]) == 3

    assert "broker daily sync: accounts=7 synced=2 expired=3 failed=2" in caplog.text
    assert SECRET not in caplog.text and CLIENT_ID not in caplog.text


def test_daily_sync_with_no_native_accounts(sib):
    assert asyncio.run(hub.daily_sync(FakeDB())) == {"accounts": 0, "synced": 0, "expired": 0, "failed": 0}
    assert sib.calls == [("sessions.expire_due_sessions", None)]


def test_daily_sync_reads_a_bounded_number_of_accounts_at_once(sib):
    n = hub.DAILY_SYNC_CONCURRENCY * 3
    state = {"now": 0, "peak": 0}

    async def slow_read():
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.005)
        state["now"] -= 1
        return [INFY]

    db = FakeDB(accounts=[native_account(f"ba_{i}", user_id=f"u{i}") for i in range(n)])
    for i in range(n):
        sib.holdings[f"ba_{i}"] = slow_read
    summary = asyncio.run(hub.daily_sync(db))
    assert summary == {"accounts": n, "synced": n, "expired": 0, "failed": 0}
    assert 1 < state["peak"] <= hub.DAILY_SYNC_CONCURRENCY


# ── The scheduled job (services/mf_scheduler.py) ─────────────────────────
def _scheduler(monkeypatch, switch: str):
    from services import mf_scheduler as sched
    from services.brokers import _helpers

    asked, runs = [], []
    monkeypatch.setattr(_helpers, "conf", lambda key: asked.append(key) or switch)

    async def fake_daily_sync(db):
        runs.append(db)
        return {"accounts": 0, "synced": 0, "expired": 0, "failed": 0}
    monkeypatch.setattr(hub, "daily_sync", fake_daily_sync)
    return sched, asked, runs


@pytest.mark.parametrize("switch", ["0", "false", "off", "no", "OFF", "False", "No"])
def test_daily_job_is_skipped_when_switched_off(monkeypatch, switch):
    sched, asked, runs = _scheduler(monkeypatch, switch)
    asyncio.run(sched._broker_daily_sync_job())
    assert asked == ["BROKER_DAILY_SYNC_ENABLED"] and runs == []


@pytest.mark.parametrize("switch", ["", "1", "true", "on", "yes"])
def test_daily_job_runs_by_default_and_when_switched_on(monkeypatch, switch):
    sched, asked, runs = _scheduler(monkeypatch, switch)
    asyncio.run(sched._broker_daily_sync_job())
    assert asked == ["BROKER_DAILY_SYNC_ENABLED"]
    assert runs == [sched.db]                           # the scheduler module's own db handle (deps.db)


def test_daily_job_logs_a_failure_instead_of_raising(monkeypatch, caplog):
    sched, _, _ = _scheduler(monkeypatch, "")

    async def boom(db):
        raise RuntimeError("mongo is down")
    monkeypatch.setattr(hub, "daily_sync", boom)
    with caplog.at_level(logging.WARNING, logger="services.mf_scheduler"):
        asyncio.run(sched._broker_daily_sync_job())
    assert "broker_daily_sync error: mongo is down" in caplog.text


def test_daily_job_is_registered_for_1730_ist_without_overlap():
    from services import mf_scheduler as sched

    async def registered():
        sched.start()
        try:
            job = sched._scheduler.get_job("broker_holdings_sync_daily")
            ids = [j.id for j in sched._scheduler.get_jobs()]
            return (job.func, str(job.trigger), str(job.trigger.timezone), job.max_instances,
                    job.next_run_time.strftime("%H:%M %z"), ids)
        finally:
            sched.stop()
            await asyncio.sleep(0.05)

    func, trigger, tz, max_instances, next_run, ids = asyncio.run(registered())
    assert func is sched._broker_daily_sync_job
    assert trigger == "cron[hour='17', minute='30']"
    assert tz == "Asia/Kolkata" and next_run == "17:30 +0530"   # IST whatever the container's local zone is
    assert max_instances == 1                                    # a run still going is not started again
    assert ids.count("broker_holdings_sync_daily") == 1
