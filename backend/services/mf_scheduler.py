"""APScheduler jobs for Phase 2 — off-hours Groww scrape drain.

Jobs:
  * drain_queue  — runs every hour 02:00-06:00 IST (20:30-00:30 UTC) &
                   every 6h during weekends. Pulls up to 30 queued funds.
  * nightly_stale_refresh — 03:00 IST on weekdays, re-queues funds whose
                   metadata.last_scraped_at is older than 15 days so they
                   get refreshed on the next drain.

Scheduler is started from server startup only when POSTGRES_URL is
configured; it auto-starts on first secret write.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from deps import db
from services import fund_data_resolver, pg_client

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
DRAIN_BATCH = 30


async def _drain_job():
    try:
        result = await fund_data_resolver.drain_queue(max_items=DRAIN_BATCH)
        logger.info(f"scheduler drain: {result}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scheduler drain error: {e}")


async def _stale_refresh_job():
    """Re-enqueue funds whose metadata.last_scraped_at is stale (>15 days)."""
    pool = await pg_client.get_pool()
    if pool is None:
        return
    threshold = datetime.now(timezone.utc) - timedelta(days=15)
    queued = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT im.instrument_id, im.instrument_name, im.symbol, im.isin, "
                "m.groww_slug, m.last_scraped_at "
                "FROM instrument_master im "
                "LEFT JOIN mutual_fund_metadata m ON m.instrument_id = im.instrument_id "
                "WHERE im.instrument_type = 'MUTUAL_FUND' "
                "AND (m.last_scraped_at IS NULL OR m.last_scraped_at < $1) "
                "LIMIT 100",
                threshold,
            )
        for r in rows:
            key = f"ISIN:{r['isin']}" if r["isin"] else (
                f"SCHEME:{r['symbol']}" if r["symbol"] else
                f"NAME:{(r['instrument_name'] or '').lower().strip()}"
            )
            await db.scrape_queue.update_one(
                {"instrument_key": key},
                {"$set": {
                    "instrument_key": key,
                    "scheme_name": r["instrument_name"],
                    "slug": r["groww_slug"],
                    "status": "queued",
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            queued += 1
        logger.info(f"scheduler stale_refresh: {queued} funds requeued")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"stale_refresh error: {e}")


async def _amfi_navs_job():
    """Daily AMFI EOD NAV ingestion — runs 22:00 IST (after AMFI publishes)."""
    try:
        from scripts.fetch_amfi_navs import run as _run_amfi
        res = await _run_amfi(dry_run=False)
        logger.info(
            f"amfi_navs ok: parsed={res.get('parsed')} upserted={res.get('upserted')} "
            f"skipped={res.get('skipped_no_match')} dur_ms={res.get('duration_ms')}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"amfi_navs error: {e}")


async def _analytics_sweep_job():
    """Parallel NAV-analytics refresh — runs 22:30 IST (30 min after NAV cron)."""
    try:
        from services.nav_analytics_sweep import run_analytics_sweep
        res = await run_analytics_sweep()
        logger.info(f"analytics_sweep {res}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"analytics_sweep error: {e}")


async def _v3_rescore_job():
    """Parallel V3 composite rescore — runs 22:45 IST (after analytics sweep)."""
    try:
        from services.nav_analytics_sweep import run_v3_rescore
        res = await run_v3_rescore()
        logger.info(f"v3_rescore {res}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"v3_rescore error: {e}")


async def _stock_nifty100_refresh_job():
    """Daily Groww Nifty 100 scrape + score — runs 23:00 IST.
    Populates stock_master / stock_primitives / stock_scores for all 100
    Nifty constituents."""
    try:
        from services.groww_stock_scraper import refresh_nifty_100
        res = await refresh_nifty_100()
        logger.info(
            f"nifty100_refresh ok={res.get('ok')} "
            f"succeeded={res.get('succeeded')}/{res.get('total')} "
            f"dur={res.get('duration_s')}s"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"nifty100_refresh error: {e}")


def start():
    """Idempotent start. No-op if already running."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    # Every hour between 02:00 and 05:59 IST on weekdays
    _scheduler.add_job(
        _drain_job, CronTrigger(day_of_week="mon-fri", hour="2-5", minute=0),
        id="drain_weekday", replace_existing=True, max_instances=1,
    )
    # Every 2h on weekends (24x7)
    _scheduler.add_job(
        _drain_job, CronTrigger(day_of_week="sat,sun", hour="*/2", minute=0),
        id="drain_weekend", replace_existing=True, max_instances=1,
    )
    # Stale-refresh: weekday 03:00 IST
    _scheduler.add_job(
        _stale_refresh_job, CronTrigger(day_of_week="mon-fri", hour=3, minute=0),
        id="stale_refresh", replace_existing=True, max_instances=1,
    )
    # AMFI NAV ingestion: daily 22:00 IST (AMFI publishes EOD NAVs ~20:30 IST)
    _scheduler.add_job(
        _amfi_navs_job, CronTrigger(hour=22, minute=0),
        id="amfi_navs_daily", replace_existing=True, max_instances=1,
    )
    # NAV analytics sweep: daily 22:30 IST — recompute max_drawdown,
    # consistency, downside_capture, aum_trend for every eligible fund.
    _scheduler.add_job(
        _analytics_sweep_job, CronTrigger(hour=22, minute=30),
        id="analytics_sweep_daily", replace_existing=True, max_instances=1,
    )
    # V3 composite rescore: daily 22:45 IST — recompute Quality+Health
    # from fresh primitives, write to PG + Redis cache.
    _scheduler.add_job(
        _v3_rescore_job, CronTrigger(hour=22, minute=45),
        id="v3_rescore_daily", replace_existing=True, max_instances=1,
    )
    # Nifty 100 stock refresh: daily 23:00 IST — scrapes Groww for all 100
    # constituents, writes primitives + V3 composite scores to Postgres.
    _scheduler.add_job(
        _stock_nifty100_refresh_job, CronTrigger(hour=23, minute=0),
        id="nifty100_refresh_daily", replace_existing=True, max_instances=1,
    )
    _scheduler.start()
    logger.info("MF scheduler started (Asia/Kolkata)")


def stop():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}
    return {
        "running": True,
        "timezone": str(_scheduler.timezone),
        "jobs": [
            {
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
            }
            for j in _scheduler.get_jobs()
        ],
    }
