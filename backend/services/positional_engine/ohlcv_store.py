"""OHLCV persistence layer for the positional engine.

Reads/writes `stock_ohlcv`. Source-agnostic: accepts bars from any
ingester (NSE bhavcopy, broker API, manual CSV). The ingester's only job
is to produce a list of bar dicts in this shape:

    {bar_date: date, open, high, low, close, volume, delivery_pct?, source}
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, List, Optional

from services import pg_client

logger = logging.getLogger(__name__)


async def upsert_bars(bars: Iterable[dict]) -> int:
    """Insert/update OHLCV rows. Returns count written."""
    pool = await pg_client.get_pool()
    if pool is None:
        logger.warning("upsert_bars: no pg pool")
        return 0
    payload = []
    for b in bars:
        sym = b.get("nse_symbol") or b.get("symbol")
        if not sym:
            continue
        payload.append((
            sym.upper().strip(),
            b["bar_date"],
            float(b["open"]),
            float(b["high"]),
            float(b["low"]),
            float(b["close"]),
            int(b["volume"]) if b.get("volume") is not None else None,
            int(b["delivery_qty"]) if b.get("delivery_qty") is not None else None,
            float(b["delivery_pct"]) if b.get("delivery_pct") is not None else None,
            b.get("source") or "manual",
        ))
    if not payload:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO stock_ohlcv (nse_symbol, bar_date, open_price, high_price,
                                     low_price, close_price, volume, delivery_qty,
                                     delivery_pct, source)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (nse_symbol, bar_date) DO UPDATE SET
                open_price   = EXCLUDED.open_price,
                high_price   = EXCLUDED.high_price,
                low_price    = EXCLUDED.low_price,
                close_price  = EXCLUDED.close_price,
                volume       = EXCLUDED.volume,
                delivery_qty = EXCLUDED.delivery_qty,
                delivery_pct = EXCLUDED.delivery_pct,
                source       = EXCLUDED.source,
                ingested_at  = NOW()
            """,
            payload,
        )
    return len(payload)


async def load_bars(symbol: str,
                    end_date: Optional[date] = None,
                    lookback_bars: int = 260) -> List[dict]:
    """Return bars for `symbol`, ascending by date, capped at `lookback_bars`."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        if end_date is not None:
            rows = await conn.fetch(
                """
                SELECT bar_date, open_price AS open, high_price AS high,
                       low_price AS low, close_price AS close,
                       volume, delivery_pct
                FROM stock_ohlcv
                WHERE nse_symbol = $1 AND bar_date <= $2
                ORDER BY bar_date DESC
                LIMIT $3
                """,
                symbol.upper(), end_date, lookback_bars,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT bar_date, open_price AS open, high_price AS high,
                       low_price AS low, close_price AS close,
                       volume, delivery_pct
                FROM stock_ohlcv
                WHERE nse_symbol = $1
                ORDER BY bar_date DESC
                LIMIT $2
                """,
                symbol.upper(), lookback_bars,
            )
    # asyncpg returns NUMERIC columns as Decimal; coerce to float so the
    # feature calculator's mixed-arithmetic (float SMA constants etc.) doesn't
    # blow up with `Decimal − float` TypeErrors and silently drop the symbol.
    bars: List[dict] = []
    for r in rows:
        bars.append({
            "bar_date": r["bar_date"],
            "open":  float(r["open"])  if r["open"]  is not None else None,
            "high":  float(r["high"])  if r["high"]  is not None else None,
            "low":   float(r["low"])   if r["low"]   is not None else None,
            "close": float(r["close"]) if r["close"] is not None else None,
            "volume": int(r["volume"]) if r["volume"] is not None else None,
            "delivery_pct": (float(r["delivery_pct"])
                              if r["delivery_pct"] is not None else None),
        })
    bars.reverse()      # ascending order — feature_calculator's contract
    return bars


async def latest_bar_date(symbol: str) -> Optional[date]:
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT MAX(bar_date) AS d FROM stock_ohlcv WHERE nse_symbol = $1",
            symbol.upper(),
        )
    return row["d"] if row else None
