"""NIDP backfill orchestrator.

Drives historical ingestion across multiple dates and services with
rate limiting + holiday awareness + per-day fault isolation. This is
how we prepopulate the warehouse — bhavcopy/delivery/etc. for a date
range, plus the rolling sources (bulk, block, CA, calendar,
constituents) once.

Design principles (mapped to the production stack):
    1. Per-date, per-service granularity. A single date+service failure
       leaves a FAILED row in nidp.job_log + Prometheus alert; the
       rest of the backfill continues.
    2. Holiday-aware. If nidp.nse_holidays is populated, we skip
       non-trading days for daily sources. If empty (first-run case),
       we fall back to weekday-only filtering and let job_log capture
       any 404s from NSE (those days were genuinely closed).
    3. Polite rate limit. Per-host concurrency cap + min-gap so NSE's
       Akamai bot-mgmt doesn't 503 us into a 20-min cool-off.
    4. Resumable. Re-running a backfill skips dates that already have
       a successful job_log row — driven by (ingester, target_date)
       lookup, not local state.
    5. No coupling to existing services. Pure orchestration over the
       same BaseIngester contract every NIDP service implements.

Daily-cadence sources (need date param):
    bhavcopy, delivery, index_close, fii_dii

Rolling sources (no date — one shot covers the rolling window):
    bulk_deals, block_deals, corporate_actions, index_constituents,
    nse_calendar, rbi_yields

Backfill order (locked):
    1. nse_calendar              (first — populates holiday filter)
    2. index_constituents        (second — needed for Nifty-500 views)
    3. bhavcopy per trading day  (heaviest — ~30k rows/day)
    4. delivery per trading day
    5. index_close per trading day
    6. fii_dii per trading day
    7. bulk_deals + block_deals  (rolling, one shot)
    8. corporate_actions         (rolling, one shot)
    9. rbi_yields                (rolling)

Usage:
    python -m nidp.cli backfill --from 2024-01-01 --to 2026-05-04
    python -m nidp.cli backfill --from 2024-01-01 --to 2026-05-04 \\
        --services bhavcopy,delivery
    python -m nidp.cli backfill --from 2024-01-01 --to 2026-05-04 \\
        --skip-existing
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


# ── Service registry (mirrors cli.py + adds backfill metadata) ──────
@dataclass(frozen=True)
class ServiceSpec:
    name: str
    module_path: str
    needs_date: bool                # if False, the ingester is rolling
    polite_gap_s: float = 1.0       # min gap between consecutive runs


SPECS: list[ServiceSpec] = [
    # Reference / one-shot
    ServiceSpec("nse_calendar",        "nidp.services.nse_calendar.service",       False, 0.5),
    ServiceSpec("index_constituents",  "nidp.services.index_constituents.service", False, 1.5),
    # Per-day market data
    ServiceSpec("bhavcopy",            "nidp.services.bhavcopy.service",           True,  1.5),
    ServiceSpec("delivery",            "nidp.services.delivery.service",           True,  1.0),
    ServiceSpec("index_close",         "nidp.services.index_close.service",        True,  1.0),
    ServiceSpec("fii_dii",             "nidp.services.fii_dii.service",            True,  1.0),
    # Per-day filings. run() drives NSE + BSE coarse + BSE subcategory, each
    # independently. Document discovery keys off these rows, so corpus depth can
    # never exceed this feed's history — backfilling it is what makes historical
    # filings reachable at all. polite_gap 1.5s: three sources per date against
    # exchange endpoints that already rate-limited us once.
    ServiceSpec("corporate_announcements",
                "nidp.services.corporate_announcements.service",                   True,  1.5),
    # Rolling
    ServiceSpec("bulk_deals",          "nidp.services.bulk_deals.service",         False, 0.5),
    ServiceSpec("block_deals",         "nidp.services.block_deals.service",        False, 0.5),
    ServiceSpec("corporate_actions",   "nidp.services.corporate_actions.service",  False, 0.5),
    ServiceSpec("rbi_yields",          "nidp.services.rbi_yields.service",         False, 0.5),
    # Derived analytics engines (heavy — bigger polite_gap to avoid load spike).
    # Order is load-bearing when run for the same date: technical writes
    # stock_features rows, fundamental reads them, mf_analytics is independent.
    ServiceSpec("mf_analytics_engine",        "nidp.services.mf_analytics_engine.service",        True,  3.0),
    ServiceSpec("technical_indicator_engine", "nidp.services.technical_indicator_engine.service", True,  3.0),
    ServiceSpec("fundamental_engine",         "nidp.services.fundamental_engine.service",         True,  3.0),
]
SPEC_BY_NAME = {s.name: s for s in SPECS}


# ── Trading-day enumeration ─────────────────────────────────────────
async def trading_days(start: date, end: date, *, segment: str = "CM") -> list[date]:
    """Inclusive list of trading days from start..end.

    Strategy:
        - Drop weekends.
        - Drop dates present in nidp.nse_holidays for the requested
          segment (CM by default).
        - If nse_holidays is empty (first-run case), only weekend
          filtering applies — backfill will see 404s on actual
          holidays, which job_log captures as FAILED.
    """
    holidays: set[date] = set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT holiday_date FROM nidp.nse_holidays
                WHERE segment = $1 AND holiday_date BETWEEN $2 AND $3""",
            segment, start, end,
        )
        holidays = {r["holiday_date"] for r in rows}

    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            out.append(cur)
        cur += timedelta(days=1)
    return out


# ── Resumability check ──────────────────────────────────────────────
async def already_succeeded(ingester: str, target_date: Optional[date]) -> bool:
    """Returns True if a previous OK/PARTIAL run exists for this
    (ingester, target_date) — meaning we can skip on resume."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if target_date is None:
            row = await conn.fetchval(
                """SELECT 1 FROM nidp.job_log
                    WHERE ingester=$1 AND target_date IS NULL
                      AND status IN ('OK','PARTIAL')
                    LIMIT 1""",
                ingester,
            )
        else:
            row = await conn.fetchval(
                """SELECT 1 FROM nidp.job_log
                    WHERE ingester=$1 AND target_date=$2
                      AND status IN ('OK','PARTIAL')
                    LIMIT 1""",
                ingester, target_date,
            )
    return row is not None


# ── Core orchestration ──────────────────────────────────────────────
@dataclass
class BackfillReport:
    started_at: datetime = field(default_factory=lambda: datetime.utcnow())
    finished_at: Optional[datetime] = None
    runs_ok: int = 0
    runs_failed: int = 0
    runs_skipped: int = 0
    failures: list[tuple[str, Optional[date], str]] = field(default_factory=list)


async def _run_one(
    spec: ServiceSpec,
    target_date: Optional[date],
    *,
    skip_existing: bool,
    report: BackfillReport,
) -> None:
    ds = target_date.isoformat() if target_date else "(rolling)"
    if skip_existing and await already_succeeded(spec.name, target_date):
        logger.info("backfill[%s %s] SKIP (already succeeded)", spec.name, ds)
        report.runs_skipped += 1
        return
    try:
        mod = importlib.import_module(spec.module_path)
        run_fn = getattr(mod, "run")
        logger.info("backfill[%s %s] start", spec.name, ds)
        if spec.needs_date:
            await run_fn(target_date)
        else:
            await run_fn(target_date)  # most accept Optional[date]
        report.runs_ok += 1
        logger.info("backfill[%s %s] ok", spec.name, ds)
    except Exception as e:                                         # noqa: BLE001
        report.runs_failed += 1
        report.failures.append((spec.name, target_date, f"{type(e).__name__}: {e}"[:300]))
        logger.warning("backfill[%s %s] FAILED: %s", spec.name, ds, e)


async def run_backfill(
    *,
    start: date,
    end: date,
    services: Optional[Iterable[str]] = None,
    skip_existing: bool = True,
    rolling_first: bool = True,
) -> BackfillReport:
    """Run a multi-source date-range backfill.

    Args:
        start, end:        inclusive date range for daily-cadence sources.
        services:          subset of service names; None = all.
        skip_existing:     resume mode; default True.
        rolling_first:     if True, run reference + rolling sources before
                           the heavy per-day loop. Recommended for first
                           run so holiday filter populates first.
    """
    report = BackfillReport()
    if services:
        unknown = [n for n in services if n not in SPEC_BY_NAME]
        if unknown:
            # Silently filtering these out meant `--services typo` ran zero jobs
            # and exited 0 reporting "ok: 0" — indistinguishable from success.
            raise ValueError(
                f"unknown service(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(SPEC_BY_NAME))}")
    selected = list(SPECS) if services is None else [
        SPEC_BY_NAME[n] for n in services
    ]
    daily = [s for s in selected if s.needs_date]
    rolling = [s for s in selected if not s.needs_date]

    # Phase A — rolling/reference (so holiday-aware enumeration sees data)
    if rolling_first:
        for spec in rolling:
            await _run_one(spec, None, skip_existing=skip_existing, report=report)
            await asyncio.sleep(spec.polite_gap_s)

    # Phase B — daily, per service per day. Per-service inner loop so a
    # single source's rate limit doesn't starve the others.
    if daily:
        # Cap end at the last published NSE close. Without this, a
        # backfill ending "today" runs before NSE publishes bhavcopy
        # (~18:00 IST) and burns 4xx retries against URLs that don't
        # yet exist. last_market_close_date() reads
        # nidp.v_market_session — the canonical "what's published?"
        # source — and falls back to the in-process 18:30 IST cutoff
        # heuristic if the DB lookup fails.
        from nidp.shared.trading_day import last_market_close_date
        last_close = await last_market_close_date()
        effective_end = min(end, last_close)
        if effective_end < end:
            logger.info(
                "backfill: clamping end %s → %s (last published NSE close)",
                end, effective_end,
            )
        days = await trading_days(start, effective_end)
        logger.info("backfill: %d trading day(s) from %s to %s",
                    len(days), start, effective_end)
        for spec in daily:
            for d in days:
                await _run_one(spec, d, skip_existing=skip_existing, report=report)
                await asyncio.sleep(spec.polite_gap_s)

    # Phase C — rolling/reference at the end (catches any updates published
    # while the daily loop was running). Cheap; idempotent.
    if not rolling_first:
        for spec in rolling:
            await _run_one(spec, None, skip_existing=skip_existing, report=report)
            await asyncio.sleep(spec.polite_gap_s)

    report.finished_at = datetime.utcnow()
    return report


# ── CLI subparser (also exposed via `python -m nidp.cli backfill`) ──
def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def add_subparser(sub) -> None:
    p = sub.add_parser("backfill", help="Date-range multi-source historical ingestion.")
    p.add_argument("--from", dest="start", type=_parse_date, required=True)
    p.add_argument("--to",   dest="end",   type=_parse_date, required=True)
    p.add_argument("--services", default=None,
                   help="Comma-separated subset; default = all 10.")
    p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    p.add_argument("--no-rolling-first", dest="rolling_first", action="store_false")
    p.set_defaults(skip_existing=True, rolling_first=True)


async def cmd_backfill(args: argparse.Namespace) -> int:
    services = [s.strip() for s in args.services.split(",")] if args.services else None
    if args.start > args.end:
        print("ERROR: --from must be ≤ --to")
        return 2

    report = await run_backfill(
        start=args.start, end=args.end,
        services=services,
        skip_existing=args.skip_existing,
        rolling_first=args.rolling_first,
    )
    print()
    print(f"  Backfill complete in {(report.finished_at - report.started_at).total_seconds():.1f}s")
    print(f"  ok      : {report.runs_ok}")
    print(f"  failed  : {report.runs_failed}")
    print(f"  skipped : {report.runs_skipped}")
    if report.failures:
        print()
        print("  Failures (first 20):")
        for name, dt, msg in report.failures[:20]:
            ds = dt.isoformat() if dt else "(rolling)"
            print(f"    {name:20s} {ds}  {msg}")
        if len(report.failures) > 20:
            print(f"    … {len(report.failures) - 20} more in nidp.job_log (status='FAILED')")
    return 0 if report.runs_failed == 0 else 1
