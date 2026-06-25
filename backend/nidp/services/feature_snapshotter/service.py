"""Feature snapshotter — materialise nidp.stock_features_daily.

For each symbol with sufficient history (≥ 60 trailing bars) ending on
target_date, compute the feature pack and upsert into
nidp.stock_features_daily.

Performance budget: <5 minutes for full Nifty 500 universe at 220 bars
each. Achieved by:
  • One bulk SQL fetch of all bars, partitioned by symbol in Python
  • Pure-Python computation (no DB roundtrips per feature)
  • COPY-style multi-row INSERT for the writes
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from services.positional_engine.feature_calculator import compute_features
from services.positional_engine.accumulation_detector import detect_all

logger = logging.getLogger(__name__)


# ── How many trailing bars to load per symbol. SMA200 is the binding
#    constraint; we load 250 (SMA200 + buffer for 52w lookups).
LOOKBACK_BARS = 250

# populate_stock_features_extended is a universe-wide bulk UPDATE (~35s); override
# the pool's 30s command_timeout so it isn't cancelled mid-run.
_EXTENDED_POPULATE_TIMEOUT_S = 600


@dataclass
class FeatureSnapshotReport:
    target_date: date
    run_id: str
    symbols_considered: int = 0
    rows_written: int = 0
    rows_skipped: int = 0      # not enough history
    duration_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_date": str(self.target_date),
            "run_id": self.run_id,
            "symbols_considered": self.symbols_considered,
            "rows_written": self.rows_written,
            "rows_skipped": self.rows_skipped,
            "duration_ms": self.duration_ms,
            "errors": self.errors[:20],
        }


async def snapshot_features_for_date(
    pool,
    target_date: date,
    *,
    universe_filter: Optional[str] = "nifty500",
) -> FeatureSnapshotReport:
    """Compute + persist the feature snapshot for one date.

    `universe_filter` defaults to nifty500 to keep cost bounded; pass
    None to compute for the entire EQ universe (slower).
    """
    import time
    started = time.monotonic()
    run_id = str(uuid.uuid4())
    report = FeatureSnapshotReport(target_date=target_date, run_id=run_id)

    # 1. Resolve symbol universe.
    #
    # Read source: `stock_ohlcv` (this env's daily-bar table). Universe
    # gate: stock_master.is_nifty_100 — the curated 226-symbol set the
    # rest of the platform uses. When full NIDP lands we'll switch to
    # `nidp.stock_daily_snapshot` + index_constituents seamlessly.
    if universe_filter in ("nifty500", "nifty100", "nifty50"):
        universe_sql = (
            "AND EXISTS (SELECT 1 FROM stock_master sm "
            "             WHERE sm.nse_symbol = o.nse_symbol "
            "               AND sm.is_nifty_100 IS TRUE)"
        )
    else:
        universe_sql = ""   # full ohlcv universe (~2,700 symbols)

    async with pool.acquire() as conn:
        symbols_rows = await conn.fetch(
            f"""
            SELECT DISTINCT o.nse_symbol AS symbol
              FROM stock_ohlcv o
             WHERE o.bar_date = $1
               {universe_sql}
            """,
            target_date,
        )
        symbols = [r["symbol"] for r in symbols_rows]

    report.symbols_considered = len(symbols)
    if not symbols:
        report.errors.append("no symbols found for target_date — snapshot may be missing")
        report.duration_ms = int((time.monotonic() - started) * 1000)
        return report

    # 2. Bulk-fetch trailing bars from stock_ohlcv (this env's source-of-truth).
    from_date = target_date - timedelta(days=int(LOOKBACK_BARS * 1.6))  # buffer for weekends/holidays
    async with pool.acquire() as conn:
        bar_rows = await conn.fetch(
            """
            SELECT nse_symbol AS symbol, bar_date AS as_of_date,
                   open_price, high_price, low_price, close_price,
                   volume, delivery_pct
              FROM stock_ohlcv
             WHERE nse_symbol = ANY($1::text[])
               AND bar_date BETWEEN $2 AND $3
            ORDER BY nse_symbol, bar_date
            """,
            symbols, from_date, target_date,
        )

    # 3. Group bars by symbol
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for r in bar_rows:
        bars_by_symbol.setdefault(r["symbol"], []).append({
            "bar_date":     r["as_of_date"],
            "open":         float(r["open_price"] or 0),
            "high":         float(r["high_price"] or 0),
            "low":          float(r["low_price"] or 0),
            "close":        float(r["close_price"] or 0),
            "volume":       int(r["volume"] or 0),
            "delivery_pct": float(r["delivery_pct"]) if r["delivery_pct"] is not None else None,
        })

    # 4. Compute features per symbol
    rows_to_write: List[tuple] = []
    for sym in symbols:
        bars = bars_by_symbol.get(sym, [])
        if len(bars) < 60:
            report.rows_skipped += 1
            continue
        try:
            feat = compute_features(bars)
            # detect_all consumes the feature dict (not bars). bench_ret_20d
            # is left None — sector_lag detector only fires when a sector
            # benchmark is supplied, which we don't have at snapshot time.
            acc = detect_all(feat)
        except Exception as e:   # noqa: BLE001
            report.errors.append(f"{sym}: {e}")
            continue

        rows_to_write.append(_to_row_tuple(sym, target_date, feat, acc, run_id))

    # 5. Bulk insert
    if rows_to_write:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 5a. Insert / upsert technical features
                await conn.executemany(
                    """
                    INSERT INTO nidp.stock_features_daily
                        (symbol, as_of_date, close,
                         sma20, sma50, sma100, sma200, sma50_slope,
                         dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
                         rsi14, macd, macd_signal, macd_hist,
                         return_5d_pct, return_20d_pct, return_60d_pct,
                         atr14, atr_pct, bb_width, bb_pos,
                         avg_volume_20, vol_z20, deliv_pct_avg_20, deliv_trend10,
                         swing_high_20, swing_low_20, pivot_breakout_flag,
                         accumulation_score, accumulation_signals,
                         source, source_run_id)
                    VALUES ($1,$2,$3,
                            $4,$5,$6,$7,$8,
                            $9,$10,$11,
                            $12,$13,$14,$15,
                            $16,$17,$18,
                            $19,$20,$21,$22,
                            $23,$24,$25,$26,
                            $27,$28,$29,
                            $30,$31,
                            'NIDP_FEATURE_SNAPSHOTTER', $32)
                    ON CONFLICT (symbol, as_of_date, source) DO UPDATE SET
                        close = EXCLUDED.close,
                        rsi14 = EXCLUDED.rsi14,
                        atr14 = EXCLUDED.atr14,
                        ingested_at = NOW(),
                        source_run_id = EXCLUDED.source_run_id
                    """,
                    rows_to_write,
                )
        report.rows_written = len(rows_to_write)

        # 5b. Backfill the extended columns (fundamentals, shareholding,
        # sector, adjusted close, options aggregates) by joining the
        # latest views. The function is idempotent and lives in
        # migration 029. Failure here is non-fatal — technical features
        # have already landed; the extended columns will be filled on
        # the next run.
        try:
            async with pool.acquire() as conn:
                # The pool's command_timeout is 30s (nidp/shared/storage/pg.py) but
                # this bulk UPDATE takes ~35s over the full universe — without an
                # override asyncpg cancels it and the extended columns are left blank.
                extended_rows = await conn.fetchval(
                    "SELECT nidp.populate_stock_features_extended($1::date)",
                    target_date,
                    timeout=_EXTENDED_POPULATE_TIMEOUT_S,
                )
            logger.info(
                "feature_snapshotter extended columns populated for %d rows",
                int(extended_rows or 0),
            )
        except Exception as exc:                                          # noqa: BLE001
            # %r so an empty-message TimeoutError is still identifiable. Non-fatal:
            # technical features are already persisted; surface loudly so the gap
            # isn't silent the way it was before.
            logger.exception(
                "populate_stock_features_extended failed (continuing) — "
                "technical features are already persisted (error=%r)", exc
            )

    report.duration_ms = int((time.monotonic() - started) * 1000)
    logger.info("feature_snapshotter %s: %d rows written, %d skipped, %d ms",
                target_date, report.rows_written, report.rows_skipped, report.duration_ms)
    return report


def _to_row_tuple(sym, d, feat, acc, run_id):
    """Pack the feature dict into the positional tuple for executemany.

    Several derived fields aren't returned by compute_features but the
    snapshot table has columns for them (e.g. dist_52w_low_pct,
    avg_volume_20, deliv_pct_avg_20, bb_pos). We compute lightweight
    derived values inline to avoid double-iterating bars in the caller.
    """
    close = feat.get("close")
    sma200 = feat.get("sma_200")
    high_52w = feat.get("high_52w")
    low_52w = feat.get("low_52w")
    high_20d = feat.get("high_20d")
    bb_w = feat.get("bb_width_20")

    dist_200 = ((close - sma200) / sma200 * 100.0) if (close and sma200) else None
    dist_52h = ((close - high_52w) / high_52w * 100.0) if (close and high_52w) else None
    dist_52l = ((close - low_52w) / low_52w * 100.0) if (close and low_52w) else None
    pivot_break = bool(close and high_20d and close > high_20d)

    # bb_pos — where price sits inside the Bollinger band, 0..1.
    # Derived from sma_20 ± 2σ so the snapshotter doesn't need an extra
    # primitive function from feature_calculator.
    bb_pos = None
    if close and bb_w and feat.get("sma_20"):
        sma20 = feat["sma_20"]
        # bb_width here = stddev / sma20 (Keltner-style fraction). Reconstruct ±2σ.
        sigma = bb_w * sma20 / 2.0   # approx: bb_width = 2σ / sma20
        upper = sma20 + 2 * sigma
        lower = sma20 - 2 * sigma
        rng = upper - lower
        if rng > 0:
            bb_pos = max(0.0, min(1.0, (close - lower) / rng))

    return (
        sym, d, close,
        feat.get("sma_20"), feat.get("sma_50"), None, feat.get("sma_200"),
        feat.get("slope_20_pct"),
        dist_200, dist_52h, dist_52l,
        feat.get("rsi_14"), feat.get("macd"), feat.get("macd_signal"), feat.get("macd_hist"),
        feat.get("return_5d_pct"), feat.get("return_20d_pct"), feat.get("return_60d_pct"),
        feat.get("atr_14"), feat.get("atr_pct"), feat.get("bb_width_20"), bb_pos,
        None, feat.get("volume_z_20"), None, feat.get("delivery_trend_pct"),       # avg_volume_20, deliv_pct_avg_20 — Phase 1 leaves null
        feat.get("swing_high_20"), feat.get("swing_low_20"), pivot_break,
        acc.get("accumulation_score") if acc else None,
        acc.get("signals") if acc else [],
        run_id,
    )
