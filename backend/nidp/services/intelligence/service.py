"""Market Intelligence Orchestrator.

Runs AFTER market close (default: 16:30 IST) to complete the intelligence
pipeline for all events that occurred today:

  1. Load today's post-event signals (from event_analyzer)
  2. Calculate impact scores
  3. Fetch market confirmation data (volume, delivery, OI, sector)
  4. Run pre-breakout detector (multi-layer confluence)
  5. Update corporate_event_signals with scores + confirmation
  6. Send Telegram alerts for HIGH/MEDIUM confidence setups

Can also run in retrospective mode with --date to score historical events.

Scheduled via Cloud Scheduler:
    cron: "0 11 * * 1-5"   # 16:30 IST weekdays (after market close)

Pipeline flow:
    event_calendar   → nse_financials → event_analyzer  (morning/intraday)
    bhavcopy         → delivery data                     (after 15:30)
    fno_bhavcopy     → OI data                          (after 15:30)
    intelligence     → scores + alerts                   (16:30)
    d1_prep          → tomorrow briefing                 (18:00)
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.feature_flags import is_enabled
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool
from nidp.shared.telegram import (
    format_breakout_alert, format_post_event_alert, send_alert
)

from .breakout import classify_alert_priority, detect_breakout
from .confirmation import get_confirmation
from .scorer import calc_impact_score, extract_order_value_cr

logger = logging.getLogger(__name__)


# ── Data loaders ────────────────────────────────────────────────────

async def _get_todays_signals(conn, target_date: date) -> list[dict]:
    """Fetch post-event signals that haven't been fully scored yet."""
    rows = await conn.fetch(
        """
        SELECT s.id, s.symbol, s.event_type, s.event_date, s.period,
               s.sentiment, s.confidence,
               s.estimated_move_pct_low, s.estimated_move_pct_high,
               s.signal_json, s.alert_sent,
               f.revenue_from_ops_cr, f.total_income_cr,
               f.interest_earned_cr,
               ec.company_name
          FROM nidp.corporate_event_signals s
          LEFT JOIN nidp.nse_financials_quarterly f ON f.id = s.financials_id
          LEFT JOIN nidp.event_calendar ec
                 ON ec.symbol = s.symbol AND ec.event_date = s.event_date
                AND ec.event_type = s.event_type
         WHERE s.event_date = $1
           AND s.signal_type = 'post_event'
           AND s.impact_score IS NULL   -- not yet scored
         ORDER BY s.symbol
        """,
        target_date,
    )
    return [dict(r) for r in rows]


async def _get_price_context(conn, symbol: str, trade_date: date) -> dict:
    row = await conn.fetchrow(
        """
        SELECT p.close_price, h.high_52w, h.low_52w
          FROM nidp.eod_prices p
          LEFT JOIN LATERAL (
              SELECT MAX(close_price) AS high_52w, MIN(close_price) AS low_52w
                FROM nidp.eod_prices
               WHERE symbol = $1
                 AND trade_date >= $2 - INTERVAL '52 weeks'
          ) h ON TRUE
         WHERE p.symbol = $1
           AND p.trade_date <= $2
         ORDER BY p.trade_date DESC
         LIMIT 1
        """,
        symbol, trade_date,
    )
    if row:
        return {
            "current_price": float(row["close_price"] or 0),
            "high_52w":      float(row["high_52w"] or 0),
            "low_52w":       float(row["low_52w"] or 0),
        }
    return {"current_price": 0, "high_52w": 0, "low_52w": 0}


async def _get_market_cap(conn, symbol: str) -> float:
    row = await conn.fetchrow(
        "SELECT market_cap_cr FROM nidp.symbol_master WHERE symbol = $1", symbol
    )
    return float(row["market_cap_cr"]) if row and row["market_cap_cr"] else 0.0


async def _get_annual_revenue(conn, symbol: str) -> float:
    """Sum of last 4 quarters' revenue as LTM proxy."""
    row = await conn.fetchrow(
        """
        SELECT SUM(COALESCE(revenue_from_ops_cr, total_income_cr, interest_earned_cr)) AS ltm_rev
          FROM (
              SELECT revenue_from_ops_cr, total_income_cr, interest_earned_cr
                FROM nidp.nse_financials_quarterly
               WHERE symbol = $1
               ORDER BY period_end DESC
               LIMIT 4
          ) q
        """,
        symbol,
    )
    return float(row["ltm_rev"]) if row and row["ltm_rev"] else 0.0


async def _log_alert(conn, signal_id: int, symbol: str, event_type: str,
                     alert_type: str, channel: str, message: str, delivered: bool) -> None:
    await conn.execute(
        """
        INSERT INTO nidp.intelligence_alerts
            (signal_id, symbol, event_type, alert_type, channel, message_text, delivered)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
        signal_id, symbol, event_type, alert_type, channel, message, delivered,
    )
    # Mark signal as alert-sent
    await conn.execute(
        "UPDATE nidp.corporate_event_signals SET alert_sent=TRUE, alert_sent_at=NOW() WHERE id=$1",
        signal_id,
    )


# ── Per-signal processing ────────────────────────────────────────────

async def _process_signal(pool, sig: dict, target_date: date) -> None:
    symbol     = sig["symbol"]
    event_type = sig["event_type"]
    sig_json   = sig.get("signal_json") or {}
    if isinstance(sig_json, str):
        try:
            sig_json = json.loads(sig_json)
        except Exception:
            sig_json = {}

    async with pool.acquire() as conn:
        price_ctx  = await _get_price_context(conn, symbol, target_date)
        market_cap = await _get_market_cap(conn, symbol)
        ann_rev    = await _get_annual_revenue(conn, symbol)

        # Extract order value from signal JSON or announcement text
        order_size = 0.0
        if event_type == "order_win":
            summary_text = sig_json.get("summary", "") + " ".join(
                f.get("detail", "") for f in sig_json.get("key_factors", [])
            )
            order_size = extract_order_value_cr(summary_text) or 0.0

        # Market confirmation
        confirmation = await get_confirmation(conn, symbol, target_date)

    # Impact score
    impact = calc_impact_score(
        event_type=event_type,
        order_size_cr=order_size,
        annual_revenue_cr=ann_rev,
        volume_spike_ratio=confirmation.get("volume_spike_ratio") or 1.0,
        sector_return_pct=confirmation.get("sector_return_pct") or 0.0,
        market_cap_cr=market_cap,
    )

    # Breakout detection
    bd = detect_breakout(
        event_type=event_type,
        sentiment=sig.get("sentiment", "neutral"),
        confidence=float(sig.get("confidence") or 0),
        impact_score=impact,
        confirmation=confirmation,
        current_price=price_ctx["current_price"],
        high_52w=price_ctx["high_52w"],
        low_52w=price_ctx["low_52w"],
    )

    priority = classify_alert_priority(
        bd["breakout_score"], sig.get("sentiment", "neutral"), event_type
    )

    logger.info(
        "intelligence: %s [%s] impact=%.0f breakout=%.0f(%s) priority=%s layers=%d",
        symbol, event_type, impact, bd["breakout_score"],
        bd["breakout_confidence"], priority, bd["layers_count"],
    )

    # Persist scores back to DB
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE nidp.corporate_event_signals
               SET impact_score       = $1,
                   confirmation_json  = $2,
                   breakout_score     = $3,
                   breakout_confidence= $4
             WHERE id = $5
            """,
            impact,
            json.dumps(confirmation),
            bd["breakout_score"],
            bd["breakout_confidence"],
            sig["id"],
        )

    # Send Telegram alert if warranted
    if priority == "skip" or sig.get("alert_sent"):
        return

    telegram_enabled = await is_enabled("telegram_alerts")
    if not telegram_enabled:
        logger.info("intelligence: telegram_alerts OFF — skipping alert for %s", symbol)
        return

    company_name = sig.get("company_name") or symbol
    key_factors  = sig_json.get("key_factors", [])
    trading_note = sig_json.get("trading_note", "")

    if bd["breakout_score"] >= 70 and bd["layers_count"] >= 3:
        # Full breakout alert with all signals
        msg = format_breakout_alert(
            symbol=symbol,
            company_name=company_name,
            event_type=event_type,
            event_summary=sig_json.get("summary", "")[:300],
            sentiment=sig.get("sentiment", "neutral"),
            confidence=float(sig.get("confidence") or 0),
            estimated_move_low=float(sig.get("estimated_move_pct_low") or 0),
            estimated_move_high=float(sig.get("estimated_move_pct_high") or 0),
            breakout_confidence=bd["breakout_confidence"],
            breakout_signals=bd["layers_hit"],
            current_price=price_ctx["current_price"],
            high_52w=price_ctx["high_52w"],
            low_52w=price_ctx["low_52w"],
            trading_note=trading_note,
        )
        alert_type = "breakout"
    else:
        # Standard post-event alert
        msg = format_post_event_alert(
            symbol=symbol,
            company_name=company_name,
            event_type=event_type,
            period=sig.get("period") or "",
            sentiment=sig.get("sentiment", "neutral"),
            confidence=float(sig.get("confidence") or 0),
            estimated_move_low=float(sig.get("estimated_move_pct_low") or 0),
            estimated_move_high=float(sig.get("estimated_move_pct_high") or 0),
            summary=sig_json.get("summary", "")[:300],
            key_factors=key_factors,
            trading_note=trading_note,
            current_price=price_ctx["current_price"],
        )
        alert_type = "post_event"

    delivered = await send_alert(msg)
    async with pool.acquire() as conn:
        await _log_alert(
            conn, sig["id"], symbol, event_type,
            alert_type, "telegram", msg, delivered,
        )


# ── Main runner ─────────────────────────────────────────────────────

async def run(target_date: Optional[date] = None, symbol: Optional[str] = None) -> None:
    """Score all events for target_date and send alerts. Default: today."""
    setup_logging(service="intelligence")

    if not await is_enabled("event_processing"):
        logger.info("intelligence: event_processing flag is OFF — skipping")
        return

    run_date = target_date or date.today()
    logger.info("intelligence: scoring events for %s", run_date)

    pool = await get_pool()
    async with pool.acquire() as conn:
        signals = await _get_todays_signals(conn, run_date)

    if symbol:
        sym = symbol.upper()
        signals = [s for s in signals if s["symbol"] == sym]

    if not signals:
        logger.info("intelligence: no unscored signals for %s", run_date)
        await close_pool()
        return

    logger.info("intelligence: processing %d signals", len(signals))

    for sig in signals:
        try:
            await _process_signal(pool, sig, run_date)
        except Exception as e:
            logger.error("intelligence: %s failed: %s", sig.get("symbol"), e)

    logger.info("intelligence: done")
    await close_pool()
