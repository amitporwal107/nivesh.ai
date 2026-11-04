"""Realtime scan dashboard (DESIGN.md §8; services/scan_builder/market_dashboard.py, GET /api/scan-builder/market-dashboard).

The real widget definitions, criteria writer, engine and route run; the data layer's network edges (DaaS, the live feed, Kite),
company results, intraday candles and index quotes are injected. All prices and figures below are hand-made (MOCK — not real
data)."""
import asyncio
import json
import re
from dataclasses import dataclass, field

import numpy as np
from datetime import datetime, timezone
import pytest

from services.scan_builder import data as sd
from services.scan_builder import market_dashboard as MD
from tests.test_scan_builder_data import IST_PREOPEN, FakeDaas, StubRest
from tests.test_scan_builder_routes import ROWS, H, _client, _reset  # noqa: F401  (_reset is an autouse fixture)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from services.scan_builder import signals as SIG
    MD._cache.update(at=float("-inf"), value=None)
    saved, SIG._store = SIG._store, SIG.LocalSignalStore()          # signals never touch Redis in these tests
    SIG._seen.clear()
    yield
    SIG._store = saved
    SIG._seen.clear()
    MD._cache.update(at=float("-inf"), value=None)


def W(wid):
    return next(w for w in MD.WIDGETS if w.id == wid)


def texts(lines):
    return [(ln["text"], ln["level"], ln["applied"]) for ln in lines]


# ── definitions and criteria ───────────────────────────────────────────────────────────────────────────────────────

CHARTINK_IDS = {"2798275", "2774840", "2850641", "2556934", "2750391", "2737396", "2653943", "3073022", "3072994", "2894893",
                "3072995", "2750384", "2804704", "3044849", "3072992", "2807387", "2854924"}


def test_the_seventeen_widgets_of_dashboard_247498():
    assert len(MD.WIDGETS) == 17
    assert {w.chartink_id for w in MD.WIDGETS} == CHARTINK_IDS
    assert len({w.id for w in MD.WIDGETS}) == 17


def test_criteria_are_written_from_the_definition():
    assert texts(MD.criteria_lines(W("open_interest"))) == [
        ("Universe: F&O stocks", 0, True),
        ("Volume > EMA(close, 10) × 5", 0, True),
        ("Any of:", 0, True),
        ("Close > 1 day ago Close × 1.05", 1, True),
        ("Close < 1 day ago Close × 0.95", 1, True)]
    cup = [t for t, *_ in texts(MD.criteria_lines(W("cup_handle")))]
    assert "7 months ago High < 6 months ago High" in cup
    assert "High > 6 months ago High" in cup
    assert "Volume > 1,00,000" in cup
    rsi = [t for t, *_ in texts(MD.criteria_lines(W("rsi_dwm")))]
    assert rsi[1:] == ["RSI(14) > 70", "Weekly RSI(14) > 50", "Market cap (₹ cr) > 10,000"]
    gq = [t for t, *_ in texts(MD.criteria_lines(W("good_results")))]
    assert "Net profit, latest quarter (₹ cr) > Net profit, 1 quarter ago (₹ cr)" in gq
    assert "Close ≥ 1.3 × Weekly Lowest low of 52" in gq
    assert "Close > EMA(close, 50)" in gq
    tb = MD.criteria_lines(W("triple_bottom"))
    assert any(ln["text"] == "All of:" and "57960" in (ln["note"] or "") for ln in tb)
    assert "50 days ago EMA(close, 40)" in tb[1]["text"]
    strong = [t for t, *_ in texts(MD.criteria_lines(W("strong_movers")))]
    assert "1 day ago CCI(20) ≤ 100" in strong
    assert "Parabolic SAR(0.02, 0.02, 0.2) < Close" in strong
    assert "MACD line(26, 12, 9) > MACD signal(26, 12, 9)" in strong


def test_intraday_lines_say_whether_they_were_applied():
    off = MD.criteria_lines(W("n50_gainers"), False, "not applied — no Kite login")
    assert [ln for ln in off if ln["text"].startswith("Close > today's first 15-minute")][0]["applied"] is False
    assert [ln for ln in off if ln["text"].startswith("Close > 15-minute EMA")][0]["note"] == "not applied — no Kite login"
    on = MD.criteria_lines(W("n50_gainers"), True)
    assert all(ln["applied"] for ln in on)
    v10 = MD.criteria_lines(W("vol_10x_5min"))
    assert [ln["text"] for ln in v10][:3] == ["Universe: All NSE stocks", "Volume > 10,00,000", "Open ≥ 50"]
    assert [ln["applied"] for ln in v10] == [True, True, True, False, False]          # 5-minute + trade-side not run yet
    assert all(ln["applied"] for ln in MD.criteria_lines(W("vol_10x_5min"), True, None, True, None))


BANNED = re.compile(r"\b(buy\w*|sell\w*|target\w*|stop ?loss|sl|pick|picks|recommend\w*|entry|exit)\b", re.I)


def test_no_barred_trading_words_on_screen():
    shown = []
    for w in MD.WIDGETS:
        shown.append(w.title)
        shown += [ln["text"] + " " + (ln["note"] or "") for ln in MD.criteria_lines(w, False, "not applied — x")]
        shown += [c["label"] for c in MD.COLUMNS[w.kind]]
        shown.append(w.note or "")
    hits = [s for s in shown if BANNED.search(s)]
    assert hits == []


def test_marketcap_bands_rank_the_whole_market():
    caps = {f"S{i:03d}": 10000.0 - i for i in range(300)}
    caps["NOCAP"] = float("nan")
    g = MD.marketcap_groups(caps, ["S000", "S099", "S100", "S249", "S250", "S299", "NOCAP", "UNKNOWN"])
    assert g.tolist() == [0, 0, 1, 1, 2, 2, -1, -1]


# ── computation on a hand-made market ───────────────────────────────────────────────────────────────────────────────

@dataclass
class _Results:
    values: dict
    source: str = "MOCK results"


@dataclass
class _Intra:
    values: dict = field(default_factory=dict)
    as_of: str = None
    source: str = "MOCK candles"
    warnings: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def _data(tmp_path, results=None):
    daas = FakeDaas(rows=ROWS)

    async def day_quotes(symbols, now=None):
        return {"source": None, "day": None, "as_of": None, "quotes": {}, "why": None}

    async def hol(a, b):
        return None
    d = sd.ScanData(daas_get=daas.get, daas_post=daas.post, cache_dir=tmp_path, now=lambda: IST_PREOPEN, day_quotes=day_quotes,
                    holidays=hol, rest=StubRest({}), probe_symbols=("AAA", "CCC"))

    async def results_fields(wait=False):
        return results
    d.results_fields = results_fields
    return d


async def _indices(names):
    return {"ok": True, "kind": "indices", "basis": {"text": "MOCK Kite close"}, "warnings": [],
            "rows": [{"symbol": "NIFTY", "name": "NIFTY 50", "values": [23000.0, 0.5]},
                     {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "values": [55000.0, -0.25]}]}


def _by_id(out):
    return {w["id"]: w for w in out["widgets"]}


def test_results_widgets_wait_for_results_and_intraday_widgets_fall_back_to_partial(tmp_path):
    asked = []

    async def no_candles(symbols, interval, needs, *, lookback_days, **kw):
        asked.append((list(symbols), interval, [k for k, *_ in needs]))
        return _Intra(warnings=["15-minute candles are loading"])

    out = asyncio.run(MD.compute(_data(tmp_path, results=None), intraday_values=no_candles, index_result=_indices))
    w = _by_id(out)
    assert len(out["widgets"]) == 17 and out["basis"]["mode"] == "eod" and out["market"]["refresh_seconds"] == 10
    for wid in ("good_results", "low_pe_roce", "eps_growth", "supertrend_rsi", "triple_bottom"):
        assert w[wid]["status"] == "pending" and w[wid]["rows"] == [] and "loading" in w[wid]["note"]
    assert MD.RESULTS_PENDING in out["warnings"]
    # Long Build Up has no daily condition: every F&O stock (AAA) goes to the 1-hour candles, which are not there yet.
    assert (["AAA"], "60minute", ["adx", "dip", "dim"]) in asked
    lbu = w["long_buildup"]
    assert lbu["status"] == "partial" and [r[0] for r in lbu["rows"]] == ["AAA"]
    assert [ln["applied"] for ln in lbu["criteria"] if ln["text"].startswith("1-hour")] == [False, False, False]
    assert "15-minute candles are loading" in lbu["criteria"][-1]["note"]
    # 10x volume: no stock trades 10 lakh shares in the hand-made market, so nothing reaches the 5-minute or trade-side parts.
    assert w["vol_10x_5min"]["status"] == "ok" and w["vol_10x_5min"]["rows"] == []
    assert all(ln["applied"] for ln in w["vol_10x_5min"]["criteria"])
    # Index stats: Kite rows, Ltp descending (Chartink ORDER BY 1 desc), not links.
    assert w["index_stats"]["rows"] == [["BANKNIFTY", 55000.0, -0.25], ["NIFTY", 23000.0, 0.5]]
    assert w["index_stats"]["row_kind"] == "index"
    json.dumps(out)                                             # the answer is plain JSON


def test_market_cap_groups_on_the_hand_made_market(tmp_path):
    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=lambda *a, **k: _none(),
                                 index_result=_indices))
    w = _by_id(out)
    # AAA (₹20,000 cr) 103 → 106 up, CCC (₹500 cr) 10.0 → 9.5 down: both rank inside the top 100 = Largecap.
    ad = {r[0]: r[1:] for r in w["mcap_ad"]["rows"]}
    assert ad["Largecap"] == [50.0, 50.0] and ad["Midcap"] == [None, None] and ad["Smallcap"] == [None, None]
    assert w["mcap_ad"]["rows"][0][0] == "Largecap"
    vol = {r[0]: r[1:] for r in w["pos_neg_vol"]["rows"]}
    assert vol["Largecap"] == [0.0, 0.01, 0.01]                  # 1,000 shares each way, in lakh
    assert w["mcap_ad"]["row_kind"] == "group"


async def _none():
    return _Intra()


def test_intraday_conditions_decide_when_the_candles_are_there(tmp_path):
    async def candles(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(values={"AAA": {"adx": 20.0, "dip": 25.0, "dim": 10.0}}, as_of="10:15")

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=candles, index_result=_indices))
    lbu = _by_id(out)["long_buildup"]
    assert lbu["status"] == "ok" and [r[0] for r in lbu["rows"]] == ["AAA"]
    assert "1-hour candles to 10:15" in lbu["as_of"]
    assert all(ln["applied"] for ln in lbu["criteria"])

    async def failing(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(values={"AAA": {"adx": 30.0, "dip": 25.0, "dim": 10.0}}, as_of="10:15")   # ADX above +DI: fails
    MD._cache.update(at=float("-inf"), value=None)
    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=failing, index_result=_indices))
    assert _by_id(out)["long_buildup"]["rows"] == []


def test_one_failing_widget_does_not_blank_the_dashboard(tmp_path):
    async def broken(names):
        raise RuntimeError("index feed exploded")

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=lambda *a, **k: _none(),
                                 index_result=broken))
    w = _by_id(out)
    assert w["index_stats"]["status"] == "error" and w["index_stats"]["rows"] == []
    assert w["mcap_ad"]["status"] == "ok"


# ── one computation shared by every viewer ──────────────────────────────────────────────────────────────────────────

def test_cache_single_flight_refresh_and_stale_fallback(monkeypatch):
    calls = {"n": 0}
    t = {"v": 100.0}

    async def fake_compute(data, **kw):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return {"ok": True, "run_at": "2026-11-03T04:00:00+00:00", "cached": False, "warnings": [], "n": calls["n"]}
    monkeypatch.setattr(MD, "compute", fake_compute)
    clock = lambda: t["v"]

    async def two_viewers():
        return await asyncio.gather(MD.get_dashboard(None, clock=clock), MD.get_dashboard(None, clock=clock))
    a, b = asyncio.run(two_viewers())
    assert calls["n"] == 1 and {a["cached"], b["cached"]} == {False, True}
    t["v"] += MD.CACHE_S - 1
    assert asyncio.run(MD.get_dashboard(None, clock=clock))["cached"] is True and calls["n"] == 1
    t["v"] += 2
    assert asyncio.run(MD.get_dashboard(None, clock=clock))["n"] == 2

    async def down(data, **kw):
        raise sd.DataUnavailable("DaaS is down")
    monkeypatch.setattr(MD, "compute", down)
    t["v"] += MD.CACHE_S + 1
    stale = asyncio.run(MD.get_dashboard(None, clock=clock))
    assert stale["cached"] is True and any("could not be refreshed" in w for w in stale["warnings"])
    t["v"] += MD.STALE_OK_S + 1
    with pytest.raises(sd.DataUnavailable):
        asyncio.run(MD.get_dashboard(None, clock=clock))


# ── the route ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_route_answers_the_dashboard_and_a_typed_503(monkeypatch, tmp_path):
    import routes.scan_builder as rsb
    client, _ = _client(monkeypatch, tmp_path)

    async def fake(data, **kw):
        return {"ok": True, "widgets": [], "cached": False}
    monkeypatch.setattr(rsb.market_dashboard, "get_dashboard", fake)
    r = client.get("/api/scan-builder/market-dashboard", headers=H())
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["ideas"] == {} and r.json()["ideas_meta"] is None
    assert client.get("/api/scan-builder/market-dashboard", headers=H("other")).status_code == 403   # flag: owner only

    async def down(data, **kw):
        raise sd.DataUnavailable("DaaS is down")
    monkeypatch.setattr(rsb.market_dashboard, "get_dashboard", down)
    r = client.get("/api/scan-builder/market-dashboard", headers=H())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "data_unavailable"


def test_stale_quarterly_results_are_not_used():
    from datetime import date
    from services.scan_builder import service as SV
    res = _Results({"q_pat": {"NEW": 10.0, "OLD": 20.0}, "y_eps": {"NEW": 5.0, "OLD": 6.0}})
    res.q_end = {"NEW": "2026-09-30", "OLD": "2015-06-30"}
    arr = SV.results_arrays(res, ["NEW", "OLD", "NONE"], date(2026, 11, 3))
    assert arr["q_pat"][0] == 10.0 and np.isnan(arr["q_pat"][1]) and np.isnan(arr["q_pat"][2])
    assert arr["y_eps"].tolist()[:2] == [5.0, 6.0]            # annual figures carry no quarter date: kept


def test_candidates_still_without_candles_make_the_widget_partial(tmp_path, monkeypatch):
    w = MD.Widget("t_all", "0", "Test", "scan", "cash", spec=MD._spec("t", "cash", []),
                  intraday=MD.IntradayRule("15minute", 5, [("ema21", "ema", {"source": "close", "period": 21}, 0)],
                                           ["Close > 15-minute EMA(close, 21)"], lambda v, c, p: c > v["ema21"]))
    monkeypatch.setattr(MD, "WIDGETS", [w])

    async def half(symbols, interval, needs, *, lookback_days, **kw):
        assert sorted(symbols) == ["AAA", "CCC"]
        return _Intra(values={"AAA": {"ema21": 1.0}}, as_of="09:30", missing=["CCC"])   # CCC's candles have not arrived

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=half, index_result=_indices))
    t = out["widgets"][0]
    assert t["status"] == "partial" and [r[0] for r in t["rows"]] == ["AAA"]
    assert t["note"].startswith("1 of 2 stocks have no 15-minute candles yet")
    assert all(ln["applied"] for ln in t["criteria"])            # applied to every stock that has candles



# ── 10x volume first 5 min: Kite 5-minute candles, then TrueData trade sides ────────────────────────────────────────

def _v10_any_volume():
    """The real widget with its daily part relaxed so both hand-made stocks reach the 5-minute stage."""
    w = W("vol_10x_5min")
    return MD.Widget(w.id, w.chartink_id, w.title, w.kind, w.universe,
                     spec=MD._spec("v10", "cash", [MD._f("a", MD.x(MD.m("volume")), "gt", MD.x(MD.n(0)))]),
                     intraday=w.intraday, flow=w.flow)


@dataclass
class _Flow:
    values: dict = field(default_factory=dict)
    as_of: str = None
    source: str = "MOCK ticks"
    warnings: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def test_ten_x_volume_runs_the_5_minute_test_then_the_trade_sides(tmp_path, monkeypatch):
    monkeypatch.setattr(MD, "WIDGETS", [_v10_any_volume()])
    asked = {}

    async def candles(symbols, interval, needs, *, lookback_days, **kw):
        asked["candles"] = (sorted(symbols), interval, lookback_days, [n[1] for n in needs])
        return _Intra(values={"AAA": {"first_vol": 100.0, "sma1000": 5.0},       # 100 > 10 × 5: passes
                              "CCC": {"first_vol": 40.0, "sma1000": 5.0}},       # 40 < 50: fails
                      as_of="2026-11-03T12:45:00+05:30")

    async def sides(symbols):
        asked["ticks"] = list(symbols)
        return _Flow(values={"AAA": {"buy_trades": 30.0, "sell_trades": 10.0}}, as_of="2026-11-03T12:50:01+05:30")

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=candles, index_result=_indices,
                                 tick_flow=sides))
    t = out["widgets"][0]
    assert asked["candles"] == (["AAA", "CCC"], "5minute", 15, ["first_volume", "sma"])
    assert asked["ticks"] == ["AAA"]                              # TrueData is asked only about the 5-minute survivors
    assert t["status"] == "ok" and [r[0] for r in t["rows"]] == ["AAA"]
    assert all(ln["applied"] for ln in t["criteria"])
    assert "5-minute candles to" in t["as_of"] and "ticks to 12:50:01 IST" in t["as_of"]

    async def more_bid(symbols):
        return _Flow(values={"AAA": {"buy_trades": 10.0, "sell_trades": 10.0}})  # ratio 1: not > 1
    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=candles, index_result=_indices,
                                 tick_flow=more_bid))
    assert out["widgets"][0]["rows"] == []


def test_ten_x_volume_says_partial_when_the_ticks_are_not_there(tmp_path, monkeypatch):
    monkeypatch.setattr(MD, "WIDGETS", [_v10_any_volume()])

    async def candles(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(values={"AAA": {"first_vol": 100.0, "sma1000": 5.0}, "CCC": {"first_vol": 40.0, "sma1000": 5.0}})

    async def no_login(symbols):
        return _Flow(warnings=["No TrueData login"])

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=candles, index_result=_indices,
                                 tick_flow=no_login))
    t = out["widgets"][0]
    assert t["status"] == "partial" and [r[0] for r in t["rows"]] == ["AAA"]
    flow_line = [ln for ln in t["criteria"] if ln["text"].startswith("Trades initiated at the ask")][0]
    assert flow_line["applied"] is False and flow_line["note"] == "not applied — No TrueData login"
    assert "passes the other conditions only" in t["note"]


def test_ten_x_volume_never_asks_truedata_before_the_5_minute_candles(tmp_path, monkeypatch):
    monkeypatch.setattr(MD, "WIDGETS", [_v10_any_volume()])
    called = []

    async def loading(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(warnings=["5-minute candles are loading"])

    async def sides(symbols):
        called.append(symbols)
        return _Flow()

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=loading, index_result=_indices,
                                 tick_flow=sides))
    t = out["widgets"][0]
    assert called == [] and t["status"] == "partial"
    flow_line = [ln for ln in t["criteria"] if ln["text"].startswith("Trades initiated at the ask")][0]
    assert flow_line["applied"] is False and "5-minute condition" in flow_line["note"]



def test_too_little_history_is_not_partial(tmp_path, monkeypatch):
    w = MD.Widget("t_all", "0", "Test", "scan", "cash", spec=MD._spec("t", "cash", []),
                  intraday=MD.IntradayRule("5minute", 15, [("sma1000", "sma", {"source": "volume", "period": 1000}, 1)],
                                           ["x"], lambda v, c, p: True))
    monkeypatch.setattr(MD, "WIDGETS", [w])

    async def short(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(values={"AAA": {"sma1000": 5.0}, "CCC": {"sma1000": None}})     # CCC: candles read, < 1,000 of them

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=short, index_result=_indices))
    t = out["widgets"][0]
    assert t["status"] == "ok" and [r[0] for r in t["rows"]] == ["AAA"]
    assert t["note"] == "1 stock(s) have too little 5-minute history for these conditions and cannot pass."



# ── strategy ideas, per user, attached after the shared computation ─────────────────────────────────────────────────

@dataclass
class _Ideas:
    values: dict = field(default_factory=dict)
    pending: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    source: str = "MOCK strategy builder"
    note: str = "MOCK note"
    as_of: str = None


def _dash():
    return {"widgets": [
        {"row_kind": "symbol", "rows": [["AAA", 1.0, 2.0, 3], ["BBB", 1.0, 2.0, 3]]},
        {"row_kind": "group", "rows": [["Largecap", 50.0, 50.0]]},
        {"row_kind": "symbol", "rows": [["CCC", 1.0, 2.0, 3], ["AAA", 1.0, 2.0, 3]]}]}


def test_ideas_are_attached_for_every_shown_stock_never_for_groups():
    asked = {}

    async def ideas(symbols, user_id):
        asked["symbols"], asked["user"] = list(symbols), user_id
        return _Ideas(values={"AAA": {"structure": "Bull call spread", "reward_risk": 2.1, "max_loss_inr": 4200.0,
                                      "plan_inputs": {"big": "x"}, "legs_text": "NOV 100 CE / 110 CE"},
                              "BBB": None},
                      pending=["CCC"])
    out = asyncio.run(MD.attach_ideas(_dash(), "u1", ideas_for=ideas))
    assert asked == {"symbols": ["AAA", "BBB", "CCC"], "user": "u1"}          # each stock once, symbol rows only
    assert out["ideas"]["AAA"]["structure"] == "Bull call spread" and "plan_inputs" not in out["ideas"]["AAA"]
    assert out["ideas"]["BBB"] is None and "CCC" not in out["ideas"]           # None = not favorable; absent = being built
    assert out["ideas_meta"]["built"] == 2 and out["ideas_meta"]["pending"] == 1


def test_ideas_failing_leave_the_dashboard_standing():
    async def broken(symbols, user_id):
        raise RuntimeError("builder down")
    out = asyncio.run(MD.attach_ideas(_dash(), "u1", ideas_for=broken))
    assert out["ideas"] == {} and out["ideas_meta"]["pending"] == 3 and out["widgets"] == _dash()["widgets"]



def test_the_dashboard_carries_todays_signals_and_says_when_it_is_not_recording(tmp_path):
    from services.scan_builder import signals as SIG
    pre = [{"id": "n50_gainers", "title": "Nifty 50", "row_kind": "symbol", "status": "ok", "rows": [["AAA", 1, 2, 3]],
            "criteria": [{"applied": True}]}]

    def inp(syms):
        return {"AAA": {"close": 100.0, "low": 98.0, "high": 101.0, "atr": 3.0, "swing_high": 120.0, "swing_low": 80.0,
                        "chg": 1.0}}
    when = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)                         # 07:30 IST, the same day
    asyncio.run(SIG.record(pre, inp, when))
    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=lambda *a, **k: _none(),
                                 index_result=_indices, now=lambda: when))
    assert out["signals_meta"]["recording"] is False and out["signals_meta"]["count"] == 1     # pre-open: EOD basis
    s = out["signals"][0]
    assert s["symbol"] == "AAA" and s["entry"] == 100.0 and s["price_now"] == 106.0 and s["move_since_pct"] == 6.0
    assert "Stop loss" in out["signals_meta"]["rules"] and out["signals_meta"]["caveat"]


# ── trade side: TrueData first, Kite 1-minute candles when TrueData gives nothing (owner 4 Nov) ────────────────────────

def test_trade_side_uses_truedata_when_it_answers_and_kite_when_it_does_not():
    asked = {}

    async def td_ok(symbols):
        return _Flow(values={"AAA": {"buy_trades": 9.0, "sell_trades": 3.0}}, source="TrueData ticks")

    async def td_refused(symbols):
        return _Flow(values={}, warnings=["No TrueData login (the user name or password is incorrect or subscription expired)"])

    async def kite(symbols):
        asked["kite"] = list(symbols)
        return MD._SideResult(values={"AAA": {"buy_trades": 40.0, "sell_trades": 25.0}}, as_of="2026-11-04T10:05:00+05:30",
                              source=MD.KITE_SIDE_SOURCE, warnings=[], missing=[])

    r = asyncio.run(MD._default_tick_flow(["AAA"], truedata=td_ok, kite=kite))
    assert r.source == "TrueData ticks" and "kite" not in asked
    r = asyncio.run(MD._default_tick_flow(["AAA"], truedata=td_refused, kite=kite))
    assert asked["kite"] == ["AAA"] and r.source.startswith("Kite live ticks") and r.values["AAA"]["buy_trades"] == 40.0
    assert any("No TrueData login" in w for w in r.warnings)


def test_kite_sides_read_the_live_feeds_counts_and_ask_for_the_rest():
    requested = []

    async def read_quotes(symbols):
        return {"AAA": {"ask_trades": 120, "bid_trades": 80, "ask_volume": 5000.0, "bid_volume": 3000.0,
                        "received_at": "2026-11-04T10:05:01.250+05:30", "sides_since": "2026-11-04T09:15:00+05:30"},
                "BBB": {"ltp": 50.0}}                                              # in the feed, no counts yet

    async def request(symbols):
        requested.extend(symbols)
    r = asyncio.run(MD.kite_sides(["AAA", "BBB", "CCC"], read_quotes=read_quotes, request=request))
    assert r.values == {"AAA": {"buy_trades": 120.0, "sell_trades": 80.0, "buy_volume": 5000.0, "sell_volume": 3000.0}}
    assert r.missing == ["BBB", "CCC"] and requested == ["BBB", "CCC"] and r.as_of == "2026-11-04T10:05:01.250+05:30"
    assert "not counted yet for 2 stock(s)" in r.warnings[0]


def test_the_card_says_when_the_trade_side_came_from_kite(tmp_path, monkeypatch):
    monkeypatch.setattr(MD, "WIDGETS", [_v10_any_volume()])

    async def candles(symbols, interval, needs, *, lookback_days, **kw):
        return _Intra(values={"AAA": {"first_vol": 100.0, "sma1000": 5.0}, "CCC": {"first_vol": 40.0, "sma1000": 5.0}},
                      as_of="2026-11-04T09:20:00+05:30")

    async def from_kite(symbols):
        return MD._SideResult(values={"AAA": {"buy_trades": 30.0, "sell_trades": 10.0}}, as_of="2026-11-04T10:05:00+05:30",
                              source=MD.KITE_SIDE_SOURCE, warnings=[], missing=[])

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=candles, index_result=_indices,
                                 tick_flow=from_kite))
    t = out["widgets"][0]
    assert t["status"] == "ok" and [r[0] for r in t["rows"]] == ["AAA"]
    flow_line = [ln for ln in t["criteria"] if ln["text"].startswith("Trades initiated at the ask")][0]
    assert flow_line["applied"] is True and "Kite live ticks" in flow_line["note"]
    assert "Kite ticks to 10:05:00 IST" in t["as_of"]
    assert BANNED.search(flow_line["text"] + " " + flow_line["note"]) is None
