"""Daily pipeline orchestrator.

Run path:
  1. Determine the universe for `scan_date`: every symbol with fresh
     OHLCV, plus the symbols that hit a Chartink scan uploaded for this
     date (the union; hits are added, never a replacement).
  2. For each symbol: load ~260 bars, compute features, score, classify
     stage, generate trade plan.
  3. Persist features (stock_technical_features) and signals
     (positional_signals).

A date the NSE calendar says is not a session is refused (session_calendar).
Bars are put on one price scale first (price_adjustment: warehouse split/bonus
factors, then a residual-break guard), so no feature straddles a split.
Scoring (`score_universe`) is separate from writing so the repair tool can
preview a rerun without writing anything.

The orchestrator is best-effort per-symbol — one bad symbol must not
poison the batch.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from services import pg_client

from . import (
    ENGINE_VERSION,
    accumulation_detector,
    chartink_loader,
    equity_universe,
    feature_calculator as fc,
    ohlcv_store,
    price_adjustment,
    scorer,
    session_calendar,
    sector_strength,
    trade_planner,
)

logger = logging.getLogger(__name__)

# Minimum bars required to score a symbol.
MIN_BARS = 60


# ── Universe selection ──────────────────────────────────────────────────
async def universe_for(scan_date: date) -> List[str]:
    """Every symbol with fresh bars on `scan_date`, plus any symbol that hit a Chartink scan that day: the UNION.

    Chartink hits are ADDED to the universe, never a replacement for it (owner decision 2026-10-27,
    docs/EARNINGS_SURPRISE_TRACKER.md §1): a scan that hits a handful of names must not shrink the day's scan to those
    names. With no hits the universe is the symbols with fresh bars, as before. Both sources pass through the NSE
    equity allowlist so ETFs, bond funds, REITs and InvITs (all of which trade in the EQ/BE series and so leak into
    bhavcopy) are excluded — the engine is designed around equity price action, not ETF NAV mechanics. Order: the
    bars' symbols as the database returns them, then the hits that have no bar that day.
    """
    scanned = await chartink_loader.list_universe_for(scan_date)

    syms: List[str] = []
    pool = await pg_client.get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT nse_symbol FROM stock_ohlcv WHERE bar_date = $1",
                scan_date,
            )
        syms = [r["nse_symbol"] for r in rows]

    seen = set(syms)
    extra = [s for s in dict.fromkeys(scanned) if s not in seen]
    filtered = equity_universe.filter_equities(syms + extra)
    logger.info("positional: universe = %d with bars + %d chartink-only hits (%d chartink hits in all) → %d after equity filter",
                len(syms), len(extra), len(scanned), len(filtered))
    return filtered


# ── Per-symbol scoring (testable without DB) ────────────────────────────
def score_symbol(symbol: str,
                 bars: List[dict],
                 *,
                 scan_hits: Optional[List[str]] = None,
                 bench_ret_20d: Optional[float] = None,
                 macro_multiplier: Optional[float] = None,
                 sector_modifier: Optional[float] = None,
                 macro_risk: Optional[str] = None,
                 ) -> Optional[dict]:
    """Pure-function path: bars → scored signal dict. Returns None if not
    enough data or no actionable trade plan.

    PR-2 macro inputs:
      • macro_multiplier — applied to the base score
      • sector_modifier  — added (after /100 normalisation) to the adjusted score
    Both default to None → behaviour identical to pre-macro.
    """
    if len(bars) < MIN_BARS:
        return None
    feats = fc.compute_features(bars)
    rs = sector_strength.compute_rs_pct(feats.get("return_20d_pct"), bench_ret_20d)
    s = scorer.score(
        feats, rs_vs_nifty_pct=rs, scan_hits=scan_hits or (),
        macro_multiplier=macro_multiplier, sector_modifier=sector_modifier,
    )

    # Pre-breakout accumulation layer — runs alongside the stage classifier
    # so a single symbol can be both "EARLY_OPPORTUNITY" (accumulation
    # score high but no trigger yet) and "ACCUMULATION" (engine stage).
    pre_breakout = accumulation_detector.detect_all(
        feats, bench_ret_20d=bench_ret_20d,
    )

    stage = s["stage"]
    if stage in ("WEAK", "EXTENDED"):
        return {
            "nse_symbol": symbol,
            "features": feats,
            "scores": s,
            "pre_breakout": pre_breakout,
            "trade_plan": None,
            "actionable": False,
        }

    plan = trade_planner.plan(
        stage, feats, macro_risk=macro_risk, sector_modifier=sector_modifier,
    )
    if not plan:
        return {
            "nse_symbol": symbol,
            "features": feats,
            "scores": s,
            "pre_breakout": pre_breakout,
            "trade_plan": None,
            "actionable": False,
        }

    why = trade_planner.reasons(feats, s["sub_scores"], list(scan_hits or ()), stage)
    # Append pre-breakout signals to the human-readable reason list when
    # they fired — gives the user the "why this is interesting NOW"
    # context even before the breakout confirms.
    if pre_breakout["signals"]:
        why.append(f"Pre-breakout: {', '.join(pre_breakout['signals'])}")
    return {
        "nse_symbol": symbol,
        "features": feats,
        "scores": s,
        "pre_breakout": pre_breakout,
        "trade_plan": plan,
        "reasons": why,
        "actionable": True,
    }


# ── Persistence ─────────────────────────────────────────────────────────
def _to_jsonable(o):
    """Coerce features/scores blob to JSON-safe values (Decimals from asyncpg)."""
    if o is None:
        return None
    if isinstance(o, dict):
        return {k: _to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_to_jsonable(v) for v in o]
    if isinstance(o, (int, float, str, bool)):
        return o
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


async def _persist_features(pool, scan_date: date, scored: dict) -> None:
    async with pool.acquire() as conn:
        await _write_features(conn, scan_date, scored)


async def _write_features(conn, scan_date: date, scored: dict) -> None:
    f = scored["features"]
    s = scored["scores"]
    sub = s["sub_scores"]
    components = {
        "weights": s["weights"],
        "scan_hits": s["scan_hits"],
        "raw": _to_jsonable(f),
        # Pre-breakout signals — persisted in the JSONB blob (not a column
        # of its own) so we don't need a migration. UI reads from here.
        "pre_breakout": _to_jsonable(scored.get("pre_breakout") or {}),
        # How the bars' prices were treated (price_adjustment.adjust_bars): warehouse-adjusted or raw, and where a
        # residual split/bonus break cut the window.
        "price_adjustment": _to_jsonable(scored.get("price_adjustment") or {}),
    }
    await conn.execute(
        """
        INSERT INTO stock_technical_features (
            nse_symbol, as_of_date,
            trend_score, momentum_score, structure_score, accumulation_score,
            sector_score, risk_score, final_score, confidence, stage,
            close_price, sma_50, sma_200, rsi_14, atr_14,
            return_5d_pct, return_20d_pct,
            breakout_level, support_level, resistance_level,
            components, engine_version
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
            $12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22::jsonb,$23
        )
        ON CONFLICT (nse_symbol, as_of_date) DO UPDATE SET
            trend_score = EXCLUDED.trend_score,
            momentum_score = EXCLUDED.momentum_score,
            structure_score = EXCLUDED.structure_score,
            accumulation_score = EXCLUDED.accumulation_score,
            sector_score = EXCLUDED.sector_score,
            risk_score = EXCLUDED.risk_score,
            final_score = EXCLUDED.final_score,
            confidence = EXCLUDED.confidence,
            stage = EXCLUDED.stage,
            close_price = EXCLUDED.close_price,
            sma_50 = EXCLUDED.sma_50,
            sma_200 = EXCLUDED.sma_200,
            rsi_14 = EXCLUDED.rsi_14,
            atr_14 = EXCLUDED.atr_14,
            return_5d_pct = EXCLUDED.return_5d_pct,
            return_20d_pct = EXCLUDED.return_20d_pct,
            breakout_level = EXCLUDED.breakout_level,
            support_level = EXCLUDED.support_level,
            resistance_level = EXCLUDED.resistance_level,
            components = EXCLUDED.components,
            engine_version = EXCLUDED.engine_version,
            computed_at = NOW()
        """,
        scored["nse_symbol"], scan_date,
        sub["trend"], sub["momentum"], sub["structure"], sub["accumulation"],
        sub["sector"], sub["risk"], s["final_score"], s["confidence"], s["stage"],
        f.get("close"), f.get("sma_50"), f.get("sma_200"),
        f.get("rsi_14"), f.get("atr_14"),
        f.get("return_5d_pct"), f.get("return_20d_pct"),
        f.get("high_20d"), f.get("swing_low_20"), f.get("swing_high_20"),
        json.dumps(components), ENGINE_VERSION,
    )


async def _persist_signal(pool, scan_date: date, scored: dict) -> None:
    async with pool.acquire() as conn:
        await _write_signal(conn, scan_date, scored)


async def _write_signal(conn, scan_date: date, scored: dict) -> None:
    plan = scored["trade_plan"]
    s = scored["scores"]
    payload = {
        "nse_symbol": scored["nse_symbol"],
        "scan_hits": s["scan_hits"],
        "reasons": scored.get("reasons", []),
    }
    args = (
        scored["nse_symbol"], scan_date,
        s["final_score"], s["confidence"], s["stage"],
        plan["timeframe_days_min"], plan["timeframe_days_max"],
        plan["entry"], plan["stoploss"], plan["target"], plan["risk_reward"],
        payload["scan_hits"],
        json.dumps(payload["reasons"]),
        ENGINE_VERSION,
    )
    if await signal_history_ready(conn):
        # N17: the row a re-run replaces is copied into positional_signals_history in the SAME statement, and the
        # live row's revision goes up; identical levels write no history. N13: the stop's method is stored as data.
        await conn.execute(VERSIONED_SIGNAL_SQL, *args, json.dumps(plan.get("stop_method")) if plan.get("stop_method") else None)
        return
    await conn.execute(LEGACY_SIGNAL_SQL, *args)


LEGACY_SIGNAL_SQL = """
        INSERT INTO positional_signals (
            nse_symbol, signal_date, final_score, confidence, stage,
            timeframe_days_min, timeframe_days_max,
            entry_price, stoploss, target_price, risk_reward,
            source_scans, reasons, engine_version
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14
        )
        ON CONFLICT (nse_symbol, signal_date) DO UPDATE SET
            final_score = EXCLUDED.final_score,
            confidence = EXCLUDED.confidence,
            stage = EXCLUDED.stage,
            timeframe_days_min = EXCLUDED.timeframe_days_min,
            timeframe_days_max = EXCLUDED.timeframe_days_max,
            entry_price = EXCLUDED.entry_price,
            stoploss = EXCLUDED.stoploss,
            target_price = EXCLUDED.target_price,
            risk_reward = EXCLUDED.risk_reward,
            source_scans = EXCLUDED.source_scans,
            reasons = EXCLUDED.reasons,
            engine_version = EXCLUDED.engine_version,
            computed_at = NOW()
        """

# The columns a superseded row keeps (positional_signals_history, migration 025), in this order.
_HISTORY_COLS = ("nse_symbol, signal_date, revision, final_score, confidence, stage, timeframe_days_min, "
                 "timeframe_days_max, entry_price, stoploss, target_price, risk_reward, source_scans, reasons, "
                 "engine_version, stop_method, computed_at, superseded_by")
_HISTORY_SELECT = ("nse_symbol, signal_date, COALESCE(revision, 1), final_score, confidence, stage, timeframe_days_min, "
                   "timeframe_days_max, entry_price, stoploss, target_price, risk_reward, source_scans, reasons, "
                   "engine_version, stop_method, computed_at")

VERSIONED_SIGNAL_SQL = f"""
        WITH prev AS (
            SELECT * FROM positional_signals WHERE nse_symbol = $1 AND signal_date = $2 FOR UPDATE
        ), hist AS (
            INSERT INTO positional_signals_history ({_HISTORY_COLS})
            SELECT {_HISTORY_SELECT}, 'rerun' FROM prev
             WHERE (prev.entry_price, prev.stoploss, prev.target_price, prev.risk_reward, prev.stage,
                    prev.final_score, prev.timeframe_days_min, prev.timeframe_days_max, prev.engine_version)
                   IS DISTINCT FROM ($8::numeric(14,4), $9::numeric(14,4), $10::numeric(14,4), $11::numeric(6,2),
                                     $5::text, $3::numeric(5,4), $6::integer, $7::integer, $14::text)
            ON CONFLICT DO NOTHING
            RETURNING 1
        )
        INSERT INTO positional_signals (
            nse_symbol, signal_date, final_score, confidence, stage,
            timeframe_days_min, timeframe_days_max,
            entry_price, stoploss, target_price, risk_reward,
            source_scans, reasons, engine_version, stop_method, revision
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14,$15::jsonb,
            1 + COALESCE((SELECT MAX(revision) FROM positional_signals_history
                          WHERE nse_symbol = $1 AND signal_date = $2), 0)
        )
        ON CONFLICT (nse_symbol, signal_date) DO UPDATE SET
            final_score = EXCLUDED.final_score,
            confidence = EXCLUDED.confidence,
            stage = EXCLUDED.stage,
            timeframe_days_min = EXCLUDED.timeframe_days_min,
            timeframe_days_max = EXCLUDED.timeframe_days_max,
            entry_price = EXCLUDED.entry_price,
            stoploss = EXCLUDED.stoploss,
            target_price = EXCLUDED.target_price,
            risk_reward = EXCLUDED.risk_reward,
            source_scans = EXCLUDED.source_scans,
            reasons = EXCLUDED.reasons,
            engine_version = EXCLUDED.engine_version,
            stop_method = EXCLUDED.stop_method,
            revision = COALESCE(positional_signals.revision, 1) + (SELECT COUNT(*)::int FROM hist),
            computed_at = NOW()
        """

_HISTORY_READY_TTL_S = 300.0
_history_ready: Dict[str, float] = {}          # "ok" | "missing" -> monotonic time it was last checked


async def signal_history_ready(conn) -> bool:
    """Whether migration 025 is applied (positional_signals.revision / stop_method and positional_signals_history).
    Without it the old upsert is kept, so a deploy that has not run the migration still scores, and an ERROR says
    that signal history is NOT being recorded. A positive answer is kept for the process; a negative one is
    re-checked after five minutes."""
    import time as _time

    now = _time.monotonic()
    if "ok" in _history_ready:
        return True
    if now - _history_ready.get("missing", -1e9) < _HISTORY_READY_TTL_S:
        return False
    row = await conn.fetchrow(
        "SELECT to_regclass('positional_signals_history') IS NOT NULL AS hist, "
        "       (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'positional_signals' "
        "          AND column_name IN ('revision', 'stop_method')) AS cols")
    ok = bool(row and row["hist"] and int(row["cols"] or 0) == 2)
    if ok:
        _history_ready["ok"] = now
        return True
    _history_ready["missing"] = now
    logger.error("positional: migration 025 (positional_signals_history) is not applied: a re-run OVERWRITES signal "
                 "levels without keeping the old ones (finding N17). Apply backend/migrations/025_positional_signals_history.sql.")
    return False


async def _copy_day_to_history(conn, scan_date: date) -> int:
    """Before a day is rewritten (write_scored with replace), keep every signal row it deletes."""
    if not await signal_history_ready(conn):
        return 0
    res = await conn.execute(
        f"INSERT INTO positional_signals_history ({_HISTORY_COLS}) "
        f"SELECT {_HISTORY_SELECT}, 'replace' FROM positional_signals WHERE signal_date = $1 "
        "ON CONFLICT DO NOTHING", scan_date)
    try:
        return int(str(res).split()[-1])
    except (ValueError, IndexError):
        return 0


# ── Main run ─────────────────────────────────────────────────────────────
BarLoader = Callable[[str, date, int], Awaitable[List[dict]]]


async def _load_bars(symbol: str, end_date: date, lookback_bars: int) -> List[dict]:
    return await ohlcv_store.load_bars(symbol, end_date=end_date, lookback_bars=lookback_bars)


async def session_refusal(scan_date: date) -> Optional[dict]:
    """None when `scan_date` is an NSE session; otherwise the refusal summary (a holiday, a weekend, or a calendar
    that cannot be read: a date is never scored on the assumption that a weekday trades)."""
    try:
        ok, why = await session_calendar.check_session(scan_date)
    except session_calendar.CalendarUnavailable as e:
        return {"ok": False, "error": "calendar_unavailable", "reason": str(e), "scan_date": str(scan_date)}
    if not ok:
        return {"ok": False, "error": "not_a_session", "reason": why, "scan_date": str(scan_date)}
    return None


async def score_universe(scan_date: date, *, load_bars: Optional[BarLoader] = None,
                         factors: Optional[Dict[str, Dict[date, float]]] = None,
                         adjust: bool = True) -> Tuple[dict, List[dict]]:
    """Score every symbol of the day's universe. Reads only; writes nothing. Returns (summary, scored rows).

    `load_bars` defaults to stock_ohlcv; the repair tool passes corrected bars to preview a rerun. `factors` defaults
    to the warehouse's split/bonus factors for the universe; a failed read refuses the run (fail closed).
    `adjust=False` scores the bars as stored, as engine v1.0 did: only the repair preview uses it, to check that an
    in-memory replay reproduces the stored rows.
    """
    universe = await universe_for(scan_date)
    if not universe:
        return {"ok": False, "error": "empty_universe", "scan_date": str(scan_date)}, []
    load = load_bars or _load_bars

    if not adjust:
        factors = {}
    elif factors is None:
        try:
            factors = await price_adjustment.load_factors(
                universe, scan_date - timedelta(days=price_adjustment.FACTOR_LOOKBACK_DAYS), scan_date)
        except price_adjustment.FactorsUnavailable as e:
            logger.error("positional %s: split/bonus factors unavailable, not scoring: %s", scan_date, e)
            return {"ok": False, "error": "adjustment_factors_unavailable", "reason": str(e),
                    "scan_date": str(scan_date)}, []

    bench_ret = await sector_strength.load_bench_return(end_date=scan_date,
                                                         lookback=20)

    # ── Macro overlay (PR-2 / PR-3) ──────────────────────────────────
    # Pull the day's macro state once and resolve every symbol's sector
    # tilt up front. Both lookups are best-effort — if macro data hasn't
    # ingested yet (first-deploy case), the engine falls back to its
    # PR-1 behaviour (multiplier 1.0, no sector tilt, no hard filters).
    macro_multiplier = 1.0
    macro_risk: Optional[str] = None
    sector_modifier_by_symbol: Dict[str, float] = {}
    blocked_sectors: set = set()
    try:
        from services import macro_engine
        from . import macro_overlay
        state = await macro_engine.latest_state()
        if state:
            macro_multiplier = float(state.get("multiplier") or 1.0)
            macro_risk = state.get("risk")
            blocked_sectors = await macro_overlay.blocked_sectors_today(state)
            sector_modifier_by_symbol = await macro_overlay.sector_modifiers_for_universe(
                universe, scan_date,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("macro overlay unavailable: %s", e)

    scored_rows: List[dict] = []
    errors = 0
    blocked = 0
    basis = {price_adjustment.BASIS_ADJUSTED: 0, price_adjustment.BASIS_RAW: 0, "unadjusted_replay": 0}
    # Every symbol whose prices were not a clean adjusted history, by name and reason (owner decision 2026-10-27:
    # exceptions are reported, never shown as adjusted).
    exceptions: Dict[str, List[dict]] = {"raw_prices": [], "truncated": [], "not_scored_after_truncation": []}

    for symbol in universe:
        try:
            # PR-3 hard filter: sector blocked by macro regime
            sm = sector_modifier_by_symbol.get(symbol, 0.0)
            sector_key_for_symbol = await _sector_key_for(symbol)
            if sector_key_for_symbol and sector_key_for_symbol in blocked_sectors:
                blocked += 1
                continue

            bars = await load(symbol, scan_date, 260)
            if len(bars) < MIN_BARS:
                continue
            if adjust:
                bars, adj = price_adjustment.adjust_bars(bars, factors.get(symbol))
            else:
                adj = {"price_basis": "unadjusted_replay", "factor_steps": 0, "break_truncated_at": None,
                       "bars_dropped": 0}
            if adj["break_truncated_at"]:
                exceptions["truncated"].append({"symbol": symbol, "break_date": adj["break_truncated_at"],
                                                "bars_dropped": adj["bars_dropped"], "bars_left": len(bars)})
            if len(bars) < MIN_BARS:
                exceptions["not_scored_after_truncation"].append({
                    "symbol": symbol, "break_date": adj["break_truncated_at"], "bars_left": len(bars),
                    "reason": f"a price break the warehouse factors do not explain on {adj['break_truncated_at']}; "
                              f"{len(bars)} bars after it, fewer than the {MIN_BARS} the scanner needs"})
                continue
            scan_hits = await chartink_loader.get_scans_for(scan_date, symbol)
            scored = score_symbol(symbol, bars,
                                   scan_hits=scan_hits,
                                   bench_ret_20d=bench_ret,
                                   macro_multiplier=macro_multiplier,
                                   sector_modifier=sm,
                                   macro_risk=macro_risk)
            if not scored:
                continue
            scored["price_adjustment"] = adj
            basis[adj["price_basis"]] += 1
            if adj["price_basis"] == price_adjustment.BASIS_RAW:
                exceptions["raw_prices"].append({
                    "symbol": symbol, "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) "
                                                "for this symbol: scored on raw NSE prices"})
            scored_rows.append(scored)
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.warning("positional: failed for %s: %s", symbol, e)

    summary = {
        "ok": True,
        "scan_date": str(scan_date),
        "engine_version": ENGINE_VERSION,
        "universe": len(universe),
        "scored": len(scored_rows),
        "actionable": sum(1 for r in scored_rows if r["actionable"]),
        "errors": errors,
        "blocked_by_macro": blocked,
        "macro_multiplier": macro_multiplier,
        "blocked_sectors": list(blocked_sectors),
        "bench_ret_20d": bench_ret,
        "price_basis": basis,
        "break_truncated": len(exceptions["truncated"]),
        "skipped_short_after_break": len(exceptions["not_scored_after_truncation"]),
        "exceptions": exceptions,
    }
    return summary, scored_rows


async def write_scored(conn, scan_date: date, scored_rows: List[dict], *, replace: bool = False) -> None:
    """Write a day's scored rows on one connection (the caller owns the transaction). With `replace`, the day's
    existing features and signals are deleted first, so a symbol no longer scored or no longer actionable does not
    keep a stale row."""
    if replace:
        await _copy_day_to_history(conn, scan_date)          # N17: a rewritten day keeps its old signals
        await conn.execute("DELETE FROM positional_signals WHERE signal_date = $1", scan_date)
        await conn.execute("DELETE FROM stock_technical_features WHERE as_of_date = $1", scan_date)
    for scored in scored_rows:
        await _write_features(conn, scan_date, scored)
        if scored["actionable"]:
            await _write_signal(conn, scan_date, scored)


async def run_for_date(scan_date: date) -> dict:
    """End-to-end run for a single scan_date. Returns a summary dict."""
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    refusal = await session_refusal(scan_date)
    if refusal:
        logger.warning("positional %s refused: %s (%s)", scan_date, refusal["error"], refusal["reason"])
        return refusal

    summary, scored_rows = await score_universe(scan_date)
    if not summary.get("ok"):
        return summary

    scored_count = 0
    actionable = 0
    errors = summary["errors"]
    for scored in scored_rows:
        try:
            await _persist_features(pool, scan_date, scored)
            scored_count += 1
            if scored["actionable"]:
                await _persist_signal(pool, scan_date, scored)
                actionable += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.warning("positional: failed for %s: %s", scored.get("nse_symbol"), e)

    return {**summary, "scored": scored_count, "actionable": actionable, "errors": errors}


async def _sector_key_for(symbol: str) -> Optional[str]:
    """Resolve a stock symbol → its mapped macro_sector key (cached)."""
    cache = _sector_key_for._cache  # type: ignore[attr-defined]
    if symbol in cache:
        return cache[symbol]
    raw = await _stock_sector(symbol)
    from services import macro_sector as _ms
    key = _ms._resolve_sector(raw) if raw else None
    cache[symbol] = key
    return key
_sector_key_for._cache = {}  # type: ignore[attr-defined]


async def _stock_sector(symbol: str) -> Optional[str]:
    """Look up `sector` from stock_master for one symbol."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT sector FROM stock_master WHERE nse_symbol = $1", symbol,
        )
    return row["sector"] if row else None
