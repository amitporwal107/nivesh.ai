"""nidp.nse_financials_quarterly writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_FIN"


# Columns inserted, in order. Mirrors the table DDL.
_COLS = [
    "symbol", "period_end", "period_start", "period_type", "consolidated", "audited",
    "revenue_from_ops_cr", "other_income_cr", "total_income_cr", "total_expenses_cr",
    "ebitda_cr", "finance_costs_cr", "depreciation_cr",
    "pbt_before_exc_cr", "exceptional_items_cr", "pbt_cr", "tax_expense_cr",
    "pat_continuing_cr", "pat_discontinuing_cr", "pat_cr",
    "pat_attrib_owners_cr", "pat_attrib_minority_cr",
    "eps_basic", "eps_diluted", "face_value",
    "equity_share_capital_cr", "other_equity_cr", "total_equity_cr",
    "long_term_debt_cr", "short_term_debt_cr", "cash_and_equiv_cr",
    "interest_earned_cr", "interest_expended_cr", "nim_pct",
    "filing_id", "xbrl_url", "broadcast_at",
    "source", "source_run_id",
]


async def upsert_financials(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0

    args = []
    for r in rows:
        args.append((
            r["symbol"],
            to_date(r["period_end"]),
            to_date(r.get("period_start")),
            r.get("period_type") or "UNKNOWN",
            bool(r["consolidated"]),
            r.get("audited"),
            r.get("revenue_from_ops_cr"),
            r.get("other_income_cr"),
            r.get("total_income_cr"),
            r.get("total_expenses_cr"),
            r.get("ebitda_cr"),
            r.get("finance_costs_cr"),
            r.get("depreciation_cr"),
            r.get("pbt_before_exc_cr"),
            r.get("exceptional_items_cr"),
            r.get("pbt_cr"),
            r.get("tax_expense_cr"),
            r.get("pat_continuing_cr"),
            r.get("pat_discontinuing_cr"),
            r.get("pat_cr"),
            r.get("pat_attrib_owners_cr"),
            r.get("pat_attrib_minority_cr"),
            r.get("eps_basic"),
            r.get("eps_diluted"),
            r.get("face_value"),
            r.get("equity_share_capital_cr"),
            r.get("other_equity_cr"),
            r.get("total_equity_cr"),
            r.get("long_term_debt_cr"),
            r.get("short_term_debt_cr"),
            r.get("cash_and_equiv_cr"),
            r.get("interest_earned_cr"),
            r.get("interest_expended_cr"),
            r.get("nim_pct"),
            r.get("filing_id"),
            r.get("xbrl_url"),
            _to_tstz(r.get("broadcast_at")),
            SOURCE_NAME,
            run_id,
        ))

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.nse_financials_quarterly
                    (symbol, period_end, period_start, period_type, consolidated, audited,
                     revenue_from_ops_cr, other_income_cr, total_income_cr, total_expenses_cr,
                     ebitda_cr, finance_costs_cr, depreciation_cr,
                     pbt_before_exc_cr, exceptional_items_cr, pbt_cr, tax_expense_cr,
                     pat_continuing_cr, pat_discontinuing_cr, pat_cr,
                     pat_attrib_owners_cr, pat_attrib_minority_cr,
                     eps_basic, eps_diluted, face_value,
                     equity_share_capital_cr, other_equity_cr, total_equity_cr,
                     long_term_debt_cr, short_term_debt_cr, cash_and_equiv_cr,
                     interest_earned_cr, interest_expended_cr, nim_pct,
                     filing_id, xbrl_url, broadcast_at,
                     source, source_run_id, ingested_at)
                VALUES ($1, $2::date, $3::date, $4, $5, $6,
                        $7, $8, $9, $10,
                        $11, $12, $13,
                        $14, $15, $16, $17,
                        $18, $19, $20,
                        $21, $22,
                        $23, $24, $25,
                        $26, $27, $28,
                        $29, $30, $31,
                        $32, $33, $34,
                        $35, $36, $37::timestamptz,
                        $38, $39, NOW())
                ON CONFLICT (symbol, period_end, consolidated, source) DO UPDATE SET
                    period_start            = EXCLUDED.period_start,
                    period_type             = EXCLUDED.period_type,
                    audited                 = EXCLUDED.audited,
                    revenue_from_ops_cr     = COALESCE(EXCLUDED.revenue_from_ops_cr,     nse_financials_quarterly.revenue_from_ops_cr),
                    other_income_cr         = COALESCE(EXCLUDED.other_income_cr,         nse_financials_quarterly.other_income_cr),
                    total_income_cr         = COALESCE(EXCLUDED.total_income_cr,         nse_financials_quarterly.total_income_cr),
                    total_expenses_cr       = COALESCE(EXCLUDED.total_expenses_cr,       nse_financials_quarterly.total_expenses_cr),
                    ebitda_cr               = COALESCE(EXCLUDED.ebitda_cr,               nse_financials_quarterly.ebitda_cr),
                    finance_costs_cr        = COALESCE(EXCLUDED.finance_costs_cr,        nse_financials_quarterly.finance_costs_cr),
                    depreciation_cr         = COALESCE(EXCLUDED.depreciation_cr,         nse_financials_quarterly.depreciation_cr),
                    pbt_before_exc_cr       = COALESCE(EXCLUDED.pbt_before_exc_cr,       nse_financials_quarterly.pbt_before_exc_cr),
                    exceptional_items_cr    = COALESCE(EXCLUDED.exceptional_items_cr,    nse_financials_quarterly.exceptional_items_cr),
                    pbt_cr                  = COALESCE(EXCLUDED.pbt_cr,                  nse_financials_quarterly.pbt_cr),
                    tax_expense_cr          = COALESCE(EXCLUDED.tax_expense_cr,          nse_financials_quarterly.tax_expense_cr),
                    pat_continuing_cr       = COALESCE(EXCLUDED.pat_continuing_cr,       nse_financials_quarterly.pat_continuing_cr),
                    pat_discontinuing_cr    = COALESCE(EXCLUDED.pat_discontinuing_cr,    nse_financials_quarterly.pat_discontinuing_cr),
                    pat_cr                  = COALESCE(EXCLUDED.pat_cr,                  nse_financials_quarterly.pat_cr),
                    pat_attrib_owners_cr    = COALESCE(EXCLUDED.pat_attrib_owners_cr,    nse_financials_quarterly.pat_attrib_owners_cr),
                    pat_attrib_minority_cr  = COALESCE(EXCLUDED.pat_attrib_minority_cr,  nse_financials_quarterly.pat_attrib_minority_cr),
                    eps_basic               = COALESCE(EXCLUDED.eps_basic,               nse_financials_quarterly.eps_basic),
                    eps_diluted             = COALESCE(EXCLUDED.eps_diluted,             nse_financials_quarterly.eps_diluted),
                    face_value              = COALESCE(EXCLUDED.face_value,              nse_financials_quarterly.face_value),
                    equity_share_capital_cr = COALESCE(EXCLUDED.equity_share_capital_cr, nse_financials_quarterly.equity_share_capital_cr),
                    other_equity_cr         = COALESCE(EXCLUDED.other_equity_cr,         nse_financials_quarterly.other_equity_cr),
                    total_equity_cr         = COALESCE(EXCLUDED.total_equity_cr,         nse_financials_quarterly.total_equity_cr),
                    long_term_debt_cr       = COALESCE(EXCLUDED.long_term_debt_cr,       nse_financials_quarterly.long_term_debt_cr),
                    short_term_debt_cr      = COALESCE(EXCLUDED.short_term_debt_cr,      nse_financials_quarterly.short_term_debt_cr),
                    cash_and_equiv_cr       = COALESCE(EXCLUDED.cash_and_equiv_cr,       nse_financials_quarterly.cash_and_equiv_cr),
                    interest_earned_cr      = COALESCE(EXCLUDED.interest_earned_cr,      nse_financials_quarterly.interest_earned_cr),
                    interest_expended_cr    = COALESCE(EXCLUDED.interest_expended_cr,    nse_financials_quarterly.interest_expended_cr),
                    nim_pct                 = COALESCE(EXCLUDED.nim_pct,                 nse_financials_quarterly.nim_pct),
                    filing_id               = EXCLUDED.filing_id,
                    xbrl_url                = EXCLUDED.xbrl_url,
                    broadcast_at            = EXCLUDED.broadcast_at,
                    source_run_id           = EXCLUDED.source_run_id,
                    ingested_at             = NOW()
                """,
                args,
            )
    logger.info("nse_financials upserted %d rows", len(args))
    return len(args)


def _to_tstz(s: Any):
    """Coerce ISO string to datetime for TIMESTAMPTZ binding."""
    if s is None:
        return None
    if hasattr(s, "isoformat"):
        return s
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None
