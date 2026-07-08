"""Helpers for the canonical "last NSE market close" date.

Source of truth: nidp.v_market_session in the DB. Computed from
nidp.nse_holidays + an 18:30 IST cutoff. See migration 023.

Two helpers:

    last_market_close_date(market='NSE_EQ') — async, reads the DB.
        Use this from inside async ingester / service code where a
        DB pool already exists. Falls back to the in-process cutoff
        heuristic if the DB call fails.

    default_target_date() — sync, no DB. Pure-python cutoff fallback
        for tests, bootstrap, or argparse defaults where async isn't
        available. Does NOT respect holidays — returns last weekday
        on or before the boundary.

For ingester entrypoints, the recommended pattern is:

    p.add_argument("--date", type=_d, default=None)
    a = p.parse_args()
    asyncio.run(_main_async(a))

    async def _main_async(args):
        target = args.date or await last_market_close_date()
        await run(target)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


def is_trading_day(d: date, holidays: Optional[set] = None) -> bool:
    """True if `d` is a weekday (Mon–Fri) and not in `holidays`. Sync, no DB —
    weekday is the dominant signal (NSE holidays are rare); pass a holidays set
    for exactness. Used to tell a SUSPECT empty feed (0 rows on a trading day)
    apart from a benign holiday SKIP."""
    if d.weekday() >= 5:            # 5=Sat, 6=Sun
        return False
    if holidays and d in holidays:
        return False
    return True


def default_target_date() -> date:
    """Sync fallback: cutoff-aware "last close" without DB / holidays.

    Logic: if now is past 18:30 IST, today; else yesterday.
    Walks back to most recent weekday so Mondays don't return Sunday.
    """
    now_ist = datetime.now(IST)
    cutoff = now_ist.replace(hour=18, minute=30, second=0, microsecond=0)
    boundary = now_ist.date() if now_ist >= cutoff else (now_ist - timedelta(days=1)).date()
    # Walk back to a weekday (Mon=0 .. Sun=6).
    while boundary.weekday() >= 5:
        boundary -= timedelta(days=1)
    return boundary


async def last_market_close_date(market: str = "NSE_EQ") -> date:
    """Reads nidp.v_market_session — single DB-backed source of truth.

    Falls back to default_target_date() if the DB call fails (e.g.
    fresh deployment before nse_calendar has run).
    """
    try:
        # Local import: keep this module importable from sync contexts
        # (tests, scripts) without dragging asyncpg into the import graph.
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            d = await conn.fetchval(
                "SELECT last_close_date FROM nidp.v_market_session WHERE market = $1",
                market,
            )
            if d:
                return d
            logger.warning("v_market_session has no row for market=%s", market)
    except Exception as e:                                          # noqa: BLE001
        logger.warning(
            "last_market_close_date DB lookup failed: %s — falling back to "
            "in-process cutoff heuristic", e,
        )
    return default_target_date()


async def bump_market_session(target_date: date, market: str = "NSE_EQ") -> None:
    """Update nidp.market_session_state to reflect a successfully-
    ingested target_date. Idempotent: only writes if the new date is
    >= stored last_close_date (we never go backwards).
    """
    try:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nidp.market_session_state
                    (market, last_close_date, last_close_observed_at, updated_at)
                VALUES ($1, $2, NOW(), NOW())
                ON CONFLICT (market) DO UPDATE SET
                    last_close_date        = GREATEST(market_session_state.last_close_date,
                                                      EXCLUDED.last_close_date),
                    last_close_observed_at = CASE
                        WHEN EXCLUDED.last_close_date >= market_session_state.last_close_date
                            THEN NOW()
                        ELSE market_session_state.last_close_observed_at
                    END,
                    updated_at             = NOW()
                """,
                market, target_date,
            )
    except Exception:                                              # noqa: BLE001
        logger.exception("bump_market_session failed (target=%s)", target_date)
