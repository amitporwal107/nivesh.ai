"""Daily pipeline orchestrator.

Run path:
  1. Determine the universe for `scan_date`. If Chartink scans were
     uploaded for this date, the universe = union of those scans. Else,
     fall back to all symbols with fresh OHLCV.
  2. For each symbol: load ~260 bars, compute features, score, classify
     stage, generate trade plan.
  3. Persist features (stock_technical_features) and signals
     (positional_signals).

The orchestrator is best-effort per-symbol — one bad symbol must not
poison the batch.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Dict, List, Optional

from services import pg_client

from . import (
    ENGINE_VERSION,
    chartink_loader,
    equity_universe,
    feature_calculator as fc,
    ohlcv_store,
    scorer,
    sector_strength,
    trade_planner,
)

logger = logging.getLogger(__name__)

# Minimum bars required to score a symbol.
MIN_BARS = 60


# ── Universe selection ──────────────────────────────────────────────────
async def universe_for(scan_date: date) -> List[str]:
    """Symbols that hit any Chartink scan today; else all with fresh bars.

    In both branches we pass through the NSE equity allowlist so ETFs,
    bond funds, REITs and InvITs (all of which trade in the EQ/BE series
    and so leak into bhavcopy) are excluded — the engine is designed
    around equity price action, not ETF NAV mechanics.
    """
    scanned = await chartink_loader.list_universe_for(scan_date)
    if scanned:
        filtered = equity_universe.filter_equities(scanned)
        logger.info("positional: universe from chartink (%d → %d after equity filter)",
                    len(scanned), len(filtered))
        return filtered

    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT nse_symbol FROM stock_ohlcv WHERE bar_date = $1",
            scan_date,
        )
    syms = [r["nse_symbol"] for r in rows]
    filtered = equity_universe.filter_equities(syms)
    logger.info("positional: universe from ohlcv (%d → %d after equity filter)",
                len(syms), len(filtered))
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

    stage = s["stage"]
    if stage in ("WEAK", "EXTENDED"):
        return {
            "nse_symbol": symbol,
            "features": feats,
            "scores": s,
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
            "trade_plan": None,
            "actionable": False,
        }

    why = trade_planner.reasons(feats, s["sub_scores"], list(scan_hits or ()), stage)
    return {
        "nse_symbol": symbol,
        "features": feats,
        "scores": s,
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
    f = scored["features"]
    s = scored["scores"]
    sub = s["sub_scores"]
    components = {
        "weights": s["weights"],
        "scan_hits": s["scan_hits"],
        "raw": _to_jsonable(f),
    }
    async with pool.acquire() as conn:
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
    plan = scored["trade_plan"]
    s = scored["scores"]
    payload = {
        "nse_symbol": scored["nse_symbol"],
        "scan_hits": s["scan_hits"],
        "reasons": scored.get("reasons", []),
    }
    async with pool.acquire() as conn:
        await conn.execute(
            """
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
            """,
            scored["nse_symbol"], scan_date,
            s["final_score"], s["confidence"], s["stage"],
            plan["timeframe_days_min"], plan["timeframe_days_max"],
            plan["entry"], plan["stoploss"], plan["target"], plan["risk_reward"],
            payload["scan_hits"],
            json.dumps(payload["reasons"]),
            ENGINE_VERSION,
        )


# ── Main run ─────────────────────────────────────────────────────────────
async def run_for_date(scan_date: date) -> dict:
    """End-to-end run for a single scan_date. Returns a summary dict."""
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    universe = await universe_for(scan_date)
    if not universe:
        return {"ok": False, "error": "empty_universe", "scan_date": str(scan_date)}

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

    scored_count = 0
    actionable = 0
    errors = 0
    blocked = 0

    for symbol in universe:
        try:
            # PR-3 hard filter: sector blocked by macro regime
            sm = sector_modifier_by_symbol.get(symbol, 0.0)
            sector_key_for_symbol = await _sector_key_for(symbol)
            if sector_key_for_symbol and sector_key_for_symbol in blocked_sectors:
                blocked += 1
                continue

            bars = await ohlcv_store.load_bars(symbol, end_date=scan_date,
                                                lookback_bars=260)
            if len(bars) < MIN_BARS:
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
            await _persist_features(pool, scan_date, scored)
            scored_count += 1
            if scored["actionable"]:
                await _persist_signal(pool, scan_date, scored)
                actionable += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.warning("positional: failed for %s: %s", symbol, e)

    return {
        "ok": True,
        "scan_date": str(scan_date),
        "engine_version": ENGINE_VERSION,
        "universe": len(universe),
        "scored": scored_count,
        "actionable": actionable,
        "errors": errors,
        "blocked_by_macro": blocked,
        "macro_multiplier": macro_multiplier,
        "blocked_sectors": list(blocked_sectors),
        "bench_ret_20d": bench_ret,
    }


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
