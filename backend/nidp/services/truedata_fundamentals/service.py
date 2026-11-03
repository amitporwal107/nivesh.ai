"""One run of the TrueData fundamentals job: discover → fetch (cached) → transform → load (one transaction).

    1. Switch. backend/config/market_data_source.json decides first (nidp.shared.market_data_source). `truedata_is_on()`
       is True in `shadow` (staging since 30 Oct 2026) and `truedata`, False in `current` or with
       MARKET_DATA_SOURCE_FORCE_CURRENT=1 or without TRUEDATA_USERNAME/TRUEDATA_PASSWORD. Off → a SKIPPED job_log row and
       nothing else: no TrueData call, no warehouse write. This job is a gap-filler (balance sheets, cash flows and
       finance costs our own feeds never supplied), not one of the REPLACED_FEEDS, so it runs in `shadow` as the
       owner asked on 2 Nov ("We have truedata.in please fetch the data from there"). Rollback ignores the switch: it
       is the way back.
    2. Discover. getResultList for every day of the load window (default 10) and, once, of the anchor window (default
       400 days: the fiscal-year P&L that fixes each company's unit is filed in April-May). Lists already cached are not
       asked again, except the last 3 days (a day's list grows while companies file).
    3. Fetch. For the window's filings (ours only, consolidated preferred, duplicates removed): the latest FY P&L per
       company (unit anchor), balance sheet + cash flow of half-year / fiscal-year filings, then the quarter-only P&L of
       every quarterly filing (finance costs). Largest companies first. Only what the cache lacks is fetched, at most one
       call per `min_interval` (1.2 s; TrueData's corporate limit is 1/s, 60/min, 3600/h, shared with the 22:45
       cross-check), until `max_minutes` is spent. "No such statement" answers are cached; failures are not.
    2a. STAGING ONLY (owner, 3 Nov 2026: "keep on staging.. on prod please use our snapshot data"). After the switch,
       every mode but rollback asks nidp.shared.deploy_env.truedata_load_gate() (shared with the other TrueData jobs).
       It decides from the database the rows would land in (`nidp_staging` = staging, `nidp` = production) and refuses
       on any production signal (NIDP_HOME=/opt/nidp, NIDP_ENV/APP_ENV prod/production) or anything not positively
       staging. Refused: verdict NOT_STAGING, no TrueData call, no raw cache write, no data written; a real (not dry)
       run records one SKIPPED job_log row, error_class NOT_STAGING. Not built, on purpose: a production override. If
       the owner ever wants one, it should need BOTH `truedata_licence_confirmed: true` in market_data_source.json AND
       a separate explicit owner flag for this job; until then production is refused unconditionally.
    4. Transform (transform.py) and load (plan.py, loader.py): fill-only, provenance in
       nidp.truedata_fundamentals_fills, undone exactly by `--rollback RUN_ID` (allowed in every environment).

Status: OK; PARTIAL when fetching stopped early (deadline, rate limit, repeated failures) — what was cached is still
loaded and the next run carries on; FAILED when TrueData refuses the login or the load raises (nothing is written);
SKIPPED when the switch is off. `--dry-run` reads the warehouse and writes nothing to it (no job_log row either);
it still fills the raw cache from TrueData unless `--offline`.
"""
from __future__ import annotations

import logging
import os
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from nidp.shared import deploy_env
from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

from . import transform as T
from .cache import RawCache

logger = logging.getLogger(__name__)

INGESTER = "truedata_fundamentals"
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_DAYS = 10
DEFAULT_ANCHOR_DAYS = 400
REFRESH_RECENT_DAYS = 3
DEFAULT_MAX_MINUTES = 75
DEFAULT_MIN_INTERVAL_S = 1.2
RATE_LIMIT_PAUSE_S = 65.0
MAX_RATE_LIMIT_PAUSES = 3
UNAVAILABLE_RETRY_S = 10.0
MAX_CONSECUTIVE_ERRORS = 5
REPORT_REJECTS = 25


def default_raw_root() -> Path:
    env = (os.environ.get("TRUEDATA_FUNDAMENTALS_RAW_DIR") or "").strip()
    if env:
        return Path(env)
    from nidp.shared.config import NIDP_RAW_DIR
    return Path(NIDP_RAW_DIR) / INGESTER


class Fetcher:
    """Fills the raw cache from TrueData within a deadline. Never raises for one bad answer; stops (and says why) on
    a refused login, a quota it cannot wait out, the deadline, or repeated failures."""

    def __init__(self, client: Any, cache: RawCache, deadline: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.client, self.cache, self.deadline = client, cache, deadline
        self.clock, self.sleep = clock, sleep
        self.counts: Counter = Counter()
        self.stopped: Optional[str] = None           # why fetching stopped early
        self.fatal: Optional[str] = None             # login refused / not subscribed: the run fails
        self._errors_in_row = 0

    def _call(self, fn: Callable[..., Any], *args: Any) -> Tuple[str, Any]:
        pauses = unavailable = 0
        while True:
            if self.stopped:
                return "stop", None
            if self.clock() >= self.deadline:
                self.stopped = "DEADLINE"
                return "stop", None
            self.counts["calls"] += 1
            try:
                out = fn(*args)
                self._errors_in_row = 0
                return "ok", out
            except td.TrueDataError as e:
                if e.code in (td.EMPTY_RESPONSE, td.INVALID_REQUEST):
                    self._errors_in_row = 0
                    return "empty", (e.code, e.message)
                if e.code in (td.NOT_CONFIGURED, td.AUTH_EXPIRED):
                    self.fatal = self.stopped = e.code
                    return "stop", None
                if e.code == td.RATE_LIMITED and pauses < MAX_RATE_LIMIT_PAUSES:
                    pauses += 1
                    self.counts["rate_limit_pauses"] += 1
                    self.sleep(RATE_LIMIT_PAUSE_S)
                    continue
                if e.code == td.RATE_LIMITED:
                    self.stopped = "RATE_LIMITED"
                    return "stop", None
                if e.code == td.PROVIDER_UNAVAILABLE and unavailable < 1:
                    unavailable += 1
                    self.sleep(UNAVAILABLE_RETRY_S)
                    continue
                self.counts[f"error_{e.code}"] += 1
                self._errors_in_row += 1
                if self._errors_in_row >= MAX_CONSECUTIVE_ERRORS:
                    self.stopped = "TOO_MANY_ERRORS"
                logger.warning("truedata_fundamentals: %s", e.message)
                return "error", e.code

    def fetch_lists(self, days: Sequence[date], today: date) -> None:
        fresh_from = today - timedelta(days=REFRESH_RECENT_DAYS - 1)
        for day in days:
            if self.cache.has("lists", day) and day < fresh_from:
                self.counts["lists_cached"] += 1
                continue
            kind, out = self._call(self.client.result_list, day)
            if kind == "ok":
                self.cache.write("lists", day, {"status": "Success", "Records": out})
                self.counts["lists_fetched"] += 1
            elif kind == "empty":
                self.cache.write("lists", day, {"status": "Success", "Records": []})
                self.counts["lists_fetched"] += 1
            elif kind == "stop":
                return

    def fetch_statements(self, needed: Iterable[Tuple[str, int]]) -> None:
        calls = {"al": lambda i: self.client.balance_sheet(i), "cf": lambda i: self.client.cash_flow(i, True),
                 "pl": lambda i: self.client.pnl(i, True), "plq": lambda i: self.client.pnl(i, False)}
        for kind, fid in needed:
            if self.cache.has(kind, fid):
                self.counts["statements_cached"] += 1
                continue
            outcome, out = self._call(calls[kind], fid)
            if outcome == "ok":
                self.cache.write(kind, fid, out)
                self.counts[f"{kind}_fetched"] += 1
            elif outcome == "empty":
                self.cache.write_empty(kind, fid, *out)
                self.counts[f"{kind}_empty"] += 1
            elif outcome == "stop":
                self.counts["statements_not_fetched"] += 1
            if self.stopped:
                return


def window_days(today: date, days: int) -> List[date]:
    return [today - timedelta(days=i) for i in range(max(days, 0))]


def select(cache: RawCache, refs: Any, today: date, days: int) -> Tuple[List[T.Filing], List[T.Filing], Counter]:
    """(window_filings: the load window's filings, all: every cached filing for the unit anchors), both ours, consolidated
    preferred, duplicates removed."""
    filings, counts = T.filings_from_records(cache.list_records(), refs.known, refs.bse_map)
    all_f = T.dedupe(T.prefer_consolidated(filings))
    window_ids = set()
    for day in window_days(today, days):
        for r in (cache.read("lists", day) or {}).get("Records") or []:
            try:
                window_ids.add(int(r.get("id")))
            except (TypeError, ValueError):
                continue
    window_filings = [f for f in all_f if f.id in window_ids]
    counts["filings_ours_deduped"] = len(all_f)
    counts["filings_in_window"] = len(window_filings)
    return window_filings, all_f, counts


async def run(*, days: int = DEFAULT_DAYS, symbols: Optional[Sequence[str]] = None, dry_run: bool = False,
              offline: bool = False, anchor_days: int = DEFAULT_ANCHOR_DAYS, max_minutes: float = DEFAULT_MAX_MINUTES,
              finance_costs: bool = True, today: Optional[date] = None, raw_root: Optional[Path] = None,
              client: Any = None, warehouse: Any = None, resolution: Optional[mds.Resolution] = None,
              job_factory: Optional[Callable[[], Any]] = None, clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep, environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    today = today or datetime.now(IST).date()
    resolution = resolution or mds.resolve()
    if warehouse is None:
        from .loader import Warehouse
        warehouse = Warehouse()
    if job_factory is None:
        from nidp.shared.storage.job_log import JobRun
        job_factory = lambda: JobRun(INGESTER, target_date=today)            # noqa: E731

    if not mds.truedata_is_on(resolution):
        report = {"status": "SKIPPED", "verdict": "SWITCHED_OFF", "reason": mds.truedata_off_message(resolution),
                  "dry_run": dry_run}
        if not dry_run:
            async with job_factory() as job:
                job.metadata = dict(report)
                await job.finalize("SKIPPED", error_message=report["reason"])
            report["run_id"] = str(job.run_id)
        return report

    gate = await warehouse.load_gate(environ)                 # staging only: decided by the database written to
    if not gate.allowed:
        report = {"status": "SKIPPED", "verdict": deploy_env.NOT_STAGING, "environment": gate.environment,
                  "reason": gate.reason, "dry_run": dry_run}
        if not dry_run:
            async with job_factory() as job:
                job.metadata = dict(report)
                await job.finalize("SKIPPED", error_message=gate.reason[:500], error_class=deploy_env.NOT_STAGING)
            report["run_id"] = str(job.run_id)
        return report

    kwargs = dict(days=days, symbols=symbols, offline=offline, anchor_days=anchor_days, max_minutes=max_minutes,
                  finance_costs=finance_costs, today=today, raw_root=raw_root, client=client, warehouse=warehouse,
                  clock=clock, sleep=sleep)
    if dry_run:
        return {"environment": gate.environment, **(await _run(run_id=None, dry_run=True, **kwargs))}
    async with job_factory() as job:
        report = {"environment": gate.environment, **(await _run(run_id=str(job.run_id), dry_run=False, **kwargs))}
        job.rows_fetched = int(report.get("fetch", {}).get("calls", 0))
        job.rows_inserted = int(report.get("load", {}).get("rows_written", 0))
        job.rows_skipped = int(report.get("transform", {}).get("rejects", 0))
        job.metadata = {k: report[k] for k in ("window", "fetch", "transform", "load", "status_reason") if k in report}
        await job.finalize(report["status"], error_message=report.get("status_reason"),
                           error_class=report.get("error_class"))
    return report


async def _run(*, run_id: Optional[str], dry_run: bool, days: int, symbols: Optional[Sequence[str]], offline: bool,
               anchor_days: int, max_minutes: float, finance_costs: bool, today: date, raw_root: Optional[Path],
               client: Any, warehouse: Any, clock: Callable[[], float], sleep: Callable[[float], None]) -> Dict[str, Any]:
    cache = RawCache(raw_root or default_raw_root())
    report: Dict[str, Any] = {"run_id": run_id, "dry_run": dry_run, "offline": offline,
                              "window": {"today": today.isoformat(), "days": days, "anchor_days": anchor_days,
                                         "symbols": list(symbols) if symbols else None},
                              "raw_cache": str(cache.root)}
    if not offline and client is None:
        client = td.TrueDataClient(min_interval=float(os.environ.get("TRUEDATA_FUNDAMENTALS_MIN_INTERVAL_S",
                                                                     DEFAULT_MIN_INTERVAL_S)))
    if not offline and not getattr(client, "configured", True):
        report.update(status="FAILED", status_reason="TrueData credentials are not configured", error_class="NOT_CONFIGURED")
        return report

    refs = await warehouse.references(symbols)
    report["universe"] = {"symbols": len(refs.known), "bse_codes": len(refs.bse_map), "with_shares": len(refs.shares)}

    fetcher = None
    if not offline:
        fetcher = Fetcher(client, cache, clock() + max_minutes * 60.0, clock=clock, sleep=sleep)
        fetcher.fetch_lists(window_days(today, max(days, anchor_days)), today)
    window_filings, all_f, sel_counts = select(cache, refs, today, days)
    needed = T.statements_needed(window_filings, all_f, finance_costs, rank=_size_rank(refs))
    if fetcher is not None and not fetcher.stopped:
        fetcher.fetch_statements(needed)
    report["fetch"] = {"needed": len(needed), **(dict(fetcher.counts) if fetcher else {}),
                       "calls": fetcher.counts["calls"] if fetcher else 0,
                       "stopped": fetcher.stopped if fetcher else None, **dict(sel_counts)}
    if fetcher is not None and fetcher.fatal:
        report.update(status="FAILED", status_reason=f"TrueData refused: {fetcher.fatal}", error_class=fetcher.fatal)
        return report

    result = T.build(window_filings, all_f, cache.read, refs.ours, refs.shares, finance_costs)
    report["transform"] = result.summary()
    report["rejected"] = [{"kind": r.kind, "symbol": r.symbol, "period_end": str(r.period_end),
                           "filing_id": r.filing_id, "why": r.reason} for r in result.rejects[:REPORT_REJECTS]]
    report["load"] = await warehouse.load(result.offers, run_id, dry_run)

    stopped = fetcher.stopped if fetcher else None
    errors = sum(v for k, v in (fetcher.counts.items() if fetcher else []) if k.startswith("error_"))
    if stopped or errors:
        report.update(status="PARTIAL", status_reason=f"fetch stopped: {stopped}" if stopped else f"{errors} fetch errors")
    else:
        report["status"] = "OK"
    logger.info("truedata_fundamentals %s: %s filings in window, %s offers, load %s", report["status"],
                len(window_filings), len(result.offers), report["load"])
    return report


def _size_rank(refs: Any) -> Dict[str, int]:
    """Largest companies first (our market cap), so a run cut short by its deadline has covered the biggest names."""
    caps = getattr(refs, "caps", None) or {}
    order = sorted(refs.known, key=lambda s: (-(caps.get(s) or 0.0), s))
    return {s: i for i, s in enumerate(order)}


async def rollback(run_id: str, warehouse: Any = None) -> Dict[str, Any]:
    """Undo one run exactly (loader.rollback_run). Works whatever the switch says and in every environment (the
    staging-only gate does not apply): it is the way back."""
    if warehouse is None:
        from .loader import Warehouse
        warehouse = Warehouse()
    return {"rollback_of": run_id, **(await warehouse.rollback(run_id))}
