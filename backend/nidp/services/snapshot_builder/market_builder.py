"""Build the per-date `nidp.market_daily_snapshot` row.

One row per date. Pulls headline indices, FII/DII totals, RBI yields,
and computes market-breadth from prices_eod.

Carry-forward: if a domain doesn't have a row for `target_date`, we
fall back to the most-recent prior date and stamp it in `*_as_of` —
never silently pretend it's current.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class CarryForward:
    domain: str
    as_of: date
    lag_days: int


@dataclass
class MarketBuildResult:
    built: bool
    rows: int = 0
    carry_forward: list[CarryForward] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def _latest_index_close(
    conn: asyncpg.Connection, target_date: date, name_pattern: str,
):
    """Most recent index_eod row matching name_pattern (ILIKE) on or
    before target_date. Returns (close, pct_change, as_of) or (None, None, None)."""
    return await conn.fetchrow(
        """
        SELECT close_price, pct_change, as_of_date
          FROM nidp.index_eod
         WHERE as_of_date <= $1::date
           AND index_name ILIKE $2
         ORDER BY as_of_date DESC
         LIMIT 1
        """,
        target_date, name_pattern,
    )


async def _latest_fii_dii_segment(
    conn: asyncpg.Connection, target_date: date, category: str, segment: str,
):
    return await conn.fetchrow(
        """
        SELECT net_value_cr, as_of_date
          FROM nidp.fii_dii_flows
         WHERE as_of_date <= $1::date AND category = $2 AND segment = $3
         ORDER BY as_of_date DESC
         LIMIT 1
        """,
        target_date, category, segment,
    )


async def _latest_yield(
    conn: asyncpg.Connection, target_date: date, tenor: str,
):
    return await conn.fetchrow(
        """
        SELECT yield_pct, as_of_date
          FROM nidp.rbi_yields
         WHERE as_of_date <= $1::date AND tenor = $2
         ORDER BY as_of_date DESC
         LIMIT 1
        """,
        target_date, tenor,
    )


async def _market_breadth(
    conn: asyncpg.Connection, target_date: date,
):
    """Counts of advances / declines / unchanged from prices_eod for
    the target date. Returns dict with counts + total volume/value."""
    row = await conn.fetchrow(
        """
        SELECT
            sum(CASE WHEN close_price > prev_close THEN 1 ELSE 0 END) AS adv,
            sum(CASE WHEN close_price < prev_close THEN 1 ELSE 0 END) AS dec,
            sum(CASE WHEN close_price = prev_close THEN 1 ELSE 0 END) AS unc,
            sum(volume)                                                  AS vol,
            sum(turnover) / 1e7                                          AS val_cr
          FROM nidp.prices_eod
         WHERE as_of_date = $1::date
           AND series IN ('EQ','BE','BZ','SM')
           AND close_price IS NOT NULL AND prev_close IS NOT NULL
        """,
        target_date,
    )
    return row


def _lag(target: date, actual) -> int:
    if actual is None:
        return 0
    return (target - actual).days


async def build_market(
    conn: asyncpg.Connection,
    target_date: date,
    build_run_id: uuid.UUID,
) -> MarketBuildResult:
    res = MarketBuildResult(built=True)

    # Indices
    n50 = await _latest_index_close(conn, target_date, "Nifty 50%")
    n500 = await _latest_index_close(conn, target_date, "Nifty 500%")
    bnk = await _latest_index_close(conn, target_date, "Nifty Bank%")
    vix = await _latest_index_close(conn, target_date, "India VIX%")

    if n50 and n50["as_of_date"] != target_date:
        res.carry_forward.append(CarryForward(
            "index_eod[Nifty 50]", n50["as_of_date"], _lag(target_date, n50["as_of_date"]),
        ))
    if not n50:
        res.warnings.append("Nifty 50 not present (even historically)")

    # FII/DII
    fii_cash = await _latest_fii_dii_segment(conn, target_date, "FII", "EQUITY_CASH")
    dii_cash = await _latest_fii_dii_segment(conn, target_date, "DII", "EQUITY_CASH")
    fii_fno_idx = await _latest_fii_dii_segment(conn, target_date, "FII", "INDEX_FUTURES")
    dii_fno_idx = await _latest_fii_dii_segment(conn, target_date, "DII", "INDEX_FUTURES")

    if fii_cash and fii_cash["as_of_date"] != target_date:
        res.carry_forward.append(CarryForward(
            "fii_dii_flows[FII cash]", fii_cash["as_of_date"],
            _lag(target_date, fii_cash["as_of_date"]),
        ))

    # Yields
    y10 = await _latest_yield(conn, target_date, "10Y")
    y91 = await _latest_yield(conn, target_date, "91D")

    if y10 and y10["as_of_date"] != target_date:
        res.carry_forward.append(CarryForward(
            "rbi_yields[10Y]", y10["as_of_date"], _lag(target_date, y10["as_of_date"]),
        ))

    breadth = await _market_breadth(conn, target_date)

    # As-of bookkeeping
    prices_as_of = target_date if (breadth and breadth["adv"] is not None) else None
    fii_dii_as_of = (fii_cash and fii_cash["as_of_date"]) or None
    yields_as_of = (y10 and y10["as_of_date"]) or None
    index_as_of = (n50 and n50["as_of_date"]) or None

    # Single-row write — DELETE + INSERT for idempotency
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM nidp.market_daily_snapshot WHERE as_of_date = $1::date",
            target_date,
        )
        await conn.execute(
            """
            INSERT INTO nidp.market_daily_snapshot (
                as_of_date,
                nifty50_close, nifty50_pct_change,
                nifty500_close, bank_nifty_close, india_vix,
                fii_cash_net_cr, dii_cash_net_cr,
                fii_fno_index_net_cr, dii_fno_index_net_cr,
                rbi_10y_yield, rbi_91d_yield,
                advances_count, declines_count, unchanged_count,
                total_traded_value_cr, total_traded_volume,
                prices_as_of, fii_dii_as_of, yields_as_of, index_as_of,
                build_run_id, built_at
            ) VALUES (
                $1::date,
                $2, $3,
                $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12,
                $13, $14, $15,
                $16, $17,
                $18::date, $19::date, $20::date, $21::date,
                $22, NOW()
            )
            """,
            target_date,
            n50["close_price"] if n50 else None,
            n50["pct_change"] if n50 else None,
            n500["close_price"] if n500 else None,
            bnk["close_price"] if bnk else None,
            vix["close_price"] if vix else None,
            fii_cash["net_value_cr"] if fii_cash else None,
            dii_cash["net_value_cr"] if dii_cash else None,
            fii_fno_idx["net_value_cr"] if fii_fno_idx else None,
            dii_fno_idx["net_value_cr"] if dii_fno_idx else None,
            y10["yield_pct"] if y10 else None,
            y91["yield_pct"] if y91 else None,
            int(breadth["adv"] or 0) if breadth else None,
            int(breadth["dec"] or 0) if breadth else None,
            int(breadth["unc"] or 0) if breadth else None,
            float(breadth["val_cr"] or 0) if breadth else None,
            int(breadth["vol"] or 0) if breadth else None,
            prices_as_of, fii_dii_as_of, yields_as_of, index_as_of,
            build_run_id,
        )

    res.rows = 1
    return res
