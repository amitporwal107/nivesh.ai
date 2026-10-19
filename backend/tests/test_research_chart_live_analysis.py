"""Research → Charts, live analysis for ANY symbol (routes/research_chart.py, matrix B11; PRD §7.3–§7.5):

    GET /api/research/chart/live/{symbol}/indicators   indicator values, lookbacks and overlay series
    GET /api/research/chart/live/{symbol}/patterns     research.charting detect_as_of on the same bars, PRD states

Both read nidp.prices_eod_adjusted through the DaaS (the chart-live source) and are computed at request time, so
they carry pit_status PIT_UNVERIFIED and never the snapshot's guarantees.

What is pinned here:
  - every indicator value equals the function in nidp/services/technical_indicator_engine/calculator.py (the engine
    that fills stock_features_daily) run on the same bars: one convention for the backend, the chart and the backtest;
  - the overlay series end on the scalar value (the chart line and the tile cannot disagree);
  - lookbacks are documented in the response;
  - relative strength vs Nifty 50 over 63 sessions, from the index closes on the same two dates;
  - the price band from security_reference_daily, or null with the reason;
  - lifecycle → PRD state mapping, and the eight PRD criteria per pattern with pass / fail / pending / na;
  - 503 pattern_engine_unavailable when the research package cannot be imported, 404 when there are no bars,
    403 without the `charting` feature.

MOCK — not real data: DaaS answers are synthetic rows in the real route's shape (newest first).
"""
from __future__ import annotations

import copy
import math
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from nidp.services.technical_indicator_engine import calculator as calc

USERS = {"invited": {"user_id": "u1", "email": "invited@example.com", "role": "user"},
         "other": {"user_id": "u2", "email": "other@example.com", "role": "user"}}
ALLOW = {"charting": {"mode": "allowlist", "allowlist": ["invited@example.com"]}}


class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, *a, **k):
        for d in self.docs:
            if all(d.get(key) == v for key, v in q.items()):
                return copy.deepcopy(d)
        return None


class _DB:
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


# ── synthetic bars (oldest first here; the DaaS sends newest first) ───────────

def _weekdays(n, end=date(2026, 10, 13)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def _bars(n=300):
    days = _weekdays(n)
    out, prev = [], 480.0
    for i, d in enumerate(days):
        close = round(480 + 25 * math.sin(i / 7) + 0.15 * i + 6 * math.cos(i / 3), 2)
        opn = round(prev + 2 * math.sin(i * 1.3), 2)
        high = round(max(opn, close) + 3 + 2 * abs(math.sin(i * 0.7)), 2)
        low = round(min(opn, close) - 3 - 2 * abs(math.cos(i * 0.9)), 2)
        vol = 100_000 + (i * 7919) % 60_000 + (150_000 if i == n - 1 else 0)
        out.append((d, opn, high, low, close, float(vol)))
        prev = close
    return out


BARS = _bars()
CLOSES = np.array([b[4] for b in BARS])
HIGHS = np.array([b[2] for b in BARS])
LOWS = np.array([b[3] for b in BARS])
VOLS = np.array([b[5] for b in BARS])


def _price_rows(bars=BARS, sym="FIXBRK"):
    return {"data": [{"symbol": sym, "as_of_date": d.isoformat(), "adj_open": o, "adj_high": h, "adj_low": l,
                      "adj_close": c, "adj_volume": v, "last_event_type": None} for d, o, h, l, c, v in reversed(bars)]}


def _index_rows(level0=20_000.0, step=10.0):
    days = [b[0] for b in BARS]
    return {"data": [{"as_of_date": d.isoformat(), "index_name": "Nifty 50", "close_price": level0 + step * i}
                     for i, d in reversed(list(enumerate(days)))]}


def _client(monkeypatch, *, prices=None, index=None, reference=None, engine_error=None):
    import routes.research_chart as rc
    from services.copilot_tools import daas_client

    db = _DB(ALLOW)

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers.get("X-Test-User", "invited")])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    calls = []

    async def get_raw(path, params=None, timeout=30):
        calls.append((path, params))
        if path.startswith("/prices/adjusted/"):
            return prices if prices is not None else (200, _price_rows())
        if path.startswith("/indices/"):
            return index if index is not None else (200, _index_rows())
        return 404, None
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)

    async def ref(symbol):
        if isinstance(reference, Exception):
            raise reference
        return reference
    monkeypatch.setattr(rc, "_reference_row", ref)
    if engine_error is not None:
        def broken():
            raise engine_error
        monkeypatch.setattr(rc, "_pattern_engine", broken)

    app = FastAPI(); app.include_router(rc.router)
    for route in app.routes:
        dep_list = getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []
        for dep in dep_list:
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), calls


H = {"X-Test-User": "invited"}


# ── indicators ───────────────────────────────────────────────────────────────

def test_indicator_values_equal_the_feature_engine(monkeypatch):
    c, calls = _client(monkeypatch, reference={"as_of_date": date(2026, 10, 14), "price_band_pct": None,
                                                 "band_raw": "No Band", "fno_eligible": True, "is_etf": False,
                                                 "series": "EQ"})
    res = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H)
    assert res.status_code == 200, res.text
    b = res.json()
    v = b["values"]
    assert b["as_of"] == BARS[-1][0].isoformat() and b["mode"] == "eod" and b["pit_status"] == "PIT_UNVERIFIED"
    assert b["source"] == "nidp.prices_eod_adjusted" and b["sessions"] == len(BARS)
    assert v["close"] == pytest.approx(CLOSES[-1])
    assert v["ema20"] == pytest.approx(calc.ema(CLOSES, 20))
    assert v["ema50"] == pytest.approx(calc.ema(CLOSES, 50))
    assert v["ema200"] == pytest.approx(calc.ema(CLOSES, 200))
    assert v["rsi14"] == pytest.approx(calc.rsi(CLOSES, 14))
    assert v["atr14"] == pytest.approx(calc.atr(HIGHS, LOWS, CLOSES, 14))
    assert v["atr_pct"] == pytest.approx(calc.atr(HIGHS, LOWS, CLOSES, 14) / CLOSES[-1] * 100)
    m, s, h = calc.macd(CLOSES)
    assert (v["macd"], v["macd_signal"], v["macd_hist"]) == (pytest.approx(m), pytest.approx(s), pytest.approx(h))
    assert v["roc20"] == pytest.approx(calc.pct_return(CLOSES, 20))
    avg20, _ = calc.volume_stats(VOLS, 20)
    assert v["avg_volume20"] == pytest.approx(avg20)
    assert v["rvol20"] == pytest.approx(VOLS[-1] / avg20)
    hi20, lo20 = calc.swing_high_low(HIGHS, LOWS, 20)
    assert v["resistance20"] == pytest.approx(hi20) and v["support20"] == pytest.approx(lo20)
    typ = (HIGHS[-20:] + LOWS[-20:] + CLOSES[-20:]) / 3
    assert v["vwap20"] == pytest.approx(float((typ * VOLS[-20:]).sum() / VOLS[-20:].sum()))
    assert v["avg_traded_value_cr20"] == pytest.approx(float((CLOSES[-20:] * VOLS[-20:]).mean() / 1e7))
    # The same bars, asked for once, newest first, as chart-live asks.
    price_calls = [p for p in calls if p[0] == "/prices/adjusted/FIXBRK"]
    assert len(price_calls) == 1 and price_calls[0][1]["limit"] >= 500
    # Tradability from security_reference_daily.
    t = b["tradability"]
    # staging today: F&O stocks carry "No Band" and a null percentage — passed through, never turned into 0
    assert t == {"as_of_date": "2026-10-14", "price_band_pct": None, "band_raw": "No Band", "fno_eligible": True,
                 "is_etf": False, "series": "EQ", "source": "nidp.security_reference_daily"}


def test_series_end_on_the_tile_values_and_are_dated(monkeypatch):
    c, _ = _client(monkeypatch)
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    s = b["series"]
    assert len(s["days"]) == 126 and s["days"][-1] == BARS[-1][0].isoformat()
    for k in ("ema20", "ema50", "ema200", "vwap20"):
        assert len(s[k]) == 126
        assert s[k][-1] == pytest.approx(b["values"][k])
    # first-bar seed (calculator._ema_series), masked until the lookback is full
    full = calc._ema_series(CLOSES, 20)
    assert s["ema20"][0] == pytest.approx(full[len(BARS) - 126])


def test_lookbacks_are_documented(monkeypatch):
    c, _ = _client(monkeypatch)
    defs = {d["key"]: d for d in c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()["definitions"]}
    for k in ("ema20", "ema50", "ema200", "rsi14", "atr14", "atr_pct", "macd", "roc20", "rvol20", "avg_volume20",
              "vwap20", "rs63", "resistance20", "support20"):
        assert k in defs and defs[k]["lookback"] and defs[k]["formula"], k
    assert "first" in defs["ema20"]["formula"].lower()          # the seed convention is stated


def test_relative_strength_vs_nifty_50(monkeypatch):
    c, calls = _client(monkeypatch)
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    rs = b["values"]["rs63"]
    stock = (CLOSES[-1] / CLOSES[-64] - 1) * 100
    n = len(BARS)
    bench = ((20_000 + 10 * (n - 1)) / (20_000 + 10 * (n - 64)) - 1) * 100
    assert rs["stock_return_pct"] == pytest.approx(stock)
    assert rs["benchmark_return_pct"] == pytest.approx(bench)
    assert rs["excess_pct"] == pytest.approx(stock - bench)
    assert b["benchmark"]["name"] == "Nifty 50" and b["benchmark"]["source"] == "nidp.index_eod"
    assert any(p.startswith("/indices/Nifty%2050/eod") for p, _ in calls)


def test_missing_benchmark_and_reference_are_null_with_reasons(monkeypatch):
    c, _ = _client(monkeypatch, index=(502, None), reference=RuntimeError("no pool"))
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    assert b["values"]["rs63"] is None and b["benchmark"]["reason"]
    assert b["tradability"] is None and b["tradability_reason"]
    assert b["values"]["ema20"] is not None                    # the rest still answers


def test_short_history_gives_nulls_not_zeros(monkeypatch):
    short = BARS[-30:]
    c, _ = _client(monkeypatch, prices=(200, _price_rows(short)))
    v = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()["values"]
    assert v["ema200"] is None and v["macd"] is None and v["ema50"] is None
    assert v["ema20"] is not None and v["rsi14"] is not None


def test_ema_known_answer_on_a_short_series(monkeypatch):
    # known answer worked by hand: EMA 3 (k = 0.5) seeded with the first close of [10, 20, 30, 40]
    # -> 10, 15, 22.5, 31.25; the first n-1 values are masked
    import routes.research_chart as rc
    assert rc._ema_masked(np.array([10.0, 20.0, 30.0, 40.0]), 3) == [None, None, 22.5, 31.25]


def _split_bars(n_before=120, n_after=210, ratio=5.0):
    """MOCK -- not real data. A 5:1 split the warehouse never adjusted: ~2100 before, ~420 after."""
    days = _weekdays(n_before + n_after)
    out = []
    for i, d in enumerate(days):
        base = 2100.0 if i < n_before else 420.0
        c = round(base + 3 * math.sin(i / 5), 2)
        out.append((d, c - 1, c + 4, c - 4, c, 100_000.0))
    return out


def test_unadjusted_split_in_history_does_not_drag_the_ema(monkeypatch):
    bars = _split_bars()
    c, _ = _client(monkeypatch, prices=(200, _price_rows(bars)))
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    post = np.array([x[4] for x in bars[120:]])
    brk = b["adjustment_break"]
    assert brk["date"] == bars[120][0].isoformat() and brk["prev_close"] == bars[119][4] and brk["close"] == bars[120][4]
    assert b["sessions"] == 210                                # only the bars after the break are used
    # a consistent line: EMA 200 equals the engine on the post-split bars alone, near the price, not near 2100
    assert b["values"]["ema200"] == pytest.approx(calc.ema(post, 200))
    assert 380 < b["values"]["ema200"] < 460
    assert all(v is None or 380 < v < 460 for v in b["series"]["ema200"] + b["series"]["ema50"] + b["series"]["ema20"])


def test_adjusted_split_history_has_no_break_and_a_consistent_line(monkeypatch):
    bars = _split_bars()
    adj = [(d, o / 5 if i < 120 else o, h / 5 if i < 120 else h, l / 5 if i < 120 else l, cl / 5 if i < 120 else cl, v)
           for i, (d, o, h, l, cl, v) in enumerate(bars)]
    c, _ = _client(monkeypatch, prices=(200, _price_rows(adj)))
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    assert b["adjustment_break"] is None and b["sessions"] == 330
    assert b["values"]["ema200"] == pytest.approx(calc.ema(np.array([x[4] for x in adj]), 200))


def test_ema200_with_fewer_than_200_bars_is_null_with_the_reason(monkeypatch):
    bars = _split_bars(n_before=120, n_after=150)
    c, _ = _client(monkeypatch, prices=(200, _price_rows(bars)))
    b = c.get("/api/research/chart/live/FIXBRK/indicators", headers=H).json()
    assert b["values"]["ema200"] is None and all(v is None for v in b["series"]["ema200"])
    assert b["values"]["ema50"] is not None
    assert "150" in b["series_notes"]["ema200"] and "split" in b["series_notes"]["ema200"].lower()


def test_no_bars_is_404_and_flag_is_403(monkeypatch):
    c, _ = _client(monkeypatch, prices=(200, {"data": []}))
    assert c.get("/api/research/chart/live/NOSUCH/indicators", headers=H).status_code == 404
    c, _ = _client(monkeypatch)
    assert c.get("/api/research/chart/live/FIXBRK/indicators", headers={"X-Test-User": "other"}).status_code == 403
    assert c.get("/api/research/chart/live/bad sym/indicators", headers=H).status_code == 422


# ── patterns ─────────────────────────────────────────────────────────────────

def test_state_mapping():
    import routes.research_chart as rc
    m = rc._prd_state
    assert m("CANDIDATE", {})[0] == "candidate" and m("FORMING", {})[0] == "candidate"
    assert m("GEOMETRY_VALID", {})[0] == "candidate"
    assert m("BREAKOUT_ATTEMPT", {})[0] == "awaiting_confirmation"
    assert m("PRICE_CONFIRMED", {"volume": "PASS"})[0] == "confirmed"
    st, why = m("PRICE_CONFIRMED", {"volume": "FAIL"})
    assert st == "awaiting_confirmation" and "volume" in why.lower()
    assert m("PRICE_CONFIRMED", {"volume": "PENDING"})[0] == "awaiting_confirmation"
    assert m("VOLUME_CONFIRMED", {"volume": "PASS"})[0] == "confirmed"
    assert m("FAILED", {})[0] == "invalidated" and m("INVALIDATED", {})[0] == "invalidated"
    assert m("EXPIRED", {})[0] == "expired"
    st, why = m("DATA_BLOCKED", {})
    assert st is None and why


def _rect_breakout_rows():
    """research.charting.tests.synth RECT-1 plus a breakout on 1.6x volume: a confirmed rectangle."""
    import routes.research_chart as rc
    rc._pattern_engine()                                       # puts the repo root on sys.path
    from research.charting.tests import synth
    base = synth.rect1()
    df = synth._append(base, [(109.0, 111.6, 108.8, 111.4, 160_000.0)])
    bars = [(r.date.date(), r.open, r.high, r.low, r.close, r.volume) for r in df.itertuples()]
    return bars


def test_patterns_states_and_criteria(monkeypatch):
    bars = _rect_breakout_rows()
    c, _ = _client(monkeypatch, prices=(200, _price_rows(bars)))
    res = c.get("/api/research/chart/live/FIXBRK/patterns", headers=H)
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["as_of"] == bars[-1][0].isoformat() and b["pit_status"] == "PIT_UNVERIFIED" and b["mode"] == "eod"
    eng = b["engine"]
    assert eng["engine_version"] and eng["config_hash"] and eng["registry_version"]
    rect = [p for p in b["patterns"] if p["pattern_type"] == "RECTANGLE"]
    assert rect, b["patterns"]
    p = rect[0]
    assert p["lifecycle_status"] == "PRICE_CONFIRMED" and p["state"] == "confirmed"
    assert p["label"] == "Rectangle" and p["direction"] == "BULLISH"
    assert p["detected_on"] == bars[-1][0].isoformat()        # the PRICE_CONFIRMED event's session
    keys = [k["key"] for k in p["criteria"]]
    assert keys == ["price_structure", "volume", "trend", "relative_strength", "volatility", "liquidity", "regime", "events"]
    crit = {k["key"]: k for k in p["criteria"]}
    assert crit["price_structure"]["status"] == "pass" and crit["volume"]["status"] == "pass"
    assert crit["regime"]["status"] == "na" and crit["regime"]["reason"]
    assert crit["events"]["status"] == "na" and crit["events"]["reason"]
    # 21 bars: no EMA 200, no 63-session return → the desk rules cannot judge, and say why
    assert crit["trend"]["status"] == "na" and crit["relative_strength"]["status"] == "na"
    assert crit["liquidity"]["status"] in ("pass", "fail") and crit["liquidity"]["threshold"] == 10.0
    assert all(r["rule_id"] and r["result"] in ("PASS", "FAIL", "PENDING") for r in p["rules"])
    # The registry: every family, the disabled ones with their reason.
    fams = {f["pattern_type"]: f for f in b["families"]}
    assert fams["RECTANGLE"]["enabled"] is True
    assert fams["CUP_AND_HANDLE"]["enabled"] is False and fams["CUP_AND_HANDLE"]["disabled_reason"]
    assert b["state_rule"] and b["criteria_rule"]["liquidity"]


def test_patterns_low_volume_breakout_awaits(monkeypatch):
    import routes.research_chart as rc
    rc._pattern_engine()
    from research.charting.tests import synth
    df = synth.fixture_02_low_volume_breakout(synth.rect1())
    bars = [(r.date.date(), r.open, r.high, r.low, r.close, r.volume) for r in df.itertuples()]
    c, _ = _client(monkeypatch, prices=(200, _price_rows(bars)))
    rect = [p for p in c.get("/api/research/chart/live/FIXBRK/patterns", headers=H).json()["patterns"]
            if p["pattern_type"] == "RECTANGLE"][0]
    assert rect["state"] == "awaiting_confirmation" and "volume" in rect["state_reason"].lower()
    assert {k["key"]: k["status"] for k in rect["criteria"]}["volume"] == "fail"


def test_patterns_engine_unavailable_is_503(monkeypatch):
    c, _ = _client(monkeypatch, engine_error=ImportError("No module named 'research'"))
    res = c.get("/api/research/chart/live/FIXBRK/patterns", headers=H)
    assert res.status_code == 503 and res.json()["detail"] == "pattern_engine_unavailable"


def test_patterns_no_bars_is_404(monkeypatch):
    c, _ = _client(monkeypatch, prices=(200, {"data": []}))
    assert c.get("/api/research/chart/live/FIXBRK/patterns", headers=H).status_code == 404


def test_snapshot_routes_are_untouched():
    """The live routes are an addition: the snapshot paths and their no-compute promise are unchanged."""
    import routes.research_chart as rc
    paths = {r.path for r in rc.router.routes}
    for p in ("/api/research/chart/run", "/api/research/chart/{symbol}/ohlcv", "/api/research/chart/{symbol}/patterns",
              "/api/research/chart/live/{symbol}/indicators", "/api/research/chart/live/{symbol}/patterns"):
        assert p in paths
