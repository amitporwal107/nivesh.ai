"""Write extracted financials into nidp.nse_financials_quarterly."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


async def upsert_financials(
    symbol: str,
    data: dict[str, Any],
    source: str = "llm_extracted",
    ir_url: Optional[str] = None,
    filing_id: Optional[str] = None,
    broadcast_at: Optional[str] = None,
    source_run_id: Optional[str] = None,
) -> Optional[int]:
    from datetime import datetime as _dt

    def _parse_date(val):
        if val is None or not isinstance(val, str):
            return val
        try:
            return _dt.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return None

    period_end = _parse_date(data.get("period_end"))
    if not period_end:
        logger.warning("upsert_financials: no period_end for %s, skipping", symbol)
        return None
    period_start = _parse_date(data.get("period_start"))

    run_id = source_run_id or str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO nidp.nse_financials_quarterly (
                symbol, period_end, period_start, period_type, consolidated, audited,
                revenue_from_ops_cr, other_income_cr, total_income_cr, total_expenses_cr,
                ebitda_cr, finance_costs_cr, depreciation_cr,
                pbt_before_exc_cr, exceptional_items_cr, pbt_cr,
                tax_expense_cr, pat_cr, pat_attrib_owners_cr,
                eps_basic, eps_diluted, face_value,
                total_equity_cr, long_term_debt_cr, short_term_debt_cr, cash_and_equiv_cr,
                interest_earned_cr, interest_expended_cr, nim_pct,
                source, source_run_id, ir_url, filing_id, broadcast_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34
            )
            ON CONFLICT (symbol, period_end, consolidated)
            DO UPDATE SET
                revenue_from_ops_cr = COALESCE(EXCLUDED.revenue_from_ops_cr, nidp.nse_financials_quarterly.revenue_from_ops_cr),
                total_income_cr     = COALESCE(EXCLUDED.total_income_cr,     nidp.nse_financials_quarterly.total_income_cr),
                pat_cr              = COALESCE(EXCLUDED.pat_cr,              nidp.nse_financials_quarterly.pat_cr),
                eps_basic           = COALESCE(EXCLUDED.eps_basic,           nidp.nse_financials_quarterly.eps_basic),
                ebitda_cr           = COALESCE(EXCLUDED.ebitda_cr,           nidp.nse_financials_quarterly.ebitda_cr),
                pbt_cr              = COALESCE(EXCLUDED.pbt_cr,              nidp.nse_financials_quarterly.pbt_cr),
                source              = EXCLUDED.source,
                source_run_id       = EXCLUDED.source_run_id,
                ingested_at         = NOW()
            RETURNING id
            """,
            symbol, period_end, period_start, data.get("period_type","quarterly"),
            bool(data.get("consolidated",False)), data.get("audited"),
            data.get("revenue_from_ops_cr"), data.get("other_income_cr"), data.get("total_income_cr"),
            data.get("total_expenses_cr"), data.get("ebitda_cr"), data.get("finance_costs_cr"),
            data.get("depreciation_cr"), data.get("pbt_before_exc_cr"), data.get("exceptional_items_cr"),
            data.get("pbt_cr"), data.get("tax_expense_cr"), data.get("pat_cr"),
            data.get("pat_attrib_owners_cr"), data.get("eps_basic"), data.get("eps_diluted"),
            data.get("face_value"), data.get("total_equity_cr"), data.get("long_term_debt_cr"),
            data.get("short_term_debt_cr"), data.get("cash_and_equiv_cr"),
            data.get("interest_earned_cr"), data.get("interest_expended_cr"), data.get("nim_pct"),
            source, run_id, ir_url, filing_id, broadcast_at,
        )
    return row["id"] if row else None
