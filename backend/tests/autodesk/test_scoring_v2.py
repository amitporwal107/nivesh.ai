"""AD-SC-01..12, 14 — versioned scoring: v1 selects, v2-positional shadows (docs/autodesk/TESTCASES.md "Scoring v2").

Crafted series only (TEST DATA, not real market data). The walk-forward check on real history (AD-SC-15) is a study run,
reported in test_reports/.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from autodesk import contracts as C
from autodesk.agents import ai_trader
from autodesk.market.view import Bar
from autodesk.scoring import registry
from autodesk.scoring import v2_positional as v2
from tests.autodesk import test_ai_trader_ts as T


def weekdays(n: int, end: date = date(2026, 11, 5)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def mkbars(closes, days, vol=1_000_000, spread=1.0, deliv=55.0, opens=None):
    out = []
    for i, (d, c) in enumerate(zip(days, closes)):
        o = opens[i] if opens is not None else c - 0.2
        out.append(Bar(day=d, open=Decimal(str(round(o, 4))), high=Decimal(str(round(max(o, c) + spread, 4))),
                       low=Decimal(str(round(min(o, c) - spread, 4))), close=Decimal(str(round(c, 4))), volume=int(vol),
                       turnover_rs=Decimal(str(round(c * vol, 2))), deliv_pct=Decimal(str(deliv)) if deliv is not None else None))
    return out


def flat_bench(days, level=20000.0):
    return mkbars([level] * len(days), days, vol=0, spread=10, deliv=None)


# ── AD-SC-01 / 02 registry ─────────────────────────────────────────────────────────────────────────────────────────

def test_adsc01_registry(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    st = {v["version"]: v["status"] for v in registry.describe()}
    assert st == {"v1": "ACTIVE", "v2-positional": "SHADOW", "v3-intraday": "DISABLED"}
    assert registry.active_version() == "v1" and registry.shadow_versions() == ["v2-positional"]
    assert sum(registry.V2_WEIGHTS.values()) == 100
    assert {k: int(w) for k, w in registry.V2_WEIGHTS.items()} == {"signal_quality": 45, "trend_confirmation": 30,
                                                                   "relative_strength": 15, "supporting_evidence": 10}
    assert [v for v in registry.describe() if v["selects_signals"]] == [next(v for v in registry.describe() if v["version"] == "v1")]
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "")
    assert registry.shadow_versions() == []
    assert {v["version"]: v["status"] for v in registry.describe()}["v2-positional"] == "OFF"
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v3-intraday,nonsense")       # disabled / unknown versions never run
    assert registry.shadow_versions() == []


def test_adsc02_only_v1_selects():
    registry.require_active("v1")
    for v in ("v2-positional", "v3-intraday", "v9"):
        with pytest.raises(ValueError):
            registry.require_active(v)


# ── AD-SC-03 relative-strength breakout ────────────────────────────────────────────────────────────────────────────

def rs_series(n):
    days = weekdays(n)
    cl = [100.0 + 2.0 * math.sin(i / 5.0) for i in range(n - 1)] + [125.0]       # last close far above every earlier ratio
    return mkbars(cl, days), flat_bench(days)


def test_adsc03_rs_breakout_needs_251_sessions():
    bars, bench = rs_series(300)
    F = v2.features(bars, bench)
    entries, _, _, _ = v2.detect(F, len(F) - 1)
    assert "RS_BREAKOUT" in entries
    sh = v2.score_at(F, len(F) - 1)
    assert sh.primary_signal == "RS_BREAKOUT" and sh.tier == "TIER_1"
    rs = next(c for c in sh.components if c.dimension == "relative_strength")
    assert "half" in rs.detail
    short_bars, short_bench = rs_series(200)                                        # < 251 aligned sessions: cannot fire
    Fs = v2.features(short_bars, short_bench)
    assert "RS_BREAKOUT" not in v2.detect(Fs, len(Fs) - 1)[0]
    assert math.isnan(Fs.arr["rsmax250"][-1])


# ── AD-SC-04 structure ─────────────────────────────────────────────────────────────────────────────────────────────

def zigzag(n, slope):
    days = weekdays(n)
    cl = [500.0 + slope * i + 6.0 * math.sin(2 * math.pi * i / 10) for i in range(n)]
    return mkbars(cl, days, spread=0.5), flat_bench(days)


def test_adsc04_hh_hl_and_lh_ll():
    up, bench = zigzag(120, 0.8)
    Fu = v2.features(up, bench)
    assert Fu.arr["hhhl"][-1] and not Fu.arr["lhll"][-1]
    down, bench = zigzag(120, -0.8)
    Fd = v2.features(down, bench)
    assert Fd.arr["lhll"][-1] and not Fd.arr["hhhl"][-1]
    assert "LOWER_HIGHS_LOWER_LOWS" in v2.detect(Fd, len(Fd) - 1)[2]
    # a swing high at bar k is used only from k+2: the structure on a series cut at k+1 never knows about it
    for t in range(40, 119):
        cut = v2.features(up[:t + 1], bench[:t + 1])
        assert bool(cut.arr["hhhl"][-1]) == bool(Fu.arr["hhhl"][t])


# ── AD-SC-05 no look-ahead ─────────────────────────────────────────────────────────────────────────────────────────

def test_adsc05_no_lookahead():
    rnd = random.Random(7)
    n = 420
    days = weekdays(n)
    c, b = [200.0], [20000.0]
    for _ in range(n - 1):
        c.append(max(5.0, c[-1] * (1 + rnd.gauss(0.0006, 0.02))))
        b.append(b[-1] * (1 + rnd.gauss(0.0003, 0.008)))
    vols = [int(1_000_000 * (1 + 2.5 * rnd.random())) for _ in range(n)]
    bars = [Bar(day=d, open=Decimal(str(round(x * (1 + rnd.gauss(0, 0.005)), 3))), high=Decimal(str(round(x * 1.012, 3))),
                low=Decimal(str(round(x * 0.988, 3))), close=Decimal(str(round(x, 3))), volume=v, deliv_pct=Decimal("48"))
            for d, x, v in zip(days, c, vols)]
    bench = [Bar(day=d, open=Decimal(str(x)), high=Decimal(str(x)), low=Decimal(str(x)), close=Decimal(str(round(x, 2))), volume=0)
             for d, x in zip(days, b)]
    full = v2.features(bars, bench)
    for t in (59, 61, 130, 251, 300, 419):
        cut = v2.features(bars[:t + 1], bench)
        assert v2.score_at(full, t).model_dump() == v2.score_at(cut, t).model_dump(), f"bar {t} changed with later data"


# ── AD-SC-06..10 scoring rules (detect() controlled, real feature arrays) ──────────────────────────────────────────

@pytest.fixture
def uptrend():
    bars, bench = zigzag(300, 0.8)
    F = v2.features(bars, bench)
    assert F.arr["hhhl"][-1]
    return F


def with_signals(monkeypatch, entries, ctx=(), warn=()):
    real = v2.detect

    def fake(F, t):
        _, _, _, facts = real(F, t)
        return list(entries), list(ctx), list(warn), facts
    monkeypatch.setattr(v2, "detect", fake)


def comp(sh, dim):
    return next(c for c in sh.components if c.dimension == dim)


def test_adsc06_overlap(monkeypatch, uptrend):
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["MACD_BULL_CROSS"])
    macd = v2.score_at(uptrend, t)
    with_signals(monkeypatch, ["HH_HL_CONFIRMED"])
    hh = v2.score_at(uptrend, t)
    assert comp(macd, "trend_confirmation").points - comp(hh, "trend_confirmation").points == 6
    assert "counted in signal quality" in comp(hh, "trend_confirmation").detail
    with_signals(monkeypatch, ["RS_BREAKOUT"])
    rsb = v2.score_at(uptrend, t)
    assert comp(rsb, "relative_strength").points * 2 == comp(macd, "relative_strength").points
    # correlated signals of one family count once; another family adds 3; quality never exceeds 45
    with_signals(monkeypatch, ["MACD_BULL_CROSS", "HH_HL_CONFIRMED"])
    assert comp(v2.score_at(uptrend, t), "signal_quality").points == 38
    with_signals(monkeypatch, ["MACD_BULL_CROSS", "VOLUME_BREAKOUT"])
    assert comp(v2.score_at(uptrend, t), "signal_quality").points == 39
    with_signals(monkeypatch, ["RS_BREAKOUT", "SETUP_B_PULLBACK", "VOLUME_BREAKOUT", "MACD_BULL_CROSS"])
    assert comp(v2.score_at(uptrend, t), "signal_quality").points == 45


def test_adsc07_bearish_signals_are_warnings(monkeypatch, uptrend):
    assert not set(v2.WARNINGS) & set(v2.ENTRY)
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["MACD_BULL_CROSS"])
    clean = v2.score_at(uptrend, t)
    with_signals(monkeypatch, ["MACD_BULL_CROSS"], warn=["BREAKDOWN_ON_VOLUME"])
    warned = v2.score_at(uptrend, t)
    assert warned.warnings == ["BREAKDOWN_ON_VOLUME"] and comp(warned, "bearish_warning").points == -10
    assert float(clean.score) - float(warned.score) == pytest.approx(min(10.0, float(clean.score)))
    with_signals(monkeypatch, [], warn=["LOWER_HIGHS_LOWER_LOWS", "MACD_BEAR_CROSS"])
    only_bear = v2.score_at(uptrend, t)
    assert only_bear.tier == "NONE" and only_bear.primary_signal is None and only_bear.signals == []


def test_adsc08_no_chasing_penalty_and_rsi_band(monkeypatch, uptrend):
    t = len(uptrend) - 1
    uptrend.c[t] = uptrend.arr["e20"][t] + 4 * uptrend.arr["atr"][t]          # 4 ATR above EMA20
    with_signals(monkeypatch, ["MACD_BULL_CROSS"])
    uptrend.arr["rsi"][t] = 77.0
    sh = v2.score_at(uptrend, t)
    assert all(c.points >= 0 for c in sh.components)                           # no penalty component without a warning
    assert "RSI14 77.0 (4)" in comp(sh, "supporting_evidence").detail
    uptrend.arr["rsi"][t] = 85.0
    assert "RSI14 85.0 (2)" in comp(v2.score_at(uptrend, t), "supporting_evidence").detail


def test_adsc09_volume_not_rewarded_beyond_1_5x(monkeypatch, uptrend):
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["MACD_BULL_CROSS"])
    uptrend.arr["rvol"][t] = 10.0
    big = comp(v2.score_at(uptrend, t), "supporting_evidence").points
    uptrend.arr["rvol"][t] = 1.6
    small = comp(v2.score_at(uptrend, t), "supporting_evidence").points
    uptrend.arr["rvol"][t] = 1.2
    none = comp(v2.score_at(uptrend, t), "supporting_evidence").points
    assert big == small == none + 1


def test_adsc10_bands_and_attribution(monkeypatch, uptrend):
    assert [v2.band(x) for x in (100, 85, 84.99, 75, 65, 64.9, 50, 49.9, 0)] == [
        "Exceptional", "Exceptional", "Strong", "Strong", "Developing", "Weak", "Weak", "Avoid", "Avoid"]
    with_signals(monkeypatch, ["SETUP_B_PULLBACK"], ctx=["SUPERTREND_FLIP_UP"])
    sh = v2.score_at(uptrend, len(uptrend) - 1)
    assert [c.dimension for c in sh.components][:4] == ["signal_quality", "trend_confirmation", "relative_strength",
                                                        "supporting_evidence"]
    for c in sh.components:
        assert c.detail and c.weight > 0 and c.points <= c.weight
    assert float(sh.score) == pytest.approx(max(0.0, min(100.0, float(sum(c.points for c in sh.components)))))
    assert sh.band == v2.band(float(sh.score)) and sh.context_signals == ["SUPERTREND_FLIP_UP"]
    assert "context" in comp(sh, "supporting_evidence").detail


def test_adsc10b_not_scored_reasons():
    days = weekdays(40)
    sh = v2.score_last(mkbars([100.0] * 40, days), flat_bench(days))
    assert sh.score is None and "needs 60" in sh.reasons[0]
    days = weekdays(80)
    thin = v2.score_last(mkbars([20.0] * 80, days, vol=1000), flat_bench(days))          # ₹20k a day
    assert thin.score is None and "₹5 crore" in thin.reasons[0]


# ── AD-SC-11 / 12 AI Trader integration ────────────────────────────────────────────────────────────────────────────

def _key(s):
    return (s.instrument, s.category.value, s.direction.value)


def test_adsc11_v1_unchanged_with_shadow(monkeypatch):
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "")
    off = T.scan(T.data())
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v2-positional")
    on = T.scan(T.data())
    assert off.shadow is None and on.shadow is not None
    a = {_key(s): (s.signal_score, [c.model_dump() for c in s.score_breakdown], s.entry_zone, s.targets) for s in off.signals}
    b = {_key(s): (s.signal_score, [c.model_dump() for c in s.score_breakdown], s.entry_zone, s.targets) for s in on.signals}
    assert a == b and len(a) > 0
    assert [_key(s) for s in off.signals] == [_key(s) for s in on.signals]          # same selection order
    stocks = [s for s in on.signals if s.segment != C.Segment.INDEX]
    assert stocks and all(len(s.shadow_scores) == 1 and s.shadow_scores[0].version == "v2-positional"
                          and s.shadow_scores[0].status == "SHADOW" for s in stocks)
    assert all(s.shadow_scores == [] for s in off.signals)


def test_adsc12_scan_report_shadow_block(monkeypatch):
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v2-positional")
    rep = T.scan(T.data())
    sh = rep.shadow
    assert sh["version"] == "v2-positional" and sh["active_version"] == "v1" and sh["horizon"] == "POSITIONAL"
    assert sh["error_count"] == 0 and sh["scored"] + sum(sh["not_scored"].values()) >= 1
    for cand in sh["candidates"]:
        assert cand["signals"] and cand["band"] in ("Exceptional", "Strong", "Developing", "Weak", "Avoid")
    # candidates are recorded, never published: every published signal is a v1 signal
    assert all(s.model_version == ai_trader.MODEL_VERSION for s in rep.signals)


def test_adsc12b_shadow_failure_never_breaks_v1(monkeypatch):
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "")
    off = T.scan(T.data())

    def boom(*a, **k):
        raise RuntimeError("shadow scorer failed")
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v2-positional")
    monkeypatch.setattr(v2, "score_last", boom)
    on = T.scan(T.data())
    assert [(_key(s), s.signal_score) for s in on.signals] == [(_key(s), s.signal_score) for s in off.signals]
    assert on.shadow["error_count"] > 0 and "RuntimeError" in next(iter(on.shadow["errors"].values()))


# ── AD-SC-14 old bodies ────────────────────────────────────────────────────────────────────────────────────────────

def test_adsc14_old_bodies_parse(monkeypatch):
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "")
    rep = T.scan(T.data())
    body = rep.signals[0].model_dump(mode="json")
    body.pop("shadow_scores")
    assert C.Signal.model_validate(body).shadow_scores == []
    rb = rep.model_dump(mode="json"); rb.pop("shadow")
    assert C.ScanReport.model_validate(rb).shadow is None
