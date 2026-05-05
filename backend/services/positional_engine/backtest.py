"""Backtest + calibration for the pre-breakout accumulation detector.

Two passes:

  1. label() — for every (symbol, scan_date) in our OHLCV history, replay
     the accumulation detector against bars-as-they-were-on-that-date,
     then look forward N trading days and record the realised max-return
     and max-drawdown. Persist to `positional_backtest_labels`.

  2. calibrate() — sweep the labelled rows, bucket by accumulation_score,
     compute the empirical "moved" rate per bucket per horizon, persist
     to `accumulation_calibration`. The UI/scoring layer reads from
     this to convert "accumulation_score 0.78" into "probability of
     ≥5% move within 10d = 47%".

The calibration layer is intentionally NOT machine-learnt yet. It's
just a bucketed empirical hit rate — interpretable, deterministic,
defensible. Once we have a year+ of labels, swap the bucketed lookup
for a calibrated logistic regression / gradient boosting model.

Defensive design — backtest is best-effort per (symbol, date); a single
bad symbol must not poison the run.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from services import pg_client
from . import (
    ENGINE_VERSION,
    accumulation_detector,
    feature_calculator as fc,
    ohlcv_store,
    sector_strength,
    scorer,
)

logger = logging.getLogger(__name__)

# v1 fixed move threshold — kept for backward-compat with old labels
MOVE_THRESHOLD_PCT = 5.0

# v2 scaled move threshold — high-vol stocks need bigger moves to count.
# Floor: max(MIN_SCALED_MOVE_PCT, atr_pct × SCALED_MOVE_ATR_MULT).
MIN_SCALED_MOVE_PCT = 5.0
SCALED_MOVE_ATR_MULT = 3.0

# Forward horizons
HORIZONS = [5, 10, 20]


def _scaled_move_threshold(atr_pct: Optional[float]) -> float:
    """Per-stock scaled move threshold. Tight stocks (low ATR%) need
    a 5% move to count as a real expansion. Loose stocks (ATR 4%+)
    need 12%+. This is what makes the "moved" metric meaningful across
    very different volatility regimes."""
    if atr_pct is None or atr_pct <= 0:
        return MIN_SCALED_MOVE_PCT
    return max(MIN_SCALED_MOVE_PCT, atr_pct * SCALED_MOVE_ATR_MULT)

# Calibration buckets — granular at the high end where decisions matter
CALIBRATION_BUCKETS = [
    (0.00, 0.30),
    (0.30, 0.45),
    (0.45, 0.55),
    (0.55, 0.65),
    (0.65, 0.75),
    (0.75, 0.85),
    (0.85, 1.01),     # 1.01 to include exact 1.0
]


# ── Forward outcome computation (pure-Python on bars) ────────────────────
def _forward_outcome(bars_after: List[dict], scan_close: float,
                     horizon: int,
                     resistance: Optional[float] = None,
                     ) -> Tuple[Optional[float], Optional[float], Optional[bool]]:
    """Walk `horizon` bars forward from scan_date. Returns:
       (max_return_pct, max_drawdown_pct, broke_high)
    where:
      • max_return_pct   — max intraday-high return vs scan_close
      • max_drawdown_pct — min intraday-low return vs scan_close
      • broke_high       — True if any bar's high crossed `resistance`
                           in the window. None if resistance is None.
    None tuple if not enough bars."""
    if len(bars_after) < horizon or scan_close <= 0:
        return None, None, None
    window = bars_after[:horizon]
    max_high = max(float(b["high"]) for b in window)
    min_low = min(float(b["low"]) for b in window)
    broke = None
    if resistance is not None and resistance > 0:
        broke = max_high > resistance
    return (
        round((max_high - scan_close) / scan_close * 100.0, 2),
        round((min_low - scan_close) / scan_close * 100.0, 2),
        broke,
    )


# ── Per-symbol-per-date labelling (testable without DB) ──────────────────
def label_one(bars: List[dict], scan_date: date,
              *, bench_ret_20d: Optional[float] = None) -> Optional[Dict]:
    """Compute a backtest label for a single (symbol, scan_date).

    `bars` must include at least 60 bars BEFORE scan_date (for feature
    computation) and ideally 20 bars AFTER (for full forward labels).
    Returns the label dict or None if insufficient history.
    """
    # Find the index of the bar matching scan_date
    idx = None
    for i, b in enumerate(bars):
        if b["bar_date"] == scan_date:
            idx = i
            break
    if idx is None or idx < 60:
        return None

    bars_before = bars[: idx + 1]   # inclusive — features see scan_date close
    bars_after = bars[idx + 1:]

    feats = fc.compute_features(bars_before)
    if not feats.get("close"):
        return None

    rs = sector_strength.compute_rs_pct(feats.get("return_20d_pct"), bench_ret_20d)
    s = scorer.score(feats, rs_vs_nifty_pct=rs)
    pre = accumulation_detector.detect_all(feats, bench_ret_20d=bench_ret_20d)

    # v2: per-stock scaled move threshold + 20d-high resistance level
    scaled_thresh = _scaled_move_threshold(feats.get("atr_pct"))
    resistance = feats.get("high_20d")    # the level the stock had not broken yet

    label = {
        "scan_date": scan_date,
        "accumulation_score": pre["accumulation_score"],
        "signals": pre["signals"],
        "final_score": s["final_score"],
        "stage": s["stage"],
        "close_price": feats["close"],
        "move_threshold_pct": round(scaled_thresh, 2),
        "resistance_at_scan": resistance,
    }
    for h in HORIZONS:
        max_ret, max_dd, broke = _forward_outcome(
            bars_after, feats["close"], h, resistance=resistance,
        )
        label[f"fwd_max_return_{h}d"] = max_ret
        label[f"fwd_max_drawdown_{h}d"] = max_dd
        # v1 (kept for backward compat)
        label[f"moved_{h}d"] = (max_ret >= MOVE_THRESHOLD_PCT) if max_ret is not None else None
        # v2 metrics
        label[f"moved_scaled_{h}d"] = (max_ret >= scaled_thresh) if max_ret is not None else None
        label[f"broke_high_{h}d"] = broke
    return label


# ── DB writes ────────────────────────────────────────────────────────────
async def _persist_labels(symbol: str, labels: List[Dict]) -> int:
    if not labels:
        return 0
    pool = await pg_client.get_pool()
    if pool is None:
        return 0
    payload = []
    for l in labels:
        payload.append((
            symbol, l["scan_date"],
            l["accumulation_score"], l["signals"],
            l["final_score"], l["stage"], l["close_price"],
            l.get("fwd_max_return_5d"), l.get("fwd_max_return_10d"), l.get("fwd_max_return_20d"),
            l.get("fwd_max_drawdown_5d"), l.get("fwd_max_drawdown_10d"), l.get("fwd_max_drawdown_20d"),
            l.get("moved_5d"), l.get("moved_10d"), l.get("moved_20d"),
            # v2 columns
            l.get("move_threshold_pct"), l.get("resistance_at_scan"),
            l.get("moved_scaled_5d"), l.get("moved_scaled_10d"), l.get("moved_scaled_20d"),
            l.get("broke_high_5d"), l.get("broke_high_10d"), l.get("broke_high_20d"),
            ENGINE_VERSION,
        ))
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO positional_backtest_labels (
                nse_symbol, scan_date, accumulation_score, signals,
                final_score, stage, close_price,
                fwd_max_return_5d, fwd_max_return_10d, fwd_max_return_20d,
                fwd_max_drawdown_5d, fwd_max_drawdown_10d, fwd_max_drawdown_20d,
                moved_5d, moved_10d, moved_20d,
                move_threshold_pct, resistance_at_scan,
                moved_scaled_5d, moved_scaled_10d, moved_scaled_20d,
                broke_high_5d, broke_high_10d, broke_high_20d,
                engine_version
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                       $17,$18,$19,$20,$21,$22,$23,$24,$25)
            ON CONFLICT (nse_symbol, scan_date) DO UPDATE SET
                accumulation_score = EXCLUDED.accumulation_score,
                signals            = EXCLUDED.signals,
                final_score        = EXCLUDED.final_score,
                stage              = EXCLUDED.stage,
                close_price        = EXCLUDED.close_price,
                fwd_max_return_5d  = EXCLUDED.fwd_max_return_5d,
                fwd_max_return_10d = EXCLUDED.fwd_max_return_10d,
                fwd_max_return_20d = EXCLUDED.fwd_max_return_20d,
                fwd_max_drawdown_5d = EXCLUDED.fwd_max_drawdown_5d,
                fwd_max_drawdown_10d = EXCLUDED.fwd_max_drawdown_10d,
                fwd_max_drawdown_20d = EXCLUDED.fwd_max_drawdown_20d,
                moved_5d           = EXCLUDED.moved_5d,
                moved_10d          = EXCLUDED.moved_10d,
                moved_20d          = EXCLUDED.moved_20d,
                move_threshold_pct = EXCLUDED.move_threshold_pct,
                resistance_at_scan = EXCLUDED.resistance_at_scan,
                moved_scaled_5d    = EXCLUDED.moved_scaled_5d,
                moved_scaled_10d   = EXCLUDED.moved_scaled_10d,
                moved_scaled_20d   = EXCLUDED.moved_scaled_20d,
                broke_high_5d      = EXCLUDED.broke_high_5d,
                broke_high_10d     = EXCLUDED.broke_high_10d,
                broke_high_20d     = EXCLUDED.broke_high_20d,
                engine_version     = EXCLUDED.engine_version,
                computed_at        = NOW()
            """,
            payload,
        )
    return len(payload)


# ── Top-level driver ─────────────────────────────────────────────────────
async def label_universe(*, max_symbols: Optional[int] = None,
                          step_days: int = 1) -> Dict:
    """Sweep every symbol in stock_ohlcv, replay the detector at every
    eligible scan_date, persist labels.

    `step_days=1` labels every trading day; `step_days=5` labels every
    5th day (faster, sparser dataset). Default daily.
    """
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    async with pool.acquire() as conn:
        sym_rows = await conn.fetch("SELECT DISTINCT nse_symbol FROM stock_ohlcv")
    symbols = [r["nse_symbol"] for r in sym_rows]
    if max_symbols:
        symbols = symbols[:max_symbols]

    bench_ret_cache: Dict[date, Optional[float]] = {}
    total_labels = 0
    errors = 0

    for symbol in symbols:
        try:
            bars = await ohlcv_store.load_bars(symbol, lookback_bars=400)
            if len(bars) < 80:
                continue
            # Eligible scan dates = bars that have ≥ 60 bars before AND
            # ≥ 5 bars after (so we can label at least the 5d horizon).
            labels: List[Dict] = []
            for i in range(60, len(bars) - 5, step_days):
                scan_date = bars[i]["bar_date"]
                # Cache bench return per scan_date — avoids redundant fetches
                if scan_date not in bench_ret_cache:
                    bench_ret_cache[scan_date] = await sector_strength.load_bench_return(
                        end_date=scan_date, lookback=20,
                    )
                bench = bench_ret_cache[scan_date]
                lab = label_one(bars, scan_date, bench_ret_20d=bench)
                if lab:
                    labels.append(lab)
            if labels:
                total_labels += await _persist_labels(symbol, labels)
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.warning("backtest label failed for %s: %s", symbol, e)

    return {
        "ok": True,
        "symbols": len(symbols),
        "labels_written": total_labels,
        "errors": errors,
    }


# Three outcome metrics — calibrate() emits one row per (metric, bucket, horizon).
# Each metric maps to the SQL column in positional_backtest_labels that holds
# the binary label.
CALIBRATION_METRICS = {
    "moved_5pct":   "moved_{h}d",         # v1, fixed 5% threshold (kept for compat)
    "moved_scaled": "moved_scaled_{h}d",  # v2, max(5, atr_pct × 3) threshold
    "broke_high":   "broke_high_{h}d",    # v2, crossed 20d-high (the actual breakout)
}


async def calibrate() -> Dict:
    """Sweep positional_backtest_labels, bucket by accumulation_score,
    compute per-metric per-bucket per-horizon hit rate. Persist to
    accumulation_calibration."""
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    rows_written = 0
    async with pool.acquire() as conn:
        for metric_name, col_template in CALIBRATION_METRICS.items():
            for lo, hi in CALIBRATION_BUCKETS:
                for h in HORIZONS:
                    col = col_template.format(h=h)
                    stats = await conn.fetchrow(
                        f"""
                        SELECT
                            COUNT(*)                             AS sample_count,
                            SUM(CASE WHEN {col} THEN 1 ELSE 0 END) AS moves_count,
                            AVG(fwd_max_return_{h}d)             AS avg_fwd_return,
                            AVG(fwd_max_drawdown_{h}d)           AS avg_fwd_drawdown
                        FROM positional_backtest_labels
                        WHERE accumulation_score >= $1
                          AND accumulation_score <  $2
                          AND {col} IS NOT NULL
                        """,
                        lo, hi,
                    )
                    sc = int(stats["sample_count"] or 0)
                    mc = int(stats["moves_count"] or 0)
                    if sc == 0:
                        continue
                    prob = round(mc / sc, 4)
                    await conn.execute(
                        """
                        INSERT INTO accumulation_calibration
                            (metric, bucket_lo, bucket_hi, horizon_days,
                             sample_count, moves_count, probability,
                             avg_fwd_return, avg_fwd_drawdown)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (metric, bucket_lo, bucket_hi, horizon_days)
                        DO UPDATE SET
                            sample_count     = EXCLUDED.sample_count,
                            moves_count      = EXCLUDED.moves_count,
                            probability      = EXCLUDED.probability,
                            avg_fwd_return   = EXCLUDED.avg_fwd_return,
                            avg_fwd_drawdown = EXCLUDED.avg_fwd_drawdown,
                            refreshed_at     = NOW()
                        """,
                        metric_name, lo, hi, h, sc, mc, prob,
                        stats["avg_fwd_return"], stats["avg_fwd_drawdown"],
                    )
                    rows_written += 1
    return {"ok": True, "rows_written": rows_written, "metrics": list(CALIBRATION_METRICS)}


# ── Read API — convert score → probability via calibration table ─────────
async def probability_of_move(accumulation_score: float,
                                horizon: int = 10,
                                metric: str = "broke_high",
                                ) -> Optional[float]:
    """Look up the empirical probability that a stock with this
    `accumulation_score` hits the `metric` within `horizon` bars,
    based on the calibration table.

    `metric` ∈ {"broke_high", "moved_scaled", "moved_5pct"}.
    Default is "broke_high" — the actual breakout event, scale-invariant.
    Returns None if no data."""
    if accumulation_score is None:
        return None
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT probability FROM accumulation_calibration
            WHERE metric = $1
              AND horizon_days = $2
              AND $3 >= bucket_lo
              AND $3 <  bucket_hi
            ORDER BY sample_count DESC LIMIT 1
            """,
            metric, horizon, accumulation_score,
        )
    return float(row["probability"]) if row and row["probability"] is not None else None
