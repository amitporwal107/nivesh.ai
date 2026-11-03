"""Realtime scan dashboard (DESIGN.md §8; services/scan_builder/market_dashboard.py, GET /api/scan-builder/market-dashboard).

The real widget definitions, criteria writer, engine and route run; the data layer's network edges (DaaS, the live feed, Kite),
company results, intraday candles and index quotes are injected. All prices and figures below are hand-made (MOCK — not real
data)."""
import asyncio
import json
import re
from dataclasses import dataclass, field

import numpy as np
import pytest

from services.scan_builder import data as sd
from services.scan_builder import market_dashboard as MD
from tests.test_scan_builder_data import IST_PREOPEN, FakeDaas, StubRest
from tests.test_scan_builder_routes import ROWS, H, _client, _reset  # noqa: F401  (_reset is an autouse fixture)


@pytest.fixture(autouse=True)
def _fresh_cache():
    MD._cache.update(at=float("-inf"), value=None)
    yield
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
    nc = MD.criteria_lines(W("vol_10x_5min"))
    assert [ln["applied"] for ln in nc] == [True, False, True, True, False]


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
    assert w["vol_10x_5min"]["status"] == "not_computed" and "initiated at the ask" in w["vol_10x_5min"]["note"]
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
    assert r.status_code == 200 and r.json()["ok"] is True
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
        return _Intra(values={"AAA": {"ema21": 1.0}}, as_of="09:30")    # CCC's candles have not arrived

    out = asyncio.run(MD.compute(_data(tmp_path, results=_Results({})), intraday_values=half, index_result=_indices))
    t = out["widgets"][0]
    assert t["status"] == "partial" and [r[0] for r in t["rows"]] == ["AAA"]
    assert t["note"].startswith("1 of 2 stocks have no 15-minute candles yet")
    assert all(ln["applied"] for ln in t["criteria"])            # applied to every stock that has candles
