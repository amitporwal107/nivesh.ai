"""Quarterly financials + shareholding pattern (NSE XBRL)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="", tags=["fundamentals"], dependencies=[Depends(require_api_key)])


@router.get("/financials/{symbol}", summary="Quarterly financials (revenue/PAT/EPS/etc.)")
async def financials(
    symbol: str = Path(...),
    consolidated: Optional[bool] = Query(None, description="True = consolidated; False = standalone; omit for both"),
    period_from: Optional[str] = Query(None, description="period_end floor, YYYY-MM-DD"),
    period_to: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    p_from = parse_date(period_from, field="period_from")
    p_to = parse_date(period_to, field="period_to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, period_end, period_start, period_type,
                   consolidated, audited,
                   revenue_from_ops_cr, other_income_cr, total_income_cr,
                   total_expenses_cr, ebitda_cr,
                   finance_costs_cr, depreciation_cr,
                   pbt_before_exc_cr, exceptional_items_cr, pbt_cr,
                   tax_expense_cr, pat_cr, pat_attrib_owners_cr,
                   eps_basic, eps_diluted, face_value,
                   total_equity_cr, long_term_debt_cr, short_term_debt_cr,
                   cash_and_equiv_cr,
                   interest_earned_cr, interest_expended_cr, nim_pct,
                   filing_id, broadcast_at
              FROM nidp.nse_financials_quarterly
             WHERE symbol = $1
               AND ($2::boolean IS NULL OR consolidated = $2)
               AND ($3::date IS NULL OR period_end >= $3)
               AND ($4::date IS NULL OR period_end <= $4)
             ORDER BY period_end DESC, consolidated DESC
             LIMIT $5 OFFSET $6
            """,
            sym, consolidated, p_from, p_to, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})


@router.get("/shareholding/{symbol}", summary="Shareholding pattern (promoter/FII/DII split)")
async def shareholding(
    symbol: str = Path(...),
    period_from: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    p_from = parse_date(period_from, field="period_from")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, period_end,
                   promoter_pct, promoter_pledged_pct, promoter_pledged_to_total_pct,
                   fii_pct, dii_pct, mf_pct, insurance_pct, bank_fi_pct, govt_holding_pct,
                   public_pct, individual_pct, nri_pct, bodies_corporate_pct,
                   total_shares, promoter_shares, public_shares, pledged_shares,
                   broadcast_at
              FROM nidp.shareholding_pattern
             WHERE symbol = $1
               AND ($2::date IS NULL OR period_end >= $2)
             ORDER BY period_end DESC
             LIMIT $3 OFFSET $4
            """,
            sym, p_from, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})
