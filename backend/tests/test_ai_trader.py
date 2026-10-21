"""AI Trader Phase 1 (docs/prd/AI_TRADER_PHASE1.prd.md; cases TC-1..TC-11 in test_reports/ai_trader_phase1_TESTCASES.md).

Real data: the index files under research/index_history/data (NIFTY 500, sector indices, India VIX, breadth).
MOCK — not real data: every stock bar series below is synthetic; the route tests replace the bars source and auth.
Property tests copy the real index files into a temp folder cut at `as_of` and require identical output.

Worked examples
  calibration  10 predictions at 0.8 with 8 hits -> bin 0.8-0.9 observed 0.8; Brier = (8*0.04 + 2*0.64)/10 = 0.16
  shrinkage    5 trades, 4 winners -> raw 0.8, weight 5/30, shrunk = (5/30)*0.8 + (25/30)*0.5 = 0.55
"""
from __future__ import annotations

import random
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import ai_trader as route
from services.ai_trader import _research
from services.ai_trader.calibration import CalibrationError, calibration_report
from services.ai_trader.context import market_context
from services.ai_trader.evidence import Evidence, EvidenceError, unavailable
from services.ai_trader.sector import sector_rotation
from services.ai_trader.timeframes import _conflicts, timeframe_evidence, trend_by_timeframe
from services.ai_trader.validation import LOW_SAMPLE_N, evaluate_events, summarise

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "index_history" / "data"
ctx, regime, rw, _rs = _research.load()


# ---- helpers ----------------------------------------------------------------

def trading_dates(lo="2021-01-04", hi="2022-12-30"):
    d = pd.read_csv(DATA / "NIFTY_500.csv", parse_dates=["date"])["date"]
    return d[(d >= lo) & (d <= hi)].reset_index(drop=True)


def synth_bars(dates, start=100.0, drift=0.002, seed=1):
    """MOCK — not real data."""
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + drift + rng.normal(0, 0.004, len(dates)))
    return pd.DataFrame({"date": pd.to_datetime(dates), "open": close * 0.999, "high": close * 1.004,
                         "low": close * 0.996, "close": close, "volume": 1000.0})


def long_dates():
    d = pd.read_csv(DATA / "NIFTY_500.csv", parse_dates=["date"])["date"]
    return d[d <= "2022-12-30"].reset_index(drop=True)


def cut_copy(dst: Path, as_of: str) -> Path:
    dst.mkdir()
    for f in DATA.glob("*.csv"):
        df = pd.read_csv(f)
        df[df["date"] <= as_of].to_csv(dst / f.name, index=False)
    return dst


# ---- TC-1 Evidence schema ----------------------------------------------------

def _ev(**kw):
    base = dict(skill="technical", symbol="X", as_of="2022-01-03", horizon="daily", observation="o",
                interpretation="i", confidence=0.5, decision_impact="neutral")
    base.update(kw)
    return Evidence(**base)


def test_evidence_has_every_required_field():
    d = _ev().to_dict()
    for k in ("skill", "symbol", "as_of", "horizon", "observation", "interpretation", "confidence", "contradictions",
              "conditions", "sources", "decision_impact", "status", "reason_code"):
        assert k in d


@pytest.mark.parametrize("kw", [dict(confidence=1.2), dict(confidence=-0.1), dict(confidence=True),
                                dict(skill="nope"), dict(decision_impact="buy"), dict(status="MAYBE"),
                                dict(status="UNAVAILABLE"), dict(reason_code="X")])
def test_evidence_rejects_bad_values(kw):
    with pytest.raises(EvidenceError):
        _ev(**kw)


def test_unavailable_helper_is_valid_and_neutral():
    e = unavailable("technical", "X", "2022-01-03", "daily", "thing", "SEALED_GAP")
    assert e.status == "UNAVAILABLE" and e.reason_code == "SEALED_GAP" and e.decision_impact == "neutral"


# ---- market, sector (real index data) ----------------------------------------

def test_market_context_on_a_normal_day_is_complete():
    ev = market_context("2022-06-15")
    assert len(ev) == 4
    assert all(e.skill == "market_intelligence" and e.status == "OK" for e in ev), [e.observation for e in ev]
    assert ev[0].data["regime"]["value"] in ("BULL", "BEAR", "SIDEWAYS")


def test_sector_rotation_ranks_every_sector_index_on_disk():
    ev = sector_rotation("2022-06-15")
    names = {e.data["sector"] for e in ev if e.status == "OK"}
    on_disk = set(sector_rotation.__globals__["sector_index_names"](ctx))
    assert names == on_disk and len(names) >= 10
    ranks = sorted(e.data["rank"] for e in ev if e.status == "OK")
    assert ranks == list(range(1, len(names) + 1))
    rs = [e.data["rs_20"] for e in sorted(ev, key=lambda e: e.data["rank"])]
    assert rs == sorted(rs, reverse=True)


# ---- TC-3 sealed window -------------------------------------------------------

@pytest.mark.parametrize("as_of", ["2023-06-01", "2023-01-02", "2024-07-31"])
def test_sealed_dates_are_unavailable_never_a_number(as_of):
    for e in market_context(as_of) + sector_rotation(as_of):
        assert e.status == "UNAVAILABLE" and e.reason_code == "SEALED_GAP", e.observation
        assert e.data == {}


def test_a_window_reaching_into_the_sealed_block_is_unavailable():
    # 2024-08-01 is the first session after the block; a 200-session SMA window starts well inside it
    ev = market_context("2024-08-01")
    assert ev[0].status == "UNAVAILABLE" and ev[0].reason_code == "SEALED_GAP"


# ---- TC-4 point-in-time property ---------------------------------------------

def _same(a, b):
    """OK evidence must be identical. UNAVAILABLE evidence must match in status and carry no data; its reason code may
    differ only because cutting a file to nothing turns BEFORE_COVERAGE into NO_DATA_FOR_DATE."""
    if a["status"] == "UNAVAILABLE" and b["status"] == "UNAVAILABLE":
        return a["data"] == b["data"] == {} and a["horizon"] == b["horizon"]
    return _round(a) == _round(b)


def _round(x):
    """Floats to 9 places: the cut copies are re-written as CSV, which can change the last digit of a float."""
    if isinstance(x, float):
        return round(x, 9)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def test_outputs_do_not_change_when_all_later_data_is_removed(tmp_path, monkeypatch):
    dates = pd.read_csv(DATA / "NIFTY_500.csv", parse_dates=["date"])["date"]
    pool = [d for d in dates if d >= pd.Timestamp("2020-01-01") and not rw.is_sealed_gap(d)]
    picks = random.Random(7).sample(pool, 50)
    full = {d: ([e.to_dict() for e in market_context(d.date().isoformat())],
                [e.to_dict() for e in sector_rotation(d.date().isoformat())]) for d in picks}
    mismatches = []
    for n, d in enumerate(picks):
        folder = cut_copy(tmp_path / f"c{n}", d.date().isoformat())
        monkeypatch.setenv("CHARTING_INDEX_HISTORY_DIR", str(folder))
        monkeypatch.setenv("CHARTING_BREADTH_UNIVERSE_PATH", str(folder / "BREADTH_UNIVERSE.csv"))
        cut = ([e.to_dict() for e in market_context(d.date().isoformat())],
               [e.to_dict() for e in sector_rotation(d.date().isoformat())])
        if [_same(a, b) for a, b in zip(sum(cut, []), sum(full[d], []))].count(False) or \
                len(sum(cut, [])) != len(sum(full[d], [])):
            mismatches.append(d.date().isoformat())
        shutil.rmtree(folder)
    assert mismatches == []


def test_stock_trends_do_not_change_when_later_bars_are_removed():
    dates = long_dates()
    bars = synth_bars(dates, seed=3)
    for as_of in random.Random(5).sample([d for d in dates[300:]], 10):
        a = trend_by_timeframe("X", bars, as_of.date().isoformat())
        b = trend_by_timeframe("X", bars[bars["date"] <= as_of].copy(), as_of.date().isoformat())
        assert a == b


# ---- TC-8 timeframe conflicts --------------------------------------------------

def test_conflict_between_timeframes_names_both():
    src = [{"name": "t", "timestamp": "d"}]
    ev = _conflicts("X", "2022-06-15", {"daily": "bullish", "weekly": "bullish", "monthly": "bearish"}, src)
    assert len(ev) == 2 and all(e.decision_impact == "opposes" for e in ev)
    assert "monthly trend is bearish while daily trend is bullish." in ev[1].contradictions[0] or \
        "monthly trend is bearish while daily trend is bullish." in ev[0].contradictions[0]


def test_no_conflict_when_trends_agree_or_are_flat():
    src = [{"name": "t", "timestamp": "d"}]
    assert _conflicts("X", "d", {"daily": "bullish", "weekly": "bullish", "monthly": "bullish"}, src) == []
    assert _conflicts("X", "d", {"daily": "bullish", "weekly": "flat", "monthly": "bearish"}, src) == [
    ] or all("weekly" not in c for e in _conflicts("X", "d", {"daily": "bullish", "weekly": "flat", "monthly": "bearish"}, src)
             for c in e.contradictions)


def test_uptrend_stock_is_bullish_on_every_timeframe_with_no_conflict():
    dates = long_dates()
    ev = timeframe_evidence("X", synth_bars(dates, drift=0.003), "2022-12-30")
    by = {e.horizon: e for e in ev if e.status == "OK"}
    assert set(by) == {"daily", "weekly", "monthly"}, [(e.horizon, e.reason_code) for e in ev]
    assert all(e.decision_impact == "supports" for e in by.values())
    assert not any(e.contradictions for e in ev)


def test_reversal_stock_produces_a_real_conflict():
    dates = long_dates()
    n = len(dates)
    close = np.concatenate([np.linspace(300, 100, n - 30), np.linspace(100, 160, 30)])
    bars = pd.DataFrame({"date": dates, "open": close, "high": close * 1.003, "low": close * 0.997,
                         "close": close, "volume": 1000.0})
    ev = timeframe_evidence("X", bars, "2022-12-30")
    tr = trend_by_timeframe("X", bars, "2022-12-30")
    assert tr["daily"]["class"] in ("BULL", "STRONG_BULL")
    assert tr["monthly"]["class"] in ("BEAR", "STRONG_BEAR")
    assert any(e.contradictions for e in ev)


def test_timeframes_withheld_when_as_of_is_not_a_session_of_the_symbol():
    bars = synth_bars(long_dates())
    for as_of, reason in (("2023-06-01", "SEALED_GAP"), ("2022-01-01", "NO_DATA_FOR_DATE")):   # 1 Jan 2022 = Saturday
        tr = trend_by_timeframe("X", bars, as_of)
        assert {v["reason"] for v in tr.values()} == {reason} and all(v["class"] is None for v in tr.values())


def test_unfinished_bar_is_not_used():
    dates = long_dates()
    tr = trend_by_timeframe("X", synth_bars(dates), "2022-12-30")
    assert tr["monthly"]["bar_date"] < "2022-12-30"      # December is incomplete at as_of -> last complete is November
    assert tr["weekly"]["bar_date"] < "2022-12-30"


# ---- TC-5, TC-9 pattern validation --------------------------------------------

def _flat_bars(dates, price=100.0):
    return pd.DataFrame({"date": dates, "open": price, "high": price, "low": price, "close": price, "volume": 1.0})


def _events(dates, k):
    return [{"symbol": "X", "signal_date": str(d.date()), "direction": "long"} for d in dates[10:10 + k]]


def test_small_sample_is_shrunk_and_flagged():
    s = summarise([{"net_pct": x} for x in (0.01, 0.02, 0.01, 0.03, -0.01)])
    assert s["n"] == 5 and s["hits"] == 4 and s["hit_rate"] == 0.8
    assert s["shrunk_hit_rate"] == pytest.approx(5 / 30 * 0.8 + 25 / 30 * 0.5)
    assert "LOW_SAMPLE" in s["flags"]


def test_adequate_sample_is_not_shrunk_or_flagged():
    s = summarise([{"net_pct": 0.01 if i % 4 else -0.01} for i in range(LOW_SAMPLE_N)])
    assert s["shrunk_hit_rate"] == pytest.approx(s["hit_rate"]) and s["flags"] == []


def test_empty_sample_has_no_numbers():
    s = summarise([])
    assert s["n"] == 0 and s["hit_rate"] is None and s["expectancy_net_pct"] is None and "NO_SAMPLE" in s["flags"]


def test_expectancy_is_net_of_costs():
    d = trading_dates("2021-01-04", "2021-06-30")
    out = evaluate_events(_events(d, 3), {"X": _flat_bars(d)}, horizon=5)
    assert out["n"] == 3 and out["hits"] == 0
    # flat price: gross 0, so net must be exactly minus the round-trip cost card on Rs 100,000
    assert out["expectancy_net_pct"] < 0
    rt = evaluate_events(_events(d, 1), {"X": _flat_bars(d)}, horizon=5)["expectancy_net_pct"]
    assert out["expectancy_net_pct"] == pytest.approx(rt)
    assert "zerodha-equity-v1" in out["cost_basis"]


def test_events_in_or_across_the_sealed_block_are_skipped():
    d = pd.read_csv(DATA / "NIFTY_500.csv", parse_dates=["date"])["date"]
    d = pd.concat([d, pd.Series(pd.bdate_range("2023-01-02", "2024-09-30"))]).drop_duplicates().sort_values().reset_index(drop=True)
    bars = _flat_bars(d)
    ev = [{"symbol": "X", "signal_date": "2022-12-28", "direction": "long"},     # exit lands inside the block
          {"symbol": "X", "signal_date": "2023-05-02", "direction": "long"},     # inside the block
          {"symbol": "X", "signal_date": "2024-08-02", "direction": "long"}]     # clear
    out = evaluate_events(ev, {"X": bars}, horizon=5)
    assert out["skipped"]["sealed_window"] == 2 and out["n"] == 1


def test_short_and_missing_data_are_counted_not_faked():
    d = trading_dates("2021-01-04", "2021-06-30")
    ev = _events(d, 2) + [{"symbol": "X", "signal_date": str(d[20].date()), "direction": "short"},
                          {"symbol": "ZZ", "signal_date": str(d[20].date()), "direction": "long"},
                          {"symbol": "X", "signal_date": str(d.iloc[-1].date()), "direction": "long"}]
    out = evaluate_events(ev, {"X": _flat_bars(d)}, horizon=5)
    assert out["n"] == 2
    assert out["skipped"] == {"short_not_supported": 1, "sealed_window": 0, "no_bars": 1, "horizon_beyond_data": 1}


def test_regime_breakdown():
    s = summarise([{"net_pct": 0.01, "regime": "BULL"}, {"net_pct": -0.01, "regime": "BEAR"},
                   {"net_pct": 0.02, "regime": "BULL"}])
    assert s["by_regime"]["BULL"]["n"] == 2 and s["by_regime"]["BEAR"]["hits"] == 0


# ---- TC-6 calibration -----------------------------------------------------------

def test_calibration_matches_hand_calculation():
    r = calibration_report([(0.8, True)] * 8 + [(0.8, False)] * 2)
    b = next(x for x in r["bins"] if x["low"] == 0.8)
    assert b["n"] == 10 and b["observed_rate"] == pytest.approx(0.8) and b["mean_confidence"] == pytest.approx(0.8)
    assert r["brier"] == pytest.approx(0.16) and r["calibration_error"] == pytest.approx(0.0)


def test_overconfident_predictions_show_a_gap():
    r = calibration_report([(0.9, True)] * 5 + [(0.9, False)] * 5)
    assert r["calibration_error"] == pytest.approx(0.4)


def test_calibration_edges_and_empty():
    assert calibration_report([])["brier"] is None
    r = calibration_report([(1.0, True), (0.5, True), (0.0, False), (0.4999, False)])
    assert [b["n"] for b in r["bins"]] == [2, 1, 0, 0, 0, 1]
    with pytest.raises(CalibrationError):
        calibration_report([(1.5, True)])


# ---- TC-2, TC-7 routes ------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)

    async def user(): return {"user_id": "u1"}
    app.dependency_overrides[route.get_current_user] = user
    return TestClient(app)


@pytest.fixture
def bars_source(monkeypatch):
    """MOCK — not real data: stands in for the Kite daily-bars loader."""
    bars = synth_bars(long_dates())
    monkeypatch.setattr(route, "_load_bars", lambda sym: (bars, None) if sym.upper() == "TESTCO" else
                        (_ for _ in ()).throw(route.HTTPException(status_code=404, detail="unknown_symbol")))
    return bars


def test_route_market_only_when_no_symbol(client):
    r = client.get("/api/ai-trader/evidence", params={"as_of": "2022-06-15"})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] is None and len(body["evidence"]) >= 5
    assert all(0 <= e["confidence"] <= 1 and e["skill"] and e["decision_impact"] for e in body["evidence"])


def test_route_with_symbol_adds_timeframes(client, bars_source):
    r = client.get("/api/ai-trader/evidence", params={"as_of": "2022-12-30", "symbol": "testco"})
    assert r.status_code == 200
    horizons = {e["horizon"] for e in r.json()["evidence"] if e["symbol"] == "TESTCO"}
    assert {"daily", "weekly", "monthly"} <= horizons


def test_route_sealed_date_is_unavailable_everywhere(client, bars_source):
    r = client.get("/api/ai-trader/evidence", params={"as_of": "2023-06-01", "symbol": "TESTCO"})
    assert r.status_code == 200
    assert all(e["status"] == "UNAVAILABLE" and e["reason_code"] == "SEALED_GAP" for e in r.json()["evidence"])


def test_route_errors(client, bars_source):
    assert client.get("/api/ai-trader/evidence").status_code == 422
    assert client.get("/api/ai-trader/evidence", params={"as_of": "not-a-date"}).status_code == 422
    assert client.get("/api/ai-trader/evidence", params={"as_of": "2022-06-15", "symbol": "bad symbol!"}).status_code == 422
    r = client.get("/api/ai-trader/evidence", params={"as_of": "2022-06-15", "symbol": "NOPE"})
    assert r.status_code == 404 and r.json()["detail"] == "unknown_symbol"


def test_route_requires_auth():
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    assert c.get("/api/ai-trader/evidence", params={"as_of": "2022-06-15"}).status_code == 401
    assert c.post("/api/ai-trader/calibration", json={"predictions": []}).status_code == 401
    assert c.post("/api/ai-trader/pattern-validation", json={"events": []}).status_code == 401


def test_route_missing_bars_source_is_reported_not_hidden(client, monkeypatch):
    monkeypatch.setattr(route, "_load_bars", lambda sym: (None, "bars source not present on this host"))
    r = client.get("/api/ai-trader/evidence", params={"as_of": "2022-06-15", "symbol": "TESTCO"})
    assert r.status_code == 200 and r.json()["notes"]
    tf = [e for e in r.json()["evidence"] if e["symbol"] == "TESTCO"]
    assert len(tf) == 3 and all(e["reason_code"] == "BARS_SOURCE_MISSING" for e in tf)


def test_route_calibration(client):
    r = client.post("/api/ai-trader/calibration",
                    json={"predictions": [{"confidence": 0.8, "hit": True}] * 8 + [{"confidence": 0.8, "hit": False}] * 2})
    assert r.status_code == 200 and r.json()["brier"] == pytest.approx(0.16)
    assert client.post("/api/ai-trader/calibration", json={"predictions": [{"confidence": 2, "hit": True}]}).status_code == 422


def test_route_pattern_validation(client, bars_source):
    ds = trading_dates("2021-03-01", "2021-09-30")
    ev = [{"symbol": "TESTCO", "signal_date": str(d.date())} for d in ds[:40]]
    r = client.post("/api/ai-trader/pattern-validation", json={"events": ev, "horizon_sessions": 5})
    assert r.status_code == 200 and r.json()["n"] == 40 and r.json()["flags"] == []
    assert client.post("/api/ai-trader/pattern-validation", json={"events": ev, "horizon_sessions": 0}).status_code == 422
    big = [{"symbol": "TESTCO", "signal_date": "2021-03-01"}] * (route.MAX_EVENTS + 1)
    assert client.post("/api/ai-trader/pattern-validation", json={"events": big}).status_code == 422


# ---- TC-10 data -------------------------------------------------------------------

def test_sector_rows_match_files_and_latest_date_is_fresh():
    files = {p.stem for p in DATA.glob("NIFTY_*.csv")} - {"NIFTY_500", "NIFTY_50", "NIFTY_MIDCAP_150", "NIFTY_SMLCAP_250"}
    ev = [e for e in sector_rotation("2022-06-15") if e.status == "OK"]
    assert len(ev) == len(files)
    for f in files:
        last = pd.read_csv(DATA / f"{f}.csv", parse_dates=["date"])["date"].max()
        assert last >= pd.Timestamp("2024-08-01"), f"{f} ends {last.date()}"
