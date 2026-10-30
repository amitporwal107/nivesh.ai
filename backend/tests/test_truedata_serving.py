"""TrueData serving the live feed: TS-1 … TS-11 in test_reports/truedata_serving_TESTCASES.md.

No network, no Mongo, no TrueData. Replaced, and by what:
  * TrueData's symbol master  FakeClient below (rows in the shape of the real getAllSymbols answer read on 30 Oct 2026)
  * TrueData's WebSocket      FakeSocket below, scripted in the formats of TrueData's Market Data API documentation v2.6
  * Mongo                     tests.test_kite_live_feed.FakeDB
MOCK — not real data: every symbol id, price, quantity and login below is made up.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from nidp.shared import market_data_source as mds
from services.kite_live_feed import feed as kf
from services.kite_live_feed import universe as uni
from services.truedata_live import checks as ck
from services.truedata_live import gateway as tg
from services.truedata_live import protocol as pr
from services.truedata_live import serve
from services.truedata_live import shadow as sh
from tests.test_kite_live_feed import FakeDB

IST = pr.IST
OPEN = datetime(2026, 10, 30, 10, 0, 0, tzinfo=IST)                  # a Friday, mid-session
TODAY = OPEN.date()
WS_PASSWORD = "ws-S3CRET-pw"
REST_PASSWORD = "rest-S3CRET-pw"
ENV = {"TRUEDATA_WS_USERNAME": "trial-x", "TRUEDATA_WS_PASSWORD": WS_PASSWORD, "TRUEDATA_WS_PORT": "8086",
       "TRUEDATA_USERNAME": "rest-x", "TRUEDATA_PASSWORD": REST_PASSWORD, "TRUEDATA_INDICES": "NIFTY 50,NIFTY BANK"}

EQ = [
    {"symbolid": 100001262, "symbol": "RELIANCE", "series": "EQ", "lotsize": 1, "company": "Reliance Industries Limited",
     "tick_size": 0.1, "circuit_low": 1050.7, "circuit_high": 1284.1},
    {"symbolid": 100016683, "symbol": "RELIANCE0", "series": "T0", "lotsize": 1, "tick_size": 0.1},     # not EQ: left out
    {"symbolid": 100000001, "symbol": "AAAA", "series": "EQ", "lotsize": 1, "tick_size": 0.05},
]
FO = [
    {"symbolid": 900000596, "symbol": "NIFTY-I", "series": "XX", "lotsize": 65, "underlying": "NIFTY", "expiry_date": "2026-11-23", "tick_size": 0.1},
    {"symbolid": 900000598, "symbol": "NIFTY-II", "series": "XX", "lotsize": 65, "underlying": "NIFTY", "expiry_date": "2026-12-29", "tick_size": 0.1},
    {"symbolid": 900000702, "symbol": "RELIANCE-I", "series": "XX", "lotsize": 500, "underlying": "RELIANCE", "expiry_date": "2026-11-23", "tick_size": 0.1},
    {"symbolid": 303000001, "symbol": "NIFTY26110322900CE", "series": "CE", "lotsize": 65, "underlying": "NIFTY", "strike": 22900, "expiry_date": "2026-11-03", "tick_size": 0.05},
    {"symbolid": 303000002, "symbol": "NIFTY26110322900PE", "series": "PE", "lotsize": 65, "underlying": "NIFTY", "strike": 22900, "expiry_date": "2026-11-03", "tick_size": 0.05},
    {"symbolid": 303000003, "symbol": "NIFTY26110322950CE", "series": "CE", "lotsize": 65, "underlying": "NIFTY", "strike": 22950, "expiry_date": "2026-11-03", "tick_size": 0.05},
    {"symbolid": 303000004, "symbol": "NIFTY26112322900CE", "series": "CE", "lotsize": 65, "underlying": "NIFTY", "strike": 22900, "expiry_date": "2026-11-23", "tick_size": 0.05},
    {"symbolid": 302991666, "symbol": "RELIANCE2611231172.5PE", "series": "PE", "lotsize": 500, "underlying": "RELIANCE", "strike": 1172.5, "expiry_date": "2026-11-23", "tick_size": 0.05},
    {"symbolid": 303000009, "symbol": "BROKEN", "series": "CE", "lotsize": 65, "underlying": "NIFTY", "strike": None, "expiry_date": "2026-11-03"},
]


class FakeClient:
    def __init__(self):
        self.calls = []

    def symbol_master(self, segment, search=None, limit=None):
        self.calls.append(segment)
        return {"eq": EQ, "fo": FO}[segment]


def rows():
    return tg.instrument_rows(EQ, FO, ["NIFTY 50", "NIFTY BANK"])


# ── TS-1 … TS-4: instruments ─────────────────────────────────────────────────
def test_ts1_nse_rows_are_eq_and_the_configured_indices():
    nse, _, names, meta = rows()
    by = {r["tradingsymbol"]: r for r in nse}
    assert set(by) == {"NIFTY 50", "NIFTY BANK", "RELIANCE", "AAAA"}               # RELIANCE0 (T0) is left out
    assert by["RELIANCE"]["instrument_token"] == 100001262 and by["RELIANCE"]["segment"] == "NSE"
    assert by["RELIANCE"]["instrument_type"] == "EQ" and by["RELIANCE"]["tick_size"] == 0.1
    assert by["NIFTY 50"]["segment"] == "INDICES" and by["NIFTY 50"]["instrument_token"] >= tg.INDEX_TOKEN_BASE
    assert meta["RELIANCE"].circuit_low == 1050.7 and meta["NIFTY 50"].kind == "INDEX"


def test_ts2_continuous_futures_become_dated_kite_futures():
    _, nfo, names, _ = rows()
    futs = {r["tradingsymbol"]: r for r in nfo if r["instrument_type"] == "FUT"}
    assert set(futs) == {"NIFTY26NOVFUT", "NIFTY26DECFUT", "RELIANCE26NOVFUT"}
    f = futs["NIFTY26NOVFUT"]
    assert (f["name"], f["expiry"], f["lot_size"], f["segment"], f["instrument_token"]) == ("NIFTY", date(2026, 11, 23), 65, "NFO-FUT", 900000596)
    assert names["NIFTY26NOVFUT"] == "NIFTY26NOVFUT"                               # TrueData subscribes the dated name


@pytest.mark.parametrize("u, e, k, r, monthly, want", [
    ("NIFTY", date(2026, 11, 3), 22900, "CE", False, "NIFTY26N0322900CE"),
    ("NIFTY", date(2026, 11, 23), 22900, "CE", True, "NIFTY26NOV22900CE"),
    ("RELIANCE", date(2026, 11, 23), 1172.5, "PE", True, "RELIANCE26NOV1172.5PE"),
    ("NIFTY", date(2027, 1, 6), 23000, "PE", False, "NIFTY2710623000PE"),
    ("NIFTY", date(2026, 10, 6), 25000, "CE", False, "NIFTY26O0625000CE"),
    ("NIFTY", date(2026, 12, 1), 23500, "CE", False, "NIFTY26D0123500CE"),
])
def test_ts3_kite_option_names(u, e, k, r, monthly, want):
    assert tg.kite_option_symbol(u, e, k, r, monthly) == want


def test_ts3_monthly_is_the_last_expiry_of_the_month_and_names_map_back_to_truedata():
    _, nfo, names, _ = rows()
    opts = {r["tradingsymbol"] for r in nfo if r["instrument_type"] in ("CE", "PE")}
    assert opts == {"NIFTY26N0322900CE", "NIFTY26N0322900PE", "NIFTY26N0322950CE", "NIFTY26NOV22900CE", "RELIANCE26NOV1172.5PE"}
    assert names["NIFTY26N0322900CE"] == "NIFTY26110322900CE" and names["NIFTY26NOV22900CE"] == "NIFTY26112322900CE"
    assert tg.monthly_expiries([date(2026, 11, 3), date(2026, 11, 23), date(2026, 12, 1)]) == {date(2026, 11, 23), date(2026, 12, 1)}


def test_ts4_the_kite_universe_code_reads_the_rows():
    nse, nfo, _, _ = rows()
    assert uni.index_symbols(nse) == ["NIFTY 50", "NIFTY BANK"]
    assert uni.fno_underlyings(nfo) == ["NIFTY", "RELIANCE"]
    near = {f["underlying"]: f for f in uni.near_month_futures(nfo, TODAY)}
    assert near["NIFTY"]["symbol"] == "NIFTY26NOVFUT" and near["NIFTY"]["lot_size"] == 65 and near["NIFTY"]["expiry"] == "2026-11-23"
    chains = uni.option_contracts(nfo, ["NIFTY"], TODAY, 2)
    assert sorted(chains["NIFTY"]) == ["2026-11-03", "2026-11-23"]
    c = next(x for x in chains["NIFTY"]["2026-11-03"] if x["strike"] == 22950.0)
    assert (c["symbol"], c["option_type"], c["token"]) == ("NIFTY26N0322950CE", "CE", 303000003)


def test_ts4_the_adapter_loads_the_master_once_a_day_and_quote_answers_nothing():
    client, clock = FakeClient(), [OPEN]
    a = tg.TrueDataAsKite(client=client, indices=["NIFTY 50"], clock=lambda: clock[0])
    a.instruments("NSE"); a.instruments("NFO")
    assert client.calls == ["eq", "fo"]
    clock[0] = OPEN + timedelta(days=1)
    a.instruments("NSE")
    assert client.calls == ["eq", "fo", "eq", "fo"]
    assert a.quote(["NSE:RELIANCE"]) == {} and a.tokens[100001262] == "RELIANCE"


# ── TS-5 … TS-8: the ticker ──────────────────────────────────────────────────
def tl(sym, sid, ltp, bid=0, ask=0, vol=1000, oi=0, prev=99.8):
    return [sym, sid, "2026-10-30T10:00:01", str(ltp), "0", str(ltp), str(vol), "100", "101", "99.5", str(prev), str(oi),
            "0", "0", str(bid), "10", str(ask), "12"]


def trade(sid, ltp, vol, bid=0, ask=0, seq=1, oi=0):
    return {"trade": [sid, "2026-10-30T10:00:02", str(ltp), "5", str(ltp), str(vol), "100", "101", "99.5", "99.8", str(oi),
                      "0", "0", "", str(seq), str(bid), "10", str(ask), "12"]}


LOGIN = {"success": True, "message": "TrueData Real Time Data Service", "segments": ["EQ", "FO", "IND"], "maxsymbols": 50,
         "subscription": "tick", "validity": "2026-12-31T00:00:00"}


class Recorder:
    def __init__(self, t):
        self.ticks, self.errors, self.closes, self.connected = [], [], [], 0
        t.on_ticks = lambda ws, ticks: self.ticks.append(list(ticks))
        t.on_error = lambda ws, code, reason: self.errors.append((code, reason))
        t.on_close = lambda ws, code, reason: self.closes.append((code, reason))
        t.on_connect = lambda ws, resp: setattr(self, "connected", self.connected + 1)


def ticker(names, dq=None):
    t = tg.TrueDataKiteTicker({}, lambda: names, dq=dq, clock=lambda: OPEN)
    return t, Recorder(t)


def test_ts5_trade_and_touchline_become_kite_ticks_and_bidask_updates_the_depth():
    t, rec = ticker({100001262: "RELIANCE"})
    t._handle(json.dumps({"success": True, "message": "symbols added", "symbollist": [tl("RELIANCE", "7001", 1160.2, 1160.1, 1160.2)]}), OPEN)
    t._handle(json.dumps(trade("7001", 1160.3, 2000, bid=1160.2, ask=1160.3, oi=0)), OPEN)
    t._handle(json.dumps({"bidask": ["7001", "2026-10-30T10:00:03", "1160.25", "40", "1160.35", "30"]}), OPEN)
    first, second, third = rec.ticks[0][0], rec.ticks[1][0], rec.ticks[2][0]
    assert first["instrument_token"] == 100001262 and first["last_price"] == 1160.2
    assert first["ohlc"] == {"open": 100.0, "high": 101.0, "low": 99.5, "close": 99.8}
    assert second["volume_traded"] == 2000 and second["exchange_timestamp"] == datetime(2026, 10, 30, 10, 0, 2, tzinfo=IST)
    assert second["depth"] == {"buy": [{"price": 1160.2, "quantity": 10.0}], "sell": [{"price": 1160.3, "quantity": 12.0}]}
    assert third["last_price"] == 1160.3 and third["depth"]["buy"][0]["price"] == 1160.25
    q = kf.make_quote("RELIANCE", third["last_price"], third["ohlc"], third["volume_traded"], third["oi"],
                      third["exchange_timestamp"], OPEN, third["depth"])
    assert (q["bid"], q["ask"], q["close"], q["exchange_ts"]) == (1160.25, 1160.35, 99.8, "2026-10-30T10:00:02+05:30")


def test_ts6_a_crossed_book_is_never_published_and_is_counted():
    checks = serve.ServingChecks(FakeDB(), lambda: {"RELIANCE": ck.SymbolMeta("EQ", 0.1, 1050, 1290)}, env=ENV, clock=lambda: OPEN)
    t, rec = ticker({100001262: "RELIANCE"}, dq=checks)
    t._handle(json.dumps({"success": True, "message": "symbols added", "symbollist": [tl("RELIANCE", "7001", 1160.2, 1160.1, 1160.2)]}), OPEN)
    t._handle(json.dumps({"bidask": ["7001", "2026-10-30T10:00:03", "1195.8", "40", "1126.2", "30"]}), OPEN)    # the 30 Oct shape
    crossed = rec.ticks[-1][0]
    assert crossed["depth"] is None and crossed["last_price"] == 1160.2
    q = kf.make_quote("RELIANCE", crossed["last_price"], crossed["ohlc"], None, None, None, OPEN, crossed["depth"])
    assert q["bid"] is None and q["ask"] is None
    sample = checks.shadow._minute_for(OPEN).samples["CROSSED_BOOK"][0]
    assert sample["kind"] == "bidask" and sample["raw"][2:5] == ["1195.8", "40", "1126.2"]


class FakeSocket:
    """Scripted TrueData socket: plays `script`, then heartbeats until closed. Records what was sent."""

    def __init__(self, script):
        self.script, self.sent, self.closed = list(script), [], False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        self.closed = True

    async def recv(self):
        if self.closed:
            raise ConnectionError("closed")
        if self.script:
            m = self.script.pop(0)
            return m if isinstance(m, str) else json.dumps(m)
        await asyncio.sleep(0.02)
        return json.dumps({"success": True, "message": "HeartBeat", "timestamp": "2026-10-30T10:00:05"})


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_ts7_subscribes_up_to_the_symbol_limit_in_order_and_sends_only_the_difference():
    names = {1: "AAAA", 2: "BBBB", 3: "CCCC"}
    sock = FakeSocket([{**LOGIN, "maxsymbols": 2}])
    t = tg.TrueDataKiteTicker({}, lambda: names, connect=lambda creds: sock, clock=lambda: OPEN)
    rec = Recorder(t)
    t.subscribe([1, 2, 3])
    t.connect(threaded=True)
    assert wait_for(lambda: any(m.get("method") == "addsymbol" for m in sock.sent))
    assert sock.sent[0] == {"method": "addsymbol", "symbols": ["AAAA", "BBBB"]} and t.over_limit == ["CCCC"]
    t.unsubscribe([1])
    assert wait_for(lambda: any(m.get("method") == "removesymbol" for m in sock.sent))
    assert {"method": "removesymbol", "symbols": ["AAAA"]} in sock.sent and {"method": "addsymbol", "symbols": ["CCCC"]} in sock.sent
    t.close()
    assert wait_for(lambda: rec.closes)
    assert {"method": "logout"} in sock.sent


def test_ts8_a_refused_login_is_an_auth_failure_and_heartbeats_count_as_liveness():
    sock = FakeSocket([{"success": False, "message": "User already connected", "maxsymbols": 0}])
    t = tg.TrueDataKiteTicker({}, lambda: {}, connect=lambda creds: sock, clock=lambda: OPEN)
    from services.kite_live_feed import gateway as kgw
    src = kgw.TickerSource("truedata", "marker", lambda tok, tick: None, factory=lambda k, tok: t)   # installs its callbacks
    src.start([])
    assert wait_for(lambda: src.auth_failed and src.last_error.startswith("closed"))
    assert not src.healthy() and not src.connected and not sock.sent          # no subscription after a refused login
    alive = FakeSocket([LOGIN])
    t2 = tg.TrueDataKiteTicker({}, lambda: {}, connect=lambda creds: alive, clock=lambda: OPEN)
    src2 = kgw.TickerSource("truedata", "marker", lambda tok, tick: None, factory=lambda k, tok: t2)
    src2.start([])
    assert wait_for(lambda: src2.connected and src2.healthy())
    src2.stop()


# ── TS-9: the LiveFeed end to end on TrueData ────────────────────────────────
class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    async def sleep(self, s):
        self.now += timedelta(seconds=s)


def test_ts9_the_live_feed_publishes_truedata_quotes_under_kite_names(monkeypatch):
    sockets = []

    def connect(creds):
        assert creds["TRUEDATA_WS_PASSWORD"] == WS_PASSWORD
        s = FakeSocket([LOGIN, {"success": True, "message": "symbols added", "symbollist": [
            tl("NIFTY 50", "8001", 22950.5), tl("RELIANCE", "7001", 1160.2, 1160.1, 1160.2),
            tl("NIFTY26NOVFUT", "9001", 23005.0, 23004.0, 23005.5, oi=15800000)]}])
        sockets.append(s)
        return s

    async def no_holidays(day):
        return set()

    async def no_n500():
        return []

    monkeypatch.setattr(kf.cfg, "option_underlyings", lambda: ["NIFTY"])
    clock, db = Clock(OPEN.astimezone(timezone.utc)), FakeDB()
    feed, adapter, checks = serve.build_feed(db, env=ENV, client=FakeClient(), connect=connect, clock=clock,
                                             holder="h1", sleep=clock.sleep, cadence=5, force_rest=False,
                                             load_holidays=no_holidays, load_nifty500=no_n500)
    assert feed.provider == "truedata"
    asyncio.run(feed.tick())                                   # loads the master, builds the universe, starts the ticker
    assert wait_for(lambda: {"NIFTY 50", "RELIANCE", "NIFTY26NOVFUT"} <= set(feed.quotes))
    asyncio.run(feed.tick())                                   # the spot is known now: the NIFTY options join the window
    assert wait_for(lambda: any("NIFTY26110322950CE" in m.get("symbols", []) for m in sockets[0].sent))
    snap = feed.snapshot
    assert snap["source"] == "ws" and feed.state == "live"
    by = {q["symbol"]: q for q in snap["quotes"]}
    assert by["RELIANCE"]["ltp"] == 1160.2 and by["RELIANCE"]["bid"] == 1160.1
    assert by["NIFTY26NOVFUT"]["instrument"] == "FUT" and by["NIFTY26NOVFUT"]["lot_size"] == 65
    assert by["NIFTY26NOVFUT"]["oi"] == 15800000
    assert any(k[0] == "NIFTY" and k[1] == "2026-11-03" for k in feed._chains)
    chain = feed._chains[("NIFTY", "2026-11-03")]
    assert "NFO:NIFTY26N0322950CE" in chain.values()
    st = db[kf.COL_SNAP].docs.get("status") or {}
    assert st.get("provider") == "truedata" and st.get("state") == "live"
    feed._stop_ticker()


def test_ts9_without_a_websocket_login_the_feed_says_so_in_truedata_words():
    async def no_holidays(day):
        return set()
    clock, db = Clock(OPEN.astimezone(timezone.utc)), FakeDB()
    feed, _, _ = serve.build_feed(db, env={"TRUEDATA_USERNAME": "rest-x", "TRUEDATA_PASSWORD": REST_PASSWORD},
                                  client=FakeClient(), clock=clock, holder="h1", sleep=clock.sleep, cadence=5,
                                  load_holidays=no_holidays)
    asyncio.run(feed.tick())
    assert feed.state == "not_connected" and "TrueData WebSocket login" in feed.message and "Kite" not in feed.message


def test_ts9_the_kite_feed_is_unchanged_by_default():
    f = kf.LiveFeed(FakeDB(), holder="h1")
    assert f.provider == "kite" and f._status_doc(OPEN)["provider"] == "kite"


# ── TS-10: switch wiring ─────────────────────────────────────────────────────
def test_ts10_truedata_effective_starts_the_served_feed_and_no_shadow_connection(monkeypatch):
    started = []

    async def fake_start_serving(db):
        started.append(db)
        return True
    monkeypatch.setattr(serve, "start_serving", fake_start_serving)
    monkeypatch.setattr(mds, "feed_is_on", lambda feed, resolution=None: False)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: mds.Resolution(configured="truedata", effective="truedata",
                                                                     serve_from="truedata", our_feeds_on=False,
                                                                     truedata_feeds_on=True, reasons=()))
    monkeypatch.setattr(mds, "truedata_is_on", lambda resolution=None: True)
    monkeypatch.setattr(kf, "_task", None)
    db = FakeDB()
    assert asyncio.run(kf.start(db)) is True and started == [db]
    why = sh.why_not_started(ENV)
    assert why and "TrueData serves the live feed" in why


def test_ts10_at_current_and_shadow_nothing_is_served_from_truedata(monkeypatch):
    called = []

    async def fake_start_serving(db):
        called.append(db)
        return True
    monkeypatch.setattr(serve, "start_serving", fake_start_serving)
    monkeypatch.setattr(mds, "feed_is_on", lambda feed, resolution=None: True)
    monkeypatch.setattr(kf, "_task", None)
    monkeypatch.setattr(kf, "_feed", None)
    monkeypatch.setattr(kf.LiveFeed, "run", lambda self: asyncio.sleep(0))
    assert asyncio.run(kf.start(FakeDB())) is True and called == []


# ── TS-11: no secret anywhere ────────────────────────────────────────────────
def test_ts11_no_password_in_documents_or_logs(caplog, monkeypatch):
    def connect(creds):
        return FakeSocket([LOGIN, {"success": True, "message": "symbols added", "symbollist": [tl("RELIANCE", "7001", 1160.2)]}])

    async def no_holidays(day):
        return set()

    async def no_n500():
        return []
    clock, db = Clock(OPEN.astimezone(timezone.utc)), FakeDB()
    feed, _, checks = serve.build_feed(db, env=ENV, client=FakeClient(), connect=connect, clock=clock, holder="h1",
                                       sleep=clock.sleep, cadence=5, force_rest=False, load_holidays=no_holidays,
                                       load_nifty500=no_n500)
    caplog.set_level("DEBUG")
    asyncio.run(feed.tick())
    wait_for(lambda: "RELIANCE" in feed.quotes)
    asyncio.run(feed.tick())
    asyncio.run(checks.write_status(OPEN))
    feed._stop_ticker()
    text = json.dumps({n: c.docs for n, c in db.cols.items()}, default=str) + caplog.text
    assert WS_PASSWORD not in text and REST_PASSWORD not in text
    assert serve.ws_marker(ENV).startswith("truedata:") and WS_PASSWORD not in serve.ws_marker(ENV)


# ── TI-1 … TI-3: intraday candles from TrueData ──────────────────────────────
def bar_row(t, o, h, l, c, v, oi=0, vol_key="Volume"):
    return {"timestamp": t, "open": o, "high": h, "low": l, "close": c, vol_key: v, "oi": oi}


class FakeBarsClient(FakeClient):
    """MOCK — not real data: two 5-minute bars per contract, in the shapes TrueData's history returned on 30 Oct."""

    def __init__(self):
        super().__init__()
        self.bar_calls = []

    def bars(self, symbol, start, end, interval="1min", bidask=False):
        self.bar_calls.append((symbol, start, end, interval))
        base = {"RELIANCE": 1160.0, "NIFTY26NOVFUT": 23000.0, "NIFTY26DECFUT": 23150.0}.get(symbol, 100.0)
        return [bar_row("2026-10-30T09:15:00", base, base + 4, base - 2, base + 1, 1500, oi=15800000 if "FUT" in symbol else 0),
                bar_row("2026-10-30T09:20:00", base + 1, base + 3, base, base + 2, 900, oi=15810000 if "FUT" in symbol else 0,
                        vol_key="volume")]


def test_ti1_history_maps_kite_intervals_and_reads_either_volume_column():
    client = FakeBarsClient()
    a = tg.TrueDataAsKite(client=client, indices=["NIFTY 50"], clock=lambda: OPEN)
    rows = a.historical_data_oi(900000596, datetime(2026, 10, 30, 9, 0, tzinfo=IST), OPEN, "5minute")
    assert client.bar_calls[-1] == ("NIFTY26NOVFUT", datetime(2026, 10, 30, 9, 0), datetime(2026, 10, 30, 10, 0), "5min")
    assert rows[0] == {"date": datetime(2026, 10, 30, 9, 15, tzinfo=IST), "open": 23000.0, "high": 23004.0, "low": 22998.0,
                       "close": 23001.0, "volume": 1500.0, "oi": 15800000.0}
    assert rows[1]["volume"] == 900.0                                         # the lower-case column
    assert "oi" not in a.historical_data(100001262, OPEN, OPEN, "15minute")[0]
    with pytest.raises(tg.td.TrueDataError):
        a.historical_data(424242, OPEN, OPEN, "5minute")                      # unknown token: nothing invented
    with pytest.raises(tg.td.TrueDataError):
        a.historical_data(100001262, OPEN, OPEN, "2minute")                   # no Kite interval of that name


def test_ti2_the_intraday_service_answers_from_truedata_labelled_and_adjusted(monkeypatch):
    monkeypatch.setenv("TRUEDATA_USERNAME", "rest-x")
    monkeypatch.setenv("TRUEDATA_PASSWORD", REST_PASSWORD)
    svc = serve.intraday_service(client=FakeBarsClient(), clock=lambda: OPEN.astimezone(timezone.utc))
    out = asyncio.run(svc.bars("RELIANCE", "5m", 1))
    assert out["availability"] == "ok" and out["count"] == 2 and out["bars"][0][4] == 1161.0
    assert (out["source"], out["provider"], out["adjusted"]) == ("TrueData intraday", "truedata-rest-v1", True)
    assert "adjusted for corporate actions" in out["note"]
    fut = asyncio.run(svc.futures_bars("NIFTY", "5m", 1))
    assert fut["availability"] == "ok" and fut["adjusted"] is True and fut["source"].startswith("TrueData intraday")
    assert [c["tradingsymbol"] for c in fut["contracts"]][:2] == ["NIFTY26NOVFUT", "NIFTY26DECFUT"]
    assert fut["contracts"][0]["bars"][0][6] == 15800000.0
    from services.kite_live_feed.intraday import IntradayService
    kite = IntradayService()
    assert (kite.source, kite.adjusted) == ("Kite intraday", False)


def test_ti3_get_service_picks_truedata_only_when_it_serves(monkeypatch):
    from routes import research_chart_intraday as rci
    serving = mds.Resolution(configured="truedata", effective="truedata", serve_from="truedata", our_feeds_on=False,
                             truedata_feeds_on=True, reasons=())
    monkeypatch.setattr(rci, "_service", None)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: serving)
    assert rci.get_service().source == "TrueData intraday"
    monkeypatch.setattr(rci, "_service", None)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: mds.Resolution(configured="shadow", effective="shadow",
                                                                     serve_from="current", our_feeds_on=True,
                                                                     truedata_feeds_on=True, reasons=()))
    assert rci.get_service().source == "Kite intraday"
