"""AD-SC-16..25 — scoring v2.1 in shadow beside v2 (docs/autodesk/testcases_scoring_v21.md).

Crafted series and stub market data only (TEST DATA, not real market data).
"""
from __future__ import annotations

import pytest

from autodesk import contracts as C
from autodesk.agents import ai_trader
from autodesk.scoring import registry
from autodesk.scoring import v21_positional as v21
from autodesk.scoring import v2_positional as v2
from tests.autodesk import test_ai_trader_ts as T
from tests.autodesk.test_scoring_v2 import _key, comp, zigzag


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


# ── AD-SC-16 registry ──────────────────────────────────────────────────────────────────────────────────────────────

def test_adsc16_registry(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    st = {v["version"]: v for v in registry.describe()}
    assert st["v21-positional"]["status"] == "SHADOW" and not st["v21-positional"]["selects_signals"]
    assert st["v21-positional"]["weights"] == st["v2-positional"]["weights"]
    assert [k for k, v in st.items() if v["status"] == "ACTIVE"] == ["v1"]
    assert registry.shadow_versions() == ["v2-positional", "v21-positional"]
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v2-positional")
    assert registry.shadow_versions() == ["v2-positional"]
    assert {v["version"]: v["status"] for v in registry.describe()}["v21-positional"] == "OFF"
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "")
    assert registry.shadow_versions() == []
    with pytest.raises(ValueError):
        registry.require_active("v21-positional")


# ── AD-SC-17 setup A is context only ───────────────────────────────────────────────────────────────────────────────

def test_adsc17_setup_a_is_context_only(monkeypatch, uptrend):
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["SETUP_A_ACCUMULATION", "VOLUME_BREAKOUT"])
    a, b = v2.score_at(uptrend, t), v21.score_at(uptrend, t)
    assert "SETUP_A_ACCUMULATION" in a.signals and a.primary_signal == "SETUP_A_ACCUMULATION"
    assert "SETUP_A_ACCUMULATION" not in b.signals and "SETUP_A_ACCUMULATION" in b.context_signals
    assert b.primary_signal == "VOLUME_BREAKOUT"
    assert comp(b, "signal_quality").points <= comp(a, "signal_quality").points
    # alone, it earns no quality points and no tier
    with_signals(monkeypatch, ["SETUP_A_ACCUMULATION"])
    alone = v21.score_at(uptrend, t)
    assert comp(alone, "signal_quality").points == 0 and alone.primary_signal is None and alone.tier == "CONTEXT"


# ── AD-SC-18 no bearish penalty ────────────────────────────────────────────────────────────────────────────────────

def test_adsc18_no_bearish_penalty(monkeypatch, uptrend):
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["MACD_BULL_CROSS"], warn=["BREAKDOWN_ON_VOLUME"])
    a, b = v2.score_at(uptrend, t), v21.score_at(uptrend, t)
    assert b.warnings == ["BREAKDOWN_ON_VOLUME"]
    assert "bearish_warning" in [c.dimension for c in a.components]
    assert "bearish_warning" not in [c.dimension for c in b.components]
    assert float(b.score) == pytest.approx(min(100.0, float(a.score) + 10))


# ── AD-SC-19 v2 unchanged, v2.1 version-pinned ─────────────────────────────────────────────────────────────────────

def test_adsc19_versions_pinned(monkeypatch, uptrend):
    assert v2.RULES == "v2-positional-2026-11-05" and v21.RULES == "v21-positional-2026-11-07"
    t = len(uptrend) - 1
    with_signals(monkeypatch, ["MACD_BULL_CROSS"], ctx=["SUPERTREND_FLIP_UP"])   # nothing v2.1 changes is present
    a, b = v2.score_at(uptrend, t), v21.score_at(uptrend, t)
    assert a.version == "v2-positional" and b.version == "v21-positional"
    da, db = a.model_dump(), b.model_dump()
    da.pop("version"); db.pop("version")
    assert da == db                                    # identical wherever the two changes do not apply


# ── AD-SC-20 no look-ahead ─────────────────────────────────────────────────────────────────────────────────────────

def test_adsc20_no_lookahead():
    bars, bench = zigzag(420, 0.3)
    full = v2.features(bars, bench)
    for t in (59, 130, 251, 300, 419):
        cut = v2.features(bars[:t + 1], bench)
        assert v21.score_at(full, t).model_dump() == v21.score_at(cut, t).model_dump(), f"bar {t} changed with later data"


# ── AD-SC-21..25 AI Trader integration ─────────────────────────────────────────────────────────────────────────────

def _sig(s):
    return (_key(s), s.signal_score, [c.model_dump() for c in s.score_breakdown], s.entry_zone, s.targets)


def test_adsc21_both_scores_per_signal(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    rep = T.scan(T.data())
    stocks = [s for s in rep.signals if s.segment != C.Segment.INDEX]
    assert stocks
    for s in stocks:
        assert [x.version for x in s.shadow_scores] == ["v2-positional", "v21-positional"]
        assert all(x.status == "SHADOW" for x in s.shadow_scores)
    assert all(s.shadow_scores == [] for s in rep.signals if s.segment == C.Segment.INDEX)


def test_adsc22_v1_identical_with_0_1_2_shadows(monkeypatch):
    runs = []
    for env in ("", "v2-positional", "v21-positional", "v2-positional,v21-positional"):
        monkeypatch.setenv("AUTODESK_SCORING_SHADOW", env)
        runs.append([_sig(s) for s in T.scan(T.data()).signals])
    assert runs[0] and all(r == runs[0] for r in runs)


def test_adsc23_report_blocks(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    sh = T.scan(T.data()).shadow
    assert sh["version"] == "v2-positional" and sh["rules"] == v2.RULES                 # the v2 block shape, unchanged
    assert set(sh["versions"]) == {"v2-positional", "v21-positional"}
    assert sh["versions"]["v21-positional"]["rules"] == v21.RULES
    assert all(b["active_version"] == "v1" and b["error_count"] == 0 for b in sh["versions"].values())
    monkeypatch.setenv("AUTODESK_SCORING_SHADOW", "v21-positional")
    only = T.scan(T.data()).shadow
    assert only["version"] == "v21-positional" and set(only["versions"]) == {"v21-positional"}
    old = {k: v for k, v in sh.items() if k != "versions"}                               # a stored report without `versions`
    assert C.ScanReport.model_validate({**T.scan(T.data()).model_dump(mode="json"), "shadow": old}).shadow == old


def test_adsc24_failure_isolated_per_version(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    off = T.scan(T.data())

    def boom(F, t):
        raise RuntimeError("v21 scorer failed")
    monkeypatch.setitem(ai_trader.SHADOW_SCORERS, "v21-positional", (boom, v21.RULES))
    on = T.scan(T.data())
    assert [_sig(s)[:2] for s in on.signals] == [_sig(s)[:2] for s in off.signals]
    blocks = on.shadow["versions"]
    assert blocks["v21-positional"]["error_count"] > 0 and "RuntimeError" in next(iter(blocks["v21-positional"]["errors"].values()))
    assert blocks["v2-positional"]["error_count"] == 0 and blocks["v2-positional"]["scored"] > 0
    stocks = [s for s in on.signals if s.segment != C.Segment.INDEX]
    assert all([x.version for x in s.shadow_scores] == ["v2-positional"] for s in stocks)


def test_adsc25_features_built_once_per_stock(monkeypatch):
    monkeypatch.delenv("AUTODESK_SCORING_SHADOW", raising=False)
    calls = []
    real = v2.features
    monkeypatch.setattr(v2, "features", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    rep = T.scan(T.data())
    scored = rep.shadow["versions"]["v2-positional"]["scored"] + sum(rep.shadow["versions"]["v2-positional"]["not_scored"].values())
    assert scored > 0 and len(calls) == scored


def test_adsc36b_score_last_runs():
    """Coordinator's review: score_last called an unimported name (NameError); the live scan does not use it, so no test saw it."""
    from datetime import date, timedelta
    from decimal import Decimal

    from autodesk.market.view import Bar
    from autodesk.scoring import v21_positional as v21
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(70)]
    bars = [Bar(day=d, open=Decimal(100), high=Decimal(101), low=Decimal(99), close=Decimal(100), volume=1_000_000) for d in days]
    sh = v21.score_last(bars, bars)
    assert sh.version == "v21-positional" and sh.score is not None
    assert v21.score_last([], bars).reasons == ["no bars"]
