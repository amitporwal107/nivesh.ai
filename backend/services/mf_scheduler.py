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
import fcntl
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from deps import db
from services import fund_data_resolver, pg_client

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
DRAIN_BATCH = 30

# ── One process runs the scheduled jobs ──────────────────────────────────────
# `uvicorn --workers N` starts N processes and each runs the startup hook, so every
# job here ran N times at once (staging, 4 workers: four 17:30 broker syncs racing on
# the same holdings). An exclusive, non-blocking flock on one file elects the first
# process to start; the others start no scheduler. The kernel drops the lock when its
# holder exits, so a worker restarted by uvicorn takes it over at its own startup.
# Scope: one host / container (the file's directory). MF_SCHEDULER_LOCK_PATH moves it.
LOCK_PATH_ENV = "MF_SCHEDULER_LOCK_PATH"
DEFAULT_LOCK_PATH = "/tmp/nivesh-mf-scheduler.lock"
_lock_fd: Optional[int] = None


def _lock_path() -> str:
    return os.environ.get(LOCK_PATH_ENV) or DEFAULT_LOCK_PATH


def _acquire_leader_lock() -> bool:
    """True when this process holds (or now takes) the scheduler lock."""
    global _lock_fd
    if _lock_fd is not None:
        return True
    fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        os.close(fd)
        return False
    except Exception:
        os.close(fd)
        raise
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _lock_fd = fd
    return True


def _release_leader_lock() -> None:
    global _lock_fd
    if _lock_fd is None:
        return
    fd, _lock_fd = _lock_fd, None
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def is_leader() -> bool:
    return _lock_fd is not None


async def _drain_job():
    try:
        result = await fund_data_resolver.drain_queue(max_items=DRAIN_BATCH)
        logger.info("scheduler drain: %s", result)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler drain error: %s", e)


async def _stale_refresh_job():
    """Re-enqueue funds whose metadata.last_scraped_at is stale (>15 days)."""
    from services import pipeline_progress
    await pipeline_progress.start(
        "stale_refresh", total=None,
        phase="query",
        message="finding funds with last_scraped_at NULL or > 15d old",
    )
    pool = await pg_client.get_pool()
    if pool is None:
        await pipeline_progress.finish("stale_refresh", "failed", error_msg="no_pg")
        return
    # `mutual_fund_metadata.last_scraped_at` is stored as TIMESTAMP WITHOUT
    # TIME ZONE in Postgres; asyncpg rejects a tz-aware comparand. We convert
    # to naive UTC for the parameter binding.
    threshold = (datetime.now(timezone.utc) - timedelta(days=15)).replace(tzinfo=None)
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
            await pipeline_progress.tick(
                "stale_refresh", processed_delta=1, total=len(rows),
                phase="enqueue",
                message=f"queued {queued}/{len(rows)} stale fund(s)",
            )
        logger.info("scheduler stale_refresh: %s funds requeued", queued)
        await pipeline_progress.finish(
            "stale_refresh", "ok", total=queued, processed=queued, failed=0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("stale_refresh error: %s", e)
        await pipeline_progress.finish("stale_refresh", "failed",
                                        error_msg=str(e), processed=queued, failed=0)


async def _is_pipeline_paused() -> bool:
    """Pause flag — set to True after a successful seamless refresh.
    Cron jobs check this before doing any work so the pipeline can be
    silenced until a human re-enables it."""
    try:
        from deps import db
        cfg = await db.system_config.find_one({"key": "data_pipeline"}) or {}
        return bool(cfg.get("paused", False))
    except Exception:  # noqa: BLE001
        return False


async def _amfi_navs_job():
    """Daily AMFI EOD NAV ingestion — runs 22:00 IST (after AMFI publishes)."""
    if await _is_pipeline_paused():
        logger.info("amfi_navs skipped — data_pipeline.paused=true")
        return
    try:
        from scripts.fetch_amfi_navs import run as _run_amfi
        res = await _run_amfi(dry_run=False)
        logger.info(
            f"amfi_navs ok: parsed={res.get('parsed')} upserted={res.get('upserted')} "
            f"skipped={res.get('skipped_no_match')} dur_ms={res.get('duration_ms')}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("amfi_navs error: %s", e)


async def _analytics_sweep_job():
    """Parallel NAV-analytics refresh — runs 22:30 IST (30 min after NAV cron)."""
    if await _is_pipeline_paused():
        logger.info("analytics_sweep skipped — data_pipeline.paused=true")
        return
    try:
        from services.nav_analytics_sweep import run_analytics_sweep
        res = await run_analytics_sweep()
        logger.info("analytics_sweep %s", res)
    except Exception as e:  # noqa: BLE001
        logger.warning("analytics_sweep error: %s", e)


async def _v3_rescore_job():
    """Parallel V3 composite rescore — runs 22:45 IST (after analytics sweep)."""
    if await _is_pipeline_paused():
        logger.info("v3_rescore skipped — data_pipeline.paused=true")
        return
    try:
        from services.nav_analytics_sweep import run_v3_rescore
        res = await run_v3_rescore()
        logger.info("v3_rescore %s", res)
    except Exception as e:  # noqa: BLE001
        logger.warning("v3_rescore error: %s", e)


async def _stock_nifty100_refresh_job():
    """Daily Groww Nifty 100 scrape + score — runs 23:00 IST.
    Populates stock_master / stock_primitives / stock_scores for all 100
    Nifty constituents."""
    if await _is_pipeline_paused():
        logger.info("nifty100_refresh skipped — data_pipeline.paused=true")
        return
    try:
        from services.groww_stock_scraper import refresh_nifty_100
        res = await refresh_nifty_100()
        logger.info(
            f"nifty100_refresh ok={res.get('ok')} "
            f"succeeded={res.get('succeeded')}/{res.get('total')} "
            f"dur={res.get('duration_s')}s"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("nifty100_refresh error: %s", e)


async def _benchmark_refresh_job():
    """Daily benchmark-index refresh — runs 18:30 IST per PRD. Pulls
    OHLC for every index in benchmark_index._YF_TICKERS via yfinance,
    upserts market_index_data, recomputes returns / volatility /
    drawdown into index_metrics, busts Redis cache for `/api/index/latest`.
    """
    try:
        from services import benchmark_index as _bm
        results = await _bm.refresh_all()
        ok = sum(1 for r in results if r.get("ok"))
        logger.info("benchmark_refresh: %s/%s indices refreshed", ok, len(results))
    except Exception as e:  # noqa: BLE001
        logger.warning("benchmark_refresh error: %s", e)


async def _macro_intelligence_job():
    """Daily macro intelligence refresh — runs 19:30 IST on weekdays, with a 21:30 IST retry. Ingests Nifty 50 and
    India VIX from the warehouse (yfinance as fallback) and the global series from yfinance, computes features,
    classifies regime, persists everything so /api/macro/today and the risk service read the session that closed."""
    try:
        from services import macro_engine
        out = await macro_engine.run_daily()
        ing = out.get("ingest", {})
        state = out.get("state", {})
        logger.info(
            f"macro_intelligence: success={ing.get('success_count')}/4 "
            f"confidence={ing.get('overall_confidence')} "
            f"risk={state.get('risk')} regime={state.get('market')} "
            f"insight='{state.get('insight')}'"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("macro_intelligence error: %s", e)


async def _portfolio_snapshot_job():
    """Daily EOD portfolio snapshot — runs 23:30 IST, after all NAV /
    analytics / V3 rescore jobs have completed, so per-holding
    current_price + portfolio scores reflect the freshest EOD numbers."""
    try:
        from services.portfolio_snapshot import run_eod_snapshot_job
        res = await run_eod_snapshot_job()
        logger.info(
            f"portfolio_snapshot ok={res.get('ok')}/{res.get('total')} "
            f"failed={res.get('failed')} date={res.get('date')}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("portfolio_snapshot error: %s", e)


async def _nidp_gcs_export_job():
    """Daily portfolio sync to NIDP — runs 22:50 IST. Sends holdings,
    transactions and goals (HTTP push to the NIDP Query API; GCS export only
    where that API is not configured) so NIDP sees today's state for every
    user — not just users who happened to upload a CAS that day.

    The CAS-import hook in cas_snapshot_engine.py already triggers an
    event-driven export, so this job is the catch-all for goal edits
    and idle days.
    """
    try:
        from services.portfolio_direct_push import sync_portfolio_to_nidp
        from server import db  # avoid circular import at module load
        res = await sync_portfolio_to_nidp(db)
        logger.info(
            "nidp portfolio sync (%s): holdings=%s txns=%s goals=%s",
            res.get("via"),
            *(res.get(k, {}).get("exported", res.get(k, {}).get("error")) for k in ("holdings", "transactions", "goals")),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("nidp_gcs_export error: %s", e)


async def _gmail_auto_import_job():
    """Monthly — 1st of each month, 06:30 IST — for every Gmail-connected
    user with a saved CAS password, scan the inbox and import any new
    NSDL/CDSL/CAMS/KFintech statements. ECAS providers email monthly
    statements in the first few days of the month; running on the 1st at
    06:30 IST catches same-day delivery while the inbox is still fresh.
    Users can also trigger an immediate sync via the Dashboard 'Sync Gmail'
    button which calls /api/gmail/auto-import/run on demand."""
    try:
        from services.gmail_auto_import import auto_import_all_users
        res = await auto_import_all_users()
        logger.info("gmail_auto_import: %s", res)
    except Exception as e:  # noqa: BLE001
        logger.warning("gmail_auto_import error: %s", e)


async def _broker_daily_sync_job():
    """Daily broker holdings refresh — runs 17:30 IST, after market close
    and while the day's broker sessions are still live. Re-reads holdings
    for every directly connected broker account with a live session;
    accounts whose session has ended are left for the user to reconnect.

    Off switch (no deploy): set the secret / env `BROKER_DAILY_SYNC_ENABLED`
    to 0, false, off or no. Unset means on."""
    try:
        from services.brokers._helpers import conf
        if conf("BROKER_DAILY_SYNC_ENABLED").lower() in ("0", "false", "off", "no"):
            logger.info("broker_daily_sync skipped — BROKER_DAILY_SYNC_ENABLED is off")
            return
        from services.brokers import hub_reads
        res = await hub_reads.daily_sync(db)
        logger.info("broker_daily_sync %s", res)
    except Exception as e:  # noqa: BLE001
        logger.warning("broker_daily_sync error: %s", e)


def start():
    """Idempotent start. No-op if already running, or if another process holds the
    scheduler lock (it runs the jobs; see _acquire_leader_lock)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    if not _acquire_leader_lock():
        logger.info("MF scheduler not started in pid %s: another process holds %s and runs the jobs",
                    os.getpid(), _lock_path())
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
    # Portfolio snapshot: daily 23:30 IST — immutable per-user snapshot
    # of total value / allocation / V3 health. Powers the Time-Machine.
    _scheduler.add_job(
        _portfolio_snapshot_job, CronTrigger(hour=23, minute=30),
        id="portfolio_snapshot_daily", replace_existing=True, max_instances=1,
    )
    # NIDP GCS export: daily 22:50 IST — refreshes holdings + transactions
    # + goals into the GCS landing zone so NIDP's portfolio_*_sync jobs
    # (running 23:00–23:15 on the NIDP VM) see today's state. Event-driven
    # exports after CAS imports remain in place for immediate refresh.
    _scheduler.add_job(
        _nidp_gcs_export_job, CronTrigger(hour=22, minute=50),
        id="nidp_gcs_export_daily", replace_existing=True, max_instances=1,
    )
    # Benchmark indices: daily 18:30 IST per the PRD. Pulls NSE indices
    # (Nifty 50, Midcap 150, Smallcap 250, Bank, IT, etc.) from yfinance,
    # upserts OHLC into market_index_data, recomputes returns/volatility/
    # drawdown, busts the latest-snapshot Redis cache.
    # The trigger names its timezone: a CronTrigger without one runs in the process's zone (UTC in the backend
    # image), so "18:30" ran at 00:00 IST.
    _scheduler.add_job(
        _benchmark_refresh_job, CronTrigger(hour=18, minute=30, timezone="Asia/Kolkata"),
        id="benchmark_index_daily", replace_existing=True, max_instances=1,
    )
    # Macro Intelligence layer: 19:30 IST on weekdays, after the warehouse's NSE index close lands (about 19:00 IST),
    # and again at 21:30 IST in case that close was late (the upsert is idempotent). Until 2026-10-27 the trigger had
    # no timezone and ran at 00:05 IST, when yfinance often left out the session that had just closed, so macro_daily
    # lagged (21 and 26 Oct were never stored) and the risk service's regime read three sessions old.
    _scheduler.add_job(
        _macro_intelligence_job,
        CronTrigger(day_of_week="mon-fri", hour=19, minute=30, timezone="Asia/Kolkata"),
        id="macro_intelligence_daily", replace_existing=True, max_instances=1,
    )
    _scheduler.add_job(
        _macro_intelligence_job,
        CronTrigger(day_of_week="mon-fri", hour=21, minute=30, timezone="Asia/Kolkata"),
        id="macro_intelligence_retry", replace_existing=True, max_instances=1,
    )
    # Gmail auto-import: monthly, 1st of month 06:30 IST — pull new ECAS
    # statements (NSDL priority, then CDSL). On-demand sync is available
    # via /api/gmail/auto-import/run (Dashboard "Sync Gmail" button).
    _scheduler.add_job(
        _gmail_auto_import_job, CronTrigger(day=1, hour=6, minute=30),
        id="gmail_auto_import_monthly", replace_existing=True, max_instances=1,
    )
    # Broker holdings: daily 17:30 IST — refresh holdings of every directly
    # connected broker account whose session is still live. Switched off
    # with BROKER_DAILY_SYNC_ENABLED=0 (checked on each run). The trigger
    # names its timezone: a CronTrigger instance does not take the
    # scheduler's, it defaults to the process's local zone (UTC in the
    # backend image).
    _scheduler.add_job(
        _broker_daily_sync_job,
        CronTrigger(hour=17, minute=30, timezone="Asia/Kolkata"),
        id="broker_holdings_sync_daily", replace_existing=True, max_instances=1,
    )
    _scheduler.start()
    logger.info("MF scheduler started (Asia/Kolkata)")


def stop():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            # APScheduler's own event loop may already be closed (e.g. a test that ran start() and stop() in
            # separate asyncio.run() calls). The leader lock still has to come free so another process can take
            # over the jobs, so this never blocks that release.
            logger.warning("mf_scheduler: shutdown raised; releasing the leader lock anyway", exc_info=True)
        _scheduler = None
    _release_leader_lock()


def status() -> dict:
    if _scheduler is None or not _scheduler.running:
        out = {"running": False, "jobs": []}
        if not is_leader():
            out["note"] = "This process does not run the scheduled jobs; the process holding the scheduler lock does."
        return out
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
