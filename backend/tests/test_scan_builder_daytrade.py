"""Second scan dashboard "Day trade" = Chartink 503347 (DESIGN.md §9; services/scan_builder/market_dashboard.py,
GET /api/scan-builder/market-dashboard?dashboard=daytrade), and the intraday measures it added (max / min, session VWAP,
regrouped candles in services/scan_builder/intraday.py).

The real widget definitions, criteria writer, engine and route run; the data layer's network edges, company results and
intraday candles are injected. All prices and figures below are hand-made (MOCK — not real data)."""
import asyncio
import re

import numpy as np
import pytest

from services.scan_builder import indicators as I
from services.scan_builder import intraday as SI
from services.scan_builder import market_dashboard as MD
from tests.test_scan_builder_market_dashboard import BANNED, _by_id, _data, _indices, _Intra, _Results
from tests.test_scan_builder_routes import H, _client, _reset  # noqa: F401  (_reset is an autouse fixture)


@pytest.fixture(autouse=True)
def _fresh_caches():
    from services.scan_builder import signals as SIG
    MD.reset_caches()
    saved, SIG._store = SIG._store, SIG.LocalSignalStore()          # signals never touch Redis in these tests
    yield
    SIG._store = saved
    MD.reset_caches()


def DW(wid):
    return next(w for w in MD.DAYTRADE_WIDGETS if w.id == wid)


def texts(w):
    return [ln["text"] for ln in MD.criteria_lines(w)]


CHARTINK_503347 = ["5518231", "5518232", "5518234", "5518233", "5518236", "5518237", "5518240", "5518241", "5518230",
                   "5518228", "5518242", "5518245", "5518238", "5518239", "5518243", "5518229", "5518235", "5518244",
                   "5518247", "5518246"]


# ── TC-1 / TC-2: definitions and criteria ───────────────────────────────────────────────────────────────────────────

def test_the_twenty_widgets_of_dashboard_503347_in_layout_order():
    assert [w.chartink_id for w in MD.DAYTRADE_WIDGETS] == CHARTINK_503347
    assert len({w.id for w in MD.DAYTRADE_WIDGETS}) == 20
    assert not {w.id for w in MD.DAYTRADE_WIDGETS} & {w.id for w in MD.WIDGETS}
    assert MD.DASHBOARDS["daytrade"].meta() == {"key": "daytrade", "title": "Day trade", "chartink_id": "503347"}
    assert MD.DASHBOARDS["atlas"].meta() == {"key": "atlas", "title": "Atlas fresh", "chartink_id": "247498"}
    assert len(MD.DASHBOARDS["atlas"].widgets) == 17


def test_criteria_are_written_from_the_definitions():
    assert texts(DW("dt_52w_breakout")) == ["Universe: All NSE stocks", "Close > 1 day ago Highest high of 240"]
    assert texts(DW("dt_52w_high"))[1] == "High = Highest high of 260"
    assert texts(DW("dt_down10_all")) == ["Universe: F&O stocks", "Close < 1 month ago Close × 0.9"]
    assert "1 week ago Close ≥ 12 months ago Close × 1.75" in texts(DW("dt_high_growth"))
    assert "Highest close of 5 > 6 days ago Highest close of 120 × 1.05" in texts(DW("dt_short_breakouts"))
    assert "Weekly Close ≥ Weekly Highest close of 52" in texts(DW("dt_uptrend_52w"))
    below = texts(DW("dt_below_dma"))
    assert "Close ÷ EPS, latest year (₹) > 5" in below and "Close ÷ EPS, latest year (₹) < 25" in below
    assert "Net profit, latest quarter (₹ cr) ≥ Net profit, latest year (₹ cr)" in texts(DW("dt_swing_breakout"))
    assert texts(DW("dt_strong"))[1:] == ["Close > 1 day ago Close", "1 day ago Close > 2 days ago Close",
                                          "2 days ago Close > 3 days ago Close", "3 days ago Close > 4 days ago Close",
                                          "4 days ago Close > 5 days ago Close"]
    multi = MD.criteria_lines(DW("dt_multiyear"))
    assert [ln["text"] for ln in multi][1:] == ["Any of:", "High = Highest high of 520", "Market cap (₹ cr) > 10,000",
                                                "Volume > 10,00,000"]
    assert "520-session high" in multi[1]["note"] and "April 2024" in multi[1]["note"]
    b15 = MD.criteria_lines(DW("dt_breakout_15m"))
    assert b15[0]["text"] == "Universe: F&O stocks" and "57960" in b15[0]["note"]
    assert DW("dt_vol_10x_5min").intraday is next(w for w in MD.WIDGETS if w.id == "vol_10x_5min").intraday


def test_no_barred_trading_words_on_the_day_trade_tab():
    shown = []
    for w in MD.DAYTRADE_WIDGETS:
        shown.append(w.title)
        shown += [ln["text"] + " " + (ln["note"] or "") for ln in MD.criteria_lines(w, False, "not applied — x")]
        shown += [c["label"] for c in MD.COLUMNS[w.kind]]
        shown += [w.note or "", w.partial_note or "", w.universe_note or ""]
    shown += [b.title for b in MD.DASHBOARDS.values()]
    assert [s for s in shown if BANNED.search(s)] == []


# ── TC-4: the intraday measures added for this tab ──────────────────────────────────────────────────────────────────

def _c(day, hhmm, o, h, l, c, v):
    return [f"{day}T{hhmm}:00+05:30", o, h, l, c, v]


BARS15 = [_c("2026-11-02", "15:00", 100, 101, 99, 100, 10), _c("2026-11-02", "15:15", 100, 102, 100, 101, 20),
          _c("2026-11-03", "09:15", 102, 104, 101, 103, 30), _c("2026-11-03", "09:30", 103, 106, 102, 105, 50),
          _c("2026-11-03", "09:45", 105, 105, 103, 104, 40)]


def test_regroup_makes_30_minute_candles_from_09_15_within_each_session():
    assert SI.regroup(BARS15, 30) == [
        _c("2026-11-02", "15:00", 100, 101, 99, 100, 10),             # 15:00 is slot 9 (14:45–15:15) on its own
        _c("2026-11-02", "15:15", 100, 102, 100, 101, 20),            # 15:15–15:30 is the last, short slot
        _c("2026-11-03", "09:15", 102, 106, 101, 105, 80),            # 09:15 + 09:30
        _c("2026-11-03", "09:45", 105, 105, 103, 104, 40)]            # 09:45, still in progress


def test_vwap_max_and_regrouped_rsi_equal_hand_computed_values():
    vals = SI.compute({"X": BARS15}, [("vwap", "vwap", {}, 0), ("mx", "max", {"source": "close", "period": 3}, 1),
                                      ("mn", "min", {"source": "low", "period": 2}, 0),
                                      ("r30", "rsi", {"period": 2, "bucket": 30}, 0), ("c", "close", {}, 0)])["X"]
    tp = [(104 + 101 + 103) / 3, (106 + 102 + 105) / 3, (105 + 103 + 104) / 3]
    assert vals["vwap"] == pytest.approx((tp[0] * 30 + tp[1] * 50 + tp[2] * 40) / 120)   # today's candles only
    assert vals["mx"] == 105 and vals["mn"] == 102 and vals["c"] == 104
    closes30 = np.array([[100.0], [101.0], [105.0], [104.0]])
    assert vals["r30"] == pytest.approx(float(I.rsi(closes30, 2)[-1, 0]))
    assert SI.compute({"X": [_c("2026-11-03", "09:15", 1, 1, 1, 1, 0)]}, [("v", "vwap", {}, 0)])["X"]["v"] is None
    with pytest.raises(ValueError):
        SI.check_needs([("r", "rsi", {"period": 14, "bucket": 0}, 0)])


# ── TC-3 / TC-5: computation on a hand-made market ──────────────────────────────────────────────────────────────────

def _run(tmp_path, candles, results=None):
    return asyncio.run(MD.compute(_data(tmp_path, results=results if results is not None else _Results({})),
                                  dashboard="daytrade", intraday_values=candles, index_result=_indices))


async def _no_candles(symbols, interval, needs, *, lookback_days, **kw):
    return _Intra(values={}, warnings=["intraday candles are loading"], missing=list(symbols))


def test_the_day_trade_dashboard_answers_its_twenty_widgets_with_honest_statuses(tmp_path):
    out = _run(tmp_path, _no_candles)
    assert out["dashboard"]["key"] == "daytrade" and [d["key"] for d in out["dashboards"]] == ["atlas", "daytrade", "early"]
    w = _by_id(out)
    assert [x["chartink_id"] for x in out["widgets"]] == CHARTINK_503347
    assert w["dt_12y_high"]["status"] == "not_computed" and "12 years" in w["dt_12y_high"]["note"]
    assert w["dt_high_momentum"]["status"] == "ok" and w["dt_high_momentum"]["rows"] == []
    assert "can never hold" in " ".join(ln["note"] or "" for ln in w["dt_high_momentum"]["criteria"])
    u300 = w["dt_under_300"]
    assert u300["status"] == "partial" and "200-week" in u300["note"]
    assert [ln["applied"] for ln in u300["criteria"] if ln["text"].startswith("Weekly SMA(close, 200)")] == [False]
    # intraday widgets without candles: partial, their intraday lines not applied
    assert w["dt_rsi_vwap"]["status"] == "partial" and [r[0] for r in w["dt_rsi_vwap"]["rows"]] == ["AAA"]
    assert all(not ln["applied"] for ln in w["dt_rsi_vwap"]["criteria"] if "RSI" in ln["text"] or "VWAP" in ln["text"])
    assert w["dt_breakout_15m"]["status"] == "partial"


def test_results_based_day_trade_widgets_wait_for_the_results(tmp_path):
    out = asyncio.run(MD.compute(_data(tmp_path, results=None), dashboard="daytrade", intraday_values=_no_candles,
                                 index_result=_indices))
    w = _by_id(out)
    for wid in ("dt_high_growth", "dt_below_dma", "dt_under_300", "dt_swing_breakout"):
        assert w[wid]["status"] == "pending", wid
    assert w["dt_52w_high"]["status"] == "ok"


def test_rsi_vwap_and_15_minute_breakouts_decide_on_the_candles(tmp_path):
    def answer(by_interval):
        async def candles(symbols, interval, needs, *, lookback_days, **kw):
            assert interval == "15minute" and lookback_days == 5
            keys = {k for k, *_ in needs}
            vals = {s: v for s, v in by_interval.items() if s in symbols and keys <= set(v)}
            return _Intra(values=vals, as_of="2026-11-03T10:30:00+05:30")
        return candles

    good = {"AAA": {"rsi30": 65.0, "vwap": 104.0, "c15": 106.0, "c0": 106.0, "mx20": 105.0, "v0": 900.0, "smav20": 500.0}}
    w = _by_id(_run(tmp_path, answer(good)))
    assert w["dt_rsi_vwap"]["status"] == "ok" and [r[0] for r in w["dt_rsi_vwap"]["rows"]] == ["AAA"]
    assert w["dt_breakout_15m"]["status"] == "ok" and [r[0] for r in w["dt_breakout_15m"]["rows"]] == ["AAA"]
    assert "15-minute candles to" in w["dt_breakout_15m"]["as_of"]

    MD.reset_caches()
    weak = {"AAA": {"rsi30": 55.0, "vwap": 104.0, "c15": 106.0, "c0": 104.0, "mx20": 105.0, "v0": 900.0, "smav20": 500.0}}
    w = _by_id(_run(tmp_path, answer(weak)))
    assert w["dt_rsi_vwap"]["rows"] == [] and w["dt_breakout_15m"]["rows"] == []     # RSI ≤ 60; close under the 20-high

    MD.reset_caches()
    above_vwap = {"AAA": {"rsi30": 65.0, "vwap": 107.0, "c15": 106.0, "c0": 106.0, "mx20": 105.0, "v0": 400.0,
                          "smav20": 500.0}}
    w = _by_id(_run(tmp_path, answer(above_vwap)))
    assert w["dt_rsi_vwap"]["rows"] == [] and w["dt_breakout_15m"]["rows"] == []     # VWAP above the price; volume low


# ── TC-6 / TC-7: route and one cache per dashboard ──────────────────────────────────────────────────────────────────

def test_cache_is_kept_per_dashboard(monkeypatch):
    calls = []

    async def fake_compute(data, *, dashboard, **kw):
        calls.append(dashboard)
        return {"ok": True, "dashboard": {"key": dashboard}, "run_at": "2026-11-03T04:00:00+00:00", "cached": False,
                "warnings": []}
    monkeypatch.setattr(MD, "compute", fake_compute)
    clock = lambda: 100.0
    a = asyncio.run(MD.get_dashboard(None, clock=clock))
    d = asyncio.run(MD.get_dashboard(None, dashboard="daytrade", clock=clock))
    a2 = asyncio.run(MD.get_dashboard(None, dashboard="atlas", clock=clock))
    d2 = asyncio.run(MD.get_dashboard(None, dashboard="daytrade", clock=clock))
    assert calls == ["atlas", "daytrade"]
    assert (a["dashboard"]["key"], d["dashboard"]["key"], a2["dashboard"]["key"], d2["dashboard"]["key"]) == \
        ("atlas", "daytrade", "atlas", "daytrade")
    assert a2["cached"] is True and d2["cached"] is True
    with pytest.raises(KeyError):
        asyncio.run(MD.get_dashboard(None, dashboard="nope", clock=clock))


def test_route_picks_the_dashboard_and_refuses_an_unknown_one(monkeypatch, tmp_path):
    import routes.scan_builder as rsb
    client, _ = _client(monkeypatch, tmp_path)
    asked = []

    async def fake(data, *, dashboard="atlas", **kw):
        asked.append(dashboard)
        return {"ok": True, "dashboard": MD.DASHBOARDS[dashboard].meta(), "widgets": [], "cached": False}
    monkeypatch.setattr(rsb.market_dashboard, "get_dashboard", fake)
    r = client.get("/api/scan-builder/market-dashboard?dashboard=daytrade", headers=H())
    assert r.status_code == 200 and r.json()["dashboard"]["key"] == "daytrade"
    r = client.get("/api/scan-builder/market-dashboard", headers=H())
    assert r.status_code == 200 and r.json()["dashboard"]["key"] == "atlas"
    assert asked == ["daytrade", "atlas"]
    r = client.get("/api/scan-builder/market-dashboard?dashboard=bogus", headers=H())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_dashboard"
    assert re.search(r"atlas, daytrade", r.json()["detail"]["message"])
    assert asked == ["daytrade", "atlas"]                                           # never computed for an unknown key


def test_a_list_cut_at_the_row_limit_says_how_many_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(MD, "LIMIT", 1)
    w = MD.Widget("t_all", "0", "Every stock", "scan", "cash", spec=MD._spec("t", "cash", []))
    monkeypatch.setattr(MD, "DAYTRADE_WIDGETS", [w])
    out = _run(tmp_path, _no_candles)
    t = out["widgets"][0]
    assert t["count"] == 1 and t["note"] == "2 stocks pass; the 1 with the largest % change are shown."
