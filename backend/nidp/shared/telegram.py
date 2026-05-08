"""Shared Telegram alert sender for NIDP intelligence services.

Configure via env vars:
    NIDP_TELEGRAM_BOT_TOKEN   — bot token from @BotFather
    NIDP_TELEGRAM_CHAT_ID     — chat/channel ID (use @ChannelName or numeric ID)

Both must be set for alerts to fire. Missing config → silent no-op (logged as warning).

Usage:
    from nidp.shared.telegram import send_alert, format_breakout_alert
    await send_alert("📊 Hello from NIDP")
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _credentials() -> tuple[Optional[str], Optional[str]]:
    return (
        os.environ.get("NIDP_TELEGRAM_BOT_TOKEN"),
        os.environ.get("NIDP_TELEGRAM_CHAT_ID"),
    )


async def send_alert(text: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message. Returns True on success."""
    token, chat_id = _credentials()
    if not token or not chat_id:
        logger.warning("telegram: NIDP_TELEGRAM_BOT_TOKEN or NIDP_TELEGRAM_CHAT_ID not set — skipping")
        return False
    try:
        import aiohttp
        url = _API_BASE.format(token=token)
        payload = {
            "chat_id":    chat_id,
            "text":       text[:4096],  # Telegram message limit
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return True
                body = await r.text()
                logger.warning("telegram: send failed status=%d body=%s", r.status, body[:200])
                return False
    except Exception as e:
        logger.error("telegram: send_alert failed: %s", e)
        return False


def format_breakout_alert(
    symbol: str,
    company_name: str,
    event_type: str,
    event_summary: str,
    sentiment: str,
    confidence: float,
    estimated_move_low: float,
    estimated_move_high: float,
    breakout_confidence: str,
    breakout_signals: list[str],
    current_price: float,
    high_52w: float,
    low_52w: float,
    trading_note: str,
) -> str:
    """Format a rich Telegram breakout alert."""
    sentiment_emoji = {
        "strongly_bullish": "🚀",
        "bullish": "📈",
        "neutral": "➡️",
        "bearish": "📉",
        "strongly_bearish": "💥",
    }.get(sentiment, "📊")

    confidence_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💡"}.get(breakout_confidence, "⚡")
    move_str = f"{estimated_move_low:+.1f}% to {estimated_move_high:+.1f}%"

    signals_text = "\n".join(f"  • {s}" for s in breakout_signals) if breakout_signals else "  • Event-driven signal"

    return (
        f"{confidence_emoji} <b>BREAKOUT ALERT — {breakout_confidence} CONFIDENCE</b>\n\n"
        f"{sentiment_emoji} <b>{symbol}</b> ({company_name})\n"
        f"📋 <b>{event_type.replace('_', ' ').title()}</b>\n\n"
        f"{event_summary}\n\n"
        f"<b>Confirmation signals:</b>\n{signals_text}\n\n"
        f"💹 Price: ₹{current_price:,.0f} | 52W: ₹{low_52w:,.0f}–₹{high_52w:,.0f}\n"
        f"🎯 Est. Move: <b>{move_str}</b>\n\n"
        f"⚡ AI Signal: <b>{sentiment.replace('_', ' ').upper()} ({confidence:.0f}%)</b>\n"
        f"📝 <i>{trading_note}</i>\n\n"
        f"<i>NIDP Intelligence Engine</i>"
    )


def format_d1_digest(
    event_date: str,
    briefings: list[dict],
) -> str:
    """Format the D-1 evening digest listing tomorrow's scheduled results."""
    if not briefings:
        return f"📅 <b>Tomorrow's Results ({event_date})</b>\n\nNo scheduled results found."

    lines = [f"📅 <b>Tomorrow's Results Briefing — {event_date}</b>\n"]
    for b in briefings[:10]:  # cap at 10 to stay under 4096 chars
        sym = b.get("symbol", "")
        name = b.get("company_name", sym)
        period = b.get("period", "")
        sentiment = b.get("sentiment", "neutral")
        move_low  = b.get("estimated_move_pct_low", 0)
        move_high = b.get("estimated_move_pct_high", 0)
        watch = b.get("key_metrics_to_watch", [])
        note  = b.get("trading_note", "")
        price = b.get("current_price", 0)

        emoji = {
            "strongly_bullish": "🚀", "bullish": "📈",
            "neutral": "➡️", "bearish": "📉", "strongly_bearish": "💥",
        }.get(sentiment, "📊")

        lines.append(f"{emoji} <b>{sym}</b> ({name}) — {period}")
        if price:
            lines.append(f"   💹 ₹{price:,.0f} | Est: {move_low:+.1f}% to {move_high:+.1f}%")
        if watch:
            lines.append(f"   👁 Watch: {', '.join(watch[:3])}")
        if note:
            lines.append(f"   📝 {note}")
        lines.append("")

    lines.append("<i>NIDP Intelligence Engine — D-1 Prep</i>")
    return "\n".join(lines)


def format_post_event_alert(
    symbol: str,
    company_name: str,
    event_type: str,
    period: str,
    sentiment: str,
    confidence: float,
    estimated_move_low: float,
    estimated_move_high: float,
    summary: str,
    key_factors: list[dict],
    trading_note: str,
    current_price: float,
) -> str:
    """Format a post-event analysis alert (after results are filed)."""
    sentiment_emoji = {
        "strongly_bullish": "🚀", "bullish": "📈",
        "neutral": "➡️", "bearish": "📉", "strongly_bearish": "💥",
    }.get(sentiment, "📊")

    top_factors = []
    for f in key_factors[:3]:
        icon = "✅" if f.get("impact") == "positive" else "❌" if f.get("impact") == "negative" else "➡️"
        top_factors.append(f"  {icon} {f.get('factor', '')}: {f.get('detail', '')[:80]}")
    factors_text = "\n".join(top_factors) if top_factors else "  No key factors listed"

    return (
        f"{sentiment_emoji} <b>RESULTS ALERT: {symbol}</b> ({company_name})\n"
        f"📋 {period} | {event_type.replace('_',' ').title()}\n\n"
        f"{summary}\n\n"
        f"<b>Key factors:</b>\n{factors_text}\n\n"
        f"💹 Price: ₹{current_price:,.0f}\n"
        f"🎯 Est. Move: <b>{estimated_move_low:+.1f}% to {estimated_move_high:+.1f}%</b>\n\n"
        f"⚡ <b>{sentiment.replace('_',' ').upper()} ({confidence:.0f}%)</b>\n"
        f"📝 <i>{trading_note}</i>\n\n"
        f"<i>NIDP Intelligence Engine</i>"
    )
