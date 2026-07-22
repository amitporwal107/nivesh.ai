"""D-1 Evening Preparation Service.

Runs every evening (default 18:00 IST) to prepare for the NEXT day's
corporate results.  For each company scheduled to report tomorrow:

  1. Fetch last 4 quarters of financials from nidp.nse_financials_quarterly
  2. Fetch current price context (52W range, sector)
  3. Call Claude to generate a pre-event briefing with estimate ranges,
     beat/miss thresholds, and key metrics to watch
  4. Store the briefing in nidp.corporate_event_signals (signal_type='d1_prep')
  5. Send a Telegram digest to the configured channel

Scheduled via Cloud Scheduler:
    cron: "30 12 * * 1-5"   # 18:00 IST (UTC+5:30) weekdays

Env vars required:
    ANTHROPIC_API_KEY           — Claude API key
    NIDP_TELEGRAM_BOT_TOKEN     — optional; if set, digest is sent
    NIDP_TELEGRAM_CHAT_ID       — optional
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Optional

from nidp.shared.feature_flags import is_enabled
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool
from nidp.shared.telegram import format_d1_digest, send_alert

from .prompts import D1_EARNINGS_PROMPT, D1_BOARD_MEETING_PROMPT, D1_SYSTEM

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("NIDP_ANALYZER_MODEL", "claude-sonnet-4-6")


# ── Data helpers ────────────────────────────────────────────────────

async def _get_historical_financials(conn, symbol: str, limit: int = 4) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT period_end, consolidated, revenue_from_ops_cr, total_income_cr,
               ebitda_cr, pat_cr, eps_basic, interest_earned_cr, nim_pct
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
        SELECT p.close_price,
               h.high_52w, h.low_52w,
               ref.sector
          FROM nidp.prices_eod p
          LEFT JOIN LATERAL (
              SELECT MAX(close_price) AS high_52w, MIN(close_price) AS low_52w
                FROM nidp.prices_eod
               WHERE symbol = $1
                 AND series = 'EQ'
                 AND as_of_date >= CURRENT_DATE - INTERVAL '52 weeks'
          ) h ON TRUE
          LEFT JOIN nidp.symbol_master ref ON ref.symbol = $1
         WHERE p.symbol = $1
           AND p.series = 'EQ'
         ORDER BY p.as_of_date DESC
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


async def _get_recent_announcements(conn, symbol: str, days: int = 14) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT title, body
          FROM nidp.announcements
         WHERE symbol = $1
           AND broadcast_at >= NOW() - ($2 || ' days')::INTERVAL
         ORDER BY broadcast_at DESC LIMIT 3
        """,
        symbol, str(days),
    )
    return [f"{r['title']}: {(r['body'] or '')[:150]}" for r in rows]


def _fmt_financials(rows: list[dict]) -> str:
    if not rows:
        return "No historical data available."
    lines = []
    for r in rows:
        rev = r.get("revenue_from_ops_cr") or r.get("total_income_cr") or r.get("interest_earned_cr")
        lines.append(
            f"  {r.get('period_end','')}: "
            f"Revenue=₹{rev or 'N/A'}Cr  "
            f"PAT=₹{r.get('pat_cr','N/A')}Cr  "
            f"EPS={r.get('eps_basic','N/A')}"
            + (f"  NIM={r.get('nim_pct','N/A')}%" if r.get("nim_pct") else "")
        )
    return "\n".join(lines)


# ── Claude call ─────────────────────────────────────────────────────

async def _call_claude(prompt: str) -> Optional[dict[str, Any]]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1500,
            system=D1_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logger.error("d1_prep._call_claude failed: %s", e)
        return None


# ── Per-symbol briefing ─────────────────────────────────────────────

async def _build_briefing(
    symbol: str,
    company_name: str,
    event_type: str,
    event_date: date,
    period: Optional[str],
) -> Optional[dict[str, Any]]:
    """Generate and store a D-1 briefing for one company."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        historical = await _get_historical_financials(conn, symbol)
        price_ctx  = await _get_price_context(conn, symbol)
        announcements = await _get_recent_announcements(conn, symbol)

    if event_type == "board_meeting":
        prompt = D1_BOARD_MEETING_PROMPT.format(
            symbol=symbol,
            company_name=company_name,
            event_date=event_date,
            period=period or "agenda TBD",
            historical_financials=_fmt_financials(historical),
            current_price=price_ctx["current_price"],
            high_52w=price_ctx["high_52w"],
            low_52w=price_ctx["low_52w"],
            sector=price_ctx["sector"],
            recent_announcements="\n".join(f"  - {a}" for a in announcements) or "  None",
        )
    else:
        prompt = D1_EARNINGS_PROMPT.format(
            symbol=symbol,
            company_name=company_name,
            event_date=event_date,
            period=period or "Quarterly Results",
            historical_financials=_fmt_financials(historical),
            current_price=price_ctx["current_price"],
            high_52w=price_ctx["high_52w"],
            low_52w=price_ctx["low_52w"],
            sector=price_ctx["sector"],
            recent_announcements="\n".join(f"  - {a}" for a in announcements) or "  None",
        )

    result = await _call_claude(prompt)
    if not result:
        return None

    # Store in corporate_event_signals with signal_type='d1_prep'
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.corporate_event_signals
                (symbol, event_type, event_date, period, signal_type,
                 sentiment, confidence,
                 estimated_move_pct_low, estimated_move_pct_high,
                 signal_json, model_used)
            VALUES ($1,$2,$3,$4,'d1_prep',$5,$6,$7,$8,$9,$10)
            -- predicate matches the partial index (migration 128), which excludes
            -- filing_insight rows; d1_prep rows always satisfy it (signal_type='d1_prep').
            ON CONFLICT (symbol, event_type, event_date, period, signal_type)
                WHERE signal_type <> 'filing_insight'
            DO UPDATE SET
                sentiment              = EXCLUDED.sentiment,
                confidence             = EXCLUDED.confidence,
                estimated_move_pct_low = EXCLUDED.estimated_move_pct_low,
                estimated_move_pct_high= EXCLUDED.estimated_move_pct_high,
                signal_json            = EXCLUDED.signal_json,
                analysed_at            = NOW()
            """,
            symbol, event_type, event_date, period or "",
            result.get("sentiment", "neutral"),
            result.get("confidence"),
            result.get("estimated_move_pct_low"),
            result.get("estimated_move_pct_high"),
            json.dumps(result),
            _MODEL,
        )

    return {
        "symbol":                   symbol,
        "company_name":             company_name,
        "period":                   period,
        "sentiment":                result.get("sentiment", "neutral"),
        "confidence":               result.get("confidence"),
        "estimated_move_pct_low":   result.get("estimated_move_pct_low"),
        "estimated_move_pct_high":  result.get("estimated_move_pct_high"),
        "key_metrics_to_watch":     result.get("key_metrics_to_watch", []),
        "beat_scenario":            result.get("beat_scenario", ""),
        "miss_scenario":            result.get("miss_scenario", ""),
        "trading_note":             result.get("trading_note", ""),
        "current_price":            price_ctx["current_price"],
    }


# ── Main runner ─────────────────────────────────────────────────────

async def run(target_date: Optional[date] = None) -> None:
    """Run D-1 prep for all companies reporting on target_date (default: tomorrow)."""
    setup_logging(service="d1_prep")

    if not await is_enabled("event_processing"):
        logger.info("d1_prep: event_processing flag is OFF — skipping")
        return
    if not await is_enabled("d1_prep"):
        logger.info("d1_prep: d1_prep flag is OFF — skipping")
        return

    briefing_date = target_date or (date.today() + timedelta(days=1))
    logger.info("d1_prep: preparing briefings for %s", briefing_date)

    pool = await get_pool()
    async with pool.acquire() as conn:
        events = await conn.fetch(
            """
            SELECT symbol, company_name, event_type, event_date, period
              FROM nidp.event_calendar
             WHERE event_date = $1
               AND event_type IN ('quarterly_results', 'board_meeting', 'agm')
             ORDER BY symbol
            """,
            briefing_date,
        )

    if not events:
        logger.info("d1_prep: no events scheduled for %s", briefing_date)
        await close_pool()
        return

    logger.info("d1_prep: %d events to prepare for on %s", len(events), briefing_date)
    briefings = []

    for ev in events:
        symbol = ev["symbol"]
        try:
            b = await _build_briefing(
                symbol=symbol,
                company_name=ev["company_name"] or symbol,
                event_type=ev["event_type"],
                event_date=ev["event_date"],
                period=ev["period"],
            )
            if b:
                briefings.append(b)
                logger.info(
                    "d1_prep: %s %s → %s (%.0f%% confidence, %+.1f%% to %+.1f%%)",
                    symbol, ev.get("period", ""),
                    b["sentiment"], b.get("confidence") or 0,
                    b.get("estimated_move_pct_low") or 0,
                    b.get("estimated_move_pct_high") or 0,
                )
        except Exception as e:
            logger.error("d1_prep: %s failed: %s", symbol, e)

    logger.info("d1_prep: generated %d/%d briefings", len(briefings), len(events))

    # Send Telegram digest
    if briefings and await is_enabled("telegram_alerts"):
        digest = format_d1_digest(str(briefing_date), briefings)
        delivered = await send_alert(digest)
        if delivered:
            logger.info("d1_prep: Telegram digest sent for %s", briefing_date)
    elif briefings:
        logger.info("d1_prep: telegram_alerts flag is OFF — digest not sent")

    await close_pool()
