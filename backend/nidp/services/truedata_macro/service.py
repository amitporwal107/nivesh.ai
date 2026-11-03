"""Nightly refresh of the TrueData macro / factor series in nidp.fred_macro (series_id TD_*, source 'truedata').

The 24 series were first loaded on 2 Nov 2026 (test_reports/truedata_research_data_20261102.md, 89,561 rows); this job
appends the days since each series' last stored day. Series ids, names, units and caveats are the ones of that load,
so a reader sees one series, not two.

Rules
  * Only new days: the fetch starts the day after the series' last stored date (an empty series starts at 2010-01-01);
    a series already up to date makes no call. Rows are inserted with ON CONFLICT DO NOTHING: a stored day is never
    rewritten, so a run's rows are exactly its source_run_id and rollback(run_id) undoes it.
  * Never an unfinished bar: MCX trades until ~23:30-23:55 IST, so today's MCX bar is never stored before 23:59 IST;
    index bars for today only after 16:00 IST (NSE closes 15:30). Future-dated bars are dropped.
  * Duplicate days: identical copies collapse; a day whose copies disagree is dropped and reported
    (MCX 2020-10-08 in the 2 Nov load).
  * TrueData's INDIA VIX, NIFTY50 USD and NIFTY GS * values are snapshots, often a day off NSE's official close (median
    gap 0.02-0.03 %, max 2.6 %, measured 2 Nov 2026 against nidp.index_eod): their series_name says so ("use weekly
    returns"). NIFTY 50 equals NSE's official close and carries no caveat. Prefer nidp.index_eod where it exists.
  * The market-data switch: at `current` nothing calls TrueData; the run is recorded as SKIPPED (SWITCHED_OFF), like
    truedata_crosscheck. A dry run at `current` touches neither TrueData nor the database.

Not available from TrueData (2 Nov 2026): USDINR (currency segment not subscribed; INR proxy = NIFTY 50 / NIFTY50 USD),
repo-rate history, bond yields (only G-Sec index prices), rollover-adjusted continuous futures (-I / -II roll at expiry).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td
from nidp.services.truedata_history import bars as B

logger = logging.getLogger(__name__)

INGESTER = "truedata_macro"
SOURCE = "truedata"
IST = timezone(timedelta(hours=5, minutes=30))
FIRST_DAY = date(2010, 1, 1)

# TrueData code -> (series_id, name, units, segment). Same ids / names / units as the 2 Nov load.
SERIES: Dict[str, Tuple[str, str, str, str]] = {
    "CRUDEOIL-I": ("TD_MCX_CRUDEOIL_1M", "MCX crude oil, near-month continuous future, close", "INR per barrel", "mcx"),
    "CRUDEOIL-II": ("TD_MCX_CRUDEOIL_2M", "MCX crude oil, next-month continuous future, close", "INR per barrel", "mcx"),
    "NATURALGAS-I": ("TD_MCX_NATURALGAS_1M", "MCX natural gas, near-month continuous future, close", "INR per mmBtu", "mcx"),
    "NATURALGAS-II": ("TD_MCX_NATURALGAS_2M", "MCX natural gas, next-month continuous future, close", "INR per mmBtu",
                      "mcx"),
    "GOLD-I": ("TD_MCX_GOLD_1M", "MCX gold, near-month continuous future, close", "INR per 10 g", "mcx"),
    "GOLD-II": ("TD_MCX_GOLD_2M", "MCX gold, next-month continuous future, close", "INR per 10 g", "mcx"),
    "SILVER-I": ("TD_MCX_SILVER_1M", "MCX silver, near-month continuous future, close", "INR per kg", "mcx"),
    "SILVER-II": ("TD_MCX_SILVER_2M", "MCX silver, next-month continuous future, close", "INR per kg", "mcx"),
    "COPPER-I": ("TD_MCX_COPPER_1M", "MCX copper, near-month continuous future, close", "INR per kg", "mcx"),
    "COPPER-II": ("TD_MCX_COPPER_2M", "MCX copper, next-month continuous future, close", "INR per kg", "mcx"),
    "ALUMINIUM-I": ("TD_MCX_ALUMINIUM_1M", "MCX aluminium, near-month continuous future, close", "INR per kg", "mcx"),
    "ALUMINIUM-II": ("TD_MCX_ALUMINIUM_2M", "MCX aluminium, next-month continuous future, close", "INR per kg", "mcx"),
    "ZINC-I": ("TD_MCX_ZINC_1M", "MCX zinc, near-month continuous future, close", "INR per kg", "mcx"),
    "ZINC-II": ("TD_MCX_ZINC_2M", "MCX zinc, next-month continuous future, close", "INR per kg", "mcx"),
    "INDIA VIX": ("TD_INDIA_VIX", "India VIX, close", "index", "index"),
    "NIFTY 50": ("TD_NIFTY_50", "Nifty 50, close", "index", "index"),
    "NIFTY50 USD": ("TD_NIFTY50_USD", "Nifty50 USD (Nifty 50 in US dollars), close", "index", "index"),
    "NIFTY GS 10YR": ("TD_NIFTY_GSEC_10Y", "Nifty 10 yr Benchmark G-Sec index (total return), close", "index", "index"),
    "NIFTY GS 10YR CLN": ("TD_NIFTY_GSEC_10Y_CLEAN", "Nifty 10 yr Benchmark G-Sec clean-price index, close", "index",
                          "index"),
    "NIFTY GS 4 8YR": ("TD_NIFTY_GSEC_4_8Y", "Nifty 4-8 yr G-Sec index, close", "index", "index"),
    "NIFTY GS 8 13YR": ("TD_NIFTY_GSEC_8_13Y", "Nifty 8-13 yr G-Sec index, close", "index", "index"),
    "NIFTY GS 11 15YR": ("TD_NIFTY_GSEC_11_15Y", "Nifty 11-15 yr G-Sec index, close", "index", "index"),
    "NIFTY GS 15YRPLUS": ("TD_NIFTY_GSEC_15Y_PLUS", "Nifty 15 yr and above G-Sec index, close", "index", "index"),
    "NIFTY GS COMPSITE": ("TD_NIFTY_GSEC_COMPOSITE", "Nifty Composite G-Sec index, close", "index", "index"),
}

# Measured 2 Nov 2026 against NSE index_eod (Apr 2024 - Nov 2026). Nifty 50 matches exactly and carries no caveat.
CAVEATS: Dict[str, str] = {
    "INDIA VIX": "TrueData snapshot, not NSE official close: median gap 0.02%, 8% of days >0.05%, max 2.6%",
    "NIFTY50 USD": "TrueData snapshot, not NSE official close: median gap 0.03%, max 1.7%; use weekly returns",
}
for _c in ("NIFTY GS 10YR", "NIFTY GS 10YR CLN", "NIFTY GS 4 8YR", "NIFTY GS 8 13YR", "NIFTY GS 11 15YR",
           "NIFTY GS 15YRPLUS", "NIFTY GS COMPSITE"):
    CAVEATS[_c] = "TrueData snapshot, often a day off NSE official close (median gap 0.02-0.03%); use weekly returns"


def series_label(code: str) -> str:
    name = SERIES[code][1]
    caveat = CAVEATS.get(code)
    return f"{name} ({caveat})" if caveat else name


def last_final_day(segment: str, now_ist: datetime) -> date:
    """The latest day whose bar is final at `now_ist` for this segment."""
    today = now_ist.date()
    return today if now_ist.time() >= B.FINAL_AFTER[segment] else today - timedelta(days=1)


def new_rows(code: str, rows: Sequence[Dict[str, Any]], after: Optional[date], now_ist: datetime
             ) -> Tuple[List[Tuple[date, float]], Dict[str, Any]]:
    """TrueData rows → [(day, close)] strictly after `after`, finished, deduped; and what was dropped."""
    seg = SERIES[code][3]
    clean, rep = B.clean_bars(rows)
    kept, unfinished = B.drop_unfinished(clean, seg, now_ist)
    out = [(d, b.close) for d, b in sorted(kept.items()) if after is None or d > after]
    return out, {"rows_in": rep.rows_in, "conflicting_dates": [d.isoformat() for d in rep.conflicting_dates],
                 "unfinished_dropped": [d.isoformat() for d in unfinished], "bad_rows": rep.bad_rows}


_LAST_SQL = ("SELECT series_id, max(as_of_date) AS last FROM nidp.fred_macro WHERE source = $1 "
             "AND series_id = ANY($2::text[]) GROUP BY 1")

_INSERT_SQL = """
INSERT INTO nidp.fred_macro (as_of_date, series_id, series_name, value, units, frequency, source, source_run_id)
SELECT d, s, n, v, u, 'daily', $6, $7
  FROM unnest($1::date[], $2::text[], $3::text[], $4::numeric[], $5::text[]) AS t(d, s, n, v, u)
ON CONFLICT (as_of_date, series_id, source) DO NOTHING"""


def _fetch(client: td.TrueDataClient, code: str, start: date, end: date) -> List[Dict[str, Any]]:
    try:
        return client.bars(code, datetime.combine(start, time(0, 0)), datetime.combine(end, time(23, 59, 59)),
                           interval="eod")
    except td.TrueDataError as e:
        if e.code == td.EMPTY_RESPONSE:          # a holiday / weekend window: no new day, not a failure
            return []
        raise


async def refresh(*, client: Optional[td.TrueDataClient] = None, switch: Optional[Callable[[], mds.Resolution]] = None,
                  pool=None, now_ist: Optional[datetime] = None, dry_run: bool = False, codes: Optional[Sequence[str]] = None,
                  job_run_factory=None) -> Dict[str, Any]:
    resolution = (switch or mds.resolve)()
    now_ist = now_ist or datetime.now(IST)
    codes = list(codes or SERIES)
    report: Dict[str, Any] = {"ingester": INGESTER, "dry_run": dry_run, "market_data_source": resolution.effective,
                              "now_ist": now_ist.isoformat(timespec="minutes")}
    if job_run_factory is None and not dry_run:
        from nidp.shared.storage.job_log import JobRun as job_run_factory

    if not mds.truedata_is_on(resolution):
        report.update(verdict="SWITCHED_OFF", message=mds.truedata_off_message(resolution))
        if not dry_run:                                       # recorded like truedata_crosscheck: SKIPPED, nothing else
            async with job_run_factory(INGESTER, target_date=now_ist.date()) as run:
                await run.finalize("SKIPPED", error_message=report["message"][:500], error_class="SWITCHED_OFF")
            report["job_status"] = "SKIPPED"
        return report

    client = client or td.TrueDataClient()
    if pool is None:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()

    async def body(run_id: Optional[uuid.UUID]) -> Dict[str, Any]:
        async with pool.acquire() as conn:
            last = {r["series_id"]: r["last"] for r in await conn.fetch(_LAST_SQL, SOURCE, [SERIES[c][0] for c in codes])}
        per: Dict[str, Any] = {}
        batch: List[Tuple[date, str, str, float, str]] = []
        for code in codes:
            sid, _name, units, seg = SERIES[code]
            after = last.get(sid)
            start = (after + timedelta(days=1)) if after else FIRST_DAY
            end = last_final_day(seg, now_ist)
            entry: Dict[str, Any] = {"series_id": sid, "last_stored": after, "fetch_from": start, "fetch_to": end}
            if start > end:
                per[code] = {**entry, "status": "UP_TO_DATE", "new_days": 0, "calls": 0}
                continue
            try:
                rows = await asyncio.to_thread(_fetch, client, code, start, end)
            except td.TrueDataError as e:
                per[code] = {**entry, "status": "FAILED", "error_code": e.code, "message": e.message, "calls": 1}
                continue
            got, rep = new_rows(code, rows, after, now_ist)
            label = series_label(code)
            batch.extend((d, sid, label, v, units) for d, v in got)
            per[code] = {**entry, "status": "OK", "new_days": len(got), "calls": 1,
                         "first_new": got[0][0] if got else None, "last_new": got[-1][0] if got else None, **rep}
        inserted = 0
        if run_id is not None and batch:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    status = await conn.execute(_INSERT_SQL, [b[0] for b in batch], [b[1] for b in batch],
                                                [b[2] for b in batch], [b[3] for b in batch], [b[4] for b in batch],
                                                SOURCE, run_id)
                    inserted = int(status.split()[-1])
        failed = [c for c, v in per.items() if v["status"] == "FAILED"]
        return {"series": per, "new_rows": len(batch), "rows_inserted": inserted, "failed": failed,
                "calls": sum(v["calls"] for v in per.values()),
                "conflicting_dates": {c: v["conflicting_dates"] for c, v in per.items() if v.get("conflicting_dates")},
                "unfinished_dropped": {c: v["unfinished_dropped"] for c, v in per.items() if v.get("unfinished_dropped")}}

    if dry_run:
        report.update(await body(None))
        report["verdict"] = "DRY_RUN"
        return report

    async with job_run_factory(INGESTER, target_date=now_ist.date()) as run:
        out = await body(run.run_id)
        n_failed, n_called = len(out["failed"]), sum(1 for v in out["series"].values() if v["calls"])
        status = "OK" if not n_failed else ("FAILED" if n_failed == n_called else "PARTIAL")
        run.rows_fetched = out["new_rows"]
        run.rows_inserted = out["rows_inserted"]
        run.metadata = {"failed": out["failed"], "calls": out["calls"], "conflicting_dates": out["conflicting_dates"],
                        "unfinished_dropped": out["unfinished_dropped"]}
        await run.finalize(status, error_class="TRUEDATA_CALL_FAILED" if n_failed else None,
                           error_message=(f"{n_failed} series failed: {', '.join(out['failed'])}"[:500]
                                          if n_failed else None))
        report.update(out, run_id=str(run.run_id), job_status=status, verdict=status)
    return report


async def rollback(run_id: str, *, dry_run: bool = False, pool=None) -> Dict[str, Any]:
    """Delete exactly one run's rows (the job never rewrites a stored day, so nothing else changed). Any switch
    position."""
    rid = uuid.UUID(run_id)
    if pool is None:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
    async with pool.acquire() as conn:
        if dry_run:
            n = await conn.fetchval("SELECT count(*) FROM nidp.fred_macro WHERE source = $1 AND source_run_id = $2",
                                    SOURCE, rid)
            return {"run_id": run_id, "dry_run": True, "would_delete_rows": n}
        status = await conn.execute("DELETE FROM nidp.fred_macro WHERE source = $1 AND source_run_id = $2", SOURCE, rid)
    return {"run_id": run_id, "deleted_rows": int(status.split()[-1])}
