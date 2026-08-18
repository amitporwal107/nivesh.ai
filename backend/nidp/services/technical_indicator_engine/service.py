"""Technical Indicator Engine — Option B parallel service.

Reads OHLCV data from nidp.prices_eod (already populated: 3,425 symbols,
up to current date) and writes computed technical features to
nidp.stock_features_daily so the DAAS API /v1/features/stocks/{symbol}
can serve them to copilot agents.

Performance:
  - One bulk SQL fetch per symbol batch (not N round-trips)
  - Pure-Python/numpy computation — no TA-Lib dependency
  - asyncpg executemany upsert for writes
  - Full 3,425-symbol run: ~3–5 minutes on e2-standard-4
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import asyncpg
import numpy as np

from .calculator import compute_features

logger = logging.getLogger(__name__)

SOURCE = "COPILOT_TI_ENGINE"
MIN_BARS = 60        # minimum bars before we compute anything
LOOKBACK_BARS = 280  # bars to fetch per symbol (SMA200 + 52w + buffer)
BATCH_SIZE = 100     # symbols processed per DB round-trip


# ── Result reporting ────────────────────────────────────────────────

@dataclass
class RunReport:
    target_date: date
    run_id: str
    symbols_found: int = 0
    symbols_computed: int = 0
    symbols_skipped: int = 0   # insufficient history
    rows_upserted: int = 0
    # PR D — 252-bar price features populated via nidp.populate_stock_price_features.
    # Tracks how many rows the SQL function updated (vol_1y, drawdown, beta, ret_252d).
    price_features_rows: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def log(self) -> None:
        logger.info(
            "ti_engine_complete date=%s run=%s found=%d computed=%d skipped=%d upserted=%d "
            "price_features=%d errors=%d duration_ms=%d",
            self.target_date, self.run_id, self.symbols_found, self.symbols_computed,
            self.symbols_skipped, self.rows_upserted, self.price_features_rows,
            len(self.errors), self.duration_ms,
        )

    def as_dict(self) -> dict:
        return {
            "target_date": str(self.target_date),
            "run_id": self.run_id,
            "symbols_found": self.symbols_found,
            "symbols_computed": self.symbols_computed,
            "symbols_skipped": self.symbols_skipped,
            "rows_upserted": self.rows_upserted,
            "price_features_rows": self.price_features_rows,
            "errors": self.errors[:20],
            "duration_ms": self.duration_ms,
        }


# ── DB helpers ──────────────────────────────────────────────────────

async def _get_symbols(conn: asyncpg.Connection, target_date: date, only: Optional[list[str]] = None) -> list[str]:
    """Symbols in prices_eod for target_date with EQ series."""
    if only:
        rows = await conn.fetch(
            "SELECT DISTINCT symbol FROM nidp.prices_eod "
            "WHERE as_of_date = $1 AND series = 'EQ' AND symbol = ANY($2::text[]) "
            "ORDER BY symbol",
            target_date, only,
        )
    else:
        rows = await conn.fetch(
            "SELECT DISTINCT symbol FROM nidp.prices_eod "
            "WHERE as_of_date = $1 AND series = 'EQ' "
            "ORDER BY symbol",
            target_date,
        )
    return [r["symbol"] for r in rows]


async def _fetch_price_history(
    conn: asyncpg.Connection,
    symbols: list[str],
    up_to_date: date,
    lookback: int,
) -> dict[str, list[asyncpg.Record]]:
    """Bulk-fetch price history for multiple symbols in one query."""
    since = up_to_date - timedelta(days=lookback * 2)  # calendar days buffer
    rows = await conn.fetch(
        """
        SELECT symbol, as_of_date, close_price, high_price, low_price,
               open_price, volume, deliv_pct, source
          FROM nidp.prices_eod
         WHERE symbol = ANY($1::text[])
           AND series = 'EQ'
           AND as_of_date >= $2
           AND as_of_date <= $3
           AND close_price > 0
         ORDER BY symbol, as_of_date
        """,
        symbols, since, up_to_date,
    )
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["symbol"], []).append(r)
    return grouped


# prices_eod can be filled from BSE on days NSE's edge blocked us. Prices
# track closely across the two exchanges, so BSE bars are fine for
# price-derived indicators (SMA, RSI, MACD, returns). Volume and delivery
# are NOT: they measure one exchange's order book, and BSE turnover runs
# roughly an order of magnitude below NSE's. Feeding those bars into a
# 20-day volume baseline would read as a volume collapse and fire false
# "distribution" signals, so they are masked to NaN instead.
_VOLUME_TRUSTED_SOURCES = frozenset({"NSE_BHAVCOPY"})


def _to_arrays(records: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    closes = np.array([float(r["close_price"]) for r in records])
    opens = np.array([float(r["open_price"] or r["close_price"]) for r in records])
    highs = np.array([float(r["high_price"]) for r in records])
    lows = np.array([float(r["low_price"]) for r in records])

    def _vol(r):
        src = r["source"] if "source" in r else None
        if src is not None and src not in _VOLUME_TRUSTED_SOURCES:
            return np.nan
        v = r["volume"]
        return float(v) if v is not None else np.nan

    def _dlv(r):
        src = r["source"] if "source" in r else None
        if src is not None and src not in _VOLUME_TRUSTED_SOURCES:
            return np.nan
        v = r["deliv_pct"]
        # A missing delivery figure is unknown, not 0% — coercing it to
        # zero drags deliv_pct_avg_20 down and mis-scores the
        # accumulation pillar. delivery_stats already skips NaN.
        return float(v) if v is not None else np.nan

    volumes = np.array([_vol(r) for r in records])
    deliv = np.array([_dlv(r) for r in records])
    return closes, opens, highs, lows, volumes, deliv


_UPSERT_SQL = """
INSERT INTO nidp.stock_features_daily (
    symbol, as_of_date,
    close, sma20, sma50, sma100, sma200, sma50_slope,
    dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
    rsi14, macd, macd_signal, macd_hist,
    return_5d_pct, return_20d_pct, return_60d_pct,
    atr14, atr_pct, bb_width, bb_pos,
    avg_volume_20, vol_z20,
    deliv_pct_avg_20, deliv_trend10,
    swing_high_20, swing_low_20, pivot_breakout_flag,
    accumulation_score, accumulation_signals,
    source, source_run_id, ingested_at
) VALUES (
    $1, $2,
    $3, $4, $5, $6, $7, $8,
    $9, $10, $11,
    $12, $13, $14, $15,
    $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24,
    $25, $26,
    $27, $28, $29,
    $30, $31,
    $32, $33, NOW()
)
ON CONFLICT (symbol, as_of_date, source)
DO UPDATE SET
    close = EXCLUDED.close,
    sma20 = EXCLUDED.sma20, sma50 = EXCLUDED.sma50,
    sma100 = EXCLUDED.sma100, sma200 = EXCLUDED.sma200,
    sma50_slope = EXCLUDED.sma50_slope,
    dist_200dma_pct = EXCLUDED.dist_200dma_pct,
    dist_52w_high_pct = EXCLUDED.dist_52w_high_pct,
    dist_52w_low_pct = EXCLUDED.dist_52w_low_pct,
    rsi14 = EXCLUDED.rsi14, macd = EXCLUDED.macd,
    macd_signal = EXCLUDED.macd_signal, macd_hist = EXCLUDED.macd_hist,
    return_5d_pct = EXCLUDED.return_5d_pct,
    return_20d_pct = EXCLUDED.return_20d_pct,
    return_60d_pct = EXCLUDED.return_60d_pct,
    atr14 = EXCLUDED.atr14, atr_pct = EXCLUDED.atr_pct,
    bb_width = EXCLUDED.bb_width, bb_pos = EXCLUDED.bb_pos,
    avg_volume_20 = EXCLUDED.avg_volume_20,
    vol_z20 = EXCLUDED.vol_z20,
    deliv_pct_avg_20 = EXCLUDED.deliv_pct_avg_20,
    deliv_trend10 = EXCLUDED.deliv_trend10,
    swing_high_20 = EXCLUDED.swing_high_20,
    swing_low_20 = EXCLUDED.swing_low_20,
    pivot_breakout_flag = EXCLUDED.pivot_breakout_flag,
    accumulation_score = EXCLUDED.accumulation_score,
    ingested_at = NOW()
"""


def _row_tuple(symbol: str, target_date: date, f: dict, run_id: str) -> tuple:
    return (
        symbol, target_date,
        f["close"], f["sma20"], f["sma50"], f["sma100"], f["sma200"], f["sma50_slope"],
        f["dist_200dma_pct"], f["dist_52w_high_pct"], f["dist_52w_low_pct"],
        f["rsi14"], f["macd"], f["macd_signal"], f["macd_hist"],
        f["return_5d_pct"], f["return_20d_pct"], f["return_60d_pct"],
        f["atr14"], f["atr_pct"], f["bb_width"], f["bb_pos"],
        f["avg_volume_20"], f["vol_z20"],
        f["deliv_pct_avg_20"], f["deliv_trend10"],
        f["swing_high_20"], f["swing_low_20"], f["pivot_breakout_flag"],
        f["accumulation_score"], f["accumulation_signals"],
        SOURCE, run_id,
    )


async def _upsert_batch(conn: asyncpg.Connection, rows: list[tuple]) -> int:
    await conn.executemany(_UPSERT_SQL, rows)
    return len(rows)


# ── Core compute loop ────────────────────────────────────────────────

async def compute_for_date(
    pool: asyncpg.Pool,
    target_date: date,
    *,
    only_symbols: Optional[list[str]] = None,
    batch_size: int = BATCH_SIZE,
) -> RunReport:
    t0 = time.monotonic()
    run_id = str(uuid.uuid4())
    report = RunReport(target_date=target_date, run_id=run_id)

    async with pool.acquire() as conn:
        symbols = await _get_symbols(conn, target_date, only_symbols)
        report.symbols_found = len(symbols)
        if not symbols:
            logger.warning("ti_engine_no_symbols date=%s", target_date)
            return report

        logger.info("ti_engine_start date=%s symbols=%d run=%s", target_date, len(symbols), run_id)

        # Process in batches to avoid huge memory spikes
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i: i + batch_size]
            try:
                history = await _fetch_price_history(conn, batch, target_date, LOOKBACK_BARS)
            except Exception as exc:
                logger.error("ti_engine_fetch_error batch=%d error=%s", i, exc)
                report.errors.append(f"fetch_batch_{i}: {exc}")
                continue

            upsert_rows: list[tuple] = []
            for symbol in batch:
                records = history.get(symbol, [])
                if len(records) < MIN_BARS:
                    report.symbols_skipped += 1
                    continue
                try:
                    closes, opens, highs, lows, volumes, deliv = _to_arrays(records)
                    feats = compute_features(closes, opens, highs, lows, volumes, deliv)
                    upsert_rows.append(_row_tuple(symbol, target_date, feats, run_id))
                    report.symbols_computed += 1
                except Exception as exc:
                    logger.warning("ti_engine_compute_error symbol=%s error=%s", symbol, exc)
                    report.errors.append(f"{symbol}: {exc}")

            if upsert_rows:
                try:
                    await _upsert_batch(conn, upsert_rows)
                    report.rows_upserted += len(upsert_rows)
                except Exception as exc:
                    logger.error("ti_engine_upsert_error batch=%d error=%s", i, exc)
                    report.errors.append(f"upsert_batch_{i}: {exc}")

            logger.info("ti_engine_batch_done batch=%d-%d computed=%d total_upserted=%d",
                        i, i + len(batch), len(upsert_rows), report.rows_upserted)

        # ── 252-bar price-history features ──
        # Single-pass SQL window-function compute over prices_eod_adjusted →
        # populates volatility_1y_pct, return_252d_pct, beta_1y,
        # max_drawdown_1y_pct on the rows we just upserted. Faster + more
        # accurate than reimplementing in numpy here. Function is defined
        # in migration 053_nidp_stock_derived_metrics.sql.
        # Side effect: requires price_adjuster to have already run for
        # target_date (cron orders us at 22:35, after price_adjuster at
        # 22:30). If adj-close is missing we still complete; the SQL
        # function just leaves NULL where input data is absent.
        try:
            n = await conn.fetchval(
                "SELECT nidp.populate_stock_price_features($1::date)",
                target_date,
            )
            report.price_features_rows = int(n or 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("ti_engine_price_features_error date=%s error=%s", target_date, exc)
            report.errors.append(f"populate_stock_price_features: {exc}")

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.log()
    return report


async def compute_date_range(
    pool: asyncpg.Pool,
    from_date: date,
    to_date: date,
    *,
    only_symbols: Optional[list[str]] = None,
) -> list[RunReport]:
    """Run compute_for_date for every trading day in [from_date, to_date]."""
    reports: list[RunReport] = []
    current = from_date
    while current <= to_date:
        report = await compute_for_date(pool, current, only_symbols=only_symbols)
        reports.append(report)
        # Skip weekends automatically — if no symbols found, just skip
        current += timedelta(days=1)
    return reports


# ── Pool factory ─────────────────────────────────────────────────────

async def create_pool(url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=8,
        command_timeout=120,
        statement_cache_size=0,
        server_settings={"search_path": "nidp,public"},
    )


# ── Backfill / cron adapter ─────────────────────────────────────────
# Matches the run(target_date) convention every NIDP ingester exposes,
# so this service can be invoked by nidp/backfill.py and the existing
# run_service.sh wrapper that nidp.cron uses.
async def run(target_date: Optional[date] = None) -> dict:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("NIDP_POSTGRES_URL not set")
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    pool = await create_pool(url)
    try:
        report = await compute_for_date(pool, target_date)
        return report.as_dict()
    finally:
        await pool.close()
