"""Build per-(symbol, series, date) rows of `nidp.stock_daily_snapshot`.

Joins:
    prices_eod        — primary; row exists for every persisted symbol
    delivery_data     — left join on (symbol, series, date); may lag T+1
    index_constituents — most-recent as_of_date <= target, projected to
                         in_nifty50 / in_nifty100 / in_nifty500 flags
    bulk_deals/block_deals — aggregated by (symbol, side) for the date
    corporate_actions — flag if any with ex_date in (D, D+7d]

Single-transaction DELETE+INSERT for idempotency. Uses a CTE to keep
the read-then-write pattern atomic on TimescaleDB hypertables.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class StockBuildResult:
    rows: int = 0
    constituents_as_of: date | None = None
    warnings: list[str] = field(default_factory=list)


# CTE-driven single-pass build. Index membership uses the latest
# as_of_date <= target_date; deal aggregates are JOINed in separate
# CTEs to keep the join graph readable.
_BUILD_SQL = """
WITH cons_latest AS (
    SELECT index_name, max(as_of_date) AS max_as_of
      FROM nidp.index_constituents
     WHERE as_of_date <= $1::date
     GROUP BY index_name
),
cons_eff AS (
    SELECT c.index_name, c.symbol, c.industry, c.as_of_date
      FROM nidp.index_constituents c
      JOIN cons_latest cl
        ON cl.index_name = c.index_name AND cl.max_as_of = c.as_of_date
),
bulk_agg AS (
    SELECT symbol,
           count(*)::int AS deal_count,
           sum(CASE WHEN deal_type='BUY'  THEN quantity ELSE 0 END)::bigint AS buy_qty,
           sum(CASE WHEN deal_type='SELL' THEN quantity ELSE 0 END)::bigint AS sell_qty
      FROM nidp.bulk_deals
     WHERE as_of_date = $1::date
     GROUP BY symbol
),
block_agg AS (
    SELECT symbol,
           count(*)::int AS deal_count,
           sum(CASE WHEN deal_type='BUY'  THEN quantity ELSE 0 END)::bigint AS buy_qty,
           sum(CASE WHEN deal_type='SELL' THEN quantity ELSE 0 END)::bigint AS sell_qty
      FROM nidp.block_deals
     WHERE as_of_date = $1::date
     GROUP BY symbol
),
ca_upcoming AS (
    SELECT symbol,
           array_agg(DISTINCT action_type)::text[] AS types
      FROM nidp.corporate_actions
     WHERE ex_date > $1::date AND ex_date <= ($1::date + INTERVAL '7 days')
     GROUP BY symbol
),
-- Exact match (not ILIKE 'Nifty 50%') because the % wildcard would
-- also match 'Nifty 500', causing a symbol in BOTH Nifty 50 and
-- Nifty 500 to appear twice in n50 — which fans out the join and
-- breaks the (symbol, as_of_date, series) PK on insert.
n50  AS (SELECT DISTINCT symbol FROM cons_eff WHERE index_name = 'Nifty 50'),
n100 AS (SELECT DISTINCT symbol FROM cons_eff WHERE index_name = 'Nifty 100'),
n500 AS (SELECT DISTINCT symbol FROM cons_eff WHERE index_name = 'Nifty 500'),
-- DISTINCT ON (symbol) handles the case where the same symbol has
-- two industry values in the constituent file (data error upstream).
ind500 AS (SELECT DISTINCT ON (symbol) symbol, industry
             FROM cons_eff WHERE index_name = 'Nifty 500')
INSERT INTO nidp.stock_daily_snapshot (
    symbol, as_of_date, series, isin,
    open_price, high_price, low_price, close_price, prev_close,
    volume, turnover, trades,
    return_1d_pct,
    deliv_qty, deliv_pct,
    in_nifty50, in_nifty100, in_nifty500, industry,
    bulk_deal_count, bulk_buy_qty, bulk_sell_qty,
    block_deal_count, block_buy_qty, block_sell_qty,
    has_upcoming_ca, upcoming_ca_types,
    prices_as_of, delivery_as_of, constituents_as_of,
    build_run_id, built_at
)
SELECT
    p.symbol, p.as_of_date, p.series, p.isin,
    p.open_price, p.high_price, p.low_price, p.close_price, p.prev_close,
    p.volume, p.turnover, p.trades,
    CASE
        WHEN p.prev_close IS NOT NULL AND p.prev_close > 0 AND p.close_price IS NOT NULL
        THEN ((p.close_price - p.prev_close) / p.prev_close * 100)::numeric(10,4)
    END,
    d.deliverable_qty, d.deliverable_pct,
    (n50.symbol  IS NOT NULL),
    (n100.symbol IS NOT NULL),
    (n500.symbol IS NOT NULL),
    ind500.industry,
    COALESCE(bk.deal_count, 0), COALESCE(bk.buy_qty, 0), COALESCE(bk.sell_qty, 0),
    COALESCE(bl.deal_count, 0), COALESCE(bl.buy_qty, 0), COALESCE(bl.sell_qty, 0),
    (ca.types IS NOT NULL),
    ca.types,
    p.as_of_date,                                          -- prices_as_of = today
    d.as_of_date,                                          -- delivery_as_of (may be null)
    (SELECT max(max_as_of) FROM cons_latest),              -- constituents_as_of
    $2,                                                     -- build_run_id
    NOW()
  FROM nidp.prices_eod p
  -- delivery_data PK is (date, symbol, series, source). Without
  -- filtering by source the join fans out if any past run wrote
  -- under a different source name (or some other feed ever
  -- populated this table) — producing duplicate (symbol,
  -- as_of_date, series) on insert. Pin to the canonical source.
  LEFT JOIN LATERAL (
      SELECT deliverable_qty, deliverable_pct, as_of_date
        FROM nidp.delivery_data dd
       WHERE dd.as_of_date = p.as_of_date
         AND dd.symbol     = p.symbol
         AND dd.series     = p.series
         AND dd.source     = 'NSE_SEC_BHAVDATA'
       LIMIT 1
  ) d ON TRUE
  LEFT JOIN n50    ON n50.symbol  = p.symbol
  LEFT JOIN n100   ON n100.symbol = p.symbol
  LEFT JOIN n500   ON n500.symbol = p.symbol
  LEFT JOIN ind500 ON ind500.symbol = p.symbol
  LEFT JOIN bulk_agg  bk ON bk.symbol = p.symbol
  LEFT JOIN block_agg bl ON bl.symbol = p.symbol
  LEFT JOIN ca_upcoming ca ON ca.symbol = p.symbol
 WHERE p.as_of_date = $1::date
   AND p.series IN ('EQ','BE','BZ','SM')
   AND p.source = 'NSE_BHAVCOPY'
ON CONFLICT (symbol, as_of_date, series) DO UPDATE SET
    isin               = EXCLUDED.isin,
    open_price         = EXCLUDED.open_price,
    high_price         = EXCLUDED.high_price,
    low_price          = EXCLUDED.low_price,
    close_price        = EXCLUDED.close_price,
    prev_close         = EXCLUDED.prev_close,
    volume             = EXCLUDED.volume,
    turnover           = EXCLUDED.turnover,
    trades             = EXCLUDED.trades,
    return_1d_pct      = EXCLUDED.return_1d_pct,
    deliv_qty          = EXCLUDED.deliv_qty,
    deliv_pct          = EXCLUDED.deliv_pct,
    in_nifty50         = EXCLUDED.in_nifty50,
    in_nifty100        = EXCLUDED.in_nifty100,
    in_nifty500        = EXCLUDED.in_nifty500,
    industry           = EXCLUDED.industry,
    bulk_deal_count    = EXCLUDED.bulk_deal_count,
    bulk_buy_qty       = EXCLUDED.bulk_buy_qty,
    bulk_sell_qty      = EXCLUDED.bulk_sell_qty,
    block_deal_count   = EXCLUDED.block_deal_count,
    block_buy_qty      = EXCLUDED.block_buy_qty,
    block_sell_qty     = EXCLUDED.block_sell_qty,
    has_upcoming_ca    = EXCLUDED.has_upcoming_ca,
    upcoming_ca_types  = EXCLUDED.upcoming_ca_types,
    prices_as_of       = EXCLUDED.prices_as_of,
    delivery_as_of     = EXCLUDED.delivery_as_of,
    constituents_as_of = EXCLUDED.constituents_as_of,
    build_run_id       = EXCLUDED.build_run_id,
    built_at           = EXCLUDED.built_at
"""


async def build_stocks(
    conn: asyncpg.Connection,
    target_date: date,
    build_run_id: uuid.UUID,
) -> StockBuildResult:
    res = StockBuildResult()

    # Pure UPSERT — no DELETE+INSERT. Same target row is overwritten
    # if it already exists, so retries are idempotent and a stray
    # join-fan-out can't crash the whole batch.
    async with conn.transaction():
        result = await conn.execute(_BUILD_SQL, target_date, build_run_id)

    # asyncpg returns "INSERT 0 N" on bulk insert
    rows = int(result.rsplit(" ", 1)[-1]) if result.startswith("INSERT") else 0
    res.rows = rows

    cons_as_of = await conn.fetchval(
        """
        SELECT max(as_of_date) FROM nidp.index_constituents
         WHERE as_of_date <= $1::date
        """,
        target_date,
    )
    res.constituents_as_of = cons_as_of

    if rows == 0:
        res.warnings.append("stock_daily_snapshot built 0 rows")
    return res
