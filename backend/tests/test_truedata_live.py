"""TrueData live feed in shadow + its data-quality checks (LP, LC, LT, LK, LR in test_reports/truedata_live_dq_TESTCASES.md).

No network, no Mongo, no TrueData: messages are SYNTHETIC, written in the formats of TrueData's Market Data API
documentation v2.6 (MOCK — not real data). The real sandbox run is in the PR's report.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from nidp.shared import market_data_source as mds
from services.truedata_live import checks as ck
from services.truedata_live import compare as cmp
from services.truedata_live import protocol as pr
from services.truedata_live import shadow as sh
from tests.test_kite_live_feed import FakeDB

IST = pr.IST
OPEN = datetime(2026, 10, 30, 10, 0, 0, tzinfo=IST)            # a Friday, mid-session
PASSWORD = "ws-S3CRET-pw"
WS_ENV = {"TRUEDATA_WS_USERNAME": "trial-x", "TRUEDATA_WS_PASSWORD": PASSWORD, "TRUEDATA_WS_PORT": "8086",
          "TRUEDATA_SHADOW_INDICES": "NIFTY 50", "TRUEDATA_SHADOW_STOCKS": "AAAA,BBBB", "TRUEDATA_SHADOW_FUTURES": "IDXA"}
LOGIN_OK = {"success": True, "message": "TrueData Real Time Data Service", "segments": ["EQ", "FO", "IND", "MCX"],
            "maxsymbols": 50, "subscription": "tick", "validity": "2026-12-31T00:00:00"}


def tl(sym, sid, ts, ltp, o, h, l, prev, vol=1000, oi=0, prev_oi=0, bid=0, ask=0):
    return [sym, sid, ts, str(ltp), "0", str(ltp), str(vol), str(o), str(h), str(l), str(prev), str(oi), str(prev_oi),
            "0", str(bid), "10", str(ask), "10"]


def trade(sid, ts, ltp, vol, o, h, l, prev, seq, oi=0, prev_oi=0, bid=0, ask=0):
    return {"trade": [sid, ts, str(ltp), "5", str(ltp), str(vol), str(o), str(h), str(l), str(prev), str(oi), str(prev_oi),
                      "0", "", str(seq), str(bid), "10", str(ask), "10"]}


# ── LP: parsing ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_lp1_login_replies():
    ok = pr.parse_login(LOGIN_OK)
    assert (ok.ok, ok.segments, ok.maxsymbols, ok.subscription, ok.validity) == \
        (True, ["EQ", "FO", "IND", "MCX"], 50, "tick", date(2026, 12, 31))
    dup = pr.parse_login({"success": False, "message": "User Already Connected", "segments": None, "maxsymbols": 0,
                          "subscription": None, "validity": "0001-01-01T00:00:00"})
    assert dup.ok is False and dup.duplicate and dup.validity is None
    doc = pr.parse_login({"success": True, "message": "x", "segments": ["nseeq"], "maxsymbols": 250,
                          "subscription": "tick", "validity": "31/12/2020T23:30:00"})
    assert doc.validity == date(2020, 12, 31) and doc.segments == ["NSEEQ"]
    assert pr.kind_of(LOGIN_OK) == "login"


def test_lp2_lp3_lp4_touchline_trade_bidask():
    msg = {"success": True, "message": "symbols added", "symbolsadded": 1,
           "symbollist": [tl("AAAA", "100000001", "2026-10-30T09:59:58", 100.5, 100, 101, 99.5, 99.8, bid=100.45, ask=100.5)],
           "totalsymbolsubscribed": 1}
    assert pr.kind_of(msg) == "touchline"
    row = pr.parse_touchline(msg)[0]
    assert (row["symbol"], row["symbol_id"], row["ltp"], row["prev_close"], row["bid"], row["ask"]) == \
        ("AAAA", "100000001", 100.5, 99.8, 100.45, 100.5)
    assert row["ts"] == datetime(2026, 10, 30, 9, 59, 58, tzinfo=IST)
    t = pr.parse_trade(trade("100000001", "2026-10-30T10:00:01", 100.55, 1500, 100, 101, 99.5, 99.8, 42))
    assert (t["symbol_id"], t["ltp"], t["volume"], t["seq"], t["tag"]) == ("100000001", 100.55, 1500, 42, "")
    b = pr.parse_bidask({"bidask": ["950000606", "2/18/2020 3:43:45 PM", "3698", "34", "3700", "54"]})
    assert b["ts"] == datetime(2020, 2, 18, 15, 43, 45, tzinfo=IST) and (b["bid"], b["ask"]) == (3698, 3700)
    no_bidask = pr.parse_trade({"trade": ["1", "2026-10-30T10:00:01", "1", "1", "1", "1", "1", "1", "1", "1", "0", "0",
                                          "0", "", "7"]})
    assert no_bidask["seq"] == 7 and no_bidask.get("bid") is None


def test_lp5_lp6_heartbeat_market_and_malformed():
    assert pr.kind_of({"success": True, "message": "HeartBeat", "timestamp": "2026-10-30T10:00:00.123"}) == "heartbeat"
    assert pr.kind_of({"success": True, "message": "marketstatus", "data": "NSE EQ Normal Market Start"}) == "marketstatus"
    with pytest.raises(pr.Malformed):
        pr.parse_trade({"trade": ["1", "2026-10-30T10:00:01"]})
    with pytest.raises(pr.Malformed):
        pr.parse_bidask({"bidask": "nope"})


# ── LC: connection checks ───────────────────────────────────────────────────────────────────────────────────────

def test_lc1_to_lc4_login_findings():
    today = date(2026, 10, 30)
    assert ck.login_findings(pr.parse_login(LOGIN_OK), 30, today) == []
    assert ck.login_findings(pr.parse_login({"success": False, "message": "User Already Connected"}), 30, today)[0][0] == \
        "DUPLICATE_LOGIN"
    assert ck.login_findings(pr.parse_login({"success": False, "message": "invalid login credentials"}), 30, today)[0][0] == \
        "LOGIN_FAILED"
    sandbox = pr.parse_login({**LOGIN_OK, "segments": ["EQ", "MCX"], "validity": "2026-11-05T00:00:00"})
    codes = [c for c, _ in ck.login_findings(sandbox, 60, today)]
    assert codes == ["SEGMENT_MISSING", "SYMBOL_LIMIT", "LOGIN_EXPIRING"]


def test_lc5_lc6_subscription_and_heartbeat():
    assert ck.subscription_findings(["NIFTY 50", "AAAA", "ZZZZ"], ["nifty 50", "AAAA"]) == [("SYMBOL_NOT_SUBSCRIBED", "ZZZZ")]
    now = OPEN
    assert ck.heartbeat_state(now - timedelta(seconds=6), now)[0] == "ok"
    assert ck.heartbeat_state(now - timedelta(seconds=20), now)[0] == "delayed"
    assert ck.heartbeat_state(now - timedelta(seconds=61), now)[0] == "lost"
    assert ck.heartbeat_state(None, now)[0] == "lost"


# ── LT: per-tick checks ─────────────────────────────────────────────────────────────────────────────────────────

def q(ltp, ts=OPEN, o=100.0, h=101.0, l=99.0, vol=1000, oi=None, prev_oi=None, bid=None, ask=None, seq=None):
    return {"ltp": ltp, "ts": ts, "open": o, "high": h, "low": l, "volume": vol, "oi": oi, "prev_oi": prev_oi,
            "bid": bid, "ask": ask, "seq": seq}


def checker():
    return ck.TickChecker(meta={"AAAA": ck.SymbolMeta("EQ", 0.05, 90.0, 110.0), "IDX": ck.SymbolMeta("INDEX"),
                                "FUTX": ck.SymbolMeta("FUT", 0.1), "BBBB": ck.SymbolMeta("EQ", 0.05)})


@pytest.mark.parametrize("tick,code", [
    (q(0), "PRICE_NONPOSITIVE"),                                             # LT-1
    (q(100.02), "OFF_TICK"),                                                 # LT-2
    (q(111.0, h=111.0), "CIRCUIT_BREACH"),                                   # LT-3
    (q(100.0, bid=100.1, ask=100.0), "CROSSED_BOOK"),                        # LT-4
    (q(102.0, h=101.0), "OHLC_INCONSISTENT"),                                # LT-5
    (q(100.0, ts=OPEN + timedelta(seconds=30)), "TS_FUTURE"),                # LT-9
])
def test_lt_single_tick_findings(tick, code):
    assert code in checker().check("AAAA", tick, OPEN)


def test_lt6_to_lt11_sequences():
    c = checker()
    assert c.check("AAAA", q(100.0, h=101.0, l=99.0, vol=1000, seq=10), OPEN) == []                     # LT-13 clean
    later = OPEN + timedelta(seconds=1)
    codes = c.check("AAAA", q(100.05, ts=later, h=100.5, l=99.5, vol=900, seq=13), later)
    assert {"HIGH_DECREASED", "LOW_INCREASED", "VOLUME_DECREASED", "SEQ_GAP"} <= set(codes)               # LT-6/7/10
    codes = c.check("AAAA", q(100.1, ts=OPEN - timedelta(seconds=5), h=101.0, l=99.0, vol=2000), later)
    assert "TS_BACKWARDS" in codes                                                                         # LT-9
    f = ck.TickChecker(meta={"FUTX": ck.SymbolMeta("FUT", 0.1)})
    assert "OI_SUSPECT_ZERO" in f.check("FUTX", q(100.0, oi=0, prev_oi=6_173_152_800), OPEN)               # LT-8
    assert "OI_NEGATIVE" in f.check("FUTX", q(100.0, oi=-1), OPEN)
    i = ck.TickChecker(meta={"IDX": ck.SymbolMeta("INDEX")})
    assert i.check("IDX", q(22000.0, o=22000, h=22010, l=21990), OPEN) == []
    assert "JUMP_UNCONFIRMED" in i.check("IDX", q(25000.0, o=22000, h=25000, l=21990), OPEN + timedelta(seconds=1))  # LT-11
    assert "OFF_TICK" not in i.check("IDX", q(22000.37, o=22000, h=25000, l=21990), OPEN + timedelta(seconds=2))   # no grid


def test_lt12_stale_symbols_and_new_day_reset():
    c = checker()
    c.check("IDX", q(22000.0, o=22000, h=22010, l=21990), OPEN)
    c.check("AAAA", q(100.0), OPEN)
    later = OPEN + timedelta(seconds=10)
    assert c.stale_symbols(later, ["IDX", "AAAA", "BBBB"]) == ["IDX", "BBBB"]       # index > 5 s; BBBB never updated
    tomorrow = OPEN + timedelta(days=1)
    assert c.check("AAAA", q(100.0, ts=tomorrow, h=100.5, l=99.9, vol=10), tomorrow) == []   # day high/volume restart


# ── LK: comparison with Kite ────────────────────────────────────────────────────────────────────────────────────

def kite_row(ltp, received, prev=99.8, oi=None, exchange_ts=None):
    return {"ltp": ltp, "received_at": received.isoformat(), "exchange_ts": exchange_ts, "ohlc": {"close": prev}, "oi": oi}


def test_lk_compare_on_receive_times():
    td_q = {"symbol": "AAAA", "ltp": 100.5, "ts": None, "received_at": OPEN, "prev_close": 99.8, "oi": None}
    assert cmp.compare(td_q, kite_row(100.5, OPEN + timedelta(seconds=1)), 0.05)[0] == "agree"                  # LK-1
    out, codes, detail = cmp.compare(td_q, kite_row(101.0, OPEN), 0.05)
    assert out == "disagree" and "KITE_DISAGREE" in codes and detail["kite_ltp"] == 101.0                        # LK-2
    assert cmp.compare(td_q, kite_row(101.0, OPEN + timedelta(seconds=5)), 0.05)[0] == "not_comparable"          # LK-3
    out, codes, _ = cmp.compare(td_q, kite_row(100.5, OPEN, prev=99.7), 0.05)
    assert out == "agree" and codes == ["PREV_CLOSE_MISMATCH"]                                                  # LK-4
    assert cmp.compare(td_q, None)[0] == "no_kite_quote"                                                        # LK-5
    fut = {"symbol": "IDEA26NOVFUT", "ltp": 11.93, "ts": OPEN, "received_at": OPEN, "prev_close": 12.15, "oi": 0}
    assert "OI_MISMATCH" in cmp.compare(fut, kite_row(11.93, OPEN, prev=12.15, oi=6_173_152_800), 0.01)[1]


def test_lk6_kite_exchange_time_missing_or_mislabelled():
    """Seen live 30 Oct: Kite cash/index rows have exchange_ts None; its F&O exchange_ts was UTC labelled as IST."""
    td_q = {"symbol": "NIFTY26NOVFUT", "ltp": 23056.1, "ts": OPEN, "received_at": OPEN + timedelta(seconds=0.6),
            "prev_close": 22990.0}
    wrong = (OPEN - timedelta(hours=5, minutes=30)).isoformat()                 # 05:30 behind, labelled +05:30
    out, _, detail = cmp.compare(td_q, kite_row(23056.1, OPEN, prev=22990.0, exchange_ts=wrong), 0.1, "FUT")
    assert out == "agree" and detail["kite_ts_mislabelled"] is True and detail["basis"] == "exchange_second"
    later = (OPEN + timedelta(seconds=1)).isoformat()
    out, _, detail = cmp.compare(td_q, kite_row(23060.0, OPEN, exchange_ts=later), 0.1, "FUT")
    assert out == "not_comparable" and detail["basis"] == "exchange_second"     # different exchange seconds
    out, _, detail = cmp.compare(td_q, kite_row(23056.1, OPEN, prev=22990.0), 0.1, "FUT")
    assert out == "agree" and detail["basis"] == "receive_time"


def test_lk7_options_get_a_wider_band_than_stocks():
    td_q = {"symbol": "X", "ltp": 100.4, "ts": None, "received_at": OPEN, "prev_close": None}
    assert cmp.compare(td_q, kite_row(100.0, OPEN), 0.05, "OPT")[0] == "agree"                 # 0.4% < 0.5%
    assert cmp.compare(td_q, kite_row(100.0, OPEN), 0.05, "EQ")[0] == "disagree"               # 0.4% > 0.05%


def test_lt6_high_decrease_is_counted_once_then_rebaselined():
    """INDIA VIX on 30 Oct: touchline high 16.57, every trade high 15.695."""
    c = ck.TickChecker(meta={"INDIA VIX": ck.SymbolMeta("INDEX")})
    assert c.check("INDIA VIX", q(15.49, o=16.245, h=16.57, l=14.47), OPEN) == []
    t1 = OPEN + timedelta(seconds=1)
    assert "HIGH_DECREASED" in c.check("INDIA VIX", q(15.4875, ts=t1, o=15.1175, h=15.695, l=14.47), t1)
    t2 = OPEN + timedelta(seconds=2)
    assert "HIGH_DECREASED" not in c.check("INDIA VIX", q(15.48, ts=t2, o=15.1175, h=15.695, l=14.47), t2)


# ── LR: runner ──────────────────────────────────────────────────────────────────────────────────────────────────

class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Closed(Exception):
    pass


class FakeWS:
    """Plays scripted messages; each recv advances the clock by `step` seconds; ends with Closed."""

    def __init__(self, script, clock, step=1.0):
        self.script, self.clock, self.step = list(script), clock, step
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if not self.script:
            raise Closed("end of script")
        self.clock.now += timedelta(seconds=self.step)
        m = self.script.pop(0)
        return m if isinstance(m, str) else json.dumps(m)


def meta_loader(wanted):
    return {"meta": {"NIFTY 50": ck.SymbolMeta("INDEX"), "AAAA": ck.SymbolMeta("EQ", 0.05, 90, 110),
                     "BBBB": ck.SymbolMeta("EQ", 0.05, 45, 55), "IDXA26NOVFUT": ck.SymbolMeta("FUT", 0.05)},
            "futures": ["IDXA26NOVFUT"], "meta_missing": []}


def make_shadow(db, script, clock, kite=None, sent_alerts=None, env=WS_ENV):
    async def kite_reader(symbols):
        return {s: r for s, r in (kite or {}).items() if s in symbols}

    async def holidays(day):
        return set()
    ws_holder = {}

    def connect(creds):
        assert creds["TRUEDATA_WS_PASSWORD"] == PASSWORD
        ws_holder["ws"] = FakeWS(script, clock)
        return ws_holder["ws"]
    s = sh.TrueDataShadow(db, env=env, connect=connect, kite_reader=kite_reader, meta_loader=meta_loader,
                          holidays_loader=holidays, notifier=lambda subj, body: (sent_alerts if sent_alerts is not None else []).append((subj, body)),
                          clock=clock, holder="h1")
    return s, ws_holder


def session_script(start):
    t = lambda s: (start + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S")
    hb = {"success": True, "message": "HeartBeat", "timestamp": t(0)}
    return [hb, LOGIN_OK,
            {"success": True, "message": "symbols added", "symbolsadded": 3, "totalsymbolsubscribed": 3, "symbollist": [
                tl("NIFTY 50", "200000001", t(1), 22000, 21950, 22010, 21940, 21900),
                tl("AAAA", "100000001", t(1), 100.5, 100, 101, 99.5, 99.8, bid=100.45, ask=100.5),
                tl("IDXA26NOVFUT", "300000001", t(1), 22100, 22050, 22120, 22040, 22000, oi=150, prev_oi=140)]},
            trade("100000001", t(3), 100.55, 1500, 100, 101, 99.5, 99.8, 1, bid=100.5, ask=100.55),
            trade("100000001", t(4), 100.52, 1400, 100, 101, 99.5, 99.8, 2, bid=100.6, ask=100.5),     # volume falls, crossed
            {"bidask": ["100000001", t(5), "100.5", "3", "100.55", "4"]},
            hb, trade("999", t(6), 1, 1, 1, 1, 1, 1, 1),                                               # unmapped id
            {"success": True, "message": "marketstatus", "data": "NSE EQ Normal Market Start"}] + \
        [hb] * 60                                                                                  # past the minute


def test_lt4b_crossed_book_samples_name_the_message_and_keep_the_raw_bidask():
    """LT-4b. MOCK — not real data: a trade with a crossed book, then a bidask whose bid/ask sit at ±3% of the price
    (the shape seen on 30 Oct)."""
    db, clock = FakeDB(), Clock(OPEN)
    s, _ = make_shadow(db, [], clock)
    s.checker.meta = meta_loader(None)["meta"]
    s.handle(json.dumps({"success": True, "message": "symbols added", "symbollist": [
        tl("AAAA", "100000001", "2026-10-30T10:00:01", 100.5, 100, 101, 99.5, 99.8, bid=100.45, ask=100.5)]}), OPEN)
    s.handle(json.dumps(trade("100000001", "2026-10-30T10:00:02", 100.55, 1500, 100, 101, 99.5, 99.8, 1,
                              bid=100.6, ask=100.5)), OPEN)
    s.handle(json.dumps({"bidask": ["100000001", "2026-10-30T10:00:03", "103.55", "12", "97.5", "9"]}), OPEN)
    samples = s._minute_for(OPEN).samples["CROSSED_BOOK"]
    assert samples[0]["kind"] == "trade" and samples[0]["ltp"] == 100.55
    b = samples[1]
    assert b["kind"] == "bidask" and (b["bid"], b["ask"]) == (103.55, 97.5) and b["ltp"] == 100.55
    assert (b["bid_before"], b["ask_before"]) == (100.6, 100.5)
    assert b["raw"] == ["100000001", "2026-10-30T10:00:03", "103.55", "12", "97.5", "9"]


def test_lr3_session_writes_minute_and_status_documents():
    db, clock, alerts = FakeDB(), Clock(OPEN), []
    # The fake clock moves 1 s per message: TrueData's last AAAA update (the bidask) lands at +6 s, NIFTY 50's at +3 s.
    kite = {"AAAA": {"ltp": 100.5, "received_at": (OPEN + timedelta(seconds=6)).isoformat(), "exchange_ts": None,
                     "ohlc": {"close": 99.8}},
            "NIFTY 50": {"ltp": 22000, "received_at": (OPEN + timedelta(seconds=3)).isoformat(), "exchange_ts": None,
                         "ohlc": {"close": 21900}}}
    s, holder = make_shadow(db, session_script(OPEN), clock, kite=kite, sent_alerts=alerts)
    with pytest.raises(Closed):
        asyncio.run(s.connect_once())
    ws = holder["ws"]
    assert ws.sent[0] == {"method": "addsymbol", "symbols": ["NIFTY 50", "IDXA26NOVFUT", "AAAA", "BBBB"]}
    assert ws.sent[-1] == {"method": "logout"}
    minutes = db[sh.COL_MINUTES].docs
    assert minutes, "a minute document was written"
    first = minutes[sorted(minutes)[0]]
    assert first["findings"]["VOLUME_DECREASED"] == 1 and first["findings"]["CROSSED_BOOK"] >= 1
    assert first["findings"]["UNMAPPED_ID"] == 1 and first["findings"]["SYMBOL_NOT_SUBSCRIBED"] == 1   # BBBB
    assert first["kite"]["agree"] >= 1 and first["session"] == "open"
    st = db[sh.COL].docs["status"]
    assert st["login"]["maxsymbols"] == 50 and st["subscribed"] == ["NIFTY 50", "AAAA", "IDXA26NOVFUT"]
    assert st["not_subscribed"] == ["BBBB"] and st["market_status"] == "NSE EQ Normal Market Start"


def test_lr4_no_secret_in_documents_logs_or_status(caplog):
    caplog.set_level(logging.DEBUG)
    db, clock = FakeDB(), Clock(OPEN)
    s, _ = make_shadow(db, session_script(OPEN), clock)
    with pytest.raises(Closed):
        asyncio.run(s.connect_once())
    out = asyncio.run(sh.status(db, now=clock.now))
    blob = json.dumps({k: c.docs for k, c in db.cols.items()}, default=str) + json.dumps(out, default=str) + caplog.text
    assert PASSWORD not in blob and "holder" not in out["status"]


def test_lr6_never_touches_kite_collections():
    db, clock = FakeDB(), Clock(OPEN)
    s, _ = make_shadow(db, session_script(OPEN), clock)
    with pytest.raises(Closed):
        asyncio.run(s.connect_once())
    assert set(db.cols) <= {sh.COL, sh.COL_MINUTES}


def test_lc1_refused_login_alerts_and_backs_off():
    db, clock, alerts = FakeDB(), Clock(OPEN), []
    s, _ = make_shadow(db, [{"success": False, "message": "User Already Connected", "maxsymbols": 0}], clock,
                       sent_alerts=alerts)
    assert asyncio.run(s.connect_once()) == "login_refused"
    assert alerts and "DUPLICATE_LOGIN" in alerts[0][0] and db[sh.COL].docs["status"]["state"] == "login_refused"


def test_lc6_heartbeat_lost_in_market_hours_reconnects_and_alerts():
    db, clock, alerts = FakeDB(), Clock(OPEN), []
    script = session_script(OPEN)[:3] + [{"success": True, "message": "marketstatus", "data": "x"}] * 3
    s, holder = make_shadow(db, script, clock, sent_alerts=alerts)

    class Silent(FakeWS):                     # after the script: silence (the clock moves, no heartbeat)
        async def recv(self):
            if self.script:
                return await super().recv()
            self.clock.now += timedelta(seconds=5)
            raise asyncio.TimeoutError
    s._connect = lambda creds: holder.setdefault("ws", Silent(script, clock))
    assert asyncio.run(s.connect_once()) == "heartbeat_lost"
    assert any("HEARTBEAT_LOST" in a[0] for a in alerts)


def test_lc3_symbol_limit_never_fills_in():
    db, clock = FakeDB(), Clock(OPEN)
    script = session_script(OPEN)
    script[1] = {**LOGIN_OK, "maxsymbols": 2}
    s, holder = make_shadow(db, script, clock)
    with pytest.raises(Closed):
        asyncio.run(s.connect_once())
    assert holder["ws"].sent[0]["symbols"] == ["NIFTY 50", "IDXA26NOVFUT"]
    assert s.over_limit == ["AAAA", "BBBB"]


def test_lr2_one_lease_holder():
    db, clock = FakeDB(), Clock(OPEN)
    a, _ = make_shadow(db, [], clock)
    b, _ = make_shadow(db, [], clock)
    b.holder = "h2"
    assert asyncio.run(a._lease(clock.now)) is True
    assert asyncio.run(b._lease(clock.now)) is False
    clock.now += timedelta(seconds=sh.LEASE_TTL_S + 1)
    assert asyncio.run(b._lease(clock.now)) is True


def test_lr1_start_conditions(monkeypatch):
    on = mds.resolve({"source": "shadow"}, {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"})
    off = mds.resolve({"source": "current"}, {})
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: off)
    assert "switched off" in sh.why_not_started(WS_ENV)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: on)
    assert sh.why_not_started(WS_ENV) is None
    assert "WebSocket login" in sh.why_not_started({})
    assert sh.why_not_started({**WS_ENV, "TRUEDATA_SHADOW_ENABLED": "0"}) == "TRUEDATA_SHADOW_ENABLED=0"
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: off)
    assert asyncio.run(sh.start(FakeDB())) is False            # the shipped switch: nothing starts


def test_lr5_status_endpoint(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import live_quotes
    db, clock = FakeDB(), Clock(OPEN)
    s, _ = make_shadow(db, session_script(OPEN), clock)
    with pytest.raises(Closed):
        asyncio.run(s.connect_once())

    async def user(request):
        return {"user_id": "u1"}
    monkeypatch.setattr(live_quotes, "get_current_user", user)
    monkeypatch.setattr(live_quotes, "get_feed", lambda: type("F", (), {"db": db})())
    monkeypatch.setattr(sh, "utcnow", lambda: clock.now)
    app = FastAPI()
    app.include_router(live_quotes.router)
    r = TestClient(app).get("/api/live/truedata/status")
    assert r.status_code == 200
    body = r.json()
    assert body["switch"]["effective"] == "current" and body["today"]["minutes_recorded"] >= 1
    assert body["today"]["findings"]["VOLUME_DECREASED"] == 1 and body["status"]["login"]["subscription"] == "tick"
    assert PASSWORD not in r.text


def test_ws_credentials_from_file(tmp_path):
    f = tmp_path / "ws.env"
    f.write_text(f"TRUEDATA_WS_USERNAME=u\nTRUEDATA_WS_PASSWORD={PASSWORD}\nTRUEDATA_WS_PORT=8086\n")
    assert sh.ws_credentials({"TRUEDATA_WS_CRED_FILE": str(f)})["TRUEDATA_WS_PORT"] == "8086"
    assert sh.ws_credentials({}) is None
