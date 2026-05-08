"""Positional Trading Engine API.

Public (auth-required):
  GET  /api/positional/picks?date=&min_score=&stage=&limit=
  GET  /api/positional/picks/{symbol}?date=
  GET  /api/positional/picks/mine          — portfolio-aware filtered picks

Admin:
  POST /api/positional/run?date=YYYY-MM-DD
  POST /api/positional/scans/upload        — upload a Chartink CSV
  POST /api/positional/ohlcv/bhavcopy?date=YYYY-MM-DD
"""
from __future__ import annotations

import json
import logging
import asyncio
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from deps import db, get_current_user, require_admin
from services import pg_client
from services.positional_engine import (
    backtest,
    bhavcopy_ingester,
    chartink_api,
    chartink_loader,
    conviction,
    pipeline,
    portfolio_filter,
    scan_config,
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
                        limit: int) -> List[dict]:
    """Fetch picks for a date. LEFT JOINs stock_technical_features so
    callers can read the pre_breakout block (signals + accumulation_score)
    without a second round-trip."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    sql = (
        "SELECT ps.nse_symbol, ps.signal_date, ps.final_score, ps.confidence, ps.stage, "
        "       ps.timeframe_days_min, ps.timeframe_days_max, "
        "       ps.entry_price, ps.stoploss, ps.target_price, ps.risk_reward, "
        "       ps.source_scans, ps.reasons, "
        "       stf.components->'pre_breakout' AS pre_breakout, "
        "       stf.components->'raw' AS features_raw "
        "FROM positional_signals ps "
        "LEFT JOIN stock_technical_features stf "
        "       ON stf.nse_symbol = ps.nse_symbol AND stf.as_of_date = ps.signal_date "
        "WHERE ps.signal_date = $1 AND ps.final_score >= $2 "
    )
    params: list = [signal_date, min_score]
    if stage:
        sql += "AND ps.stage = $3 "
        params.append(stage.upper())
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
        return {"signal_date": None, "picks": [], "message": "no signals available yet"}
    picks = await _fetch_picks(sig_date, min_score, stage, limit)
    return {
        "signal_date": str(sig_date),
        "count": len(picks),
        "picks": picks,
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
    pool = await pg_client.get_pool()
    if pool is None:
        return {"as_of_date": None, "buckets": {}, "_reason": "no pg pool"}

    try:
        async with pool.acquire() as conn:
            latest = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM stock_technical_features"
            )
            if not latest or latest["d"] is None:
                return {
                    "as_of_date": None, "buckets": {},
                    "_reason": "no technical features yet — run the engine first",
                }
            d = latest["d"]
            # First pass — narrow candidates by score so we only do the
            # OHLCV round-trip for the top ~80. WEAK/EXTENDED dropped here
            # because their structure rules out our 4 buckets anyway.
            cand_rows = await conn.fetch(
                """
                SELECT stf.nse_symbol, stf.stage, stf.confidence, stf.final_score,
                       stf.close_price, stf.sma_50, stf.sma_200,
                       stf.rsi_14, stf.atr_14,
                       stf.breakout_level, stf.support_level, stf.resistance_level,
                       sm.sector
                FROM stock_technical_features stf
                LEFT JOIN stock_master sm ON sm.nse_symbol = stf.nse_symbol
                WHERE stf.as_of_date = $1
                  AND stf.stage IS NOT NULL
                  AND stf.stage NOT IN ('WEAK', 'EXTENDED')
                  AND stf.close_price > 5
                ORDER BY stf.final_score DESC NULLS LAST
                LIMIT 80
                """,
                d,
            )
            candidate_syms = [r["nse_symbol"] for r in cand_rows]
            # Second pass — bulk-load last 60 bars for each candidate
            # symbol from stock_ohlcv. One query.
            bars_by_sym: dict = {}
            if candidate_syms:
                ohlcv_rows = await conn.fetch(
                    """
                    SELECT nse_symbol, bar_date, open, high, low, close, volume,
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
                "_reason": f"{type(e).__name__}: {str(e)[:200]}"}

    # Smart-money classifier — uses helpers from feature_calculator.
    from services.positional_engine import feature_calculator as fc

    true_accum: list = []
    pre_break: list = []
    confirmed: list = []
    continuation: list = []

    for r in cand_rows:
        sym = r["nse_symbol"]
        bars = bars_by_sym.get(sym) or []
        if len(bars) < 30:
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

        def _stop(entry, mult=1.5):
            if entry is None or atr is None:
                return None
            return round(entry - mult * atr, 2)

        base_item = {
            "nse_symbol": sym,
            "sector": r["sector"],
            "stage": r["stage"],
            "confidence": r["confidence"],
            "final_score": round(float(r["final_score"] or 0), 3),
            "close_price": close,
            "trigger_price": bo,
            "stop_price": None,
            "atr_pct": (round(atr / close * 100, 2) if close and atr else None),
            "rsi_14": float(r["rsi_14"]) if r["rsi_14"] is not None else None,
            "sma_50": sma50,
            "sma_200": sma200,
            "ema_20": ema20,
            "signals": signals,
        }

        # ── Bucket gates (precedence: confirmed → pre → continuation → accum) ──
        # 1) BREAKOUT CONFIRMED — close just above the breakout level on
        #    elevated volume. The most actionable bucket.
        if (dist_pct is not None and 0 <= dist_pct <= 3
                and vol_spike is not None and vol_spike >= 1.5
                and r["stage"] in ("BREAKOUT", "EARLY_BREAKOUT")):
            it = {**base_item, "stop_price": _stop(bo)}
            it["why"] = (f"Broke above ₹{bo:.2f} ({dist_pct:+.1f}%) on "
                         f"{vol_spike:.1f}× avg volume")
            confirmed.append(it)
            continue

        # 2) PRE_BREAKOUT — within 2% below resistance, volume building.
        if (dist_pct is not None and -2 <= dist_pct < 0
                and vol_spike is not None and vol_spike >= 1.2
                and (vol_dry_10 is None or vol_dry_10 > -3)):
            it = {**base_item, "stop_price": _stop(bo)}
            it["why"] = (f"{abs(dist_pct):.1f}% below ₹{bo:.2f} resistance · "
                         f"volume {vol_spike:.1f}× avg")
            pre_break.append(it)
            continue

        # 3) TRUE ACCUMULATION — tight range + volume drying + higher
        #    lows + small upper wicks. This is the "real" accumulation
        #    rather than just stage='ACCUMULATION'.
        if (rng_15 is not None and rng_15 < 8.0                     # tight base
                and vol_dry_10 is not None and vol_dry_10 < 0       # volume contracting
                and hl_count >= 1                                    # higher-lows structure
                and (wick is None or wick < 0.5)                     # no heavy upper-wick selling
                and (sma50 is None or close > sma50 * 0.97)          # price not far below 50DMA
                ):
            it = {**base_item, "stop_price": _stop(close)}
            wick_msg = "" if wick is None else f", wick {wick:.0%}"
            dlv_msg = "" if delivery_t is None else f", delivery {delivery_t:+.0f}%"
            it["why"] = (f"Tight {rng_15:.1f}% range, vol drying "
                         f"{vol_dry_10:+.1f}%/d, {hl_count} higher lows{wick_msg}{dlv_msg}")
            true_accum.append(it)
            continue

        # 4) TREND CONTINUATION — close > 20EMA > 50EMA (ascending),
        #    within ~3% of the 20EMA (pullback zone), no fresh weakness.
        if (sma50 is not None and ema20 is not None
                and close > ema20 > sma50
                and dist_ema20 is not None and 0 <= dist_ema20 <= 4
                and (wick is None or wick < 0.5)):
            it = {**base_item, "stop_price": _stop(ema20)}
            it["why"] = (f"Trend intact (close > 20EMA ₹{ema20:.2f} > 50EMA), "
                         f"{dist_ema20:.1f}% above 20EMA — pullback zone")
            continuation.append(it)
            continue

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
        "_classifier_version": "smart_v2",
    }


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
    """
    await require_admin(request)
    run_date = _parse_date(date) or datetime.utcnow().date()
    out = {"date": str(run_date), "steps": {}}

    if fetch_bhavcopy:
        try:
            n = await bhavcopy_ingester.ingest_for_date(run_date)
            out["steps"]["bhavcopy"] = {"ok": n > 0, "rows_written": n}
        except Exception as e:  # noqa: BLE001
            out["steps"]["bhavcopy"] = {"ok": False, "error": str(e)[:200]}

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


@router.get("/backtest/calibration")
async def get_calibration(request: Request):
    """Public (auth): returns the bucketed hit-rate table the UI uses
    to convert accumulation_score → probability of move."""
    await get_current_user(request)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"buckets": [], "_reason": "no_pg_pool"}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT metric, bucket_lo, bucket_hi, horizon_days,
                       sample_count, moves_count, probability,
                       avg_fwd_return, avg_fwd_drawdown
                FROM accumulation_calibration
                ORDER BY metric, horizon_days, bucket_lo
                """
            )
        return {"buckets": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"buckets": [], "_reason": str(e)[:200]}


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
    Gating layer for the BTST framework — answers "is today a green-light
    day to deploy aggressively, or a sit-on-hands day?"."""
    await get_current_user(request)
    import time
    now = time.time()
    if _MARKET_DASH_CACHE["data"] and (now - _MARKET_DASH_CACHE["ts"]) < _md_cache_ttl():
        return {**_MARKET_DASH_CACHE["data"], "_cache_hit": True}
    from services.positional_engine import market_dashboard as md
    data = await md.build()
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
