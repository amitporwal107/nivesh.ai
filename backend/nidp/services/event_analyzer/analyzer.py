"""Corporate event AI analyzer.

For each new event (earnings, announcement, dividend, etc.):
  1. Fetches historical financials, price context, recent announcements
  2. Constructs a rich prompt using all 20 event-type contexts
  3. Calls Claude Sonnet to generate bullish/bearish signal + reasoning
  4. Stores result in nidp.corporate_event_signals

Designed to run after each new event is ingested.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool
from .prompts import (
    ANNOUNCEMENT_PROMPT, EARNINGS_PROMPT, EVENT_TYPE_CONTEXT, SYSTEM
)

logger = logging.getLogger(__name__)
_MODEL = os.environ.get("NIDP_ANALYZER_MODEL", "claude-sonnet-4-6")


# ── Data fetchers ────────────────────────────────────────────────────

async def _get_historical_financials(conn, symbol: str, limit: int = 4) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT period_end, consolidated, revenue_from_ops_cr, total_income_cr,
               ebitda_cr, pat_cr, eps_basic, eps_diluted,
               interest_earned_cr, nim_pct
          FROM nidp.nse_financials_quarterly
         WHERE symbol = $1
         ORDER BY period_end DESC
         LIMIT $2
        """,
        symbol, limit,
    )
    return [dict(r) for r in rows]


async def _get_price_context(conn, symbol: str) -> dict:
    row = await conn.fetchrow(
        """
        SELECT close_price,
               MAX(close_price) OVER (ORDER BY trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w,
               MIN(close_price) OVER (ORDER BY trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_52w
          FROM nidp.eod_prices
         WHERE symbol = $1
         ORDER BY trade_date DESC
         LIMIT 1
        """,
        symbol,
    ) if False else None  # placeholder — query adjusted for actual schema below
    row = await conn.fetchrow(
        """
        SELECT p.close_price,
               h.high_52w,
               h.low_52w,
               ref.sector
          FROM nidp.eod_prices p
          LEFT JOIN LATERAL (
              SELECT MAX(close_price) AS high_52w, MIN(close_price) AS low_52w
                FROM nidp.eod_prices
               WHERE symbol = $1
                 AND trade_date >= CURRENT_DATE - INTERVAL '52 weeks'
          ) h ON TRUE
          LEFT JOIN nidp.symbol_master ref ON ref.symbol = $1
         WHERE p.symbol = $1
         ORDER BY p.trade_date DESC
         LIMIT 1
        """,
        symbol,
    )
    if row:
        return {
            "current_price": float(row["close_price"] or 0),
            "high_52w":      float(row["high_52w"] or 0),
            "low_52w":       float(row["low_52w"] or 0),
            "sector":        row["sector"] or "Unknown",
        }
    return {"current_price": 0, "high_52w": 0, "low_52w": 0, "sector": "Unknown"}


async def _get_recent_announcements(conn, symbol: str, days: int = 30) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT title, body
          FROM nidp.announcements
         WHERE symbol = $1
           AND broadcast_at >= NOW() - ($2 || ' days')::INTERVAL
         ORDER BY broadcast_at DESC
         LIMIT 5
        """,
        symbol, str(days),
    )
    return [f"{r['title']}: {(r['body'] or '')[:200]}" for r in rows]


def _fmt_financials(rows: list[dict]) -> str:
    if not rows:
        return "No historical data available."
    lines = []
    for r in rows:
        pe = r.get("period_end", "")
        lines.append(
            f"  {pe}: Revenue=₹{r.get('revenue_from_ops_cr') or r.get('total_income_cr','N/A')}Cr "
            f"PAT=₹{r.get('pat_cr','N/A')}Cr "
            f"EPS={r.get('eps_basic','N/A')} "
            f"EBITDA=₹{r.get('ebitda_cr','N/A')}Cr"
        )
    return "\n".join(lines)


# ── Core analyzer ────────────────────────────────────────────────────

async def analyse_earnings(
    symbol: str,
    financials_id: int,
    period: Optional[str] = None,
    event_date: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Generate AI signal for a quarterly earnings event."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Current quarter
        fin_row = await conn.fetchrow(
            "SELECT * FROM nidp.nse_financials_quarterly WHERE id = $1", financials_id
        )
        if not fin_row:
            return None
        current = dict(fin_row)

        # Historical (previous 4 quarters)
        historical = await _get_historical_financials(conn, symbol, limit=5)
        historical = [h for h in historical if h.get("period_end") != current.get("period_end")][:4]

        # Price + announcements
        price_ctx = await _get_price_context(conn, symbol)
        announcements = await _get_recent_announcements(conn, symbol)
        company_row = await conn.fetchrow(
            "SELECT company_name FROM nidp.event_calendar WHERE symbol=$1 LIMIT 1", symbol
        )

    company_name = (company_row["company_name"] if company_row else "") or symbol

    prompt = EARNINGS_PROMPT.format(
        symbol=symbol,
        company_name=company_name,
        period=period or str(current.get("period_end", "")),
        current_financials=_fmt_financials([current]),
        historical_financials=_fmt_financials(historical),
        recent_announcements="\n".join(f"  - {a}" for a in announcements) or "  None",
        current_price=price_ctx["current_price"],
        high_52w=price_ctx["high_52w"],
        low_52w=price_ctx["low_52w"],
        sector=price_ctx["sector"],
    )

    result = await _call_claude(prompt)
    if not result:
        return None

    await _store_signal(
        symbol=symbol,
        event_type="quarterly_results",
        event_date=event_date or (current.get("period_end") or date.today()),
        period=period,
        result=result,
        financials_id=financials_id,
    )
    return result


async def analyse_announcement(
    symbol: str,
    announcement_id: int,
    event_type: str,
    event_date: date,
    announcement_text: str,
) -> Optional[dict[str, Any]]:
    """Generate AI signal for any non-earnings corporate event."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        historical = await _get_historical_financials(conn, symbol, limit=2)
        price_ctx  = await _get_price_context(conn, symbol)
        company_row = await conn.fetchrow(
            "SELECT company_name FROM nidp.event_calendar WHERE symbol=$1 LIMIT 1", symbol
        )

    company_name = (company_row["company_name"] if company_row else "") or symbol
    ctx = EVENT_TYPE_CONTEXT.get(event_type, EVENT_TYPE_CONTEXT["other"])

    prompt = ANNOUNCEMENT_PROMPT.format(
        symbol=symbol,
        company_name=company_name,
        event_type=event_type,
        event_date=event_date,
        announcement_text=announcement_text[:3000],
        recent_financials=_fmt_financials(historical),
        current_price=price_ctx["current_price"],
        sector=price_ctx["sector"],
        event_type_context=ctx,
    )

    result = await _call_claude(prompt)
    if not result:
        return None

    await _store_signal(
        symbol=symbol,
        event_type=event_type,
        event_date=event_date,
        period=None,
        result=result,
        announcement_id=announcement_id,
    )
    return result


async def _call_claude(prompt: str) -> Optional[dict]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logger.error("_call_claude failed: %s", e)
        return None


async def _store_signal(
    symbol: str,
    event_type: str,
    event_date,
    period: Optional[str],
    result: dict,
    financials_id: Optional[int] = None,
    announcement_id: Optional[int] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.corporate_event_signals
                (symbol, event_type, event_date, period,
                 sentiment, confidence,
                 estimated_move_pct_low, estimated_move_pct_high,
                 signal_json, financials_id, announcement_id, model_used)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (symbol, event_type, event_date, period)
            DO UPDATE SET
                sentiment                = EXCLUDED.sentiment,
                confidence               = EXCLUDED.confidence,
                estimated_move_pct_low   = EXCLUDED.estimated_move_pct_low,
                estimated_move_pct_high  = EXCLUDED.estimated_move_pct_high,
                signal_json              = EXCLUDED.signal_json,
                analysed_at              = NOW()
            """,
            symbol, event_type, event_date, period,
            result.get("sentiment", "neutral"),
            result.get("confidence"),
            result.get("estimated_move_pct_low"),
            result.get("estimated_move_pct_high"),
            json.dumps(result),
            financials_id,
            announcement_id,
            _MODEL,
        )
