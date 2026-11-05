"""AD-20..AD-24 (AI Trader) and AD-25 (Tech Support) on crafted bars (TEST DATA in a FrozenMarketView)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from autodesk import contracts as C
from autodesk.agents import ai_trader, tech_support
from autodesk.agents.ai_trader import AITrader
from autodesk.agents.tech_support import TechSupport
from autodesk.market.view import IST, Bar, BuildupRow, FnoContract, FrozenMarketView
from tests.autodesk import marketdata as md
from tests.autodesk.conftest import run

D = md.FNO_DAY                     # last visible session
SD = md.SD
AS_OF = md.AS_OF
DAYS = [d for d in md.SESSIONS if d <= D]


def series(closes: list[Decimal], vols: list[int], deliv: Decimal | None = Decimal("55")) -> list[Bar]:
    days = DAYS[-len(closes):]
    return [Bar(day=d, open=c - 1, high=c + 2, low=c - 2, close=c, volume=v, turnover_rs=c * v, deliv_pct=deliv)
            for d, c, v in zip(days, closes, vols)]


def breakout_bars() -> list[Bar]:
    cl = [Decimal(400) + Decimal(i) * Decimal("0.5") for i in range(59)] + [Decimal("440")]   # last bar jumps
    return series(cl, [100_000] * 59 + [220_000])


def down_bars() -> list[Bar]:
    cl = [Decimal(600) - Decimal(i) for i in range(60)]
    return series(cl, [100_000] * 60)


def flat_index() -> list[Bar]:
    cl = [Decimal(24000) + (Decimal(30) if i % 2 else Decimal(-30)) for i in range(60)]
    return [Bar(day=d, open=c, high=c + 60, low=c - 60, close=c, volume=0) for d, c in zip(DAYS[-60:], cl)]


def bench() -> list[Bar]:
    cl = [Decimal(23000) + Decimal(i * 5) for i in range(60)]
    return [Bar(day=d, open=c, high=c + 50, low=c - 50, close=c, volume=0) for d, c in zip(DAYS[-60:], cl)]


def fut(sym: str) -> FnoContract:
    return FnoContract(day=D, underlying=sym, kind="FUT", expiry=md.EXP, strike=None, close=Decimal(1), settle=None,
                       underlying_price=None, open_interest=1, change_in_oi=0, traded_volume=1, lot_size=100)


def buildup(sym: str, label: str) -> BuildupRow:
    return BuildupRow(day=D, underlying=sym, label=label, price_change_pct=Decimal("1.2"),
                      oi_change_pct=Decimal("6.5"), fut_close=Decimal(1), open_interest=1000)


def data(**over) -> dict:
    base = {"sessions": md.SESSIONS,
            "bars": {"BRK": breakout_bars(), "DWN": down_bars(), "LB": breakout_bars(), "SB": down_bars(),
                     "SC": breakout_bars(), "LU": down_bars()},
            "index": {"Nifty 50": bench(), "Nifty Bank": flat_index()},
            "vix": {D: Decimal("13.5")},
            "buildup": {D: [buildup("LB", "long_buildup"), buildup("SB", "short_buildup"),
                            buildup("SC", "short_covering"), buildup("LU", "long_unwinding"),
                            buildup("DWN", "neutral"), buildup("BANKNIFTY", "neutral")]},
            "fno": {s: [fut(s)] for s in ("LB", "SB", "SC", "LU", "DWN", "BANKNIFTY")},
            "sector": {"BRK": "Capital Goods"}}
    base.update(over)
    return base


def scan(d: dict, symbols=None) -> C.ScanReport:
    ctx = md.ctx(FrozenMarketView(AS_OF, d), {"session_date": SD.isoformat(), "universe": "FNO", "symbols": symbols,
                                              "min_score": "0"})
    res = run(AITrader().run(md.task(C.TaskType.SCAN_MARKET), ctx))
    return C.ScanReport.model_validate(res.output)


def by(rep, sym, cat=None):
    return [s for s in rep.signals if s.instrument == sym and (cat is None or s.category == cat)]


def test_ad20_breakout_and_score_sum():
    rep = scan(data(), symbols=["BRK"])
    [s] = by(rep, "BRK", C.SignalCategory.BREAKOUT)
    assert s.direction == C.Direction.BULLISH and s.segment == C.Segment.CASH and not s.fno_eligible
    assert s.signal_score == sum(c.points for c in s.score_breakdown)
    assert {c.dimension: c.weight for c in s.score_breakdown} == ai_trader.WEIGHTS
    assert sum(ai_trader.WEIGHTS.values()) == 100 and s.calibrated_probability is None
    assert s.rule_version == "ait-rules-v1" and s.invalidation_price < s.reference_price < s.targets[0]
    structure = next(c for c in s.score_breakdown if c.dimension == "structure")
    assert structure.points == 15 and "derivatives" in s.missing_inputs      # not an F&O underlying


def test_ad21_buildup_categories():
    rep = scan(data())
    want = {"LB": (C.SignalCategory.LONG_BUILDUP, C.Direction.BULLISH),
            "SB": (C.SignalCategory.SHORT_BUILDUP, C.Direction.BEARISH),
            "SC": (C.SignalCategory.SHORT_COVERING, C.Direction.BULLISH),
            "LU": (C.SignalCategory.LONG_UNWINDING, C.Direction.BEARISH)}
    for sym, (cat, d) in want.items():
        [s] = by(rep, sym, cat)
        assert s.direction == d and s.segment == C.Segment.FUTURES and s.fno_eligible
        der = next(c for c in s.score_breakdown if c.dimension == "derivatives")
        assert der.available and der.points > 0
    [idx] = by(rep, "BANKNIFTY")
    assert idx.category == C.SignalCategory.RANGE_BOUND and idx.direction == C.Direction.NEUTRAL
    assert idx.segment == C.Segment.INDEX and idx.invalidation_price is None


def test_ad22_missing_inputs_score_zero():
    d = data(index={}, vix={}, bars={"BRK": [b.__class__(**{**b.__dict__, "deliv_pct": None})
                                             for b in breakout_bars()]})
    rep = scan(d, symbols=["BRK"])
    [s] = by(rep, "BRK", C.SignalCategory.BREAKOUT)
    comps = {c.dimension: c for c in s.score_breakdown}
    assert not comps["relative_strength"].available and comps["relative_strength"].points == 0
    assert not comps["regime"].available and comps["regime"].points == 0
    for name in ("relative_strength", "regime", "delivery_pct", "india_vix"):
        assert name in s.missing_inputs, s.missing_inputs
    assert "Nifty 50 bars" in rep.regime["missing"] or "Nifty 50 history" in rep.regime["missing"]


def test_ad23_time_fields():
    rep = scan(data())
    close = datetime(SD.year, SD.month, SD.day, 15, 30, tzinfo=IST).astimezone(timezone.utc)
    assert rep.signals
    for s in rep.signals:
        assert s.data_as_of <= AS_OF and s.session_date == SD and s.expires_at == close


def test_ad24_deterministic():
    strip = lambda r: [s.model_dump(mode="json", exclude={"signal_id"}) for s in r.signals]   # noqa: E731
    assert strip(scan(data())) == strip(scan(data()))


def test_score_floor_suppresses():
    ctx = md.ctx(FrozenMarketView(AS_OF, data()), {"session_date": SD.isoformat(), "universe": "FNO",
                                                   "min_score": "101"})
    rep = C.ScanReport.model_validate(run(AITrader().run(md.task(C.TaskType.SCAN_MARKET), ctx)).output)
    assert rep.signals == [] and any("below 101" in x["reason"] for x in rep.suppressed)


# ── Tech Support ────────────────────────────────────────────────────────────────────────────────────────────────────

def premarket(d: dict) -> C.PremarketReport:
    ctx = md.ctx(FrozenMarketView(AS_OF, d), {"session_date": SD.isoformat(), "db_ok": True})
    return C.PremarketReport.model_validate(run(TechSupport().run(md.task(C.TaskType.PREMARKET_HEALTH_CHECK), ctx)).output)


def test_ad25_ready_degraded_blocked(monkeypatch):
    monkeypatch.setattr(tech_support, "MIN_CASH_ROWS", 2)
    monkeypatch.setattr(tech_support, "MIN_FNO_UNDERLYINGS", 2)
    r = premarket(data())
    assert r.status == C.HealthStatus.READY and r.allowed_segments == [C.Segment.CASH, C.Segment.FUTURES,
                                                                       C.Segment.OPTIONS]
    assert r.data_as_of == {"cash_eod": D.isoformat(), "fno_eod": D.isoformat()}
    r = premarket(data(fno={}))
    assert r.status == C.HealthStatus.DEGRADED and r.allowed_segments == [C.Segment.CASH]
    cut = {k: [b for b in v if b.day < D] for k, v in data()["bars"].items()}       # D's cash file missing
    r = premarket(data(bars=cut))
    assert r.status == C.HealthStatus.BLOCKED and r.allowed_segments == []
    names = {c.name: c.status for c in r.checks}
    assert names["cash_eod"] == C.HealthStatus.BLOCKED
