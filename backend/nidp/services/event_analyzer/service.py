"""NIDP event_analyzer service.

Runs after event_calendar + nse_financials to generate AI signals for:
  - New quarterly earnings results
  - All 20 corporate event types from announcements

Can be run:
  - Daily (processes all new events from today)
  - With --symbol to analyse a specific stock
  - Triggered automatically after nse_financials upserts new data
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .analyzer import analyse_announcement, analyse_earnings

logger = logging.getLogger(__name__)

# Map announcement classifier labels → event types for the 20-type framework
_ANNOUNCEMENT_TYPE_MAP = {
    "financial_results":    "quarterly_results",
    "dividend":             "dividend",
    "bonus":                "bonus",
    "split":                "split",
    "buyback":              "buyback",
    "merger":               "merger_acquisition",
    "acquisition":          "merger_acquisition",
    "order_win":            "order_win",
    "promoter_buying":      "promoter_buying",
    "promoter_selling":     "promoter_selling",
    "shareholding":         "shareholding",
    "rights_issue":         "rights_issue",
    "qip":                  "qip",
    "debt_reduction":       "debt_reduction",
    "credit_rating":        "credit_rating",
    "regulatory_approval":  "regulatory",
    "management_change":    "management",
    "litigation":           "litigation",
    "delisting":            "delisting",
    "index_change":         "index_change",
    "pledge_change":        "pledge_change",
    "insolvency":           "insolvency",
}


async def _get_new_earnings(conn, since: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT f.id AS financials_id, f.symbol, f.period_end,
               ec.period, ec.event_date, ec.company_name
          FROM nidp.nse_financials_quarterly f
          LEFT JOIN nidp.event_calendar ec
                 ON ec.symbol = f.symbol
                AND ec.event_type = 'quarterly_results'
                AND ec.event_date >= $1
          LEFT JOIN nidp.corporate_event_signals s
                 ON s.symbol = f.symbol
                AND s.event_type = 'quarterly_results'
                AND s.event_date = ec.event_date
         WHERE f.ingested_at >= $1
           AND s.id IS NULL
         ORDER BY f.ingested_at DESC
        """,
        since,
    )
    return [dict(r) for r in rows]


async def _get_new_announcements(conn, since: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT a.id, a.symbol, a.title, a.body, a.category,
               a.broadcast_at::date AS event_date
          FROM nidp.announcements a
          LEFT JOIN nidp.corporate_event_signals s
                 ON s.symbol = a.symbol
                AND s.announcement_id = a.id
         WHERE a.broadcast_at >= $1
           AND a.category IS NOT NULL
           AND a.category != 'other'
           AND s.id IS NULL
         ORDER BY a.broadcast_at DESC
         LIMIT 100
        """,
        since,
    )
    return [dict(r) for r in rows]


async def run(target_date: Optional[date] = None, symbol: Optional[str] = None) -> None:
    setup_logging(service="event_analyzer")
    since = target_date or (date.today() - timedelta(days=1))

    pool = await get_pool()
    async with pool.acquire() as conn:
        earnings = await _get_new_earnings(conn, since)
        announcements = await _get_new_announcements(conn, since)

    if symbol:
        sym = symbol.upper()
        earnings = [e for e in earnings if e["symbol"] == sym]
        announcements = [a for a in announcements if a["symbol"] == sym]

    logger.info("event_analyzer: %d new earnings, %d new announcements to analyse",
                len(earnings), len(announcements))

    # Analyse earnings
    for e in earnings:
        try:
            result = await analyse_earnings(
                symbol=e["symbol"],
                financials_id=e["financials_id"],
                period=e.get("period"),
                event_date=e.get("event_date") or e.get("period_end"),
            )
            if result:
                logger.info(
                    "event_analyzer: %s %s → %s (%.0f%% confidence, %+.1f%% to %+.1f%%)",
                    e["symbol"], e.get("period", ""),
                    result["sentiment"], result.get("confidence", 0),
                    result.get("estimated_move_pct_low", 0),
                    result.get("estimated_move_pct_high", 0),
                )
        except Exception as ex:
            logger.error("event_analyzer: earnings %s failed: %s", e["symbol"], ex)

    # Analyse announcements (all 20 event types)
    for a in announcements:
        event_type = _ANNOUNCEMENT_TYPE_MAP.get(a.get("category", ""), "other")
        text = f"{a.get('title','')} {a.get('body','')}"
        try:
            result = await analyse_announcement(
                symbol=a["symbol"],
                announcement_id=a["id"],
                event_type=event_type,
                event_date=a["event_date"],
                announcement_text=text,
            )
            if result:
                logger.info(
                    "event_analyzer: %s [%s] → %s",
                    a["symbol"], event_type, result["sentiment"],
                )
        except Exception as ex:
            logger.error("event_analyzer: announcement %s/%d failed: %s",
                         a["symbol"], a["id"], ex)

    logger.info("event_analyzer: done")
    await close_pool()
