"""F&O bhavcopy — futures + options across every expiry, with chain helper."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/fno", tags=["fno"], dependencies=[Depends(require_api_key)])


@router.get("/{symbol}", summary="F&O contracts for one underlying (futures + options)")
async def fno_for_symbol(
    symbol: str = Path(..., description="Underlying ticker, e.g. RELIANCE, NIFTY, BANKNIFTY"),
    on: Optional[str] = Query(None, description="Trading day; defaults to most recent"),
    instrument_type: Optional[str] = Query(None, description="FUTIDX | FUTSTK | OPTIDX | OPTSTK"),
    expiry: Optional[str] = Query(None, description="Expiry date YYYY-MM-DD"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    on_d = parse_date(on, field="on")
    exp_d = parse_date(expiry, field="expiry")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if on_d is None:
            row = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM nidp.fno_bhavcopy WHERE ticker_symbol = $1",
                sym,
            )
            on_d = row["d"] if row else None
        if on_d is None:
            return envelope([], limit=page["limit"], offset=page["offset"],
                            extra={"symbol": sym, "as_of": None})
        rows = await conn.fetch(
            """
            SELECT as_of_date, ticker_symbol, instrument_type,
                   expiry_date, strike_price, option_type,
                   open_price, high_price, low_price, close_price,
                   settle_price, underlying_price,
                   open_interest, change_in_oi,
                   traded_volume, traded_value, num_trades
              FROM nidp.fno_bhavcopy
             WHERE ticker_symbol = $1
               AND as_of_date = $2
               AND ($3::text IS NULL OR instrument_type = $3)
               AND ($4::date IS NULL OR expiry_date = $4)
             ORDER BY expiry_date, option_type NULLS FIRST, strike_price NULLS FIRST
             LIMIT $5 OFFSET $6
            """,
            sym, on_d, instrument_type, exp_d,
            page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        **page,
        extra={"symbol": sym, "as_of": on_d.isoformat()},
    )


@router.get("/{symbol}/chain", summary="Latest options chain (CE+PE per strike)")
async def options_chain(
    symbol: str = Path(...),
    expiry: Optional[str] = Query(None, description="Expiry; defaults to nearest"),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    exp_d = parse_date(expiry, field="expiry")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Latest available date for this underlying
        latest = await conn.fetchrow(
            "SELECT MAX(as_of_date) AS d FROM nidp.fno_bhavcopy WHERE ticker_symbol = $1",
            sym,
        )
        if latest is None or latest["d"] is None:
            raise HTTPException(status_code=404, detail=f"no F&O data for {sym}")
        d = latest["d"]
        if exp_d is None:
            row = await conn.fetchrow(
                """
                SELECT MIN(expiry_date) AS d
                  FROM nidp.fno_bhavcopy
                 WHERE ticker_symbol = $1 AND as_of_date = $2
                   AND option_type IS NOT NULL
                   AND expiry_date >= $2
                """,
                sym, d,
            )
            exp_d = row["d"] if row else None
        if exp_d is None:
            raise HTTPException(status_code=404, detail=f"no upcoming expiry for {sym}")
        rows = await conn.fetch(
            """
            SELECT strike_price, option_type,
                   close_price, settle_price, underlying_price,
                   open_interest, change_in_oi,
                   traded_volume, traded_value
              FROM nidp.fno_bhavcopy
             WHERE ticker_symbol = $1
               AND as_of_date = $2
               AND expiry_date = $3
               AND option_type IN ('CE', 'PE')
             ORDER BY strike_price, option_type
            """,
            sym, d, exp_d,
        )
    chain: Dict[float, Dict[str, Any]] = {}
    for r in rows:
        strike = float(r["strike_price"]) if r["strike_price"] is not None else None
        if strike is None:
            continue
        side = r["option_type"]
        slot = chain.setdefault(strike, {"strike": strike, "CE": None, "PE": None})
        slot[side] = row_to_dict(r)
    return {
        "symbol":      sym,
        "as_of":       d.isoformat(),
        "expiry":      exp_d.isoformat(),
        "strikes":     [chain[k] for k in sorted(chain.keys())],
        "strike_count": len(chain),
    }


@router.get("/{symbol}/expiries", summary="Distinct expiries with contract counts")
async def expiries(symbol: str = Path(...)) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT expiry_date,
                   COUNT(*) FILTER (WHERE option_type = 'CE') AS ce_count,
                   COUNT(*) FILTER (WHERE option_type = 'PE') AS pe_count,
                   COUNT(*) FILTER (WHERE option_type IS NULL) AS futures_count,
                   MAX(as_of_date) AS latest_seen
              FROM nidp.fno_bhavcopy
             WHERE ticker_symbol = $1
             GROUP BY expiry_date
             ORDER BY expiry_date DESC
            """,
            sym,
        )
    return {"symbol": sym, "data": [row_to_dict(r) for r in rows], "count": len(rows)}
