"""Capital flows + large-trade prints — FII/DII, bulk deals, block deals.

Bulk and block deals have ONE reader, `read_deals` below: /flows/bulk-deals, /flows/block-deals and the trading
desk's /desk/deals (desk_market.py) all call it, so the deal rows and their enrichment are worked out in one SQL.

Each deal row also carries, where the warehouse has it (null otherwise, never 0):
  total_shares / shares_period_end   the company's total shares from its latest shareholding pattern ON OR BEFORE
                                     the deal date (nidp.shareholding_pattern); pct_of_shares = quantity ÷ total_shares
                                     × 100, 4 decimals, worked out by the caller (`pct_of_shares`)
  close_on_day / prev_close          the stock's own close and previous close on the deal date (nidp.prices_eod,
                                     the first normal-market series in EQ, BE, BZ, SM, ST)
  next_date / next_close             the first session after the deal date and its close, null until it exists
  ingested_at                        when Nivesh loaded the row from NSE's bulk / block deal file
Every row is an exchange disclosure (NSE's own file); nothing here is inferred.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/flows", tags=["flows"], dependencies=[Depends(require_api_key)])

DEALS_SOURCE = "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)"
DEAL_SERIES = ["EQ", "BE", "BZ", "SM", "ST"]

# $1 first day or NULL, $2 last day or NULL, $3 'all' | 'bulk' | 'block', $4 symbol or NULL, $5 client LIKE pattern or
# NULL, $6 limit, $7 offset, $8 the price series in preference order. `total` counts every match before the page.
# Newest day first, largest value first within a day.
DEALS_SQL = """
    WITH d AS (
        SELECT as_of_date, 'bulk' AS kind, symbol, client_name, deal_type, quantity, avg_price, deal_seq, remarks, ingested_at
          FROM nidp.bulk_deals
         WHERE $3::text IN ('all', 'bulk')
           AND ($1::date IS NULL OR as_of_date >= $1) AND ($2::date IS NULL OR as_of_date <= $2)
           AND ($4::text IS NULL OR symbol = $4)
           AND ($5::text IS NULL OR UPPER(client_name) LIKE $5)
        UNION ALL
        SELECT as_of_date, 'block' AS kind, symbol, client_name, deal_type, quantity, avg_price, deal_seq, remarks, ingested_at
          FROM nidp.block_deals
         WHERE $3::text IN ('all', 'block')
           AND ($1::date IS NULL OR as_of_date >= $1) AND ($2::date IS NULL OR as_of_date <= $2)
           AND ($4::text IS NULL OR symbol = $4)
           AND ($5::text IS NULL OR UPPER(client_name) LIKE $5)
    ), page AS (
        SELECT d.*, COUNT(*) OVER () AS total
          FROM d
         ORDER BY as_of_date DESC, quantity * avg_price DESC NULLS LAST, symbol, client_name, deal_seq
         LIMIT $6 OFFSET $7
    )
    SELECT p.as_of_date, p.kind, p.symbol, p.client_name, p.deal_type, p.quantity, p.avg_price, p.deal_seq, p.remarks,
           p.ingested_at, p.total,
           sh.total_shares, sh.period_end AS shares_period_end,
           px.close_price AS close_on_day, px.prev_close,
           nx.as_of_date AS next_date, nx.close_price AS next_close
      FROM page p
      LEFT JOIN LATERAL (
            SELECT s.total_shares, s.period_end
              FROM nidp.shareholding_pattern s
             WHERE s.symbol = p.symbol AND s.period_end <= p.as_of_date AND s.total_shares > 0
             ORDER BY s.period_end DESC
             LIMIT 1) sh ON TRUE
      LEFT JOIN LATERAL (
            SELECT e.close_price, e.prev_close
              FROM nidp.prices_eod e
             WHERE e.symbol = p.symbol AND e.as_of_date = p.as_of_date AND e.series = ANY($8::text[])
             ORDER BY array_position($8::text[], e.series)
             LIMIT 1) px ON TRUE
      LEFT JOIN LATERAL (
            SELECT e.as_of_date, e.close_price
              FROM nidp.prices_eod e
             WHERE e.symbol = p.symbol AND e.as_of_date > p.as_of_date AND e.series = ANY($8::text[])
             ORDER BY e.as_of_date, array_position($8::text[], e.series)
             LIMIT 1) nx ON TRUE
     ORDER BY p.as_of_date DESC, p.quantity * p.avg_price DESC NULLS LAST, p.symbol, p.client_name, p.deal_seq
"""


async def read_deals(conn: Any, *, start: Optional[date], end: Optional[date], kind: str = "all",
                     symbol: Optional[str] = None, client: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> list:
    """Bulk and block deal rows with their enrichment (see the module docstring), newest day first."""
    pattern = f"%{client.upper()}%" if client else None
    return await conn.fetch(DEALS_SQL, start, end, kind, symbol, pattern, limit, offset, DEAL_SERIES)


def pct_of_shares(quantity: Any, total_shares: Any) -> Optional[float]:
    """quantity ÷ total shares × 100, to 4 decimals. None when either is missing or the share count is not positive."""
    try:
        q, t = float(quantity), float(total_shares)
    except (TypeError, ValueError):
        return None
    return round(q / t * 100.0, 4) if t > 0 and q >= 0 else None


def _deal_dict(r: Any) -> Dict[str, Any]:
    d = row_to_dict(r)
    d.pop("total", None)
    d["pct_of_shares"] = pct_of_shares(r.get("quantity"), r.get("total_shares"))
    return d


@router.get("/fii-dii", summary="FII / DII net flows by category × segment")
async def fii_dii(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="FII | DII | PROP | CLIENT"),
    segment: Optional[str] = Query(
        None,
        description="EQUITY_CASH | INDEX_FUTURES | INDEX_OPTIONS | STOCK_FUTURES | STOCK_OPTIONS",
    ),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, category, segment,
                   buy_value_cr, sell_value_cr, net_value_cr,
                   buy_contracts, sell_contracts, net_contracts,
                   open_interest
              FROM nidp.fii_dii_flows
             WHERE ($1::date IS NULL OR as_of_date >= $1)
               AND ($2::date IS NULL OR as_of_date <= $2)
               AND ($3::text IS NULL OR category = $3)
               AND ($4::text IS NULL OR segment = $4)
             ORDER BY as_of_date DESC, category, segment
             LIMIT $5 OFFSET $6
            """,
            d_start, d_end, category, segment,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/bulk-deals", summary="Bulk deals (>0.5% of listed shares in one client name)")
async def bulk_deals(
    symbol: Optional[str] = Query(None),
    client: Optional[str] = Query(None, description="Substring match on client_name"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    return await _deals_page("bulk", symbol, client, start, end, page)


@router.get("/block-deals", summary="Block deals (negotiated > ₹10 Cr or > 5L shares)")
async def block_deals(
    symbol: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    return await _deals_page("block", symbol, client, start, end, page)


async def _deals_page(kind: str, symbol: Optional[str], client: Optional[str], start: Optional[str],
                      end: Optional[str], page: Dict[str, int]) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await read_deals(conn, start=d_start, end=d_end, kind=kind, symbol=sym, client=client,
                                limit=page["limit"], offset=page["offset"])
    total = int(rows[0]["total"]) if rows else None
    return envelope([_deal_dict(r) for r in rows], **page, total=total, extra={"source": DEALS_SOURCE})
