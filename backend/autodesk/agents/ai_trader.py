"""AI Trader — Opportunity Scanner (PRD §6.1). Deterministic in Phase 1 (rule ait-rules-v1).

Scans the universe on the PREVIOUS session's end-of-day data (the only data visible before the open) and publishes
signals. Universe "FNO" = the underlyings with futures that session (point-in-time, no survivorship bias); an explicit
symbol list may narrow it.

Categories (one signal per instrument and category):
  stocks   BREAKOUT / BREAKDOWN        close beyond the prior 20-session high / low on ≥ 1.5× average volume
           TREND_CONTINUATION          close > SMA20 > SMA50 with SMA50 rising (or the mirror), RSI not stretched
           LONG_BUILDUP / SHORT_BUILDUP / SHORT_COVERING / LONG_UNWINDING   the session's futures build-up label
  indices  TREND_CONTINUATION (BULLISH / BEARISH) or RANGE_BOUND (NEUTRAL)

Score 0–100 = the sum of eight weighted dimensions (WEIGHTS). A dimension whose input is missing is `available=False`,
earns 0 and is listed in `missing_inputs`: a missing input is never evidence. The score is not a probability;
`calibrated_probability` stays empty until outcomes exist to calibrate it (Phase 2+).

Levels: invalidation 1.5 × ATR14 beyond the close; levels 3 × and 4.5 × ATR14 the other way (2 : 1 and 3 : 1 before
costs). The Trading Assistant and the risk engine work from these.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Optional

from ..contracts import (AgentDescriptor, AgentKey, AgentResult, Direction, ScanReport, ScoreComponent, Segment,
                         Signal, SignalCategory, TaskSpec, TaskType, Timeframe)
from ..market import indicators as ind
from ..market.pit import INDEX_FUTURES
from ..market.view import IST, Bar, BuildupRow, DataUnavailable, published_at
from ..scoring import registry as scoring
from ..scoring import v2_positional as v2
from .base import Agent, AgentContext

VERSION = "autodesk-ait-v1"
RULE_VERSION = "ait-rules-v1"
MODEL_VERSION = f"{VERSION}/{RULE_VERSION}"
WEIGHTS = {"trend": Decimal("15"), "momentum": Decimal("15"), "volume_delivery": Decimal("15"),
           "relative_strength": Decimal("10"), "structure": Decimal("15"), "derivatives": Decimal("15"),
           "regime": Decimal("5"), "liquidity": Decimal("10")}
BARS = 60
CONCURRENCY = 8
BENCHMARK = "Nifty 50"
BUILDUP = {"long_buildup": (SignalCategory.LONG_BUILDUP, Direction.BULLISH),
           "short_buildup": (SignalCategory.SHORT_BUILDUP, Direction.BEARISH),
           "short_covering": (SignalCategory.SHORT_COVERING, Direction.BULLISH),
           "long_unwinding": (SignalCategory.LONG_UNWINDING, Direction.BEARISH)}
DESCRIPTOR = AgentDescriptor(
    agent_key=AgentKey.AI_TRADER, version=VERSION, kind="DETERMINISTIC", task_types=[TaskType.SCAN_MARKET],
    tools=["market.daily_bars", "market.index_bars", "market.fno_universe", "market.fno_buildup", "market.vix",
           "market.sector", "market.sessions_between"],
    prohibited=["size positions", "approve", "execute"])

ZERO = Decimal("0")


def _c(dim: str, points, detail: str, available: bool = True) -> ScoreComponent:
    w = WEIGHTS[dim]
    p = max(ZERO, min(Decimal(points), w)) if available else ZERO
    return ScoreComponent(dimension=dim, weight=w, points=p, available=available, detail=detail)


class _Market:
    """What every symbol is scored against, read once per scan."""
    def __init__(self):
        self.bench: list[Bar] = []
        self.vix: Optional[Decimal] = None
        self.buildup: dict[str, BuildupRow] = {}
        self.fno_day: Optional[date] = None
        self.cash_day: Optional[date] = None
        self.missing: list[str] = []
        # shadow scoring (scoring/registry.py): never used for selection
        self.shadow_on: bool = False
        self.bench_long: list[Bar] = []
        self.shadow: dict[str, Any] = {}
        self.shadow_errors: dict[str, str] = {}
        self.sector_bars: dict[str, Any] = {}

    def regime(self) -> dict[str, Any]:
        cl = ind.closes(self.bench)
        s50 = ind.sma(cl, 50)
        return {"benchmark": BENCHMARK, "close": str(cl[-1]) if cl else None, "sma50": str(s50) if s50 else None,
                "trend": None if not cl or s50 is None else ("up" if cl[-1] > s50 else "down"),
                "vix": str(self.vix) if self.vix is not None else None}


def _trend_points(cl: list[Decimal], direction: Direction) -> tuple[Optional[Decimal], str]:
    s20, s50 = ind.sma(cl, 20), ind.sma(cl, 50)
    s50_prev = ind.sma(cl[:-10], 50) if len(cl) >= 60 else None
    if s20 is None or s50 is None or s50_prev is None:
        return None, "needs 60 sessions"
    sign = 1 if direction == Direction.BULLISH else -1
    p = (5 if sign * (cl[-1] - s20) > 0 else 0) + (5 if sign * (s20 - s50) > 0 else 0) + \
        (5 if sign * (s50 - s50_prev) > 0 else 0)
    return Decimal(p), f"close {cl[-1]:.2f}, SMA20 {s20:.2f}, SMA50 {s50:.2f} (10 sessions ago {s50_prev:.2f})"


def _momentum_points(cl: list[Decimal], direction: Direction) -> tuple[Optional[Decimal], str]:
    r = ind.rsi(cl, 14)
    if r is None:
        return None, "needs 15 sessions"
    x = r if direction == Direction.BULLISH else Decimal("100") - r
    p = 15 if 55 <= x <= 70 else 8 if (50 <= x < 55 or 70 < x <= 78) else 0
    return Decimal(p), f"RSI14 {r:.1f}"


def _volume_points(bars: list[Bar], direction: Direction) -> tuple[Optional[Decimal], str, list[str]]:
    vr = ind.volume_ratio(bars, 20)
    if vr is None:
        return None, "needs 21 sessions", []
    p = 10 if vr >= 2 else 7 if vr >= Decimal("1.5") else 4 if vr >= Decimal("1.2") else 0
    detail = f"volume {vr:.2f}× the 20-session average"
    missing = []
    dp = bars[-1].deliv_pct
    up = bars[-1].close >= bars[-2].close
    if dp is None:
        missing.append("delivery_pct")
    elif dp >= 50 and (up == (direction == Direction.BULLISH)):
        p += 5
        detail += f"; delivery {dp:.1f}%"
    else:
        detail += f"; delivery {dp:.1f}%"
    return Decimal(p), detail, missing


def _rs_points(cl: list[Decimal], bench: list[Bar], direction: Direction) -> tuple[Optional[Decimal], str]:
    r, b = ind.pct_return(cl, 20), ind.pct_return(ind.closes(bench), 20)
    if r is None or b is None:
        return None, f"needs 21 sessions of the symbol and of {BENCHMARK}"
    diff = (r - b) if direction == Direction.BULLISH else (b - r)
    p = 10 if diff >= 5 else 6 if diff >= 2 else 3 if diff > 0 else 0
    return Decimal(p), f"20-session return {r:.2f}% vs {BENCHMARK} {b:.2f}%"


def _liquidity_points(bars: list[Bar]) -> tuple[Optional[Decimal], str]:
    adv = ind.avg_traded_value(bars, 20)
    if adv is None:
        return None, "needs 20 sessions"
    cr = adv / Decimal("10000000")
    p = 10 if cr >= 50 else 6 if cr >= 10 else 3 if cr >= 1 else 0
    return Decimal(p), f"20-session average traded value ₹{cr:.1f} cr"


def _regime_points(mk: _Market, direction: Direction) -> tuple[Optional[Decimal], str]:
    cl = ind.closes(mk.bench)
    s50 = ind.sma(cl, 50)
    if s50 is None:
        return None, f"needs 50 sessions of {BENCHMARK}"
    sign = 1 if direction == Direction.BULLISH else -1
    p = 3 if sign * (cl[-1] - s50) > 0 else 0
    detail = f"{BENCHMARK} {'above' if cl[-1] > s50 else 'below'} its SMA50"
    if mk.vix is not None:
        if mk.vix < 18:
            p += 2
        detail += f"; India VIX {mk.vix:.2f}"
    return Decimal(p), detail


def _derivatives_points(row: Optional[BuildupRow], direction: Direction) -> tuple[Optional[Decimal], str]:
    if row is None:
        return None, "no futures build-up row for the session"
    good = {Direction.BULLISH: {"long_buildup": 15, "short_covering": 10},
            Direction.BEARISH: {"short_buildup": 15, "long_unwinding": 10}}[direction]
    return Decimal(good.get(row.label, 0)), (f"futures {row.label.replace('_', ' ')}: price {row.price_change_pct}% "
                                             f"OI {row.oi_change_pct}%")


class AITrader(Agent):
    descriptor = DESCRIPTOR

    # ── universe and shared inputs ────────────────────────────────────────────────────────────────────────────────

    async def _market(self, m) -> _Market:
        mk = _Market()
        mk.cash_day = m.latest_session("cash")
        mk.shadow_on = v2.VERSION in scoring.shadow_versions()
        try:
            if mk.shadow_on:
                # one read serves both: v1 gets exactly the last BARS sessions it always had
                mk.bench_long = await m.index_bars(BENCHMARK, sessions=max(BARS, scoring.v2_bars()))
                mk.bench = mk.bench_long[-BARS:]
            else:
                mk.bench = await m.index_bars(BENCHMARK, sessions=BARS)
        except DataUnavailable:
            mk.missing.append(f"{BENCHMARK} bars")
        if len(mk.bench) < 21:
            mk.missing.append(f"{BENCHMARK} history")
        try:
            mk.vix = await m.vix()
        except DataUnavailable:
            mk.vix = None
        if mk.vix is None:
            mk.missing.append("india_vix")
        try:
            mk.fno_day = m.latest_session("fno")
            mk.buildup = {r.underlying: r for r in await m.fno_buildup(mk.fno_day)}
        except DataUnavailable:
            mk.missing.append("fno_buildup")
        return mk

    async def _universe(self, m, mk: _Market, ctx: AgentContext) -> list[str]:
        symbols = ctx.inputs.get("symbols")
        if mk.buildup:
            uni = sorted(mk.buildup)
        else:
            try:
                uni = await m.fno_universe(mk.fno_day) if mk.fno_day else []
            except DataUnavailable:
                uni = []
        if symbols:
            wanted = {s.upper() for s in symbols}
            uni = sorted(wanted & set(uni)) + sorted(wanted - set(uni))   # listed non-F&O symbols scan as cash
        return uni

    # ── scoring ───────────────────────────────────────────────────────────────────────────────────────────────────

    def _score(self, dims: list[tuple[str, Optional[Decimal], str]]) -> tuple[list[ScoreComponent], list[str], Decimal]:
        comps, missing = [], []
        for name, pts, detail in dims:
            if pts is None:
                comps.append(_c(name, 0, detail, available=False))
                missing.append(name)
            else:
                comps.append(_c(name, pts, detail))
        return comps, missing, sum((c.points for c in comps), ZERO)

    def _levels(self, close: Decimal, atr: Decimal, direction: Direction) -> tuple[dict, Optional[Decimal], list]:
        q = Decimal("0.05")
        r = lambda x: (x / q).quantize(Decimal("1")) * q        # noqa: E731
        zone = {"low": r(close - atr / 4), "high": r(close + atr / 4)}
        if direction == Direction.NEUTRAL:
            return zone, None, []
        s = 1 if direction == Direction.BULLISH else -1
        return zone, r(close - s * Decimal("1.5") * atr), [r(close + s * 3 * atr), r(close + s * Decimal("4.5") * atr)]

    def _signal(self, ctx: AgentContext, *, sym: str, segment: Segment, direction: Direction,
                category: SignalCategory, comps, missing, score, bars: list[Bar], atr: Decimal, evidence: list[str],
                data_as_of: datetime, sector: Optional[str], fno: bool) -> Signal:
        sd = date.fromisoformat(ctx.inputs["session_date"])
        zone, inv, levels = self._levels(bars[-1].close, atr, direction)
        return Signal(tenant_id=ctx.tenant_id, account_id=ctx.account.get("account_id"),
                      simulation_id=ctx.simulation_id, instrument=sym, segment=segment, direction=direction,
                      timeframe=Timeframe.POSITIONAL, category=category, signal_score=score,
                      calibrated_probability=None, score_breakdown=comps, entry_zone=zone, invalidation_price=inv,
                      targets=levels, evidence=evidence, missing_inputs=missing, reference_price=bars[-1].close,
                      fno_eligible=fno, sector=sector, data_as_of=data_as_of, session_date=sd,
                      model_version=MODEL_VERSION, rule_version=RULE_VERSION,
                      expires_at=datetime.combine(sd, time(15, 30), tzinfo=IST).astimezone(timezone.utc))

    async def _stock(self, m, ctx, mk: _Market, sym: str) -> tuple[list[Signal], list[dict]]:
        out, skipped = [], []
        bars_long: list[Bar] = []
        try:
            if mk.shadow_on:
                bars_long = await m.daily_bars(sym, sessions=max(BARS, scoring.v2_bars()))
                bars = bars_long[-BARS:]                         # v1's input is unchanged
            else:
                bars = await m.daily_bars(sym, sessions=BARS)
        except DataUnavailable as e:
            return [], [{"instrument": sym, "reason": f"bars unavailable: {e}"}]
        if len(bars) < 30 or bars[-1].day != mk.cash_day:
            return [], [{"instrument": sym, "reason": f"{len(bars)} bars, last {bars[-1].day if bars else None}"}]
        cl = ind.closes(bars)
        atr = ind.atr(bars, 14)
        if not atr:
            return [], [{"instrument": sym, "reason": "no ATR"}]
        row = mk.buildup.get(sym)
        fno = row is not None
        sector = await m.sector(sym)
        hi, lo, vr = ind.prior_high(bars, 20), ind.prior_low(bars, 20), ind.volume_ratio(bars, 20)
        s20, s50 = ind.sma(cl, 20), ind.sma(cl, 50)
        rsi = ind.rsi(cl, 14)
        cands: list[tuple[SignalCategory, Direction, Segment, str, datetime]] = []
        cash_asof = published_at(mk.cash_day, "cash")
        if hi is not None and vr is not None and cl[-1] > hi and vr >= Decimal("1.5"):
            cands.append((SignalCategory.BREAKOUT, Direction.BULLISH, Segment.CASH,
                          f"close {cl[-1]} above the prior 20-session high {hi} on {vr:.2f}× volume", cash_asof))
        if lo is not None and vr is not None and cl[-1] < lo and vr >= Decimal("1.5"):
            cands.append((SignalCategory.BREAKDOWN, Direction.BEARISH, Segment.FUTURES if fno else Segment.CASH,
                          f"close {cl[-1]} below the prior 20-session low {lo} on {vr:.2f}× volume", cash_asof))
        if s20 and s50 and rsi is not None:
            if cl[-1] > s20 > s50 and rsi <= 70:
                cands.append((SignalCategory.TREND_CONTINUATION, Direction.BULLISH, Segment.CASH,
                              f"close above SMA20 above SMA50; RSI14 {rsi:.1f}", cash_asof))
            elif cl[-1] < s20 < s50 and rsi >= 30 and fno:
                cands.append((SignalCategory.TREND_CONTINUATION, Direction.BEARISH, Segment.FUTURES,
                              f"close below SMA20 below SMA50; RSI14 {rsi:.1f}", cash_asof))
        if row is not None and row.label in BUILDUP and mk.fno_day:
            cat, d = BUILDUP[row.label]
            cands.append((cat, d, Segment.FUTURES, f"futures {row.label.replace('_', ' ')} on {mk.fno_day}",
                          published_at(mk.fno_day, "fno")))
        for cat, d, seg, why, asof in cands:
            if d == Direction.BEARISH and not fno:
                continue                     # no bearish structure without F&O (no short shares positionally)
            t, td = _trend_points(cl, d)
            mo, md_ = _momentum_points(cl, d)
            vo, vd, vmiss = _volume_points(bars, d)
            rs, rd = _rs_points(cl, mk.bench, d)
            st_pts = Decimal(15) if cat in (SignalCategory.BREAKOUT, SignalCategory.BREAKDOWN) else (
                Decimal(8) if (hi and d == Direction.BULLISH and cl[-1] >= hi * Decimal("0.98")) or
                (lo and d == Direction.BEARISH and cl[-1] <= lo * Decimal("1.02")) else Decimal(0))
            de, dd = _derivatives_points(row, d) if fno else (None, "not an F&O underlying")
            rg, rgd = _regime_points(mk, d)
            li, lid = _liquidity_points(bars)
            comps, missing, score = self._score([
                ("trend", t, td), ("momentum", mo, md_), ("volume_delivery", vo, vd), ("relative_strength", rs, rd),
                ("structure", st_pts, f"20-session range {lo}–{hi}"), ("derivatives", de, dd), ("regime", rg, rgd),
                ("liquidity", li, lid)])
            missing += vmiss + [x for x in mk.missing if x == "india_vix"]
            out.append(self._signal(ctx, sym=sym, segment=seg, direction=d, category=cat, comps=comps,
                                    missing=missing, score=score, bars=bars, atr=atr, evidence=[why],
                                    data_as_of=asof, sector=sector, fno=fno))
        if mk.shadow_on:
            sh = await self._shadow(m, mk, sym, bars_long, sector)
            if sh is not None:
                for s in out:
                    s.shadow_scores = [sh]
        return out, skipped

    async def _shadow(self, m, mk: _Market, sym: str, bars_long: list[Bar], sector: Optional[str]):
        """v2-positional shadow score for one stock. Any failure is recorded in the scan report and never touches v1."""
        try:
            name = v2.SECTOR_INDEX.get(sector or "")
            sec = None
            if name:
                if name not in mk.sector_bars:
                    try:
                        mk.sector_bars[name] = await m.index_bars(name, sessions=max(BARS, scoring.v2_bars()))
                    except DataUnavailable:
                        mk.sector_bars[name] = None
                sec = mk.sector_bars[name]
            sh = await asyncio.to_thread(v2.score_last, bars_long, mk.bench_long, sec, name)
            mk.shadow[sym] = sh
            return sh
        except Exception as e:  # noqa: BLE001 — recorded (ScanReport.shadow.errors); shadow scoring must not stop the scan
            mk.shadow_errors[sym] = f"{type(e).__name__}: {str(e)[:120]}"
            return None

    async def _index(self, m, ctx, mk: _Market, sym: str) -> tuple[list[Signal], list[dict]]:
        name = INDEX_FUTURES.get(sym)
        try:
            bars = await m.index_bars(name, sessions=BARS) if name else []
        except DataUnavailable as e:
            return [], [{"instrument": sym, "reason": f"index bars unavailable: {e}"}]
        if len(bars) < 60 or bars[-1].day != mk.cash_day:
            return [], [{"instrument": sym, "reason": f"{len(bars)} index bars"}]
        cl = ind.closes(bars)
        atr = ind.atr(bars, 14)
        s20, s50, rsi = ind.sma(cl, 20), ind.sma(cl, 50), ind.rsi(cl, 14)
        s20_prev = ind.sma(cl[:-10], 20)
        row = mk.buildup.get(sym)
        asof = published_at(mk.fno_day, "fno") if mk.fno_day and row else published_at(mk.cash_day, "cash")
        flat = s20_prev and abs(s20 - s20_prev) / s20_prev < Decimal("0.01")
        if flat and abs(cl[-1] - s20) <= atr and rsi is not None and 40 <= rsi <= 60:
            d, cat = Direction.NEUTRAL, SignalCategory.RANGE_BOUND
            hi20, lo20 = max(b.high for b in bars[-20:]), min(b.low for b in bars[-20:])
            mid = (cl[-1] - lo20) / (hi20 - lo20) if hi20 > lo20 else Decimal("0.5")
            comps, missing, score = self._score([
                ("trend", Decimal(15), f"SMA20 moved {abs(s20 - s20_prev) / s20_prev * 100:.2f}% in 10 sessions"),
                ("momentum", Decimal(15) if 45 <= rsi <= 55 else Decimal(8), f"RSI14 {rsi:.1f}"),
                ("volume_delivery", None, "not applicable to an index"),
                ("relative_strength", None, "not applicable to the benchmark"),
                ("structure", Decimal(15) if Decimal("0.25") <= mid <= Decimal("0.75") else Decimal(5),
                 f"close at {mid * 100:.0f}% of the 20-session range"),
                ("derivatives", (Decimal(10) if row.label not in BUILDUP else Decimal(5)) if row else None,
                 f"futures {row.label}" if row else "no futures build-up row"),
                ("regime", (Decimal(5) if Decimal(11) <= mk.vix <= Decimal(20) else Decimal(0))
                 if mk.vix is not None else None, f"India VIX {mk.vix}"),
                ("liquidity", Decimal(10), "index derivatives")])
            why = "index in a flat 20-session range"
        elif s20 and s50 and ((cl[-1] > s20 > s50) or (cl[-1] < s20 < s50)):
            d = Direction.BULLISH if cl[-1] > s20 else Direction.BEARISH
            cat = SignalCategory.TREND_CONTINUATION
            t, td = _trend_points(cl, d)
            mo, md_ = _momentum_points(cl, d)
            de, dd = _derivatives_points(row, d)
            rg, rgd = _regime_points(mk, d)
            comps, missing, score = self._score([
                ("trend", t, td), ("momentum", mo, md_), ("volume_delivery", None, "not applicable to an index"),
                ("relative_strength", None, "not applicable to the benchmark"),
                ("structure", Decimal(8), "close on the trend side of SMA20 and SMA50"), ("derivatives", de, dd),
                ("regime", rg, rgd), ("liquidity", Decimal(10), "index derivatives")])
            why = f"index {'up' if d == Direction.BULLISH else 'down'}-trend"
        else:
            return [], []
        sig = self._signal(ctx, sym=sym, segment=Segment.INDEX, direction=d, category=cat, comps=comps,
                           missing=missing, score=score, bars=bars, atr=atr, evidence=[why], data_as_of=asof,
                           sector=None, fno=True)
        return [sig], []

    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        m = ctx.market
        sd = date.fromisoformat(ctx.inputs["session_date"])
        floor = Decimal(str(ctx.inputs.get("min_score") or "50"))
        mk = await self._market(m)
        uni = await self._universe(m, mk, ctx)
        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(sym):
            async with gate:
                return await (self._index(m, ctx, mk, sym) if sym in INDEX_FUTURES else self._stock(m, ctx, mk, sym))

        results = await asyncio.gather(*(one(s) for s in uni))
        signals, suppressed = [], []
        for sigs, skipped in results:
            suppressed += [{**x, "category": None} for x in skipped]
            for s in sigs:
                if s.signal_score < floor:
                    suppressed.append({"instrument": s.instrument, "category": s.category.value,
                                       "reason": f"score {s.signal_score} below {floor}"})
                else:
                    signals.append(s)
        signals.sort(key=lambda s: (-s.signal_score, s.instrument, s.category.value))
        data_as_of = max([s.data_as_of for s in signals], default=published_at(mk.cash_day, "cash"))
        rep = ScanReport(session_date=sd, universe=str(ctx.inputs.get("universe") or "FNO"), universe_size=len(uni),
                         scanned=len(uni) - len([x for x in suppressed if x["category"] is None]), signals=signals,
                         suppressed=suppressed, regime={**mk.regime(), "missing": mk.missing}, data_as_of=data_as_of,
                         rule_version=RULE_VERSION, shadow=_shadow_summary(mk) if mk.shadow_on else None)
        return AgentResult(output_schema="scan-report-v1", output=rep.model_dump(mode="json"),
                           summary=f"{len(signals)} signals from {len(uni)} instruments "
                                   f"({len(suppressed)} suppressed or skipped)")


def _shadow_summary(mk: _Market, top: int = 50) -> dict[str, Any]:
    """v2 candidates for the scan report — recorded for comparison, never published as signals. Ties: relative-strength
    points, then trend points (never the name)."""
    def pts(sh, dim):
        return next((float(c.points) for c in sh.components if c.dimension == dim), 0.0)
    scored = {s: sh for s, sh in mk.shadow.items() if sh.score is not None}
    cands = sorted(((s, sh) for s, sh in scored.items() if sh.signals),
                   key=lambda x: (-float(x[1].score), -pts(x[1], "relative_strength"), -pts(x[1], "trend_confirmation"), x[0]))
    not_scored: dict[str, int] = {}
    for sh in mk.shadow.values():
        if sh.score is None:
            for r in sh.reasons or ["not scored"]:
                not_scored[r] = not_scored.get(r, 0) + 1
    return {"version": v2.VERSION, "rules": v2.RULES, "horizon": "POSITIONAL", "active_version": scoring.active_version(),
            "scored": len(scored), "with_entry_signal": len(cands), "not_scored": not_scored,
            "errors": dict(list(mk.shadow_errors.items())[:20]), "error_count": len(mk.shadow_errors),
            "bands": {b: sum(1 for _, sh in cands if sh.band == b) for b in ("Exceptional", "Strong", "Developing", "Weak", "Avoid")},
            "candidates": [{"instrument": s, "score": str(sh.score), "band": sh.band, "tier": sh.tier,
                            "primary_signal": sh.primary_signal, "signals": sh.signals, "context_signals": sh.context_signals,
                            "warnings": sh.warnings} for s, sh in cands[:top]]}

