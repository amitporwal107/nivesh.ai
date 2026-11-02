"""Load TrueData's long daily stock history into nidp.prices_eod_history, stitched to our basis (migration 191).

Per symbol (logic in .bars.stitch_symbol):
  history   TrueData's adjusted daily bars HISTORY_START..HISTORY_END: from a raw directory written by a resumable
            fetch (`{"symbol","from","to","rows":[...]}` or `{"empty": reason}`, gzip JSON, one file per symbol), or
            fetched with the repo client's bars(symbol, start, end, "eod").
  warehouse our first OVERLAP_DAYS days in nidp.prices_eod_adjusted, and the symbol's demerger ex-dates in
            nidp.corporate_actions (read only; a factor above 2 needs a demerger after our first day).
  overlap   TrueData's bars from 10 days before history's last bar to our OVERLAP_DAYS-th day: one fetch per symbol,
            or a file in an overlap directory of the same format.
A symbol that is not LOADED is recorded in nidp.prices_eod_history_stitch with its status and reason, and nothing else.

Writes: one transaction per batch of symbols (rows + stitch records), source_run_id = the job_log run id. TrueData is
called outside the transaction. A symbol already loaded is SKIPPED_EXISTING (no TrueData call) unless replace=True,
which deletes its earlier rows in the same transaction.

The market-data switch (backend/nidp/shared/market_data_source.py): a load, and any path that would call TrueData, runs
only when truedata_is_on(); at `current` it returns SWITCHED_OFF having called and written nothing. A dry run from files
only (raw_dir AND overlap_dir) calls nothing and writes nothing, so it runs at any switch position. rollback() runs at any
position: it is part of the way back.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import uuid
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

from . import bars as B

logger = logging.getLogger(__name__)

INGESTER = "truedata_history"
SOURCE = "truedata"
HISTORY_START = date(2010, 1, 1)
HISTORY_END = date(2024, 3, 31)        # the day before nidp.prices_eod_adjusted's first date (2024-04-01)
BATCH_SIZE = 25

_COLS = ("symbol", "as_of_date", "adj_open", "adj_high", "adj_low", "adj_close", "volume", "stitch_factor")


def raw_path(directory: str, symbol: str) -> Path:
    """Same naming as the fetch that wrote the files: '/' and ' ' become '_'."""
    return Path(directory) / (symbol.replace("/", "_").replace(" ", "_") + ".json.gz")


def read_raw(directory: str, symbol: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """(rows, "") for a data file; (None, reason) for a missing file or an {"empty": reason} file."""
    p = raw_path(directory, symbol)
    if not p.exists():
        return None, "no raw file (fetch incomplete?)"
    with gzip.open(p, "rt") as fh:
        doc = json.load(fh)
    if doc.get("empty"):
        return None, f"TrueData answered {doc['empty']}"
    return list(doc.get("rows") or []), ""


def list_raw_symbols(directory: str) -> List[str]:
    """Symbols with a finished file (a fetch in progress leaves *.part, which is ignored)."""
    out = []
    for name in os.listdir(directory):
        if name.endswith(".json.gz"):
            with gzip.open(Path(directory) / name, "rt") as fh:
                out.append(str(json.load(fh).get("symbol") or name[:-8]))
    return sorted(out)


# ── Database reads / writes ──────────────────────────────────────────────────────────────────────────────────────

_WAREHOUSE_SQL = """
SELECT s.symbol, a.as_of_date, a.adj_close
  FROM unnest($1::text[]) AS s(symbol)
 CROSS JOIN LATERAL (
       SELECT x.as_of_date, x.adj_close
         FROM nidp.prices_eod_adjusted x
        WHERE x.symbol = s.symbol AND x.source = 'NIDP_PRICE_ADJUSTER' AND x.adj_close > 0
        ORDER BY x.as_of_date
        LIMIT $2) a
 ORDER BY 1, 2"""

_DEMERGER_SQL = ("SELECT symbol, ex_date FROM nidp.corporate_actions WHERE symbol = ANY($1::text[]) "
                 "AND (action_type ~* 'demerg' OR purpose ~* 'demerg')")

_EXISTING_SQL = "SELECT DISTINCT symbol FROM nidp.prices_eod_history WHERE symbol = ANY($1::text[]) AND source = $2"

_STITCH_INSERT = """
INSERT INTO nidp.prices_eod_history_stitch
    (source_run_id, symbol, source, status, reason, stitch_factor, overlap_days, overlap_from, overlap_to, max_dev_pct,
     history_from, history_to, warehouse_from, rows_loaded, duplicate_dates, conflicting_dates, seam_move_pct,
     td_seam_move_pct)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
ON CONFLICT (source_run_id, symbol, source) DO NOTHING"""


async def warehouse_first_days(conn, symbols: Sequence[str], k: int = B.OVERLAP_DAYS
                               ) -> Dict[str, List[Tuple[date, float]]]:
    out: Dict[str, List[Tuple[date, float]]] = {}
    for r in await conn.fetch(_WAREHOUSE_SQL, list(symbols), k):
        out.setdefault(r["symbol"], []).append((r["as_of_date"], float(r["adj_close"])))
    return out


async def demerger_dates(conn, symbols: Sequence[str]) -> Dict[str, List[date]]:
    out: Dict[str, List[date]] = {}
    for r in await conn.fetch(_DEMERGER_SQL, list(symbols)):
        out.setdefault(r["symbol"], []).append(r["ex_date"])
    return out


async def write_batch(conn, run_id: uuid.UUID, results: Sequence[B.StitchResult], *, replace: bool = False) -> int:
    """One transaction: (replace) earlier rows of the loaded symbols, the new rows, a stitch record per symbol.
    Returns rows inserted."""
    loaded = [r for r in results if r.loaded]
    inserted = 0
    async with conn.transaction():
        if replace and loaded:
            await conn.execute("DELETE FROM nidp.prices_eod_history WHERE symbol = ANY($1::text[]) AND source = $2",
                               [r.symbol for r in loaded], SOURCE)
        records = [tuple(row[c] for c in _COLS) + (SOURCE, run_id) for r in loaded for row in r.rows]
        if records:
            await conn.execute("CREATE TEMP TABLE tmp_prices_eod_history "
                               "(LIKE nidp.prices_eod_history INCLUDING DEFAULTS) ON COMMIT DROP")
            await conn.copy_records_to_table("tmp_prices_eod_history", records=records,
                                             columns=list(_COLS) + ["source", "source_run_id"])
            status = await conn.execute(
                "INSERT INTO nidp.prices_eod_history (" + ", ".join(_COLS) + ", source, source_run_id) "
                "SELECT " + ", ".join(_COLS) + ", source, source_run_id FROM tmp_prices_eod_history "
                "ON CONFLICT (symbol, as_of_date, source) DO NOTHING")
            inserted = int(status.split()[-1])
        for r in results:
            await conn.execute(_STITCH_INSERT, run_id, r.symbol, SOURCE, r.status, r.reason[:1000], r.factor,
                               r.overlap_days, r.overlap_from, r.overlap_to, r.max_dev_pct, r.history_from,
                               r.history_to, r.warehouse_from, len(r.rows), r.duplicate_dates, r.conflicting_dates,
                               r.seam_move_pct, r.td_seam_move_pct)
    return inserted


# ── Orchestration ────────────────────────────────────────────────────────────────────────────────────────────────

def _bars(client: td.TrueDataClient, symbol: str, start: date, end: date) -> List[Dict[str, Any]]:
    from datetime import datetime, time
    try:
        return client.bars(symbol, datetime.combine(start, time(0, 0)), datetime.combine(end, time(23, 59, 59)),
                           interval="eod")
    except td.TrueDataError as e:
        if e.code in (td.EMPTY_RESPONSE, td.IDENTIFIER_NOT_RESOLVED):
            return []
        raise


async def stitch_one(symbol: str, warehouse: List[Tuple[date, float]], *, raw_dir: Optional[str],
                     overlap_dir: Optional[str], client: Optional[td.TrueDataClient],
                     demergers: Sequence[date] = (), history_start: date = HISTORY_START,
                     history_end: date = HISTORY_END) -> B.StitchResult:
    """Gather the three inputs for one symbol (files or TrueData) and stitch. A TrueData failure is FETCH_FAILED."""
    try:
        if raw_dir:
            hist, why = read_raw(raw_dir, symbol)
            if hist is None:
                return B.StitchResult(symbol, B.NO_HISTORY, reason=why,
                                      warehouse_from=warehouse[0][0] if warehouse else None)
        else:
            hist = await asyncio.to_thread(_bars, client, symbol, history_start, history_end)
        cleaned, _ = B.clean_bars(hist)
        before = [d for d in cleaned if not warehouse or d < warehouse[0][0]]
        if not before or not warehouse:
            return B.stitch_symbol(symbol, hist, warehouse, [])          # NO_HISTORY / NO_WAREHOUSE with numbers
        if (warehouse[0][0] - max(before)).days > B.MAX_SEAM_GAP_DAYS:
            return B.stitch_symbol(symbol, hist, warehouse, [])          # SEAM_GAP: no overlap call needed
        if overlap_dir:
            over, why = read_raw(overlap_dir, symbol)
            if over is None:
                return B.StitchResult(symbol, B.NO_OVERLAP, reason=f"overlap: {why}", warehouse_from=warehouse[0][0],
                                      history_from=min(before), history_to=max(before))
        else:
            start, end = B.overlap_window(max(before), [d for d, _ in warehouse])
            over = await asyncio.to_thread(_bars, client, symbol, start, end)
        return B.stitch_symbol(symbol, hist, warehouse, over, demergers)
    except td.TrueDataError as e:
        return B.StitchResult(symbol, B.FETCH_FAILED, reason=f"{e.code}: {e.message}"[:500],
                              warehouse_from=warehouse[0][0] if warehouse else None)


def _needs_truedata(raw_dir: Optional[str], overlap_dir: Optional[str]) -> bool:
    return not (raw_dir and overlap_dir)


async def load(symbols: Optional[Sequence[str]] = None, *, raw_dir: Optional[str] = None,
               overlap_dir: Optional[str] = None, client: Optional[td.TrueDataClient] = None,
               dry_run: bool = False, replace: bool = False, batch_size: int = BATCH_SIZE,
               switch: Optional[Callable[[], mds.Resolution]] = None, pool=None,
               job_run_factory=None) -> Dict[str, Any]:
    """Backfill. Returns a JSON-able report (status counts, flagged symbols, factor stats, run id)."""
    resolution = (switch or mds.resolve)()
    report: Dict[str, Any] = {"ingester": INGESTER, "dry_run": dry_run, "market_data_source": resolution.effective,
                              "history": raw_dir or f"TrueData {HISTORY_START}..{HISTORY_END}",
                              "overlap": overlap_dir or "TrueData, one call per symbol"}
    if (not dry_run or _needs_truedata(raw_dir, overlap_dir)) and not mds.truedata_is_on(resolution):
        return {**report, "verdict": "SWITCHED_OFF", "message": mds.truedata_off_message(resolution)}
    if _needs_truedata(raw_dir, overlap_dir) and client is None:
        client = td.TrueDataClient()

    if symbols is None:
        symbols = list_raw_symbols(raw_dir) if raw_dir else None
    if pool is None:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
    async with pool.acquire() as conn:
        if symbols is None:
            symbols = [r["symbol"] for r in await conn.fetch(
                "SELECT DISTINCT symbol FROM nidp.prices_eod_adjusted WHERE source = 'NIDP_PRICE_ADJUSTER' ORDER BY 1")]
    symbols = sorted(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    report["symbols"] = len(symbols)

    results: List[B.StitchResult] = []
    inserted = 0

    async def run_batches(run_id: Optional[uuid.UUID]) -> None:
        nonlocal inserted
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    existing = set() if replace else {r["symbol"] for r in await conn.fetch(_EXISTING_SQL, batch, SOURCE)}
                    todo = [s for s in batch if s not in existing]
                    wh = await warehouse_first_days(conn, todo)
                    dm = await demerger_dates(conn, todo)
            out = []
            for s in batch:
                if s in existing:
                    out.append(B.StitchResult(s, B.SKIPPED_EXISTING, reason="already loaded; use --replace to redo"))
                    continue
                out.append(await stitch_one(s, wh.get(s, []), raw_dir=raw_dir, overlap_dir=overlap_dir, client=client,
                                            demergers=dm.get(s, ())))
            results.extend(out)
            if run_id is not None:
                async with pool.acquire() as conn:
                    inserted += await write_batch(conn, run_id, out, replace=replace)
            logger.info("truedata_history: %d/%d symbols", min(i + batch_size, len(symbols)), len(symbols))

    if dry_run:
        await run_batches(None)
    else:
        if job_run_factory is None:
            from nidp.shared.storage.job_log import JobRun as job_run_factory
        # An exception finalizes the job FAILED (JobRun.__aexit__); batches committed before it keep this run id, so
        # rollback(run_id) removes them.
        async with job_run_factory(INGESTER, target_date=HISTORY_END) as run:
            await run_batches(run.run_id)
            failed = sum(r.status == B.FETCH_FAILED for r in results)
            run.rows_fetched = sum(len(r.rows) for r in results)
            run.rows_inserted = inserted
            run.rows_skipped = sum(not r.loaded for r in results)
            run.metadata = {"status_counts": dict(Counter(r.status for r in results))}
            status = "OK" if not failed else ("FAILED" if failed == len(results) else "PARTIAL")
            await run.finalize(status, error_class="TRUEDATA_FETCH_FAILED" if failed else None,
                               error_message=f"{failed} symbol(s) failed to fetch" if failed else None)
            report["run_id"] = str(run.run_id)
            report["job_status"] = status
    report.update(summarise(results))
    report["rows_inserted"] = inserted
    report["verdict"] = "DRY_RUN" if dry_run else report.get("job_status")
    return report


def summarise(results: Sequence[B.StitchResult]) -> Dict[str, Any]:
    loaded = [r for r in results if r.loaded]
    factors = sorted(r.factor for r in loaded if r.factor is not None)
    rescaled = [r for r in loaded if r.factor != 1.0]
    seam_gap = [abs((1 + r.seam_move_pct / 100) / (1 + r.td_seam_move_pct / 100) - 1) * 100
                for r in loaded if r.seam_move_pct is not None and r.td_seam_move_pct is not None]
    return {
        "status_counts": dict(Counter(r.status for r in results)),
        "rows_stitched": sum(len(r.rows) for r in loaded),
        "factor_exactly_1": sum(r.factor == 1.0 for r in loaded),
        "factor_rescaled": [{"symbol": r.symbol, "factor": r.factor, "overlap_days": r.overlap_days,
                             "max_dev_pct": r.max_dev_pct} for r in rescaled],
        "factor_min": factors[0] if factors else None,
        "factor_max": factors[-1] if factors else None,
        "max_overlap_dev_pct": max((r.max_dev_pct for r in loaded if r.max_dev_pct is not None), default=None),
        "seam_vs_td_move_max_pct": round(max(seam_gap), 6) if seam_gap else None,
        "flagged": [{"symbol": r.symbol, "status": r.status, "reason": r.reason} for r in results
                    if not r.loaded and r.status not in (B.SKIPPED_EXISTING,)][:200],
    }


async def rollback(run_id: str, *, dry_run: bool = False, pool=None) -> Dict[str, Any]:
    """Delete exactly the rows and stitch records of one load run. Runs at any switch position."""
    rid = uuid.UUID(run_id)
    if pool is None:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
    async with pool.acquire() as conn:
        if dry_run:
            rows = await conn.fetchval("SELECT count(*) FROM nidp.prices_eod_history WHERE source_run_id = $1", rid)
            st = await conn.fetchval("SELECT count(*) FROM nidp.prices_eod_history_stitch WHERE source_run_id = $1", rid)
            return {"run_id": run_id, "dry_run": True, "would_delete_rows": rows, "would_delete_stitch": st}
        async with conn.transaction():
            a = await conn.execute("DELETE FROM nidp.prices_eod_history WHERE source_run_id = $1", rid)
            b = await conn.execute("DELETE FROM nidp.prices_eod_history_stitch WHERE source_run_id = $1", rid)
    return {"run_id": run_id, "deleted_rows": int(a.split()[-1]), "deleted_stitch": int(b.split()[-1])}
