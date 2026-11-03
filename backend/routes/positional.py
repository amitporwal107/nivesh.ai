"""Positional Trading Engine API.

Public (auth-required):
  GET  /api/positional/picks?date=&min_score=&stage=&limit=
  GET  /api/positional/watchlist?limit=
       Rows of both carry spark_closes (last 24 daily closes up to the signal / features date, oldest first, from
       stock_ohlcv), spark_end (date of the last one) and avg_traded_value_cr_20d (mean close × volume over the last
       20 sessions, ₹ crore; null with fewer than 20 sessions or a missing volume). Watchlist rows also carry
       resistance_level and support_level from stock_technical_features. Both apply the results signal at read time
       (docs/EARNINGS_SURPRISE_TRACKER.md §4d, services/results_week/signal.py): each row carries `results_signal`
       (null or {strength, points, basis, reasons, filed_at, sessions_since}) and `base_final_score` (the engine's
       stored score); `final_score` = clamp(base + points / 100, 0, 1), applied before the sort, min_score and limit.
       Stage is unchanged; the stored scores are never written.
  GET  /api/positional/picks/{symbol}?date=
  GET  /api/positional/signals/{symbol}/record?date=YYYY-MM-DD
       One scanner signal's record: the live revision (levels, stop_method, setup, computed_at) and every earlier
       revision kept in positional_signals_history (migration 025), each with the fields that changed in the
       revision that replaced it; plus the evaluated outcomes (positional_outcomes) as its state. Read only; nothing
       is inferred: a revision is shown only if a row stores it. date defaults to the symbol's latest signal date.
       404 when neither table has the signal; 503 when migration 025 is not applied (pipeline.signal_history_ready)
       or the database is unavailable.
  GET  /api/positional/picks/mine          — portfolio-aware filtered picks
  GET  /api/positional/scenario?entry=&stop=&target=&capital=&risk_pct=… — trade scenario calculator (PRD §8.5/§8.6);
       pure, read-only, nothing is sent to a broker
  GET  /api/positional/backtest/calibration?metric=&horizon_days=&symbol= — the accumulation detector's historical
       record with outcome definitions, Wilson intervals and the labelled period (PRD §7.6)
  GET  /api/positional/scan-universe?setups=&symbols=
       The opportunity scanner's universe categories (momentum, unusual volume, results-day momentum, F&O
       candidates), the eligible universe with every exclusion counted, and the move-odds model's rank percentile
       within that universe. Rules and thresholds: services/positional_engine/setup_rules.py (versioned, sent back
       as `rules`). Watchlist and picks also send the rules / engine versions behind their rows.

  GET  /api/positional/reversal-candidates?near_pct=&view=&limit=
       Stocks near their 52-week low that show stabilization evidence (never the proximity alone), each with a
       rule-based 0-100 score whose unknown components are left out, hard-gate exclusions with reasons, sector
       rotation context, fundamentals, catalyst evidence and hypothetical entry / invalidation / target levels.
       Rules: services/positional_engine/reversal_rules.py (versioned, sent back as `rules`). Research only.

Admin:
  POST /api/positional/run?date=YYYY-MM-DD
  POST /api/positional/scans/upload        — upload a Chartink CSV
  POST /api/positional/ohlcv/bhavcopy?date=YYYY-MM-DD
"""
from __future__ import annotations

import json
import logging
import asyncio
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from deps import db, get_current_user, require_admin
from feature_gate import require_feature
from services import pg_client
from services.copilot_tools import daas_client
from services.results_week import signal as results_signal
from services.positional_engine import (
    backtest,
    bhavcopy_ingester,
    chartink_api,
    chartink_loader,
    conviction,
    pipeline,
    portfolio_filter,
    reversal_rules,
    reversal_service,
    scan_config,
    scan_meta,
    setup_rules,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/positional", tags=["positional"])


# ── Helpers ──────────────────────────────────────────────────────────────
def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {s}, expected YYYY-MM-DD")


SPARK_SESSIONS = 24        # daily closes in a row's sparkline
ATV_SESSIONS = 20          # sessions in the average traded value
_CRORE = 1e7

# The last SPARK_SESSIONS bars per symbol up to a date, for every symbol of a request in one query.
_SPARK_SQL = """
    SELECT nse_symbol, bar_date, close_price, volume
      FROM (SELECT nse_symbol, bar_date, close_price, volume,
                   row_number() OVER (PARTITION BY nse_symbol ORDER BY bar_date DESC) AS rn
              FROM stock_ohlcv
             WHERE nse_symbol = ANY($1::text[])
               AND bar_date <= $2
               AND bar_date > $2 - INTERVAL '90 days') t
     WHERE rn <= $3
     ORDER BY nse_symbol, bar_date
"""


def _bar_fields(bars: Optional[list]) -> dict:
    """spark_closes / spark_end / avg_traded_value_cr_20d from (bar_date, close, volume) bars, oldest first.
    bars None (the read failed) → every field null; no bars → an empty spark and nulls."""
    if bars is None:
        return {"spark_closes": None, "spark_end": None, "avg_traded_value_cr_20d": None}
    spark = [(d, float(c)) for d, c, _ in bars if c is not None][-SPARK_SESSIONS:]
    tail = bars[-ATV_SESSIONS:]
    atv = None
    if len(tail) == ATV_SESSIONS and all(c is not None and v is not None for _, c, v in tail):
        atv = round(sum(float(c) * int(v) for _, c, v in tail) / ATV_SESSIONS / _CRORE, 2)
    return {"spark_closes": [round(c, 2) for _, c in spark],
            "spark_end": str(spark[-1][0]) if spark else None,
            "avg_traded_value_cr_20d": atv}


async def _spark_bars(symbols: List[str], through: date) -> Optional[dict]:
    """symbol → [(bar_date, close, volume)] oldest first, up to `through`; None when the read failed."""
    if not symbols:
        return {}
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SPARK_SQL, symbols, through, SPARK_SESSIONS)
    except Exception as e:  # noqa: BLE001 — the picks still answer, with the bar fields null
        logger.warning("positional: spark bars read failed (%s)", e)
        return None
    out: dict = {s: [] for s in symbols}
    for r in rows:
        out.setdefault(r["nse_symbol"], []).append((r["bar_date"], r["close_price"], r["volume"]))
    return out


async def _latest_signal_date() -> Optional[date]:
    """Return MAX(signal_date) or None. Treats 'table missing' as None so the
    UI degrades to an empty state on first launch (before migration 015 has
    been applied) instead of returning a 500."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT MAX(signal_date) AS d FROM positional_signals")
    except Exception as e:  # noqa: BLE001 — undefined table, conn drop, etc.
        logger.warning("positional: latest_signal_date failed (%s); treating as empty", e)
        return None
    return row["d"] if row else None


async def _fetch_picks(signal_date: date,
                        min_score: float,
                        stage: Optional[str],
                        limit: int,
                        symbols: Optional[List[str]] = None) -> List[dict]:
    """Fetch picks for a date. LEFT JOINs stock_technical_features so
    callers can read the pre_breakout block (signals + accumulation_score)
    without a second round-trip. `symbols` limits the read to those stocks."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    sql = (
        "SELECT ps.nse_symbol, ps.signal_date, ps.final_score, ps.confidence, ps.stage, "
        "       ps.timeframe_days_min, ps.timeframe_days_max, "
        "       ps.entry_price, ps.stoploss, ps.target_price, ps.risk_reward, "
        "       ps.source_scans, ps.reasons, ps.engine_version, "
        "       stf.components->'pre_breakout' AS pre_breakout, "
        "       stf.components->'raw' AS features_raw, "
        "       stf.components->'price_adjustment'->>'price_basis' AS price_basis "
        "FROM positional_signals ps "
        "LEFT JOIN stock_technical_features stf "
        "       ON stf.nse_symbol = ps.nse_symbol AND stf.as_of_date = ps.signal_date "
        "WHERE ps.signal_date = $1 AND ps.final_score >= $2 "
    )
    params: list = [signal_date, min_score]
    if stage:
        sql += "AND ps.stage = $3 "
        params.append(stage.upper())
    if symbols is not None:
        sql += "AND ps.nse_symbol = ANY($%d::text[]) " % (len(params) + 1)
        params.append(list(symbols))
    sql += "ORDER BY ps.final_score DESC, ps.risk_reward DESC LIMIT $%d" % (len(params) + 1)
    params.append(limit)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception as e:  # noqa: BLE001
        logger.warning("positional: fetch_picks failed (%s); returning empty", e)
        return []
    out = []
    for r in rows:
        d = dict(r)
        # warehouse_adjusted | raw_no_factors (scored on raw prices: no factors) | None (engine v1.0: raw prices)
        d["price_basis"] = d.get("price_basis") or "raw"
        # asyncpg returns JSONB as string in some envs — coerce both blobs
        for key in ("pre_breakout", "features_raw"):
            v = d.get(key)
            if isinstance(v, str):
                try:
                    d[key] = json.loads(v)
                except (TypeError, ValueError):
                    d[key] = None
        out.append(d)
    return out


async def _scan_basis(d: Optional[date]) -> Optional[Dict[str, Any]]:
    """The engine version, price basis, exceptions and data-quality status of the scan served for `d`
    (scan_meta.basis_for_date). Unreadable → said so in the payload and the log, never shown as clean."""
    if d is None:
        return None
    pool = await pg_client.get_pool()
    if pool is None:
        return {"date": d.isoformat(), "unavailable": "no database pool"}
    try:
        return await scan_meta.basis_for_date(pool, db, d)
    except Exception as e:  # noqa: BLE001
        logger.warning("positional: scan basis for %s unreadable: %s", d, e)
        return {"date": d.isoformat(), "unavailable": f"scan basis unreadable ({type(e).__name__})"}


def _rr_key(r: Dict[str, Any]):
    """ORDER BY risk_reward DESC as Postgres sorts it (NULLs first)."""
    rr = r.get("risk_reward")
    return (0, 0.0) if rr is None else (1, -float(rr))


async def _picks_with_results_signal(sig_date: date, min_score: float, stage: Optional[str],
                                     limit: int) -> "tuple[List[dict], Dict[str, Any]]":
    """The day's picks with the results signal applied BEFORE the min-score filter, the sort and the limit
    (docs/EARNINGS_SURPRISE_TRACKER.md §4d): the top rows by the engine's score plus every stock with a signal are read,
    final_score is adjusted, then filtered, sorted and cut, so a boosted stock just outside the top N can enter and a
    weak one can leave. The engine's stored scores are never changed. No signal (or a failed one) leaves the order as it was."""
    signals, gap = await results_signal.current()
    cat = sorted(signals)
    rows = await _fetch_picks(sig_date, min_score, stage, limit + len(cat))
    have = {r["nse_symbol"] for r in rows}
    extra = [s for s in cat if s not in have]
    if extra:
        rows += await _fetch_picks(sig_date, 0.0, stage, len(extra), symbols=extra)
    results_signal.apply(rows, signals)
    rows = [r for r in rows if (r.get("final_score") is not None and float(r["final_score"]) >= min_score)]
    rows.sort(key=lambda r: (-float(r["final_score"]), _rr_key(r)))
    rows = rows[:limit]
    return rows, results_signal.meta(signals, gap, sum(1 for r in rows if r.get("results_signal")))


# ── Public endpoints ─────────────────────────────────────────────────────
@router.get("/picks")
async def get_picks(request: Request,
                    date: Optional[str] = Query(None, alias="date"),
                    min_score: float = 0.55,
                    stage: Optional[str] = None,
                    limit: int = 30):
    await get_current_user(request)
    sig_date = _parse_date(date) or await _latest_signal_date()
    if sig_date is None:
        return {"signal_date": None, "picks": [], "message": "no signals available yet",
                "rules_version": setup_rules.RULES_VERSION, "engine_versions": []}
    picks, rs_meta = await _picks_with_results_signal(sig_date, min_score, stage, limit)
    bars = await _spark_bars(sorted({p["nse_symbol"] for p in picks}), sig_date)
    for p in picks:
        p.update(_bar_fields(None if bars is None else bars.get(p["nse_symbol"], [])))
    return {
        "signal_date": str(sig_date),
        "count": len(picks),
        "picks": picks,
        # docs/EARNINGS_SURPRISE_TRACKER.md §4d: final_score carries the results signal; base_final_score is the engine's.
        "results_signal": rs_meta,
        # PRD §5.8: the rules and engine versions behind these rows.
        "rules_version": setup_rules.RULES_VERSION,
        "engine_versions": sorted({p["engine_version"] for p in picks if p.get("engine_version")}),
        # Owner decision 2026-10-27: results are published with their engine version, price basis, exceptions and
        # data-quality status (services/positional_engine/scan_meta.py).
        "scan_basis": await _scan_basis(sig_date),
    }


@router.get("/watchlist")
async def get_watchlist(request: Request, limit: int = 30):
    """Weekend / between-session "preparation mode" — returns 4 buckets:

      • TRUE_ACCUMULATION   — Tight 15d range (<8%) + volume drying up +
                              higher lows + small upper wicks. The setup
                              you actually want before a breakout.
      • PRE_BREAKOUT        — Within 2% below resistance + volume rising
                              + recent volume spike. Trigger candidates.
      • BREAKOUT_CONFIRMED  — Just broke above resistance with volume
                              ≥1.5× the 20d avg. Ready for entry.
      • TREND_CONTINUATION  — Established uptrend (close > 20EMA >
                              50EMA), pullback to or near the 20EMA.
                              Lower-risk re-entry on momentum names.

    The previous version classified by `stage` from stock_technical_features
    (just "ACCUMULATION") which produced false positives — stocks in a
    downtrend with negative momentum were leaking into the accumulation
    bucket. This version pulls the last 60 bars per candidate and
    re-evaluates structure: range tightness, volume profile, swing-low
    pattern, upper-wick presence. Slower (per-symbol OHLCV scan) but
    correct.

    Each row carries trigger_price + suggested entry zone + suggested
    stop + the smart-money signals the gate evaluated. Bucket descriptors
    in the response include the qualifying rule so the UI can show
    "why this stock is here".
    """
    await get_current_user(request)
    rules = setup_rules.public_rules()
    cand = setup_rules.WATCHLIST["candidates"]
    signals, rs_gap = await results_signal.current()      # §4d, applied to the candidates before they are cut
    signalled = sorted(signals)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"as_of_date": None, "buckets": {}, "_reason": "no pg pool", "rules": rules}

    try:
        async with pool.acquire() as conn:
            latest = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM stock_technical_features"
            )
            if not latest or latest["d"] is None:
                return {
                    "as_of_date": None, "buckets": {},
                    "_reason": "no technical features yet — run the engine first",
                    "rules": rules,
                }
            d = latest["d"]
            # First pass — narrow candidates by score so we only do the
            # OHLCV round-trip for the top ~80. WEAK/EXTENDED dropped here
            # because their structure rules out our 4 buckets anyway.
            cand_sql = """
                SELECT stf.nse_symbol, stf.stage, stf.confidence, stf.final_score,
                       stf.close_price, stf.sma_50, stf.sma_200,
                       stf.rsi_14, stf.atr_14,
                       stf.breakout_level, stf.support_level, stf.resistance_level,
                       stf.engine_version,
                       stf.components->'price_adjustment'->>'price_basis' AS price_basis,
                       sm.sector
                FROM stock_technical_features stf
                LEFT JOIN stock_master sm ON sm.nse_symbol = stf.nse_symbol
                WHERE stf.as_of_date = $1
                  AND stf.stage IS NOT NULL
                  AND stf.stage <> ALL($2::text[])
                  AND stf.close_price > $3
                  {extra}
                ORDER BY stf.final_score DESC NULLS LAST
                LIMIT $4
                """
            cand_rows = [dict(r) for r in await conn.fetch(
                cand_sql.format(extra=""),
                d, cand["excluded_stages"], cand["min_close"], cand["top_by_score"] + len(signalled),
            )]
            have = {r["nse_symbol"] for r in cand_rows}
            missing = [s for s in signalled if s not in have]
            if missing:
                cand_rows += [dict(r) for r in await conn.fetch(
                    cand_sql.format(extra="AND stf.nse_symbol = ANY($5::text[])"),
                    d, cand["excluded_stages"], cand["min_close"], len(missing), missing,
                )]
            # §4d: the results signal adjusts final_score before the candidates are ranked and cut (stage unchanged).
            results_signal.apply(cand_rows, signals)
            cand_rows.sort(key=lambda r: -(r["final_score"] if r["final_score"] is not None else -1.0))
            cand_rows = cand_rows[:cand["top_by_score"]]
            candidate_syms = [r["nse_symbol"] for r in cand_rows]
            # Second pass — bulk-load last 60 bars for each candidate
            # symbol from stock_ohlcv. One query.
            bars_by_sym: dict = {}
            raw_bars_by_sym: dict = {}   # (bar_date, close, volume) as stored, for the spark / traded-value fields
            if candidate_syms:
                ohlcv_rows = await conn.fetch(
                    """
                    SELECT nse_symbol, bar_date, open_price AS open, high_price AS high,
                           low_price AS low, close_price AS close, volume,
                           delivery_qty, delivery_pct
                    FROM stock_ohlcv
                    WHERE nse_symbol = ANY($1::text[])
                      AND bar_date <= $2
                      AND bar_date > $2 - INTERVAL '90 days'
                    ORDER BY nse_symbol, bar_date ASC
                    """,
                    candidate_syms, d,
                )
                for r in ohlcv_rows:
                    raw_bars_by_sym.setdefault(r["nse_symbol"], []).append((r["bar_date"], r["close"], r["volume"]))
                    bars_by_sym.setdefault(r["nse_symbol"], []).append({
                        "date":         r["bar_date"],
                        "open":         float(r["open"]) if r["open"] is not None else 0.0,
                        "high":         float(r["high"]) if r["high"] is not None else 0.0,
                        "low":          float(r["low"]) if r["low"] is not None else 0.0,
                        "close":        float(r["close"]) if r["close"] is not None else 0.0,
                        "volume":       int(r["volume"]) if r["volume"] is not None else 0,
                        "delivery_qty": r["delivery_qty"],
                        "delivery_pct": float(r["delivery_pct"]) if r["delivery_pct"] is not None else None,
                    })
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist query failed: %s", e, exc_info=True)
        return {"as_of_date": None, "buckets": {},
                "_reason": f"{type(e).__name__}: {str(e)[:200]}", "rules": rules}

    # Smart-money classifier — uses helpers from feature_calculator.
    from services.positional_engine import feature_calculator as fc

    true_accum: list = []
    pre_break: list = []
    confirmed: list = []
    continuation: list = []

    for r in cand_rows:
        sym = r["nse_symbol"]
        bars = bars_by_sym.get(sym) or []
        if len(bars) < cand["min_bars"]:
            continue   # not enough history to evaluate structure
        close = float(r["close_price"]) if r["close_price"] is not None else None
        bo = float(r["breakout_level"]) if r["breakout_level"] is not None else None
        sma50 = float(r["sma_50"]) if r["sma_50"] is not None else None
        sma200 = float(r["sma_200"]) if r["sma_200"] is not None else None
        atr = float(r["atr_14"]) if r["atr_14"] is not None else None
        if close is None:
            continue

        # Smart-money primitives
        rng_15 = fc.range_pct_n(bars, 15)
        vol_dry_10 = fc.volume_drying(bars, 10)
        vol_spike = fc.volume_spike_ratio(bars, spike_n=3, baseline=20)
        hl_count = fc.higher_lows_count(bars, lookback=20, pivot_window=3)
        wick = fc.upper_wick_pct(bars, lookback=5)
        delivery_t = fc.delivery_trend_pct(bars, period=10)
        ema20 = fc.ema(fc._closes(bars), 20)
        # Distance to breakout in %
        dist_pct = round((close - bo) / bo * 100.0, 2) if bo and bo > 0 else None
        # Distance from 20EMA — for trend continuation pullback gate
        dist_ema20 = round((close - ema20) / ema20 * 100.0, 2) if ema20 and ema20 > 0 else None

        signals = {
            "range_pct_15d":        rng_15,
            "volume_slope_10d_pct": vol_dry_10,
            "volume_spike_3v20":    vol_spike,
            "higher_lows_count":    hl_count,
            "upper_wick_pct":       wick,
            "delivery_trend_pct":   delivery_t,
            "dist_breakout_pct":    dist_pct,
            "dist_ema20_pct":       dist_ema20,
        }

        # PRD §5.6 gap gate: the scan session's open against the previous close.
        gap_pct = setup_rules.gap_up_pct(bars[-1]["open"], bars[-2]["close"]) if len(bars) >= 2 else None
        signals["gap_up_pct"] = round(gap_pct, 2) if gap_pct is not None else None

        def _stop(entry, mult=setup_rules.WATCHLIST["stop_atr_multiple"]):
            if entry is None or atr is None:
                return None
            return round(entry - mult * atr, 2)

        base_item = {
            "nse_symbol": sym,
            "sector": r["sector"],
            "stage": r["stage"],
            "confidence": r["confidence"],
            "final_score": round(float(r["final_score"] or 0), 3),
            "base_final_score": round(float(r["base_final_score"]), 3) if r.get("base_final_score") is not None else None,
            "results_signal": r.get("results_signal"),
            "close_price": close,
            "trigger_price": bo,
            "stop_price": None,
            "atr_pct": (round(atr / close * 100, 2) if close and atr else None),
            "rsi_14": float(r["rsi_14"]) if r["rsi_14"] is not None else None,
            "sma_50": sma50,
            "sma_200": sma200,
            "ema_20": ema20,
            "signals": signals,
            "resistance_level": float(r["resistance_level"]) if r["resistance_level"] is not None else None,
            "support_level": float(r["support_level"]) if r["support_level"] is not None else None,
            "engine_version": r.get("engine_version"),
            "price_basis": r.get("price_basis") or "raw",
            **_bar_fields(raw_bars_by_sym.get(sym, [])),
        }

        # ── Bucket gates: services/positional_engine/setup_rules.py (thresholds and precedence, versioned) ──
        bucket = setup_rules.classify_setup(
            stage=r["stage"], close=close, sma50=sma50, ema20=ema20,
            dist_breakout_pct=dist_pct, dist_ema20_pct=dist_ema20, volume_spike=vol_spike,
            volume_slope=vol_dry_10, range_15d=rng_15, higher_lows=hl_count, upper_wick=wick, gap_pct=gap_pct,
        )
        if bucket == "breakout_confirmed":
            # Close just above the breakout level on elevated volume, not made on a gap. The most actionable bucket.
            it = {**base_item, "stop_price": _stop(bo)}
            it["why"] = (f"Broke above ₹{bo:.2f} ({dist_pct:+.1f}%) on "
                         f"{vol_spike:.1f}× avg volume")
            confirmed.append(it)
        elif bucket == "pre_breakout":
            # Just below resistance, volume building.
            it = {**base_item, "stop_price": _stop(bo)}
            it["why"] = (f"{abs(dist_pct):.1f}% below ₹{bo:.2f} resistance · "
                         f"volume {vol_spike:.1f}× avg")
            pre_break.append(it)
        elif bucket == "true_accumulation":
            # Tight range + volume drying + higher lows + small upper wicks — the "real" accumulation rather than
            # just stage='ACCUMULATION'.
            it = {**base_item, "stop_price": _stop(close)}
            wick_msg = "" if wick is None else f", wick {wick:.0%}"
            dlv_msg = "" if delivery_t is None else f", delivery {delivery_t:+.0f}%"
            it["why"] = (f"Tight {rng_15:.1f}% range, vol drying "
                         f"{vol_dry_10:+.1f}%/d, {hl_count} higher lows{wick_msg}{dlv_msg}")
            true_accum.append(it)
        elif bucket == "trend_continuation":
            # close > 20EMA > 50-day average, in the pullback zone above the 20EMA, no fresh weakness.
            it = {**base_item, "stop_price": _stop(ema20)}
            it["why"] = (f"Trend intact (close > 20EMA ₹{ema20:.2f} > 50EMA), "
                         f"{dist_ema20:.1f}% above 20EMA — pullback zone")
            continuation.append(it)

    # Cap each bucket so the UI stays readable. Confirmed gets the most.
    buckets = {
        "breakout_confirmed": confirmed[:max(4, int(limit / 3))],
        "pre_breakout":       pre_break[:max(4, int(limit / 3))],
        "true_accumulation":  true_accum[:max(4, int(limit / 4))],
        "trend_continuation": continuation[:max(4, int(limit / 4))],
    }

    # Day-of-week + signal-date staleness for the UI's mode banner.
    import datetime as _dt
    today = _dt.date.today()
    is_weekend = today.weekday() >= 5
    days_stale = (today - d).days if d is not None else None
    weekend_mode = is_weekend or (days_stale is not None and days_stale > 0)

    total_count = sum(len(v) for v in buckets.values())
    return {
        "as_of_date": str(d),
        "is_weekend_mode": weekend_mode,
        "is_weekend": is_weekend,
        "days_stale": days_stale,
        "total_count": total_count,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
        "_classifier_version": setup_rules.WATCHLIST["classifier"],
        # PRD §5.6 / §5.8: the thresholds these buckets used, with their version, and the engine that wrote the rows.
        "rules": rules,
        "engine_versions": sorted({r.get("engine_version") for r in cand_rows if r.get("engine_version")}),
        "scan_basis": await _scan_basis(d),
        # docs/EARNINGS_SURPRISE_TRACKER.md §4d: final_score carries the results signal; base_final_score is the engine's.
        "results_signal": results_signal.meta(signals, rs_gap, sum(1 for v in buckets.values() for it in v if it.get("results_signal"))),
    }


# ── GET /api/positional/scan-universe ───────────────────────────────────
# The data platform's scan snapshot is end of day: one read serves every caller for _SNAPSHOT_TTL seconds. The model's
# published run is per session, cached the same way. Neither cache ever serves a failed read.
_SNAPSHOT_TTL = 600.0
_snapshot_cache: Dict[str, Any] = {"at": float("-inf"), "body": None}
_model_cache: Dict[str, Any] = {}
_MODEL_HEADS = ("p_up5_1d", "p_up10_1d")
_SCAN_SYMBOLS_MAX = 150
_SCAN_SYM_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
_UNAVAILABLE = "upstream_unavailable"


def _symbol_list(raw: Optional[str], field: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").split(","):
        sym = part.strip().upper()
        if not sym:
            continue
        if not _SCAN_SYM_RE.match(sym):
            raise HTTPException(status_code=422, detail=f"invalid_symbol: {field}")
        if sym not in out:
            out.append(sym)
    if len(out) > _SCAN_SYMBOLS_MAX:
        raise HTTPException(status_code=422, detail=f"too_many_symbols: {field} (max {_SCAN_SYMBOLS_MAX})")
    return out


async def _scan_snapshot() -> Dict[str, Any]:
    """DaaS GET /v1/features/scan-snapshot, cached; 502 upstream_unavailable on any failure (never an empty universe)."""
    now = time.monotonic()
    if _snapshot_cache["body"] is not None and now - _snapshot_cache["at"] < _SNAPSHOT_TTL:
        return _snapshot_cache["body"]
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw("/features/scan-snapshot", None, timeout=30.0)
    except daas_client.DaasError as e:
        logger.warning("scan-universe: snapshot read failed: %s", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("rows"), list) or not body.get("as_of"):
        logger.warning("scan-universe: snapshot answered HTTP %s", status)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    _snapshot_cache.update(at=now, body=body)
    return body


async def _move_odds_denied(request: Request) -> Optional[str]:
    """None when the account may see the move-odds model (the same gate as /api/move-odds), else the reason."""
    try:
        await require_feature("move_odds")(request)
    except HTTPException as e:
        return "no_access" if e.status_code == 403 else "unavailable"
    return None


async def _model_head(head: str) -> Dict[str, Any]:
    """One head of the published move-odds run: {status, reason?, run?, p: {symbol: p}}. Never raises."""
    now = time.monotonic()
    hit = _model_cache.get(head)
    if hit and now - hit[0] < _SNAPSHOT_TTL:
        return hit[1]
    try:
        status, body = await daas_client.get_raw("/move-odds/latest", {"head": head, "model": "v4"})
    except daas_client.DaasError as e:
        logger.warning("scan-universe: move-odds %s failed: %s", head, e)
        return {"status": "unavailable", "reason": "The model's run could not be read.", "p": {}}
    data = (body or {}).get("data") if isinstance(body, dict) else None
    data = data if isinstance(data, dict) else {}
    if status == 200 and data.get("status") == "final" and isinstance(data.get("rows"), list):
        run = data.get("run") or {}
        p = {str(r.get("symbol") or "").upper(): float(r["p"]) for r in data["rows"]
             if isinstance(r, dict) and isinstance(r.get("p"), (int, float))}
        out = {"status": "final", "p": p,
               "run": {k: run.get(k) for k in ("model", "refit", "data_as_of", "target_session", "universe_size",
                                               "scored", "train_end")}}
    elif status == 200 and data.get("status") == "not_published":
        out = {"status": "not_published", "p": {}, "expected_session": data.get("expected_session"),
               "reason": f"Not published for the session of {data.get('expected_session')} yet."}
    elif status == 503 and data.get("status") == "withheld":
        out = {"status": "withheld", "p": {}, "reason": f"Run withheld: {data.get('reason')}"}
    else:
        return {"status": "unavailable", "reason": f"The model's run answered HTTP {status}.", "p": {}}
    _model_cache[head] = (now, out)
    return out


@router.get("/scan-universe")
async def scan_universe(request: Request,
                        setups: Optional[str] = Query(None, max_length=4000,
                                                      description="The scanner's own setups, comma-separated: returned "
                                                                  "and counted toward F&O candidates"),
                        symbols: Optional[str] = Query(None, max_length=4000,
                                                       description="Other stocks to return (e.g. a watchlist)")):
    """Universe categories, eligibility and model rank for the opportunity scanner (PRD §5.2, §5.3, §5.8).

    `rows` holds every stock in a category (up to MAX_ROWS_PER_CATEGORY each, best first by the category's rank_by
    figure) plus every stock asked for in `setups` / `symbols`. Each row: the snapshot's figures (end of day, as of
    `as_of`), eligible + exclusion (the first gate it fails), risk_class, liquidity_class, categories, and
    model_rank_pct per head: the stock's move-odds estimate as a percentile among the ELIGIBLE stocks the model
    scored (setup_rules.rank_percentiles); null when the stock is not eligible, not scored, or the model is not
    available to this account (`model.status` says which). A probability itself is not sent here.
    """
    await get_current_user(request)
    want_setups = _symbol_list(setups, "setups")
    want_symbols = _symbol_list(symbols, "symbols")
    snap = await _scan_snapshot()
    try:
        as_of = date.fromisoformat(str(snap["as_of"])[:10])
    except ValueError:
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    ev = setup_rules.evaluate(snap["rows"], as_of, setup_symbols=want_setups)
    rows = ev["rows"]

    denied = await _move_odds_denied(request)
    heads: Dict[str, Any] = {}
    ranks: Dict[str, Dict[str, Optional[float]]] = {}
    if denied is None:
        for head in _MODEL_HEADS:
            h = await _model_head(head)
            eligible_p = {s: h["p"].get(s) for s, r in rows.items() if r["eligible"] and s in h["p"]}
            ranks[head] = setup_rules.rank_percentiles(eligible_p)
            heads[head] = {k: v for k, v in h.items() if k != "p"}
            heads[head]["ranked_eligible"] = sum(1 for v in eligible_p.values() if v is not None)
        status = heads[_MODEL_HEADS[0]]["status"]
        model = {"status": status, "reason": heads[_MODEL_HEADS[0]].get("reason"), "heads": heads}
    else:
        model = {"status": denied, "heads": {},
                 "reason": ("Move probabilities are not enabled for this account." if denied == "no_access"
                            else "The feature state could not be read.")}

    wanted: List[str] = []
    for cat in ev["categories"].values():
        wanted += cat["symbols"]
    wanted += want_setups + want_symbols
    out_rows: List[Dict[str, Any]] = []
    seen: set = set()
    for sym in wanted:
        if sym in seen or sym not in rows:
            continue
        seen.add(sym)
        r = dict(rows[sym])
        r["model_rank_pct"] = {head: ranks.get(head, {}).get(sym) for head in _MODEL_HEADS}
        out_rows.append(r)
    return {
        "as_of": str(snap["as_of"])[:10],
        "reference_as_of": snap.get("reference_as_of"),
        "sessions": snap.get("sessions"),
        "source": snap.get("source"),
        "mode": "eod",
        "rules": setup_rules.public_rules(),
        "results_window": setup_rules.results_window(as_of),
        "universe": ev["universe"],
        "categories": ev["categories"],
        "model": model,
        "rows": out_rows,
        "not_found": [s for s in want_setups + want_symbols if s not in rows],
    }


# ── GET /api/positional/reversal-candidates ─────────────────────────────
_reversal_cache: Dict[float, Dict[str, Any]] = {}
_REVERSAL_MAX_DIST = 25.0


async def _reversal_snapshot(max_dist_pct: float) -> Dict[str, Any]:
    """DaaS GET /v1/features/reversal-snapshot, cached for _SNAPSHOT_TTL; 502 upstream_unavailable on any failure."""
    now = time.monotonic()
    hit = _reversal_cache.get(max_dist_pct)
    if hit and now - hit["at"] < _SNAPSHOT_TTL:
        return hit["body"]
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw("/features/reversal-snapshot", {"max_dist_pct": max_dist_pct},
                                                 timeout=60.0)
    except daas_client.DaasError as e:
        logger.warning("reversal-candidates: snapshot read failed: %s", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("rows"), list) or not body.get("as_of"):
        logger.warning("reversal-candidates: snapshot answered HTTP %s", status)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    _reversal_cache[max_dist_pct] = {"at": now, "body": body}
    return body


@router.get("/reversal-candidates")
async def reversal_candidates(request: Request,
                              near_pct: float = Query(reversal_rules.NEAR_LOW["default_pct"], ge=5.0, le=25.0,
                                                      description="Pool: within this % of the rolling 252-session low"),
                              view: str = Query("candidates", pattern="^(candidates|all)$"),
                              limit: int = Query(100, ge=1, le=300)):
    """Reversal candidates near the 52-week low (reversal-rules.v1). Proximity is a screen, not a signal.

    `rows` hold stocks with stabilization evidence (statuses confirmed, trigger_ready, early_reversal, watchlist), best
    first; `view=all` adds the near-low stocks without enough evidence. `excluded` lists stocks a hard gate removed, each
    with its reason; `universe.exclusions` counts every reason, `prefilter` what the data platform's liquidity pre-filter
    dropped. Every row carries components (score, weight, known flag), unknown_components, coverage_pct, signals with
    observed values, levels (hypothetical, never sent to a broker) and an explanation. Missing data is never neutral.
    """
    await get_current_user(request)
    snap = await _reversal_snapshot(_REVERSAL_MAX_DIST)
    try:
        out = reversal_service.run(snap, near_pct, view=view, limit=limit)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.warning("reversal-candidates: snapshot malformed: %s", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    out["mode"] = "eod"
    out["scope"] = "research / paper trading only; no order is sent anywhere"
    return out


def _readiness(ltp: Optional[float], entry: float, sl: float) -> str:
    """Classify a live LTP against an EOD-derived trade plan.

    "TRIGGERED" used to fire for any LTP ≥ entry — but that meant a
    stock 30% past entry was still labelled "actionable" alongside one
    just crossing. Real users (rightly) said: that's a chase, not a
    trigger. Now bucketed:

        LATE        LTP > entry × 1.08    — already moved >8%, skip
        TRIGGERED   entry to entry × 1.08 — just crossed, actionable now
        NEAR        -2% to entry          — within striking distance
        WAIT        -5% to -2%            — wait for better entry
        FAR         < -5%                 — too far below; not on watchlist
        STOPPED     LTP ≤ SL              — invalidated
        UNKNOWN     LTP not available
    """
    if ltp is None:
        return "UNKNOWN"
    if entry <= 0:
        return "UNKNOWN"
    if ltp <= sl:
        return "STOPPED"
    pct = (ltp - entry) / entry * 100.0
    if pct > 8.0:
        return "LATE"
    if pct >= 0.0:
        return "TRIGGERED"
    if pct >= -2.0:
        return "NEAR"
    if pct >= -5.0:
        return "WAIT"
    return "FAR"


async def _enrich_with_live(picks: list) -> list:
    """Overlay current LTP + readiness + 4-pillar conviction verdict onto
    each pick. Best-effort — a yfinance hiccup degrades to UNKNOWN /
    no-verdict, never breaks the response."""
    if not picks:
        return picks
    syms = [(p.get("nse_symbol") or "").upper() for p in picks if p.get("nse_symbol")]
    try:
        from services import live_price as _lp
        # Bound the yfinance batch download — first call for a fresh
        # symbol set can take 30s+ which freezes the UI on "Loading
        # picks…". 8s is enough for a warm cache; cold misses degrade
        # to no-LTP (UI handles live_price=null gracefully and the
        # next 60s tick repopulates from the cache).
        prices = await asyncio.wait_for(
            asyncio.to_thread(_lp._batch_fetch_prices, syms),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warning("live overlay timed out — returning picks without LTP (will repopulate next tick)")
        prices = {}
    except Exception as e:  # noqa: BLE001
        logger.warning("live overlay fetch failed: %s", e)
        prices = {}
    out = []
    for p in picks:
        sym = (p.get("nse_symbol") or "").upper()
        ltp = prices.get(sym)
        entry = float(p.get("entry_price") or 0)
        sl = float(p.get("stoploss") or 0)

        # Conviction layer — 4 pillars + penalties + verdict
        feats = p.get("features_raw") or {}
        trade_plan = {
            "entry": entry,
            "stoploss": sl,
            "target": float(p.get("target_price") or 0),
            "risk_reward": float(p.get("risk_reward") or 0),
        }
        scan_count = len(p.get("source_scans") or [])
        try:
            verdict = conviction.classify_verdict(
                features=feats,
                trade_plan=trade_plan,
                live_ltp=ltp,
                scan_count=scan_count,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("conviction classify failed for %s: %s", sym, e)
            verdict = None

        enriched = {
            **p,
            "live_price": ltp,
            "live_pct_from_entry": (
                round((ltp - entry) / entry * 100.0, 2)
                if (ltp is not None and entry > 0) else None
            ),
            "readiness": _readiness(ltp, entry, sl),
            "conviction": verdict,
        }
        # Don't ship the bulky features_raw blob to the client — it was
        # only fetched server-side to feed conviction.
        enriched.pop("features_raw", None)
        out.append(enriched)
    return out


@router.get("/picks/mine")
async def get_picks_for_me(request: Request,
                            date: Optional[str] = Query(None, alias="date"),
                            min_score: float = 0.55,
                            limit: int = 30,
                            live: bool = False):
    """Same as /picks but filtered/annotated against the caller's portfolio.

    Pass `live=true` to overlay current LTP + a readiness label per pick
    (TRIGGERED / NEAR / WAIT / FAR / STOPPED). yfinance batch fetch — adds
    ~3-5s for the first call, cached implicitly downstream."""
    user = await get_current_user(request)
    sig_date = _parse_date(date) or await _latest_signal_date()
    if sig_date is None:
        return {"signal_date": None, "picks": []}

    picks = await _fetch_picks(sig_date, min_score, None, limit)

    # Build holdings list from Mongo for portfolio_filter
    raw = await db.holdings.find(
        {"user_id": user["user_id"], "asset_type": {"$in": ["stock", "STOCK", "equity", "EQUITY"]}},
        {"_id": 0, "nse_symbol": 1, "sector": 1, "current_value": 1, "value": 1}
    ).to_list(2000)
    holdings = [{
        "nse_symbol": (h.get("nse_symbol") or "").upper(),
        "sector": h.get("sector"),
        "value": h.get("current_value") or h.get("value") or 0,
    } for h in raw if h.get("nse_symbol")]

    # Map symbol → sector for picks (from stock_master if available).
    # stock_master may not exist on a fresh deploy — degrade to empty.
    sym2sec = {}
    syms = [p["nse_symbol"] for p in picks]
    if syms:
        pool = await pg_client.get_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT nse_symbol, sector FROM stock_master WHERE nse_symbol = ANY($1::text[])",
                        syms,
                    )
                sym2sec = {r["nse_symbol"]: r["sector"] for r in rows if r["sector"]}
            except Exception as e:  # noqa: BLE001
                logger.warning("positional: stock_master lookup failed (%s)", e)

    annotated = portfolio_filter.annotate(picks, holdings, symbol_to_sector=sym2sec)
    if live:
        annotated = await _enrich_with_live(annotated)
    return {
        "signal_date": str(sig_date),
        "count": len(annotated),
        "picks": annotated,
        "live": bool(live),
    }


@router.get("/picks/{symbol}")
async def get_pick_detail(request: Request,
                           symbol: str,
                           date: Optional[str] = Query(None, alias="date")):
    await get_current_user(request)
    sig_date = _parse_date(date) or await _latest_signal_date()
    sym = symbol.upper().strip()
    pool = await pg_client.get_pool()
    if pool is None or sig_date is None:
        raise HTTPException(status_code=404, detail="No data")
    async with pool.acquire() as conn:
        sig = await conn.fetchrow(
            "SELECT * FROM positional_signals WHERE nse_symbol = $1 AND signal_date = $2",
            sym, sig_date,
        )
        feat = await conn.fetchrow(
            "SELECT * FROM stock_technical_features WHERE nse_symbol = $1 AND as_of_date = $2",
            sym, sig_date,
        )
        scans = await conn.fetch(
            "SELECT scan_name FROM chartink_scan_hits WHERE nse_symbol = $1 AND scan_date = $2",
            sym, sig_date,
        )
    if not feat and not sig:
        raise HTTPException(status_code=404, detail=f"{sym} not scored on {sig_date}")
    return {
        "symbol": sym,
        "signal_date": str(sig_date),
        "signal": dict(sig) if sig else None,
        "features": dict(feat) if feat else None,
        "scan_hits": [r["scan_name"] for r in scans],
    }


# ── Signal record (revision history) ─────────────────────────────────────
_SIGNAL_COLS = ("COALESCE(revision, 1) AS revision, final_score, confidence, stage, timeframe_days_min, "
                "timeframe_days_max, entry_price, stoploss, target_price, risk_reward, source_scans, reasons, "
                "engine_version, stop_method, computed_at")
#: What a revision is compared on, as (the field name in the answer, how to read it from a revision).
_RECORD_FIELDS = (
    ("entry", lambda r: r["levels"]["entry"]), ("stop", lambda r: r["levels"]["stop"]),
    ("target", lambda r: r["levels"]["target"]), ("risk_reward", lambda r: r["levels"]["risk_reward"]),
    ("stop_method", lambda r: r["stop_method"]), ("stage", lambda r: r["setup"]["stage"]),
    ("confidence", lambda r: r["setup"]["confidence"]), ("final_score", lambda r: r["setup"]["final_score"]),
    ("timeframe_days_min", lambda r: r["setup"]["timeframe_days_min"]),
    ("timeframe_days_max", lambda r: r["setup"]["timeframe_days_max"]),
    ("source_scans", lambda r: r["setup"]["source_scans"]), ("reasons", lambda r: r["setup"]["reasons"]),
    ("engine_version", lambda r: r["setup"]["engine_version"]),
)


def _jsonb(v):
    """A JSONB column as data (asyncpg may hand it back as text)."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    return v


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _signal_revision(row) -> Dict[str, Any]:
    """One stored row (live or history) in the record's shape. Every value is the row's own; nothing is filled in."""
    out = {
        "revision": int(row["revision"]),
        "levels": {"entry": _num(row["entry_price"]), "stop": _num(row["stoploss"]),
                   "target": _num(row["target_price"]), "risk_reward": _num(row["risk_reward"])},
        "stop_method": _jsonb(row["stop_method"]),
        "setup": {"stage": row["stage"], "confidence": row["confidence"], "final_score": _num(row["final_score"]),
                  "timeframe_days_min": row["timeframe_days_min"], "timeframe_days_max": row["timeframe_days_max"],
                  "source_scans": list(row["source_scans"]) if row["source_scans"] is not None else None,
                  "reasons": _jsonb(row["reasons"]), "engine_version": row["engine_version"]},
        "computed_at": _iso(row["computed_at"]),
    }
    if "superseded_by" in row.keys():
        out["superseded_at"] = _iso(row["superseded_at"])
        out["superseded_by"] = row["superseded_by"]
    return out


def _revision_changes(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"field": name, "from": get(old), "to": get(new)} for name, get in _RECORD_FIELDS if get(old) != get(new)]


@router.get("/signals/{symbol}/record")
async def get_signal_record(request: Request,
                            symbol: str,
                            date: Optional[str] = Query(None, alias="date")):
    """Public (auth), read only: a scanner signal's live revision and every superseded one (see the module docstring)."""
    await get_current_user(request)
    sym = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,32}", sym):
        raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol}")
    sig_date = _parse_date(date)
    pool = await pg_client.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="signal_record_unavailable: the database is not reachable")
    async with pool.acquire() as conn:
        if not await pipeline.signal_history_ready(conn):
            raise HTTPException(status_code=503, detail="signal_history_not_ready: migration 025 "
                                                        "(positional_signals_history) is not applied, so no revision "
                                                        "history can be read")
        if sig_date is None:
            sig_date = await conn.fetchval(
                "SELECT GREATEST((SELECT MAX(signal_date) FROM positional_signals WHERE nse_symbol = $1), "
                "(SELECT MAX(signal_date) FROM positional_signals_history WHERE nse_symbol = $1))", sym)
            if sig_date is None:
                raise HTTPException(status_code=404, detail=f"No scanner signal for {sym}")
        live = await conn.fetchrow(
            f"SELECT {_SIGNAL_COLS} FROM positional_signals WHERE nse_symbol = $1 AND signal_date = $2", sym, sig_date)
        history = await conn.fetch(
            f"SELECT {_SIGNAL_COLS}, superseded_at, superseded_by FROM positional_signals_history "
            "WHERE nse_symbol = $1 AND signal_date = $2 ORDER BY revision", sym, sig_date)
        if live is None and not history:
            raise HTTPException(status_code=404, detail=f"No scanner signal for {sym} on {sig_date}")
        outcomes_error = None
        try:
            outcome_rows = await conn.fetch(
                "SELECT horizon_days, outcome, realised_return_pct, bars_to_outcome, evaluated_at "
                "FROM positional_outcomes WHERE nse_symbol = $1 AND signal_date = $2 ORDER BY horizon_days",
                sym, sig_date)
        except Exception as e:  # noqa: BLE001 — the outcomes table is optional to the record; say it was unreadable
            logger.warning("positional: signal record outcomes unreadable for %s %s (%s)", sym, sig_date, e)
            outcome_rows, outcomes_error = None, "positional_outcomes could not be read"

    current = _signal_revision(live) if live is not None else None
    revisions = [_signal_revision(r) for r in history]
    for i, rev in enumerate(revisions):
        nxt = revisions[i + 1] if i + 1 < len(revisions) else current
        rev["replaced_by_revision"] = nxt["revision"] if nxt else None
        rev["changes"] = _revision_changes(rev, nxt) if nxt else None
    outcomes = None if outcome_rows is None else [
        {"horizon_days": r["horizon_days"], "outcome": r["outcome"], "realised_return_pct": _num(r["realised_return_pct"]),
         "bars_to_outcome": r["bars_to_outcome"], "evaluated_at": _iso(r["evaluated_at"])} for r in outcome_rows]
    if current is None:
        note = "The live signal row is gone (a day rewrite removed it); only its superseded revisions are stored."
    elif not revisions:
        note = "No earlier revision is stored: the levels have not changed since the signal was first written."
    else:
        note = None
    return {
        "symbol": sym,
        "signal_date": str(sig_date),
        "current": current,
        "revisions": revisions,
        "revision_count": len(revisions) + (1 if current else 0),
        "state": {"live": current is not None,
                  "stage": current["setup"]["stage"] if current else None,
                  "outcomes": outcomes, "outcomes_error": outcomes_error,
                  "outcomes_basis": "positional_outcomes: target / stop hit per horizon, written by the outcome job; "
                                    "empty until a horizon is evaluated"},
        "note": note,
        "source": "positional_signals (the live revision) and positional_signals_history (each superseded revision, "
                  "copied unchanged when a re-run changed it or a day rewrite replaced it; migration 025)",
        "read_only": True,
    }


# ── Admin endpoints ──────────────────────────────────────────────────────
@router.post("/run")
async def admin_run(request: Request,
                    date: Optional[str] = Query(None, alias="date")):
    await require_admin(request)
    run_date = _parse_date(date) or datetime.utcnow().date()
    summary = await pipeline.run_for_date(run_date)
    return summary


@router.post("/run-full")
async def admin_run_full(request: Request,
                          date: Optional[str] = Query(None, alias="date"),
                          fetch_bhavcopy: bool = True,
                          fetch_scans: bool = True):
    """End-to-end one-shot: bhavcopy → Chartink scans → score.

    Each step is best-effort and reported separately so a partial failure
    (e.g. NSE archive blocked but Chartink works) doesn't kill the run.
    Used by the 'Run engine' button on the Portfolio page.

    Fallback: if today's bhavcopy isn't published yet (NSE drops it
    18:00–19:30 IST) AND the caller didn't pin a date, we step back one
    weekday at a time (up to 3 days) so the universe isn't empty when an
    admin clicks "Run engine" pre-19:30 IST.
    """
    await require_admin(request)
    explicit_date = date is not None
    run_date = _parse_date(date) or datetime.utcnow().date()
    out: dict = {"date": str(run_date), "steps": {}, "fallback_used": False}

    if fetch_bhavcopy:
        attempts: list = []
        candidate = run_date
        n = 0
        last_err: Optional[str] = None
        # Try requested date first; if 0 rows AND we weren't pinned to a
        # specific date, walk back to find the most recent published file.
        for _ in range(4):
            try:
                n = await bhavcopy_ingester.ingest_for_date(candidate)
                attempts.append({"date": str(candidate), "rows": n})
                if n > 0 or explicit_date:
                    break
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:200]
                attempts.append({"date": str(candidate), "error": last_err})
                if explicit_date:
                    break
            # Step back a weekday
            candidate -= timedelta(days=1)
            while candidate.weekday() >= 5:  # Sat=5, Sun=6
                candidate -= timedelta(days=1)
        if n > 0 and candidate != run_date:
            out["fallback_used"] = True
            out["date"] = str(candidate)
            run_date = candidate
        out["steps"]["bhavcopy"] = {
            "ok": n > 0,
            "rows_written": n,
            "attempts": attempts,
            **({"error": last_err} if last_err and n == 0 else {}),
        }

    if fetch_scans:
        try:
            scans = await scan_config.load(db)
            if not scans:
                out["steps"]["chartink"] = {"ok": False, "error": "no_scans_configured"}
            else:
                results = await chartink_api.run_scans(scans)
                written = {}
                for name, rows in results.items():
                    if name == "_errors":
                        continue
                    n = await chartink_loader.upsert_scan_hits(run_date, name, rows)
                    written[name] = n
                out["steps"]["chartink"] = {
                    "ok": True,
                    "rows_written": written,
                    "errors": results.get("_errors", {}),
                }
        except Exception as e:  # noqa: BLE001
            out["steps"]["chartink"] = {"ok": False, "error": str(e)[:200]}

    try:
        summary = await pipeline.run_for_date(run_date)
        out["steps"]["pipeline"] = summary
    except Exception as e:  # noqa: BLE001
        out["steps"]["pipeline"] = {"ok": False, "error": str(e)[:200]}

    out["ok"] = out["steps"].get("pipeline", {}).get("ok", False)
    return out


@router.get("/health")
async def positional_health(request: Request):
    """Diagnostic snapshot for the positional engine. Auth-only (so the
    UI's empty state can render actionable hints) but no admin gate —
    every signed-in user can see whether the engine has been fed today.

    Returns the freshness + row counts for each of the three tables the
    engine depends on, plus the scan config status. Drives the diagnostic
    panel that replaces the bare "No picks yet" empty state."""
    await get_current_user(request)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}
    out: dict = {"ok": True, "as_of": datetime.utcnow().isoformat()}
    queries = {
        "ohlcv":    "SELECT MAX(bar_date) AS d, COUNT(*) AS n FROM stock_ohlcv",
        "chartink": "SELECT MAX(scan_date) AS d, COUNT(*) AS n FROM chartink_scan_hits",
        "features": "SELECT MAX(as_of_date) AS d, COUNT(*) AS n FROM stock_technical_features",
        "signals":  "SELECT MAX(signal_date) AS d, COUNT(*) AS n FROM positional_signals",
    }
    today = datetime.utcnow().date()
    async with pool.acquire() as conn:
        for key, sql in queries.items():
            try:
                row = await conn.fetchrow(sql)
                d = row["d"] if row else None
                stale_days = (today - d).days if d else None
                out[key] = {
                    "latest_date": str(d) if d else None,
                    "row_count":   int(row["n"]) if row else 0,
                    "stale_days":  stale_days,
                }
            except Exception as e:  # noqa: BLE001
                out[key] = {"error": str(e)[:200]}
    try:
        scans = await scan_config.load(db)
        out["scan_config"] = {
            "count":   len(scans),
            "enabled": sum(1 for s in scans if s.get("enabled")),
        }
    except Exception as e:  # noqa: BLE001
        out["scan_config"] = {"error": str(e)[:200]}
    return out


@router.post("/scans/upload")
async def admin_upload_scan(request: Request,
                             scan_name: str = Form(...),
                             scan_date: str = Form(...),
                             csv_file: UploadFile = File(...)):
    await require_admin(request)
    sd = _parse_date(scan_date)
    if sd is None:
        raise HTTPException(status_code=400, detail="scan_date required")
    raw = (await csv_file.read()).decode("utf-8", errors="replace")
    rows = chartink_loader.parse_csv(raw)
    if not rows:
        raise HTTPException(status_code=400,
                            detail="No symbols parsed — check CSV has a 'Symbol' column")
    written = await chartink_loader.upsert_scan_hits(sd, scan_name.strip(), rows)
    return {
        "ok": True,
        "scan_name": scan_name.strip(),
        "scan_date": str(sd),
        "rows_written": written,
        "sample": [r["symbol"] for r in rows[:10]],
    }


@router.post("/ohlcv/bhavcopy")
async def admin_ingest_bhavcopy(request: Request,
                                 date: Optional[str] = Query(None, alias="date")):
    await require_admin(request)
    on = _parse_date(date) or (datetime.utcnow().date() - timedelta(days=1))
    n = await bhavcopy_ingester.ingest_for_date(on)
    return {"ok": n > 0, "date": str(on), "rows_written": n}


# ── Chartink scan-config + live fetch ────────────────────────────────────
@router.get("/scans/active")
async def list_active_scans(request: Request):
    """Auth-only view of the saved scan list — name + clause + enabled flag.
    Used by the Portfolio page's Positional Picks panel to surface the
    underlying screener criteria so users know *why* a stock made the cut."""
    await get_current_user(request)
    scans = await scan_config.load(db)
    return {"count": len(scans), "scans": scans}


@router.get("/scans/config")
async def admin_scan_config(request: Request):
    await require_admin(request)
    scans = await scan_config.load(db)
    return {"count": len(scans), "scans": scans}


@router.put("/scans/config")
async def admin_save_scan_config(request: Request):
    """Replace the full scan list. Body: {"scans": [{name, clause, enabled?}, ...]}."""
    await require_admin(request)
    body = await request.json()
    if not isinstance(body, dict) or "scans" not in body:
        raise HTTPException(status_code=400, detail="body must be {scans: [...]}")
    saved = await scan_config.save(db, body["scans"])
    return {"ok": True, "count": len(saved), "scans": saved}


@router.post("/scans/run-all")
async def admin_run_all_scans(request: Request,
                               date: Optional[str] = Query(None, alias="date")):
    """Fetch every enabled scan from Chartink's /screener/process endpoint
    and persist the hits into chartink_scan_hits for `date` (default today)."""
    await require_admin(request)
    scans = await scan_config.load(db)
    if not scans:
        raise HTTPException(status_code=400,
                             detail="No scans configured. PUT /api/positional/scans/config first.")
    sd = _parse_date(date) or datetime.utcnow().date()

    results = await chartink_api.run_scans(scans)
    summary = {"date": str(sd), "scans": {}, "errors": results.get("_errors", {})}
    for name, rows in results.items():
        if name == "_errors":
            continue
        n = await chartink_loader.upsert_scan_hits(sd, name, rows)
        summary["scans"][name] = {"hits": len(rows), "rows_written": n}
    return summary


@router.post("/scans/test")
async def admin_test_scan(request: Request):
    """One-shot scan probe — body: {"clause": "..."} → returns matching symbols
    without persisting. For verifying a clause before saving it to config."""
    await require_admin(request)
    body = await request.json()
    clause = (body or {}).get("clause", "").strip()
    if not clause:
        raise HTTPException(status_code=400, detail="clause is required")
    rows = await chartink_api.run_scan(clause)
    if rows is None:
        return {"ok": False, "error": "fetch_failed", "symbols": []}
    return {
        "ok": True,
        "count": len(rows),
        "symbols": [r["symbol"] for r in rows[:200]],
    }


# ── Chartink webhook (production-grade integration) ─────────────────────
# Chartink doesn't publish a public API, but they DO support per-alert
# webhooks: when a saved scan triggers, Chartink POSTs a JSON payload to
# a URL of your choice. This is the supported, reliable integration path.
# The polling /scans/run-all stays for ad-hoc backfills + dev.
#
# Standard Chartink alert payload (as of 2024+):
#   {
#     "stocks":         "INFY,TCS,RELIANCE",
#     "trigger_prices": "1500.5,3500.0,2400.25",
#     "triggered_at":   "2:34 pm",
#     "scan_name":      "TODAYS TOP BUY",
#     "scan_url":       "todays-top-buy",
#     "alert_name":     "Alert from TODAYS TOP BUY",
#     "webhook_url":    "https://api.nivesh.example.com/api/positional/chartink/webhook?token=…"
#   }
@router.post("/chartink/webhook")
async def chartink_webhook(request: Request, token: str = Query(...)):
    """Receive Chartink alert POSTs. Authenticated via the per-tenant
    `?token=` shared secret. Stocks land in chartink_scan_hits the moment
    Chartink fires the alert — no polling, no rate-limiting."""
    expected = await scan_config.get_webhook_token(db)
    if not expected:
        raise HTTPException(status_code=503, detail="webhook not initialised — admin must call /chartink/webhook-info first")
    if not token or token != expected:
        # Don't echo the expected token in the error — keeps brute-force probes blind.
        raise HTTPException(status_code=401, detail="invalid token")

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body must be JSON")

    chartink_name = (body.get("scan_name") or body.get("alert_name") or "").strip()
    stocks_raw = body.get("stocks") or ""
    prices_raw = body.get("trigger_prices") or ""
    triggered_at = body.get("triggered_at") or ""
    scan_url = body.get("scan_url") or ""

    stocks = [s.strip().upper() for s in str(stocks_raw).split(",") if s.strip()]
    prices = [p.strip() for p in str(prices_raw).split(",")]
    if not stocks:
        return {"ok": False, "error": "no stocks in payload",
                "received": {"scan_name": chartink_name}}

    # Map Chartink's free-text scan_name → internal scan name.
    saved = await scan_config.load(db)
    matched = scan_config.match_scan_name(saved, chartink_name) or scan_config.match_scan_name(saved, scan_url)
    final_scan_name = matched or f"chartink:{(chartink_name or scan_url or 'unknown').lower().replace(' ', '_')}"

    # Build hit rows. Pair price by index where available.
    rows = []
    for i, sym in enumerate(stocks):
        rows.append({
            "symbol": sym,
            "extra": {
                "trigger_price": prices[i] if i < len(prices) else None,
                "triggered_at": triggered_at,
                "scan_name_chartink": chartink_name,
                "scan_url": scan_url,
                "source": "webhook",
            },
        })

    hit_date = datetime.utcnow().date()
    written = await chartink_loader.upsert_scan_hits(hit_date, final_scan_name, rows)
    logger.info("chartink webhook: scan=%s matched=%s hits=%d",
                chartink_name, matched, written)
    return {
        "ok": True,
        "scan_name_chartink": chartink_name,
        "scan_name_internal": final_scan_name,
        "matched_to_saved_config": bool(matched),
        "rows_written": written,
        "stocks": stocks[:50],
    }


@router.get("/chartink/webhook-info")
async def admin_webhook_info(request: Request):
    """Admin: fetch (or generate on first call) the webhook URL + token
    that should be pasted into each Chartink alert. Includes per-scan
    setup hints so the matcher hits cleanly."""
    await require_admin(request)
    token = await scan_config.ensure_webhook_token(db)
    base = str(request.base_url).rstrip("/")
    saved = await scan_config.load(db)
    return {
        "webhook_url": f"{base}/api/positional/chartink/webhook?token={token}",
        "token": token,
        "method": "POST",
        "configured_scans": [s["name"] for s in saved],
        "instructions": [
            "On chartink.com, open each scan you want to track",
            "Click 'Create/Modify Alert'",
            "In the alert dialog, set Webhook URL = the URL above",
            "Save the alert. Chartink will POST when the scan triggers",
            "scan_name in your alert will auto-match to internal names "
            "(e.g. 'TODAYS TOP BUY' → 'atlas.todays_top_buy')",
        ],
    }


@router.post("/chartink/webhook-info/rotate")
async def admin_rotate_webhook_token(request: Request):
    """Admin: rotate the webhook token. Existing Chartink alerts using
    the old URL will start 401-ing — admin must re-paste."""
    await require_admin(request)
    token = await scan_config.rotate_webhook_token(db)
    base = str(request.base_url).rstrip("/")
    return {
        "webhook_url": f"{base}/api/positional/chartink/webhook?token={token}",
        "token": token,
        "warning": "Old token revoked. Update every Chartink alert with the new URL.",
    }


@router.post("/backtest/label")
async def admin_backtest_label(request: Request,
                                max_symbols: Optional[int] = None,
                                step_days: int = 1):
    """Admin: sweep stock_ohlcv, replay accumulation detector at every
    eligible (symbol, scan_date), persist labels with forward returns."""
    await require_admin(request)
    return await backtest.label_universe(max_symbols=max_symbols, step_days=step_days)


@router.post("/backtest/calibrate")
async def admin_backtest_calibrate(request: Request):
    """Admin: rebuild accumulation_calibration from labelled rows."""
    await require_admin(request)
    return await backtest.calibrate()


# ── Historical validation table (PRD §7.6, matrix B13) ───────────────────
# What each calibration figure is, worded from the constants the labeller uses
# (services/positional_engine/backtest.py), so the definition follows the code.
# Every metric is a TOUCH outcome — an intraday high within the horizon — and is
# shown on its own row; the three are never blended into one hit rate.
_CALIBRATION_METRICS = {
    "broke_high": {
        "label": "Broke its 20-session high",
        "outcome_type": "touch",
        "rule": ("Within the horizon, any session's intraday high went above the 20-session high the stock had "
                 "on the scan day (the level it had not yet broken)."),
    },
    "moved_scaled": {
        "label": "Rose by its scaled threshold",
        "outcome_type": "touch",
        "rule": (f"Within the horizon, the highest intraday high was at least max({backtest.MIN_SCALED_MOVE_PCT:g}%, "
                 f"{backtest.SCALED_MOVE_ATR_MULT:g} × ATR% of the scan day) above the scan-day close."),
    },
    "moved_5pct": {
        "label": f"Rose {backtest.MOVE_THRESHOLD_PCT:g}%",
        "outcome_type": "touch",
        "rule": (f"Within the horizon, the highest intraday high was at least {backtest.MOVE_THRESHOLD_PCT:g}% above "
                 "the scan-day close (the v1 label, kept for comparison)."),
    },
}
_CALIBRATION_MEASURES = {
    "probability": "Hit rate: the share of labelled scans in the bucket where the outcome happened within the horizon.",
    "avg_fwd_return": ("Mean maximum favourable excursion: the highest intraday high within the horizon against the "
                       "scan-day close, in percent, averaged over the bucket. It is not an average realised return."),
    "avg_fwd_drawdown": ("Mean maximum adverse excursion: the lowest intraday low within the horizon against the "
                         "scan-day close, in percent, averaged over the bucket."),
    "horizon_days": "Holding period: the number of sessions after the scan day that are checked.",
    "ci95": "95% Wilson interval for the hit rate, from sample_count and moves_count.",
}
_CALIBRATION_NOT_MEASURED = {
    "median_return": "Not stored: the labeller keeps each scan's maximum excursion, not a realised exit return.",
    "costs": "None applied: the labels are price-only, with no brokerage, slippage or taxes.",
    "benchmark": "None: the labels are not compared with an index over the same sessions.",
    "out_of_sample": ("None: the buckets are fitted on every labelled scan; no later period is held out. "
                      "Treat the hit rates as in-sample."),
}


def _wilson_ci(moves: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson score interval for `moves` hits in `n` trials, as (lo, hi) fractions; (None, None) without a sample."""
    import math
    if not n:
        return (None, None)
    p = moves / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def _num(v):
    """A NUMERIC column as a float (asyncpg returns Decimal), None kept."""
    return None if v is None else float(v)


@router.get("/backtest/calibration")
async def get_calibration(request: Request,
                          metric: Optional[str] = Query(None, pattern=r"^(broke_high|moved_scaled|moved_5pct)$"),
                          horizon_days: Optional[int] = Query(None),
                          symbol: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9&\-]{1,32}$")):
    """Public (auth): the accumulation detector's bucketed historical record (accumulation_calibration).

    Each row: one score bucket × one horizon × one outcome metric, with its sample size, hit rate and a 95% Wilson
    interval, mean favourable and adverse excursions. `metrics` defines every outcome (all are intraday touches),
    `measures` says what each column is, `not_measured` names what this table does not hold and why, and `sample`
    is the labelled period. `?symbol=` adds the stock's latest accumulation score and marks the bucket rows it
    falls in (`matched`). Filters: `metric`, `horizon_days` (5, 10 or 20).
    """
    await get_current_user(request)
    if horizon_days is not None and horizon_days not in backtest.HORIZONS:
        raise HTTPException(status_code=422, detail=f"horizon_days must be one of {backtest.HORIZONS}")
    base = {
        "metrics": _CALIBRATION_METRICS,
        "measures": _CALIBRATION_MEASURES,
        "not_measured": _CALIBRATION_NOT_MEASURED,
        "source": "accumulation_calibration (positional engine Postgres), from POST /api/positional/backtest/calibrate",
        "method": ("services/positional_engine/backtest.py: each (symbol, scan date) is replayed with the bars known "
                   "that day, then the next 5 / 10 / 20 sessions are checked; scans are bucketed by accumulation score."),
    }
    pool = await pg_client.get_pool()
    if pool is None:
        return {**base, "buckets": [], "count": 0, "_reason": "no_pg_pool"}
    where, args = [], []
    if metric:
        args.append(metric)
        where.append(f"metric = ${len(args)}")
    if horizon_days is not None:
        args.append(horizon_days)
        where.append(f"horizon_days = ${len(args)}")
    sql = ("SELECT metric, bucket_lo, bucket_hi, horizon_days, sample_count, moves_count, probability, "
           "avg_fwd_return, avg_fwd_drawdown, refreshed_at FROM accumulation_calibration "
           + (("WHERE " + " AND ".join(where) + " ") if where else "")
           + "ORDER BY metric, horizon_days, bucket_lo")
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
    except Exception as e:  # noqa: BLE001
        return {**base, "buckets": [], "count": 0, "_reason": str(e)[:200]}

    out = {**base, "sample": None, "symbol_score": None}

    # The labelled period behind the table.
    try:
        async with pool.acquire() as conn:
            s = await conn.fetchrow(
                "SELECT MIN(scan_date) AS first_scan, MAX(scan_date) AS last_scan, COUNT(*) AS n, "
                "ARRAY_AGG(DISTINCT engine_version) FILTER (WHERE engine_version IS NOT NULL) AS versions "
                "FROM positional_backtest_labels"
            )
        if s and s["n"]:
            out["sample"] = {
                "first_scan_date": s["first_scan"].isoformat() if s["first_scan"] else None,
                "last_scan_date": s["last_scan"].isoformat() if s["last_scan"] else None,
                "labelled_rows": int(s["n"]),
                "engine_versions": sorted(s["versions"] or []),
            }
        else:
            out["sample_reason"] = "No labelled scans on record (positional_backtest_labels is empty)."
    except Exception as e:  # noqa: BLE001
        out["sample_reason"] = f"The labelled period could not be read: {str(e)[:120]}"

    # The stock's latest accumulation score, when asked.
    score = None
    if symbol:
        sym = symbol.upper()
        try:
            async with pool.acquire() as conn:
                r = await conn.fetchrow(
                    "SELECT as_of_date, (components->'pre_breakout'->>'accumulation_score')::float AS score "
                    "FROM stock_technical_features WHERE nse_symbol = $1 "
                    "AND components->'pre_breakout'->>'accumulation_score' IS NOT NULL "
                    "ORDER BY as_of_date DESC LIMIT 1",
                    sym,
                )
            if r and r["score"] is not None:
                score = float(r["score"])
                out["symbol_score"] = {"symbol": sym, "as_of_date": r["as_of_date"].isoformat(),
                                       "accumulation_score": score}
            else:
                out["symbol_reason"] = (f"No accumulation score on record for {sym} (stock_technical_features is empty for it). "
                                        "It is filled by the positional engine: python -m scripts.run_positional_engine.")
        except Exception as e:  # noqa: BLE001
            out["symbol_reason"] = f"The accumulation score could not be read: {str(e)[:120]}"

    buckets = []
    for r in rows:
        d = dict(r)
        lo_b, hi_b = _num(d.get("bucket_lo")), _num(d.get("bucket_hi"))
        n, k = int(d.get("sample_count") or 0), int(d.get("moves_count") or 0)
        ci_lo, ci_hi = _wilson_ci(k, n)
        refreshed = d.get("refreshed_at")
        buckets.append({
            "metric": d.get("metric"),
            "bucket_lo": lo_b, "bucket_hi": hi_b,
            "horizon_days": d.get("horizon_days"),
            "sample_count": n, "moves_count": k,
            "probability": _num(d.get("probability")),
            "avg_fwd_return": _num(d.get("avg_fwd_return")),
            "avg_fwd_drawdown": _num(d.get("avg_fwd_drawdown")),
            "ci95_lo": ci_lo, "ci95_hi": ci_hi,
            "refreshed_at": refreshed.isoformat() if hasattr(refreshed, "isoformat") else refreshed,
            "matched": bool(score is not None and lo_b is not None and hi_b is not None and lo_b <= score < hi_b),
        })
    out["buckets"] = buckets
    out["count"] = len(buckets)
    if not buckets:
        out["empty_reason"] = ("No calibration rows on record: the accumulation backtest (POST "
                               "/api/positional/backtest/label, then /backtest/calibrate) has not been run here. It replays "
                               "stock_ohlcv, which the positional engine's bhavcopy step fills (python -m "
                               "scripts.run_positional_engine, one date at a time).")
    return out


# ── Market Dashboard (gating layer) + default ChartInk scan seeding ─────
# Cache TTL adapts to market hours: 30s while NSE is open (so the live
# overlay refreshes ~once per page load), 5min after-hours.
_MARKET_DASH_CACHE: dict = {"ts": 0.0, "data": None}


def _md_cache_ttl() -> float:
    from services.positional_engine import nse_live as _nl
    return 30.0 if _nl._is_market_open_ist() else 300.0


@router.get("/market-dashboard")
async def market_dashboard(request: Request):
    """Returns Nifty / breadth / sector heatmap / VIX / macro + a single
    deploy verdict (AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE).

    Live data overlay (NSE allIndices) for Nifty/VIX/sectors/AD when
    market is open. Cached 30s during market hours, 5min after-hours.
    Auto-triggers a macro_state refresh when stale > 1 day so the lower
    Macro Context panel never lags behind the live verdict.
    Gating layer for the BTST framework — answers "is today a green-light
    day to deploy aggressively, or a sit-on-hands day?"."""
    await get_current_user(request)
    import time
    from datetime import date as _date
    now = time.time()

    # Auto-refresh stale macro_state (best-effort, non-blocking on failure).
    # Avoid hitting on every request — gate via a separate cache.
    if not _MARKET_DASH_CACHE.get("macro_checked_today") == _date.today():
        try:
            from services import macro_engine
            st = await macro_engine.latest_state()
            stale_days = None
            if st and st.get("date"):
                from datetime import datetime as _dt
                try:
                    sd = _dt.fromisoformat(str(st["date"]).split("T")[0]).date()
                    stale_days = (_date.today() - sd).days
                except (ValueError, TypeError):
                    stale_days = None
            if stale_days is None or stale_days >= 1:
                logger.info("market_dashboard: macro_state stale (%s days) — refreshing", stale_days)
                await macro_engine.classify_regime(_date.today())
                _MARKET_DASH_CACHE["data"] = None  # invalidate so verdict picks up fresh macro
        except Exception as e:  # noqa: BLE001
            logger.debug("auto macro refresh failed: %s", e)
        _MARKET_DASH_CACHE["macro_checked_today"] = _date.today()

    if _MARKET_DASH_CACHE["data"] and (now - _MARKET_DASH_CACHE["ts"]) < _md_cache_ttl():
        return {**_MARKET_DASH_CACHE["data"], "_cache_hit": True}
    from services.positional_engine import market_dashboard as md
    try:
        data = await md.build()
    except Exception as e:  # noqa: BLE001
        logger.error("market_dashboard build failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}
    if data.get("ok"):
        _MARKET_DASH_CACHE["ts"] = now
        _MARKET_DASH_CACHE["data"] = data
    return data


# Built-in defaults aligned to the user's BTST framework. Admin can
# override these via the existing `/scans/config` PUT, but seeding them
# first means a fresh deploy already has 4 useful gates.
DEFAULT_BTST_SCANS = [
    {
        "name": "btst.early_accumulation",
        "clause": (
            "( {cash} ( latest close > latest sma( close,50 ) "
            "and latest close > latest sma( close,200 ) "
            "and 15 days max( high ) - 15 days min( low ) <= latest close * 0.08 "
            "and latest volume <= latest sma( volume,20 ) "
            "and latest rsi( 14 ) >= 50 and latest rsi( 14 ) <= 65 ) )"
        ),
        "enabled": True,
    },
    {
        "name": "btst.breakout_confirmation",
        "clause": (
            "( {cash} ( latest close > 20 days max( high,1 ) "
            "and latest volume >= 1.5 * latest sma( volume,20 ) "
            "and latest close > latest sma( close,50 ) ) )"
        ),
        "enabled": True,
    },
    {
        "name": "btst.sector_leaders_rs",
        "clause": (
            "( {cash} ( latest close > latest sma( close,50 ) "
            "and 1 month ago return > 5 "
            "and 3 months ago return > 10 "
            "and latest volume > latest sma( volume,20 ) ) )"
        ),
        "enabled": True,
    },
    {
        "name": "btst.exit_warning_distribution",
        "clause": (
            "( {cash} ( latest close < latest sma( close,20 ) "
            "and latest volume >= 1.5 * latest sma( volume,20 ) "
            "and 5 days max( high ) - latest close >= latest close * 0.05 ) )"
        ),
        "enabled": True,
    },
]


@router.post("/scans/seed-defaults")
async def admin_seed_default_scans(request: Request,
                                    overwrite: bool = Query(False)):
    """Admin: seed the 4 BTST framework scans (early-accumulation,
    breakout-confirmation, sector-leaders-RS, exit-warning) into
    scan_config. By default only adds those NOT already present (won't
    touch your existing custom scans). Pass overwrite=true to replace
    the default-named scans even if they exist."""
    await require_admin(request)
    existing = await scan_config.load(db)
    by_name = {s["name"]: s for s in existing}
    added: list = []
    skipped: list = []
    for d in DEFAULT_BTST_SCANS:
        if d["name"] in by_name and not overwrite:
            skipped.append(d["name"])
            continue
        by_name[d["name"]] = d
        added.append(d["name"])
    saved = await scan_config.save(db, list(by_name.values()))
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "total_scans": len(saved),
    }



# ── Pro Trader Module ─────────────────────────────────────────────────────

from pydantic import BaseModel as _PM, Field as _F  # noqa: E402


class BasketRequest(_PM):
    capital_rs: float = _F(gt=0, description="Total capital to deploy in INR (e.g. 1000000 for ₹10L)")
    max_positions: int = _F(default=8, ge=1, le=20)
    min_conviction: str = _F(default="HIGH_CONVICTION")


class SimulateRequest(_PM):
    basket: list = _F(description="Basket items from POST /basket — list of position dicts")
    horizon_days: int = _F(default=10, ge=5, le=20)


def _size_position(
    capital_rs: float,
    max_positions: int,
    entry: float,
    stoploss: float,
    position_size_factor: float,
) -> dict:
    """Compute qty, allocated_rs, risk_rs for one position.

    Base allocation = capital_rs / max_positions, scaled by position_size_factor.
    Max risk per position = 2% of capital (risk control floor), and that risk is the loss at the stop AFTER the
    estimated round-trip costs (services/desk_trading.max_units_within_budget, the cost model a paper trade records).
    The cap always applies: a stop so wide that no whole share fits gives qty 0, never 1 (it used to force
    `max(1, ...)` and skip the cap when the cap was 0, so one share could exceed the 2% limit).
    Returns dict with qty, allocated_rs, risk_rs (loss at the stop after costs), risk_gross_rs, risk_pct, risk_basis.
    """
    import math
    from services import desk_trading as _desk
    base = capital_rs / max_positions
    adjusted = base * position_size_factor
    risk_per_share = entry - stoploss
    if risk_per_share <= 0 or entry <= 0:
        return {"qty": 0, "allocated_rs": 0.0, "risk_rs": 0.0, "risk_gross_rs": 0.0, "risk_pct": 0.0,
                "risk_basis": _BASKET_RISK_BASIS}

    qty = max(0, math.floor(adjusted / entry))
    qty = min(qty, _desk.max_units_within_budget(capital_rs * 0.02, entry, stoploss))

    allocated = round(qty * entry, 2)
    gross = round(qty * risk_per_share, 2)
    risk_rs = round(gross + _desk.round_trip_cost(qty, entry, stoploss), 2) if qty else 0.0
    risk_pct = round(risk_rs / capital_rs * 100, 2) if capital_rs > 0 else 0.0
    return {"qty": qty, "allocated_rs": allocated, "risk_rs": risk_rs, "risk_gross_rs": gross, "risk_pct": risk_pct,
            "risk_basis": _BASKET_RISK_BASIS}


_BASKET_RISK_BASIS = ("loss at the stop after estimated round-trip costs (the desk cost card: brokerage, STT, exchange "
                      "charge, SEBI fee, stamp duty, GST and slippage; DP charges and income tax not included)")


# ── Trade scenario calculator (PRD §8.5 and §8.6; desk default D6) ────────
# The one sizing rule the Smart trading desk uses for a single idea, beside the
# basket's `_size_position` above (that one splits capital over a basket; this
# one sizes one trade from a risk budget). Pure: nothing is stored, nothing is
# sent to a broker. Costs use the strategy_engine backtest's own defaults so a
# scenario and a backtest charge the same: slippage per side + flat brokerage per side.

from services.strategy_engine.backtest import (  # noqa: E402
    DEFAULT_BROKERAGE_INR as _SE_BROKERAGE_INR,
    DEFAULT_SLIPPAGE_PCT as _SE_SLIPPAGE_FRACTION,
)

_SCENARIO_CAVEATS = (
    "A stop price does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, "
    "so the loss can be larger than shown.",
    "Costs are estimates from the desk cost card, the model a paper trade records: brokerage (a desk assumption of ₹20 "
    "a side, not a broker's tariff), STT, exchange charge, SEBI fee, stamp duty, GST, and slippage of 0.05% a side that "
    "also stands in for the spread; DP charges and income tax are not included.",
    "Illustrative only: nothing is sent to a broker and no order is placed.",
)
_SCENARIO_METHOD = (
    "PRD §8.5, long only: risk per share = entry − stop; reward per share = target − entry; reward : risk = reward ÷ "
    "risk; quantity = the most shares whose loss at the stop AFTER the entry and stop-exit costs stays within the risk "
    "budget; then capped by floor(capital × max allocation % ÷ entry) and the maximum quantity, and rounded down to the "
    "lot size. Costs per side = brokerage + STT + exchange charge + SEBI fee + stamp duty (buy) + GST + traded value × "
    "slippage % (the desk cost card, equity delivery); net loss at the stop = gross loss + entry and stop-exit costs; "
    "net profit at the target = gross profit − entry and target-exit costs. Portfolio weights assume the buy is new "
    "money added to the portfolio."
)


def _scenario_problem(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def _trade_scenario(*, entry: float, stop: float, target: Optional[float] = None,
                    capital: Optional[float] = None, risk_pct: Optional[float] = None,
                    risk_budget: Optional[float] = None, max_alloc_pct: float = 25.0,
                    slippage_pct: Optional[float] = None, brokerage_per_side: Optional[float] = None,
                    max_qty: Optional[int] = None, lot_size: int = 1,
                    portfolio_value: Optional[float] = None, existing_value: Optional[float] = None,
                    sector_value: Optional[float] = None) -> dict:
    """One long trade scenario. Prices in rupees; `risk_pct`, `max_alloc_pct` and `slippage_pct` in percent units.

    Direction problems (a stop at or above the entry, a target at or below it) and a missing risk budget come back
    as `valid: false` with `problems` — never a division by zero and never a partial figure.
    """
    import math

    slip_pct = _SE_SLIPPAGE_FRACTION * 100 if slippage_pct is None else float(slippage_pct)
    brokerage = _SE_BROKERAGE_INR if brokerage_per_side is None else float(brokerage_per_side)
    from services import desk_cost_card as _card
    from services import desk_trading as _desk
    # The desk cost card (the model a paper trade records): the request may change the slippage and the brokerage; the
    # statutory charges (STT, exchange, SEBI, stamp, GST) always apply.
    desk_model = {**_desk.COST_MODEL, "slippage_pct_per_side": slip_pct, "brokerage_rs_per_side": brokerage}
    cost_model = {
        "version": _card.VERSION,
        "slippage_pct_per_side": slip_pct,
        "brokerage_inr_per_side": brokerage,
        "statutory": _card.SNAPSHOT["statutory"] + ", equity delivery rates",
        "brokerage_basis": _card.SNAPSHOT["brokerage_basis"],
        "slippage_basis": _card.SNAPSHOT["slippage_basis"],
        "default": slippage_pct is None and brokerage_per_side is None,
        "source": "services/desk_cost_card.py (the desk cost card), services/strategy_engine/backtest.py (the default slippage and brokerage)",
    }
    budget = risk_budget if risk_budget is not None else (
        capital * risk_pct / 100.0 if capital is not None and risk_pct is not None else None)
    base = {
        "side": "long",
        "inputs": {
            "entry": entry, "stop": stop, "target": target, "capital": capital, "risk_pct": risk_pct,
            "risk_budget": risk_budget, "max_alloc_pct": max_alloc_pct, "slippage_pct": slip_pct,
            "brokerage_per_side": brokerage, "max_qty": max_qty, "lot_size": lot_size,
            "portfolio_value": portfolio_value, "existing_value": existing_value, "sector_value": sector_value,
        },
        "cost_model": cost_model,
        "method": _SCENARIO_METHOD,
        "caveats": list(_SCENARIO_CAVEATS),
        "sent_to_broker": False,
    }

    problems = []
    if not (entry > 0):
        problems.append(_scenario_problem("entry", "entry_not_positive", "The entry must be a price above zero."))
    if not (stop > 0):
        problems.append(_scenario_problem("stop", "stop_not_positive", "The stop must be a price above zero."))
    if entry > 0 and stop > 0 and not (stop < entry):
        problems.append(_scenario_problem(
            "stop", "stop_not_below_entry",
            f"For a long position the stop (₹{stop:,.2f}) must be below the entry (₹{entry:,.2f})."))
    if target is not None and not (target > entry):
        problems.append(_scenario_problem(
            "target", "target_not_above_entry",
            f"For a long position the target (₹{target:,.2f}) must be above the entry (₹{entry:,.2f})."))
    if budget is None or not (budget > 0):
        problems.append(_scenario_problem(
            "risk", "needs_capital_or_risk_budget",
            "Give a risk budget in rupees, or a capital with a risk per trade."))
    if problems:
        return {**base, "valid": False, "problems": problems, "warnings": [],
                "per_share": None, "sizing": None, "costs": None, "outcomes": None, "portfolio": None}

    eps = 1e-9   # absorbs float noise in a quotient that should be whole, so floor never drops a share
    risk_ps = entry - stop
    reward_ps = (target - entry) if target is not None else None
    per_share = {
        "risk": round(risk_ps, 4),
        "reward": round(reward_ps, 4) if reward_ps is not None else None,
        "reward_to_risk": round(reward_ps / risk_ps, 4) if reward_ps is not None else None,
    }

    # Sized so the loss at the stop INCLUDING the round-trip costs stays within the budget (gate 4). It used to be
    # floor(budget / risk per share), so the net loss could exceed the budget (PRD Example A: 85 shares, ₹3,098.94 > ₹3,000).
    qty_risk = _desk.max_units_within_budget(budget, entry, stop, model=desk_model)
    qty_alloc = math.floor(capital * max_alloc_pct / 100.0 / entry + eps) if capital is not None else None
    limits = [("risk_budget", qty_risk), ("max_allocation", qty_alloc), ("max_qty", max_qty)]
    binding, qty = min(((k, q) for k, q in limits if q is not None), key=lambda kq: kq[1])
    if lot_size > 1:
        lots = (qty // lot_size) * lot_size
        if lots != qty:
            binding, qty = "lot_size", lots
    gross = qty * entry
    sizing = {
        "risk_budget": round(budget, 2),
        "qty_by_risk": qty_risk,
        "qty_by_allocation": qty_alloc,
        "qty_by_max": max_qty,
        "lot_size": lot_size,
        "quantity": qty,
        "binding": binding,
        "gross_exposure": round(gross, 2),
        "allocation_pct": round(gross / capital * 100.0, 6) if capital else None,
        "max_alloc_pct": max_alloc_pct,
        "risk_basis": "the loss at the stop after the entry and stop-exit costs fits the risk budget",
    }

    warnings = []
    costs = outcomes = None
    if qty == 0:
        warnings.append(_scenario_problem(
            "risk", "no_whole_share",
            f"The risk budget (₹{budget:,.2f}) does not cover one share's risk (₹{risk_ps:,.2f}) plus the round-trip "
            f"costs at the stop, so no whole share fits."))
    else:
        at_stop = _card.round_trip("equity_delivery", qty, entry, stop, model=desk_model)
        at_target = _card.round_trip("equity_delivery", qty, entry, target, model=desk_model) if target is not None else None
        rt_stop = at_stop["total"]["total"]
        rt_target = at_target["total"]["total"] if at_target else None
        costs = {
            "entry": at_stop["entry"]["total"],
            "exit_at_stop": at_stop["exit"]["total"],
            "exit_at_target": at_target["exit"]["total"] if at_target else None,
            "round_trip_at_stop": rt_stop,
            "round_trip_at_target": rt_target,
            "breakdown_at_stop": at_stop["total"],
        }
        loss = qty * risk_ps
        profit = qty * reward_ps if reward_ps is not None else None
        outcomes = {
            "loss_at_stop": round(loss, 2),
            "loss_at_stop_net": round(loss + rt_stop, 2),
            "profit_at_target": round(profit, 2) if profit is not None else None,
            "profit_at_target_net": round(profit - rt_target, 2) if profit is not None else None,
        }

    portfolio = None
    if portfolio_value is not None and portfolio_value > 0:
        ex = existing_value or 0.0
        after_total = portfolio_value + gross
        portfolio = {
            "portfolio_value": round(portfolio_value, 2),
            "stock_weight_before_pct": round(ex / portfolio_value * 100.0, 6),
            "stock_weight_after_pct": round((ex + gross) / after_total * 100.0, 6),
            "stock_weight_change_pct": round((ex + gross) / after_total * 100.0 - ex / portfolio_value * 100.0, 6),
            "sector_weight_before_pct": round(sector_value / portfolio_value * 100.0, 6) if sector_value is not None else None,
            "sector_weight_after_pct": (round((sector_value + gross) / after_total * 100.0, 6)
                                        if sector_value is not None else None),
            "impact_at_stop_pct": (round(-outcomes["loss_at_stop_net"] / portfolio_value * 100.0, 6)
                                   if outcomes else None),
            "impact_at_target_pct": (round(outcomes["profit_at_target_net"] / portfolio_value * 100.0, 6)
                                     if outcomes and outcomes["profit_at_target_net"] is not None else None),
            "assumption": "The buy is new money added to the portfolio; weights are of the portfolio after the buy.",
        }

    return {**base, "valid": True, "problems": [], "warnings": warnings, "per_share": per_share,
            "sizing": sizing, "costs": costs, "outcomes": outcomes, "portfolio": portfolio}


@router.get("/scenario")
async def trade_scenario(request: Request,
                         entry: float = Query(..., gt=0, description="Reference entry price, ₹"),
                         stop: float = Query(..., gt=0, description="Stop-loss price, ₹ (below the entry)"),
                         target: Optional[float] = Query(None, gt=0, description="Target price, ₹ (above the entry)"),
                         capital: Optional[float] = Query(None, gt=0, description="Available capital, ₹"),
                         risk_pct: Optional[float] = Query(None, gt=0, le=100, description="Risk per trade, % of capital"),
                         risk_budget: Optional[float] = Query(None, gt=0, description="Risk budget, ₹ (instead of capital × risk %)"),
                         max_alloc_pct: float = Query(25.0, gt=0, le=100, description="Largest share of capital in this stock, %"),
                         slippage_pct: Optional[float] = Query(None, ge=0, le=5, description="Slippage per side, %"),
                         brokerage_per_side: Optional[float] = Query(None, ge=0, le=100_000, description="Brokerage per side, ₹"),
                         max_qty: Optional[int] = Query(None, ge=1, description="Most shares allowed"),
                         lot_size: int = Query(1, ge=1, description="Shares per lot; the quantity is a whole number of lots"),
                         portfolio_value: Optional[float] = Query(None, gt=0, description="Portfolio value, ₹ (§8.6)"),
                         existing_value: Optional[float] = Query(None, ge=0, description="Value already held in this stock, ₹"),
                         sector_value: Optional[float] = Query(None, ge=0, description="Value already held in its sector, ₹"),
                         side: str = Query("long", pattern=r"^long$", description="Long only: the desk has no short trades")):
    """GET /api/positional/scenario — the trade scenario calculator (PRD §8.5) with its portfolio impact (§8.6).

    A read: it computes from the query and stores nothing; nothing is sent to a broker (`sent_to_broker: false`).
    Malformed numbers are 422; a price in the wrong direction is a 200 with `valid: false` and `problems`, so the
    screen can say which field is wrong.
    """
    await get_current_user(request)
    return _trade_scenario(
        entry=entry, stop=stop, target=target, capital=capital, risk_pct=risk_pct, risk_budget=risk_budget,
        max_alloc_pct=max_alloc_pct, slippage_pct=slippage_pct, brokerage_per_side=brokerage_per_side,
        max_qty=max_qty, lot_size=lot_size, portfolio_value=portfolio_value, existing_value=existing_value,
        sector_value=sector_value,
    )


@router.post("/basket")
async def build_basket(request: Request, body: BasketRequest):
    """Pro Trader: build a capital-allocated basket from today's best picks.

    Filters to HIGH_CONVICTION (or caller-specified tier) + TRIGGERED/NEAR
    readiness, applies macro position sizing, fetches ATM put hedge cost per
    stock from NIDP F&O data, and returns a fully sized basket.

    Response:
      deploy_verdict  AGGRESSIVE | NORMAL | CAUTIOUS | DEFENSIVE
      basket[]        symbol, entry/SL/target, qty, allocated_rs, risk_rs, hedge
      summary         total_deployed, total_risk_rs, portfolio_max_loss_pct,
                      hedge_total_cost_rs
    """
    await get_current_user(request)
    import asyncio as _asyncio

    sig_date = await _latest_signal_date()
    if sig_date is None:
        return {"deploy_verdict": None, "basket": [], "summary": {}, "message": "no signals yet"}

    # Fetch all picks and enrich with live prices + conviction
    raw_picks = await _fetch_picks(sig_date, min_score=0.5, stage=None, limit=50)
    picks = await _enrich_with_live(raw_picks)

    # Filter by conviction tier + TRIGGERED/NEAR readiness
    target_conviction = body.min_conviction.upper()
    actionable_readiness = {"TRIGGERED", "NEAR"}
    filtered = [
        p for p in picks
        if (p.get("conviction") or {}).get("verdict") == target_conviction
        and (p.get("readiness") or "UNKNOWN") in actionable_readiness
    ]
    # Fallback: if no TRIGGERED/NEAR, relax to any WAIT too
    if not filtered:
        filtered = [
            p for p in picks
            if (p.get("conviction") or {}).get("verdict") == target_conviction
        ]
    # Trim to max_positions
    filtered = filtered[:body.max_positions]

    # Get macro state for deploy verdict + position sizing
    macro_risk = "MEDIUM"
    deploy_verdict_data: dict = {"verdict": "NORMAL", "reason": ""}
    try:
        from services import macro_engine
        st = await macro_engine.latest_state()
        macro_risk = (st or {}).get("risk") or "MEDIUM"
    except Exception as e:  # noqa: BLE001
        logger.debug("basket: macro_engine unavailable (%s)", e)

    try:
        from services.positional_engine import market_dashboard as _md
        dash = await _md.build()
        deploy_verdict_data = (dash or {}).get("deploy_verdict") or deploy_verdict_data
    except Exception as e:  # noqa: BLE001
        logger.debug("basket: market_dashboard unavailable (%s)", e)

    # Get sector modifiers for all symbols
    syms = [p["nse_symbol"] for p in filtered]
    try:
        from services.positional_engine.macro_overlay import (
            sector_modifiers_for_universe,
            position_size_factor as _psf,
        )
        sector_mods = await sector_modifiers_for_universe(syms, sig_date)
    except Exception as e:  # noqa: BLE001
        logger.debug("basket: sector_modifiers failed (%s)", e)
        sector_mods = {}
        from services.positional_engine.macro_overlay import position_size_factor as _psf

    from services.positional_engine import hedge_planner

    basket: list = []
    total_deployed = 0.0
    total_risk = 0.0
    total_hedge_cost = 0.0

    for p in filtered:
        sym = p["nse_symbol"]
        entry = float(p.get("entry_price") or 0)
        sl = float(p.get("stoploss") or 0)
        target = float(p.get("target_price") or 0)
        rr = float(p.get("risk_reward") or 0)

        if entry <= 0 or sl <= 0:
            continue

        sector_mod = sector_mods.get(sym, 0.0)
        psf = _psf(risk=macro_risk, sector_modifier=sector_mod)

        sizing = _size_position(body.capital_rs, body.max_positions, entry, sl, psf)
        if sizing["qty"] == 0:
            continue

        # Hedge cost — best-effort, non-blocking
        try:
            hedge = await _asyncio.wait_for(
                hedge_planner.get_atm_put_cost(sym, entry),
                timeout=4.0,
            )
        except Exception:  # noqa: BLE001
            hedge = None

        total_deployed += sizing["allocated_rs"]
        total_risk += sizing["risk_rs"]
        if hedge:
            total_hedge_cost += hedge.get("cost_rs") or 0.0

        basket.append({
            "symbol":            sym,
            "stage":             p.get("stage"),
            "conviction_verdict": (p.get("conviction") or {}).get("verdict"),
            "readiness":         p.get("readiness"),
            "live_price":        p.get("live_price"),
            "entry_price":       entry,
            "stoploss":          sl,
            "target_price":      target,
            "risk_reward":       rr,
            "horizon_days_min":  p.get("timeframe_days_min"),
            "horizon_days_max":  p.get("timeframe_days_max"),
            "reasons":           p.get("reasons") or [],
            "qty":               sizing["qty"],
            "allocated_rs":      sizing["allocated_rs"],
            "risk_rs":           sizing["risk_rs"],
            "risk_pct":          sizing["risk_pct"],
            "risk_basis":        sizing["risk_basis"],
            "position_size_factor": psf,
            "hedge":             hedge,
            "signal_date":       str(sig_date),
            "accumulation_score": (
                ((p.get("pre_breakout") or {}).get("accumulation_score")) or None
            ),
        })

    portfolio_max_loss_pct = round(total_risk / body.capital_rs * 100, 2) if body.capital_rs > 0 else 0.0

    return {
        "signal_date": str(sig_date),
        "deploy_verdict": deploy_verdict_data,
        "basket": basket,
        "summary": {
            "capital_rs": body.capital_rs,
            "total_deployed": round(total_deployed, 2),
            "cash_remaining": round(body.capital_rs - total_deployed, 2),
            "total_risk_rs": round(total_risk, 2),
            "portfolio_max_loss_pct": portfolio_max_loss_pct,
            "hedge_total_cost_rs": round(total_hedge_cost, 2),
            "hedge_cost_pct_of_capital": round(total_hedge_cost / body.capital_rs * 100, 2) if body.capital_rs > 0 else 0.0,
            "positions": len(basket),
        },
    }


@router.post("/basket/simulate")
async def simulate_basket(request: Request, body: SimulateRequest):
    """Pro Trader: simulate BASE / BULL / BEAR P&L + drawdown for a basket.

    Uses `accumulation_calibration` (empirical hit-rate table) for each
    position's accumulation_score → probability + avg return + avg drawdown.
    Falls back to positional_backtest_labels per-symbol averages when the
    calibration row is missing.

    Scenarios:
      BASE  avg_fwd_return × probability,  avg_fwd_drawdown
      BULL  avg_fwd_return × 1.4,          avg_fwd_drawdown × 0.5
      BEAR  avg_fwd_return × 0.3,          avg_fwd_drawdown × 2.0
    """
    await get_current_user(request)
    if not body.basket:
        return {"horizon_days": body.horizon_days, "scenarios": {}, "per_position": []}

    pool = await pg_client.get_pool()
    horizon = body.horizon_days

    per_position: list = []
    for item in body.basket:
        sym = (item.get("symbol") or "").upper()
        allocated = float(item.get("allocated_rs") or 0)
        accum_score = item.get("accumulation_score")

        prob: float = 0.5
        avg_ret: float = 0.05
        avg_dd: float = 0.04

        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    # Try calibration table first
                    if accum_score is not None:
                        cal = await conn.fetchrow(
                            """
                            SELECT probability, avg_fwd_return, avg_fwd_drawdown
                            FROM accumulation_calibration
                            WHERE metric = 'broke_high'
                              AND horizon_days = $1
                              AND $2 >= bucket_lo AND $2 < bucket_hi
                            ORDER BY sample_count DESC LIMIT 1
                            """,
                            horizon, float(accum_score),
                        )
                        if cal and cal["probability"] is not None:
                            prob = float(cal["probability"])
                            avg_ret = float(cal["avg_fwd_return"] or 0.05)
                            avg_dd = float(cal["avg_fwd_drawdown"] or 0.04)

                    # Also pull label-based per-symbol stats as cross-check
                    col_ret = f"fwd_max_return_{min(horizon, 20) if horizon >= 20 else (10 if horizon >= 10 else 5)}d"
                    col_dd = f"fwd_max_drawdown_{min(horizon, 20) if horizon >= 20 else (10 if horizon >= 10 else 5)}d"
                    label_row = await conn.fetchrow(
                        f"""
                        SELECT AVG({col_ret}) as avg_ret,
                               AVG({col_dd}) as avg_dd,
                               COUNT(*) as n
                        FROM positional_backtest_labels
                        WHERE nse_symbol = $1
                        """,
                        sym,
                    )
                    label_avg_ret = float(label_row["avg_ret"]) if label_row and label_row["avg_ret"] is not None else None
                    label_avg_dd = float(label_row["avg_dd"]) if label_row and label_row["avg_dd"] is not None else None
                    # Use label stats if calibration was missing
                    if accum_score is None and label_avg_ret is not None:
                        avg_ret = label_avg_ret / 100.0  # labels are in percent
                        avg_dd = (label_avg_dd or 0) / 100.0
            except Exception as e:  # noqa: BLE001
                logger.debug("simulate: stats lookup failed for %s: %s", sym, e)

        base_return = avg_ret * prob
        bear_dd = min(avg_dd * 2.0, 0.25)  # cap at 25%

        per_position.append({
            "symbol":             sym,
            "allocated_rs":       allocated,
            "probability_of_move": round(prob, 3),
            "avg_fwd_return_pct": round(avg_ret * 100, 2),
            "avg_fwd_drawdown_pct": round(avg_dd * 100, 2),
            "scenarios": {
                "BASE": {
                    "expected_return_pct": round(base_return * 100, 2),
                    "expected_pnl_rs": round(allocated * base_return, 2),
                    "max_drawdown_pct": round(avg_dd * 100, 2),
                    "max_loss_rs": round(allocated * avg_dd, 2),
                },
                "BULL": {
                    "expected_return_pct": round(avg_ret * 1.4 * 100, 2),
                    "expected_pnl_rs": round(allocated * avg_ret * 1.4, 2),
                    "max_drawdown_pct": round(avg_dd * 0.5 * 100, 2),
                    "max_loss_rs": round(allocated * avg_dd * 0.5, 2),
                },
                "BEAR": {
                    "expected_return_pct": round(avg_ret * 0.3 * 100, 2),
                    "expected_pnl_rs": round(allocated * avg_ret * 0.3, 2),
                    "max_drawdown_pct": round(bear_dd * 100, 2),
                    "max_loss_rs": round(allocated * bear_dd, 2),
                },
            },
        })

    # Portfolio-level aggregates (weighted by allocated_rs)
    total_alloc = sum(p["allocated_rs"] for p in per_position) or 1.0
    scenarios_agg: dict = {}
    for sc in ("BASE", "BULL", "BEAR"):
        total_pnl = sum(p["scenarios"][sc]["expected_pnl_rs"] for p in per_position)
        total_loss = sum(p["scenarios"][sc]["max_loss_rs"] for p in per_position)
        win_count = sum(1 for p in per_position if p["scenarios"][sc]["expected_return_pct"] > 0)
        scenarios_agg[sc] = {
            "total_expected_pnl_rs": round(total_pnl, 2),
            "total_max_loss_rs": round(total_loss, 2),
            "portfolio_return_pct": round(total_pnl / total_alloc * 100, 2),
            "portfolio_drawdown_pct": round(total_loss / total_alloc * 100, 2),
            "win_count": win_count,
            "loss_count": len(per_position) - win_count,
        }

    return {
        "horizon_days": horizon,
        "scenarios": scenarios_agg,
        "per_position": per_position,
    }


@router.get("/health")
async def health(request: Request):
    """Lightweight admin health: counts in each engine table for the latest day."""
    await require_admin(request)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}
    async with pool.acquire() as conn:
        ohlcv_latest = await conn.fetchrow(
            "SELECT MAX(bar_date) d, COUNT(DISTINCT nse_symbol) n FROM stock_ohlcv"
        )
        scan_latest = await conn.fetchrow(
            "SELECT MAX(scan_date) d, COUNT(DISTINCT nse_symbol) n FROM chartink_scan_hits"
        )
        feat_latest = await conn.fetchrow(
            "SELECT MAX(as_of_date) d, COUNT(*) n FROM stock_technical_features"
        )
        sig_latest = await conn.fetchrow(
            "SELECT MAX(signal_date) d, COUNT(*) n FROM positional_signals"
        )
    return {
        "ohlcv":     {"latest": str(ohlcv_latest["d"]) if ohlcv_latest["d"] else None,
                       "symbols": ohlcv_latest["n"]},
        "chartink":  {"latest": str(scan_latest["d"]) if scan_latest["d"] else None,
                       "symbols": scan_latest["n"]},
        "features":  {"latest": str(feat_latest["d"]) if feat_latest["d"] else None,
                       "rows": feat_latest["n"]},
        "signals":   {"latest": str(sig_latest["d"]) if sig_latest["d"] else None,
                       "rows": sig_latest["n"]},
    }
