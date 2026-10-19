"""Read-only chart API over the committed snapshot (research/charting/export.py WRITES it,
services/research_chart.py READS + validates it).

    GET /api/research/chart/run                                manifest, minus per-file integrity hashes
    GET /api/research/chart/symbols                             manifest.symbols
    GET /api/research/chart/{symbol}/ohlcv?timeframe=1D|1W|1M    bars, statuses, findings, provenance
    GET /api/research/chart/{symbol}/indicators?timeframe=&ids=  one or more indicator series
    GET /api/research/chart/{symbol}/patterns                   detected patterns (v1: always [], daily only)

  LIVE analysis, any NSE symbol (Smart trading desk, matrix B11 — see "Live analysis" below):
    GET /api/research/chart/live/{symbol}/indicators            indicator values, lookbacks, overlay series
    GET /api/research/chart/live/{symbol}/patterns              research.charting detect_as_of, PRD §7.5 states

The snapshot routes compute nothing at request time -- no DB, no network, no other file (the Sim Lab rule,
backend/routes/sim_lab.py). The `/live/*` routes are the one, separate exception: they read
nidp.prices_eod_adjusted through the DaaS (the chart-live source) and compute at request time, so they
answer with pit_status PIT_UNVERIFIED and never borrow the snapshot's guarantees.
Kite-derived prices (NI-1): gated behind require_feature("charting"),
admins included, same posture as sim_lab. Symbol path params are validated
`^[A-Z0-9&\\-]{1,32}$` before any file is touched. A malformed or missing snapshot is 503
snapshot_unavailable, never a partial response; a symbol the manifest never listed is 404
unknown_symbol.

`timeframe` (§38.7, §38.11): one of `1D` (default -- existing callers that never pass this
param are unaffected), `1W`, `1M`. Weekly/monthly bars are resampled and hashed into the
snapshot at export time (research/charting/resample.py); this route never resamples. An unknown
timeframe is 400 `unknown_timeframe: <value>` (§27, same reason-code style as `unknown_indicator`).
Patterns stay daily-only (§38.7) -- /patterns has no `timeframe` param.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam

from feature_gate import require_feature
from services.research_chart import (
    TIMEFRAMES, catalogue_view, indicators_view, load_manifest, load_symbol, manifest_view, ohlcv_view,
    patterns_view,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research/chart", tags=["research_chart"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
SymbolPath = PathParam(..., pattern=SYMBOL_PATTERN)


def _timeframe(timeframe: str) -> str:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"unknown_timeframe: {timeframe}")
    return timeframe


def _manifest() -> dict:
    manifest = load_manifest()
    if manifest is None:
        raise HTTPException(status_code=503, detail="snapshot_unavailable")
    return manifest


def _manifest_and_symbol(symbol: str) -> dict:
    manifest = _manifest()
    for e in manifest["symbols"]:
        if e["symbol"] == symbol:
            return manifest
    raise HTTPException(status_code=404, detail="unknown_symbol")


def _payload(symbol: str) -> dict:
    """The symbol's own file must load and validate cleanly too -- a symbol the manifest DOES
    list but whose file is missing/corrupt/hash-mismatched is a snapshot-integrity problem, so
    it's 503 (never a partial response), not a 404 (that's reserved for a symbol the manifest
    never listed at all)."""
    payload = load_symbol(symbol)
    if payload is None:
        raise HTTPException(status_code=503, detail="snapshot_unavailable")
    return payload


@router.get("/run")
async def run(user: dict = Depends(require_feature(FLAG))):
    return manifest_view(_manifest())


@router.get("/catalogue")
async def catalogue(user: dict = Depends(require_feature(FLAG))):
    """The controlled indicator preset catalogue (§38.5, D-3) that this snapshot's series were built
    from. Read straight off the manifest -- nothing is computed here, same as every other route."""
    view = catalogue_view(_manifest())
    if view is None:
        raise HTTPException(status_code=503, detail="catalogue_unavailable")
    return view


@router.get("/symbols")
async def symbols(user: dict = Depends(require_feature(FLAG))):
    return {"symbols": _manifest()["symbols"]}


@router.get("/{symbol}/ohlcv")
async def ohlcv(symbol: str = SymbolPath, timeframe: str = Query("1D"),
                user: dict = Depends(require_feature(FLAG))):
    tf = _timeframe(timeframe)
    manifest = _manifest_and_symbol(symbol)
    return ohlcv_view(manifest, _payload(symbol), tf)


@router.get("/{symbol}/indicators")
async def indicators(symbol: str = SymbolPath, timeframe: str = Query("1D"), ids: Optional[str] = Query(None),
                     user: dict = Depends(require_feature(FLAG))):
    tf = _timeframe(timeframe)
    _manifest_and_symbol(symbol)
    payload = _payload(symbol)
    available = indicators_view(payload, None, tf)["indicators"]
    wanted = [i.strip() for i in ids.split(",") if i.strip()] if ids else None
    if wanted:
        unknown = [i for i in wanted if i not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown_indicator: {', '.join(unknown)}")
    return indicators_view(payload, wanted, tf)


@router.get("/{symbol}/patterns")
async def patterns(symbol: str = SymbolPath, user: dict = Depends(require_feature(FLAG))):
    _manifest_and_symbol(symbol)
    return patterns_view(_payload(symbol))


# ── Live analysis for any symbol (Smart trading desk; matrix B11, PRD §7.3–§7.5) ───────────────────
#
# Bars: nidp.prices_eod_adjusted via the DaaS, exactly as GET /api/research/chart-live/{symbol}/ohlcv reads them
# (same proxy, same bar filter), the latest LIVE_BARS sessions. End of day, split and bonus adjusted.
#
# Indicators: the functions of nidp/services/technical_indicator_engine/calculator.py — the engine that fills
# stock_features_daily — so the desk, the feature store and the strategy backtest share one convention. The few the
# calculator does not have (relative volume, 20-day VWAP of daily prices, relative strength) are defined below and in
# INDICATOR_DEFINITIONS, which the response carries so every lookback is stated on screen.
#
# Patterns: research.charting.patterns.detect_as_of (the P0 families the registry enables) on the same bars, at the
# last bar. Its lifecycle statuses map onto the PRD's five states in _prd_state, and every pattern is judged on the
# PRD §7.5 criteria in _criteria: the engine's own components where it has them, three desk rules (trend, relative
# strength, liquidity) stated in CRITERIA_RULES, and "na" with the reason where nothing judges it (market regime,
# events). The research package sits at the repository root; a container that mounts backend/ alone cannot import it,
# and the route then answers 503 pattern_engine_unavailable rather than guessing.

import asyncio  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import quote  # noqa: E402

import numpy as np  # noqa: E402

from nidp.services.technical_indicator_engine import calculator as _calc  # noqa: E402

LIVE_BARS = 750            # ~3 years: EMA 200 seeded at the window's first close keeps < 0.1% of that seed
SERIES_SESSIONS = 126      # overlay series returned: the desk chart's longest range (6 months)
BENCHMARK = "Nifty 50"     # nidp.index_eod index_name
RS_SESSIONS = 63           # relative strength look-back (about 3 months)
MAX_PATTERNS = 12

INDICATOR_DEFINITIONS = [
    {"key": "ema20", "label": "EMA 20", "lookback": "20 sessions",
     "formula": "Exponential moving average of the close, k = 2 ÷ (20 + 1), seeded with the first close of the "
                "window (calculator.py _ema_series); none until 20 sessions exist."},
    {"key": "ema50", "label": "EMA 50", "lookback": "50 sessions",
     "formula": "As EMA 20 with k = 2 ÷ (50 + 1), seeded with the first close of the window."},
    {"key": "ema200", "label": "EMA 200", "lookback": "200 sessions",
     "formula": "As EMA 20 with k = 2 ÷ (200 + 1), seeded with the first close of the window (up to 750 sessions)."},
    {"key": "rsi14", "label": "RSI 14", "lookback": "14 sessions",
     "formula": "Wilder's RSI: the first average gain and loss are the means of the first 14 daily changes, then "
                "(previous × 13 + today) ÷ 14; RSI = 100 − 100 ÷ (1 + gain ÷ loss)."},
    {"key": "atr14", "label": "ATR 14", "lookback": "14 sessions",
     "formula": "Wilder's average true range: TR = max(H − L, |H − previous C|, |L − previous C|); the first ATR is "
                "the mean of 14 TRs, then (previous × 13 + TR) ÷ 14. In rupees."},
    {"key": "atr_pct", "label": "ATR %", "lookback": "14 sessions", "formula": "ATR 14 ÷ the last close × 100."},
    {"key": "macd", "label": "MACD 12 / 26 / 9", "lookback": "35 sessions",
     "formula": "EMA 12 − EMA 26 of the close; signal = EMA 9 of the MACD line from the 26th session on; "
                "histogram = MACD − signal."},
    {"key": "roc20", "label": "Rate of change 20", "lookback": "20 sessions",
     "formula": "(Close ÷ the close 20 sessions earlier − 1) × 100 (stock_features_daily return_20d_pct)."},
    {"key": "avg_volume20", "label": "Volume MA 20", "lookback": "20 sessions",
     "formula": "Mean volume of the 20 sessions before the last one; the last session is not in its own baseline."},
    {"key": "rvol20", "label": "Relative volume", "lookback": "20 sessions",
     "formula": "The last session's volume ÷ volume MA 20."},
    {"key": "vwap20", "label": "VWAP 20D", "lookback": "20 sessions",
     "formula": "Σ(typical price × volume) ÷ Σ volume over the last 20 sessions, typical = (H + L + C) ÷ 3. A 20-day "
                "volume-weighted average of daily prices, not the intraday VWAP."},
    {"key": "rs63", "label": "Relative strength vs Nifty 50", "lookback": f"{RS_SESSIONS} sessions",
     "formula": f"The stock's {RS_SESSIONS}-session return minus Nifty 50's over the same two dates "
                "(nidp.index_eod close), in percentage points."},
    {"key": "resistance20", "label": "Resistance · 20-session high", "lookback": "20 sessions",
     "formula": "Highest high of the last 20 sessions (calculator.py swing_high_low)."},
    {"key": "support20", "label": "Support · 20-session low", "lookback": "20 sessions",
     "formula": "Lowest low of the last 20 sessions (calculator.py swing_high_low)."},
    {"key": "avg_traded_value_cr20", "label": "Traded value · 20 sessions", "lookback": "20 sessions",
     "formula": "Mean of close × volume over the last 20 sessions, ₹ crore a day."},
]

STATE_RULE = {
    "candidate": "CANDIDATE, FORMING or GEOMETRY_VALID: a shape, with no breakout yet. A shape alone is never confirmed.",
    "awaiting_confirmation": ("BREAKOUT_ATTEMPT (through the level intraday, no close beyond it), or a close beyond "
                              "the level whose follow-through volume has not passed."),
    "confirmed": ("PRICE_CONFIRMED or later, with the engine's volume component PASS: a close beyond the level by "
                  "the breakout buffer, on follow-through volume in the band."),
    "invalidated": "FAILED or INVALIDATED: price came back through the level, or the pattern's invalidation rule fired.",
    "expired": "EXPIRED: the pattern ran past its confirmation window.",
}


def _liquidity_min_cr() -> float:
    """The desk's liquidity gate, from the scanner's one config (services/positional_engine/setup_rules.py)."""
    from services.positional_engine import setup_rules
    return float(setup_rules.LIQUIDITY["min_traded_value_cr"])


def _criteria_rules() -> dict:
    return {
        "price_structure": "The engine's geometry and price components (research.charting): PASS only when both pass.",
        "volume": "The engine's volume component: follow-through volume inside the family's band (pattern_registry).",
        "trend": "Desk rule: bullish when close > EMA 50 > EMA 200, bearish when close < EMA 50 < EMA 200, judged "
                 "against the pattern's direction.",
        "relative_strength": f"Desk rule: the stock's {RS_SESSIONS}-session return beats Nifty 50's (bullish) or "
                             "trails it (bearish).",
        "volatility": "The engine's volatility component (ATR expansion on the breakout).",
        "liquidity": f"Desk rule: mean traded value over 20 sessions of at least ₹{_liquidity_min_cr():g} Cr a day.",
        "regime": "Not judged: the pattern engine has no market context yet (CONTEXT_VALIDATED is never set).",
        "events": "Not judged: the live engine does not join corporate events; the stock's filings are listed apart.",
    }


def _flt(v) -> Optional[float]:
    """A finite float, or None (never NaN or infinity in a response)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


async def _live_bars(symbol: str) -> list:
    """[date, o, h, l, c, v] oldest first, from the chart-live source. 404 when there are none."""
    from routes.move_odds import _proxy
    from routes.research_chart_live import _bar
    payload = await _proxy(f"/prices/adjusted/{symbol}", {"limit": LIVE_BARS})
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="upstream_shape")
    bars = [b for b in (_bar(r) for r in reversed(rows)) if b is not None]
    if not bars:
        raise HTTPException(status_code=404, detail="no_bars_for_symbol")
    return bars


async def _benchmark_closes() -> dict:
    """Nifty 50 closes by date (nidp.index_eod), the last ~150 sessions."""
    from routes.move_odds import _proxy
    payload = await _proxy(f"/indices/{quote(BENCHMARK)}/eod", {"limit": 150})
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="upstream_shape")
    out = {}
    for r in rows:
        d, c = str(r.get("as_of_date") or "")[:10], _flt(r.get("close_price"))
        if d and c and c > 0:
            out[d] = c
    return out


async def _reference_row(symbol: str) -> Optional[dict]:
    """The latest nidp.security_reference_daily row for the symbol (EQ series first): price band, F&O, ETF."""
    from nidp.shared.storage.pg import get_pool as _nidp_pool
    pool = await _nidp_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT as_of_date, series, price_band_pct, band_raw, fno_eligible, is_etf "
            "FROM nidp.security_reference_daily WHERE symbol = $1 "
            "ORDER BY as_of_date DESC, (series = 'EQ') DESC LIMIT 1",
            symbol,
        )
    return dict(r) if r else None


def _close_on_or_before(closes: dict, day: str) -> Optional[float]:
    keys = sorted(k for k in closes if k <= day)
    return closes[keys[-1]] if keys else None


def _vwap_series(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, n: int = 20) -> list:
    out: list = [None] * len(c)
    typ = (h + l + c) / 3.0
    for i in range(n - 1, len(c)):
        vol = float(v[i - n + 1:i + 1].sum())
        out[i] = float((typ[i - n + 1:i + 1] * v[i - n + 1:i + 1]).sum() / vol) if vol > 0 else None
    return out


def _ema_masked(c: np.ndarray, n: int) -> list:
    if len(c) == 0:
        return []
    full = _calc._ema_series(c, n)
    return [float(x) if i >= n - 1 else None for i, x in enumerate(full)]


BREAK_MOVE = 0.4           # a one-session close move this large is not a market move (NSE circuits stop at 20%)


def _adjustment_break(bars: list) -> Optional[dict]:
    """The latest session whose close is >= 40% away from the one before it, or None.

    Such a jump in bars labelled "adjusted" is a split or bonus the warehouse never applied (e.g. KOTAKBANK's
    5:1 split of 2026-01-14 has no row in nidp.corporate_actions). Bars from before it are on another price scale.
    """
    for i in range(len(bars) - 1, 0, -1):
        prev, cur = bars[i - 1][4], bars[i][4]
        if prev > 0 and abs(cur / prev - 1) >= BREAK_MOVE:
            return {"date": bars[i][0], "prev_close": prev, "close": cur, "ratio": cur / prev}
    return None


def _indicator_values(bars: list, bench: Optional[dict]) -> tuple:
    """(values, series) for the bars, oldest first. A figure without enough history is None, never 0.

    With an adjustment break the caller passes only the bars from the break on.
    """
    days = [b[0] for b in bars]
    o, h, l, c, v = (np.array([b[i] for b in bars], dtype=float) for i in range(1, 6))
    n = len(c)
    atr = _flt(_calc.atr(h, l, c, 14))
    m, s, hist = _calc.macd(c)
    avg20, _z = _calc.volume_stats(v, 20)
    hi20, lo20 = _calc.swing_high_low(h, l, 20)
    vwap = _vwap_series(h, l, c, v, 20)
    rs = None
    if bench and n > RS_SESSIONS:
        b_end, b_start = _close_on_or_before(bench, days[-1]), _close_on_or_before(bench, days[-1 - RS_SESSIONS])
        if b_end and b_start and c[-1 - RS_SESSIONS] > 0:
            stock_ret = (c[-1] / c[-1 - RS_SESSIONS] - 1) * 100
            bench_ret = (b_end / b_start - 1) * 100
            rs = {"stock_return_pct": float(stock_ret), "benchmark_return_pct": float(bench_ret),
                  "excess_pct": float(stock_ret - bench_ret), "from": days[-1 - RS_SESSIONS], "to": days[-1]}
    values = {
        "close": float(c[-1]),
        "ema20": _flt(_calc.ema(c, 20)), "ema50": _flt(_calc.ema(c, 50)), "ema200": _flt(_calc.ema(c, 200)),
        "rsi14": _flt(_calc.rsi(c, 14)),
        "atr14": atr, "atr_pct": (atr / c[-1] * 100) if atr is not None and c[-1] > 0 else None,
        "macd": _flt(m), "macd_signal": _flt(s), "macd_hist": _flt(hist),
        "roc20": _flt(_calc.pct_return(c, 20)),
        "avg_volume20": _flt(avg20),
        "rvol20": (float(v[-1]) / avg20) if avg20 else None,
        "vwap20": vwap[-1] if vwap else None,
        "resistance20": _flt(hi20), "support20": _flt(lo20),
        "avg_traded_value_cr20": float((c[-20:] * v[-20:]).mean() / 1e7) if n >= 20 else None,
        "rs63": rs,
    }
    k = min(SERIES_SESSIONS, n)
    series = {
        "days": days[-k:],
        "ema20": _ema_masked(c, 20)[-k:], "ema50": _ema_masked(c, 50)[-k:], "ema200": _ema_masked(c, 200)[-k:],
        "vwap20": vwap[-k:],
    }
    return values, series


def _series_notes(n: int, brk: Optional[dict]) -> dict:
    """Why a line is absent: fewer sessions than its lookback, and the unadjusted split that cut the history."""
    notes = {}
    for key, need in (("ema20", 20), ("ema50", 50), ("ema200", 200)):
        if n < need:
            cut = (f", because the bars before the {brk['date']} price break (close {brk['prev_close']:g} to "
                   f"{brk['close']:g}, a split or bonus the warehouse has not adjusted) are on another price scale and are left out"
                   if brk else "")
            notes[key] = f"EMA {need} needs {need} sessions; only {n} are usable{cut}."
    return notes


async def _analysis_inputs(symbol: str) -> tuple:
    """Bars (required), the benchmark and the reference row (each optional, with the reason when missing)."""
    bars_t = asyncio.ensure_future(_live_bars(symbol))
    bench_t = asyncio.ensure_future(_benchmark_closes())
    ref_t = asyncio.ensure_future(_reference_row(symbol))
    try:
        bars = await bars_t
    except BaseException:
        bench_t.cancel(); ref_t.cancel()
        raise
    bench, bench_reason = None, None
    try:
        bench = await bench_t
        if not bench:
            bench_reason = f"No {BENCHMARK} closes on record (nidp.index_eod)."
    except Exception as e:  # noqa: BLE001
        bench_reason = f"{BENCHMARK} closes did not load ({getattr(e, 'detail', None) or type(e).__name__})."
    ref, ref_reason = None, None
    try:
        ref = await ref_t
        if not ref:
            ref_reason = f"No row for {symbol} in nidp.security_reference_daily."
    except Exception as e:  # noqa: BLE001
        logger.warning("security_reference_daily read for %s failed: %s", symbol, e)
        ref_reason = "The exchange reference data (nidp.security_reference_daily) could not be read."
    return bars, bench, bench_reason, ref, ref_reason


def _provenance(bars: list) -> dict:
    return {"as_of": bars[-1][0], "sessions": len(bars), "source": "nidp.prices_eod_adjusted", "mode": "eod",
            "adjustment_status": "SPLIT_BONUS_ADJUSTED", "pit_status": "PIT_UNVERIFIED"}


@router.get("/live/{symbol}/indicators")
async def live_indicators(symbol: str = SymbolPath, user: dict = Depends(require_feature(FLAG))):
    bars, bench, bench_reason, ref, ref_reason = await _analysis_inputs(symbol)
    brk = _adjustment_break(bars)
    used = [b for b in bars if brk is None or b[0] >= brk["date"]]
    values, series = _indicator_values(used, bench)
    if bench and values["rs63"] is None and not bench_reason:
        bench_reason = f"Needs {RS_SESSIONS + 1} sessions of the stock and {BENCHMARK} closes on both dates."
    tradability = None
    if ref:
        d = ref.get("as_of_date")
        tradability = {
            "as_of_date": d.isoformat() if hasattr(d, "isoformat") else (str(d)[:10] if d else None),
            "price_band_pct": _flt(ref.get("price_band_pct")),
            "band_raw": ref.get("band_raw"),
            "fno_eligible": ref.get("fno_eligible"),
            "is_etf": ref.get("is_etf"),
            "series": ref.get("series"),
            "source": "nidp.security_reference_daily",
        }
    return {
        "symbol": symbol,
        **{**_provenance(bars), "sessions": len(used),
           **({"adjustment_status": "UNADJUSTED_BREAK_IN_HISTORY"} if brk else {})},
        "adjustment_break": brk,
        "method": ("backend/nidp/services/technical_indicator_engine/calculator.py (the engine behind "
                   "stock_features_daily), run on the adjusted daily bars above"),
        "values": values,
        "series": series,
        "series_notes": _series_notes(len(used), brk),
        "definitions": INDICATOR_DEFINITIONS,
        "benchmark": {"name": BENCHMARK, "source": "nidp.index_eod",
                      "as_of": max(bench) if bench else None, "reason": bench_reason},
        "tradability": tradability,
        "tradability_reason": ref_reason,
        "liquidity_rule": {"min_traded_value_cr": _liquidity_min_cr(),
                           "source": "services/positional_engine/setup_rules.py LIQUIDITY"},
    }


def _pattern_engine():
    """research.charting's P0 detector, its config and its registry, imported lazily.

    The research package lives at the repository root beside backend/. It is appended to sys.path (never inserted
    ahead of backend modules) only when it is actually there; otherwise the import fails and the caller says so.
    """
    root = Path(__file__).resolve().parents[2]
    if (root / "research" / "charting" / "patterns.py").is_file() and str(root) not in sys.path:
        sys.path.append(str(root))
    from research.charting import config as rc_config  # noqa: WPS433
    from research.charting import pattern_registry
    from research.charting.patterns import detect_as_of
    return detect_as_of, rc_config, pattern_registry


def _prd_state(status: str, components: dict) -> tuple:
    """A lifecycle status → (PRD §7.5 state, why). None when the status maps to none of the five."""
    vol = (components or {}).get("volume")
    if status in ("CANDIDATE", "FORMING"):
        return "candidate", "The shape is still forming; it is not a valid pattern yet."
    if status == "GEOMETRY_VALID":
        return "candidate", "A valid shape with no breakout yet. A shape alone is not a confirmed signal."
    if status == "BREAKOUT_ATTEMPT":
        return "awaiting_confirmation", "Price went through the level during a session but did not close beyond it."
    if status in ("PRICE_CONFIRMED", "VOLUME_CONFIRMED", "CONTEXT_VALIDATED", "RESEARCH_ELIGIBLE"):
        if vol == "PASS":
            return "confirmed", "Closed beyond the level by the breakout buffer, on follow-through volume in the band."
        if vol == "FAIL":
            return "awaiting_confirmation", "Closed beyond the level, but the follow-through volume did not confirm."
        return "awaiting_confirmation", "Closed beyond the level; the follow-through volume has not confirmed yet."
    if status == "FAILED":
        return "invalidated", "The breakout failed: price came back through the level."
    if status == "INVALIDATED":
        return "invalidated", "The pattern's invalidation rule fired."
    if status == "EXPIRED":
        return "expired", "The pattern ran past its confirmation window without confirming."
    return None, f"The engine reports {status or 'no status'}, which maps to none of the five states."


_COMPONENT = {"PASS": "pass", "FAIL": "fail", "PENDING": "pending"}


def _criteria(p: dict, values: dict, liquid_min: float) -> list:
    comp = p.get("components") or {}
    direction = p.get("direction")
    bull, bear = direction == "BULLISH", direction == "BEARISH"
    out = []

    g, pr = comp.get("geometry"), comp.get("price")
    if g == "FAIL" or pr == "FAIL":
        st = "fail"
    elif g == "PASS" and pr == "PASS":
        st = "pass"
    elif g in ("PASS", "PENDING") and pr in ("PASS", "PENDING"):
        st = "pending"
    else:
        st = "na"
    out.append({"key": "price_structure", "label": "Price structure", "status": st, "judged_by": "engine",
                "observed": f"geometry {g or '—'} · price {pr or '—'}",
                "reason": None if st != "na" else "The engine sent no geometry or price status."})

    for key, label, comp_key in (("volume", "Volume", "volume"),):
        cv = comp.get(comp_key)
        st = _COMPONENT.get(cv, "na")
        out.append({"key": key, "label": label, "status": st, "judged_by": "engine", "observed": cv,
                    "reason": None if st != "na" else "The engine sent no volume status."})

    close, e50, e200 = values.get("close"), values.get("ema50"), values.get("ema200")
    if not (bull or bear):
        st, why, obs = "na", "The pattern has no direction, so trend alignment is not judged.", None
    elif close is None or e50 is None or e200 is None:
        st, why, obs = "na", "Needs EMA 50 and EMA 200 (at least 200 sessions of bars).", None
    else:
        up, down = close > e50 > e200, close < e50 < e200
        st = "pass" if (up if bull else down) else "fail"
        why, obs = None, f"close {close:.2f} · EMA 50 {e50:.2f} · EMA 200 {e200:.2f}"
    out.append({"key": "trend", "label": "Trend", "status": st, "judged_by": "desk rule", "observed": obs, "reason": why})

    rs = values.get("rs63")
    if not (bull or bear):
        st, why, obs = "na", "The pattern has no direction, so relative strength is not judged.", None
    elif rs is None:
        st, why, obs = "na", f"Needs {RS_SESSIONS + 1} sessions of the stock and {BENCHMARK} closes.", None
    else:
        st = "pass" if ((rs["excess_pct"] > 0) if bull else (rs["excess_pct"] < 0)) else "fail"
        why, obs = None, f"{rs['excess_pct']:+.1f} points vs {BENCHMARK} over {RS_SESSIONS} sessions"
    out.append({"key": "relative_strength", "label": "Relative strength", "status": st, "judged_by": "desk rule",
                "observed": obs, "reason": why})

    cv = comp.get("volatility")
    st = _COMPONENT.get(cv, "na")
    out.append({"key": "volatility", "label": "Volatility", "status": st, "judged_by": "engine", "observed": cv,
                "reason": None if st != "na" else "The engine sent no volatility status."})

    atv = values.get("avg_traded_value_cr20")
    if atv is None:
        st, why, obs = "na", "Needs 20 sessions of close and volume.", None
    else:
        st, why, obs = ("pass" if atv >= liquid_min else "fail"), None, f"₹{atv:,.1f} Cr a day"
    out.append({"key": "liquidity", "label": "Liquidity", "status": st, "judged_by": "desk rule", "observed": obs,
                "threshold": liquid_min, "reason": why})

    out.append({"key": "regime", "label": "Market regime", "status": "na", "judged_by": None,
                "observed": comp.get("market"),
                "reason": "The pattern engine has no market context yet (it never sets CONTEXT_VALIDATED)."})
    out.append({"key": "events", "label": "Events", "status": "na", "judged_by": None, "observed": None,
                "reason": "The live engine does not join corporate events; the stock's filings are listed separately."})
    return out


def _detect(detect_as_of, bars: list, symbol: str) -> list:
    import pandas as pd
    df = pd.DataFrame({
        "date": pd.to_datetime([b[0] for b in bars]),
        "open": [b[1] for b in bars], "high": [b[2] for b in bars], "low": [b[3] for b in bars],
        "close": [b[4] for b in bars], "volume": [b[5] for b in bars],
    })
    return [s.to_dict() for s in detect_as_of(df, len(df) - 1, symbol=symbol)]


_STATE_ORDER = {"confirmed": 0, "awaiting_confirmation": 1, "candidate": 2, "invalidated": 3, "expired": 4, None: 5}


@router.get("/live/{symbol}/patterns")
async def live_patterns(symbol: str = SymbolPath, user: dict = Depends(require_feature(FLAG))):
    try:
        detect_as_of, rc_config, registry = _pattern_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning("live patterns: research.charting is not importable here: %s", e)
        raise HTTPException(status_code=503, detail="pattern_engine_unavailable")
    bars, bench, _bench_reason, _ref, _ref_reason = await _analysis_inputs(symbol)
    values, _series = _indicator_values(bars, bench)
    liquid_min = _liquidity_min_cr()
    raw = await asyncio.to_thread(_detect, detect_as_of, bars, symbol)

    patterns = []
    for p in raw:
        status = p.get("status")
        state, why = _prd_state(status, p.get("components") or {})
        try:
            label = registry.get(p.get("pattern_type")).label
        except Exception:  # noqa: BLE001
            label = str(p.get("pattern_type") or "").replace("_", " ").title()
        events = p.get("events") or []
        patterns.append({
            "pattern_id": p.get("pattern_id"),
            "pattern_type": p.get("pattern_type"),
            "label": label,
            "direction": p.get("direction"),
            "lifecycle_status": status,
            "state": state,
            "state_reason": why,
            "detected_on": (events[0].get("date") if events else None) or p.get("formation_end"),
            "formation_start": p.get("formation_start"),
            "formation_end": p.get("formation_end"),
            "levels": p.get("levels") or {},
            "events": events,
            "rules": p.get("rules") or [],
            "components": p.get("components") or {},
            "criteria": _criteria(p, values, liquid_min),
        })
    # Most recent first, then by state (a stable sort keeps the dates in order within a state).
    patterns.sort(key=lambda x: x["detected_on"] or "", reverse=True)
    patterns.sort(key=lambda x: _STATE_ORDER.get(x["state"], 5))
    return {
        "symbol": symbol,
        **_provenance(bars),
        "engine": {
            "name": "research.charting.patterns.detect_as_of (the P0 families the registry enables)",
            "engine_version": rc_config.ENGINE_VERSION,
            "profile": rc_config.PROFILE_NAME,
            "config_hash": rc_config.config_hash(),
            "registry_version": registry.REGISTRY_VERSION,
        },
        "state_rule": STATE_RULE,
        "criteria_rule": _criteria_rules(),
        "patterns": patterns[:MAX_PATTERNS],
        "total": len(patterns),
        "families": [
            {"pattern_type": f.pattern_type, "label": f.label, "enabled": f.enabled,
             "disabled_reason": f.disabled_reason, "spec": f.spec}
            for f in registry.FAMILIES
        ],
    }
