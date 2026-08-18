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
    raw_data: Optional[dict[str, Any]] = None,
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

    # Skip if no meaningful financial data was extracted
    financial_fields = ("pat_cr", "revenue_from_ops_cr", "total_income_cr", "pbt_cr",
                        "interest_earned_cr", "eps_basic")
    if not any(data.get(f) is not None for f in financial_fields):
        logger.warning("upsert_financials: all financial fields null for %s period=%s, skipping", symbol, period_end)
        return None
    period_start = _parse_date(data.get("period_start"))

    import json as _json

    run_id = source_run_id or str(uuid.uuid4())
    raw_data_json = _json.dumps(raw_data) if raw_data else None
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
                equity_share_capital_cr, total_equity_cr,
                long_term_debt_cr, short_term_debt_cr, cash_and_equiv_cr,
                interest_earned_cr, interest_expended_cr, nim_pct,
                source, source_run_id, ir_url, filing_id, broadcast_at, raw_data
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                $31,$32,$33,$34,$35,$36
            )
            ON CONFLICT (symbol, period_end, consolidated)
            DO UPDATE SET
                revenue_from_ops_cr     = COALESCE(EXCLUDED.revenue_from_ops_cr,     nidp.nse_financials_quarterly.revenue_from_ops_cr),
                total_income_cr         = COALESCE(EXCLUDED.total_income_cr,         nidp.nse_financials_quarterly.total_income_cr),
                pat_cr                  = COALESCE(EXCLUDED.pat_cr,                  nidp.nse_financials_quarterly.pat_cr),
                eps_basic               = COALESCE(EXCLUDED.eps_basic,               nidp.nse_financials_quarterly.eps_basic),
                ebitda_cr               = COALESCE(EXCLUDED.ebitda_cr,               nidp.nse_financials_quarterly.ebitda_cr),
                pbt_cr                  = COALESCE(EXCLUDED.pbt_cr,                  nidp.nse_financials_quarterly.pbt_cr),
                finance_costs_cr        = COALESCE(EXCLUDED.finance_costs_cr,        nidp.nse_financials_quarterly.finance_costs_cr),
                depreciation_cr         = COALESCE(EXCLUDED.depreciation_cr,         nidp.nse_financials_quarterly.depreciation_cr),
                face_value              = COALESCE(EXCLUDED.face_value,              nidp.nse_financials_quarterly.face_value),
                equity_share_capital_cr = COALESCE(EXCLUDED.equity_share_capital_cr, nidp.nse_financials_quarterly.equity_share_capital_cr),
                total_equity_cr         = COALESCE(EXCLUDED.total_equity_cr,         nidp.nse_financials_quarterly.total_equity_cr),
                long_term_debt_cr       = COALESCE(EXCLUDED.long_term_debt_cr,       nidp.nse_financials_quarterly.long_term_debt_cr),
                cash_and_equiv_cr       = COALESCE(EXCLUDED.cash_and_equiv_cr,       nidp.nse_financials_quarterly.cash_and_equiv_cr),
                raw_data                = COALESCE(EXCLUDED.raw_data,                nidp.nse_financials_quarterly.raw_data),
                source                  = EXCLUDED.source,
                source_run_id           = EXCLUDED.source_run_id,
                ingested_at             = NOW()
            RETURNING id
            """,
            symbol, period_end, period_start,
            (data.get("period_type") or "quarterly").lower(),   # normalize case (canonical=lower)
            bool(data.get("consolidated", False)), data.get("audited"),
            data.get("revenue_from_ops_cr"), data.get("other_income_cr"), data.get("total_income_cr"),
            data.get("total_expenses_cr"), data.get("ebitda_cr"), data.get("finance_costs_cr"),
            data.get("depreciation_cr"), data.get("pbt_before_exc_cr"), data.get("exceptional_items_cr"),
            data.get("pbt_cr"), data.get("tax_expense_cr"), data.get("pat_cr"),
            data.get("pat_attrib_owners_cr"), data.get("eps_basic"), data.get("eps_diluted"),
            data.get("face_value"),
            data.get("equity_share_capital_cr"), data.get("total_equity_cr"),
            data.get("long_term_debt_cr"), data.get("short_term_debt_cr"), data.get("cash_and_equiv_cr"),
            data.get("interest_earned_cr"), data.get("interest_expended_cr"), data.get("nim_pct"),
            source, run_id, ir_url, filing_id, broadcast_at, raw_data_json,
        )
    return row["id"] if row else None


def _quarter_end_on_or_before(d: "date") -> "date":
    """Snap a Screener month-end label onto the quarter it actually reports.

    Screener labels a shareholding table by the month it was published
    ("Jul 2026" -> 2026-07-31), but the figures are the *quarter's*
    filing. Writing the raw month-end pollutes shareholding_pattern's
    quarterly axis: a "latest quarter" lookup picks 2026-07-31 for a
    handful of symbols and 2026-06-30 for the rest, and any
    quarter-over-quarter delta silently compares mismatched periods.

    Returns the last quarter end on or before `d`. Used as a *predicate*
    (`d == _quarter_end_on_or_before(d)` iff d is a quarter end), not as a
    coercion: an interim month row carries different figures from the
    quarter row it sits next to (ADANIENT 2026-06-30 fii_pct 8.77 vs
    2026-07-31 fii_pct 10.51), so snapping it onto the quarter and letting
    the upsert win would overwrite a real quarter with interim data.
    """
    import calendar
    from datetime import date

    qm = ((d.month - 1) // 3) * 3 + 3            # 3, 6, 9 or 12
    q_end = date(d.year, qm, calendar.monthrange(d.year, qm)[1])
    if d >= q_end:
        return q_end
    pm, py = (qm - 3, d.year) if qm > 3 else (12, d.year - 1)
    return date(py, pm, calendar.monthrange(py, pm)[1])


async def upsert_shareholding(
    symbol: str,
    data: dict[str, Any],
    source: str = "screener_in",
    source_run_id: Optional[str] = None,
) -> bool:
    """Upsert a shareholding pattern row into nidp.shareholding_pattern.

    data must contain: period_end (ISO str), and at least one of
    promoter_pct / fii_pct / dii_pct / public_pct.
    Returns True if the row was written, False otherwise.
    """
    from datetime import datetime as _dt

    raw_period = data.get("period_end")
    if not raw_period:
        return False
    try:
        period_end = _dt.strptime(raw_period, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    # nidp.shareholding_pattern is a *quarterly* series and every consumer
    # (latest-quarter lookups, QoQ deltas, the 20-quarter backfill) assumes
    # that grain. Screener also surfaces interim month-end filings; those
    # carry real but non-quarter figures, so admitting them makes
    # "latest quarter" mean 2026-07-31 for a few symbols and 2026-06-30 for
    # the rest. Keep them out rather than corrupt the axis.
    if period_end != _quarter_end_on_or_before(period_end):
        logger.info(
            "shareholding: skipping non-quarter period_end %s for %s (%s)",
            period_end, symbol, source,
        )
        return False

    # Skip if no shareholding fields present
    shp_fields = ("promoter_pct", "fii_pct", "dii_pct", "public_pct")
    if not any(data.get(f) is not None for f in shp_fields):
        return False

    run_id = source_run_id or str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.shareholding_pattern
                (symbol, period_end, promoter_pct, fii_pct, dii_pct, public_pct,
                 source, source_run_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, period_end, source)
            DO UPDATE SET
                promoter_pct = COALESCE(EXCLUDED.promoter_pct, nidp.shareholding_pattern.promoter_pct),
                fii_pct      = COALESCE(EXCLUDED.fii_pct,      nidp.shareholding_pattern.fii_pct),
                dii_pct      = COALESCE(EXCLUDED.dii_pct,      nidp.shareholding_pattern.dii_pct),
                public_pct   = COALESCE(EXCLUDED.public_pct,   nidp.shareholding_pattern.public_pct),
                ingested_at  = NOW()
            """,
            symbol, period_end,
            data.get("promoter_pct"), data.get("fii_pct"),
            data.get("dii_pct"), data.get("public_pct"),
            source, run_id,
        )
    return True
