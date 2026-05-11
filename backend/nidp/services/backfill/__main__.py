"""nidp.services.backfill — historical NSE archive walker.

Spawned in the background to pre-populate the warehouse with N trading
days of equity/F&O/index/delivery feeds so the replay engine has a
real multi-month history to score against.

Design:
  1. Optionally TRUNCATE the equity-side tables for a clean window.
  2. Walk every trading day in [start_date, end_date] (skips weekends
     and NSE holidays from `nidp.nse_holidays`).
  3. For each (date, ingester) → spawn `python -m nidp.services.<ing> --date YYYY-MM-DD`
     as a subprocess. Wait for it. Capture row-count + timing.
  4. Sleep `politeness_ms` between each NSE-touching call so we don't
     get banned.
  5. Persist progress in audit.backfill_runs + audit.backfill_jobs so
     the UI can poll status.
  6. When done (and auto_replay=true), kick off a 90-day replay against
     the freshly populated data.

CLI:
  python -m nidp.services.backfill \\
      --start-date 2026-02-09 \\
      --end-date   2026-05-10 \\
      --ingesters  bhavcopy,delivery,index_close,fno_bhavcopy \\
      --wipe-first true \\
      --politeness-ms 4000 \\
      --auto-replay true
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)


# ─── Defaults ─────────────────────────────────────────────────────
# All four ingesters that have NSE archive backfill support.
# `fii_dii` is excluded — NSE moved it to a rolling JSON API and the
# historical archive isn't reachable.
DEFAULT_INGESTERS: Tuple[str, ...] = (
    "bhavcopy",       # nidp.prices_eod
    "delivery",       # nidp.delivery_data
    "index_close",    # nidp.index_eod
    "fno_bhavcopy",   # nidp.fno_bhavcopy
)

# Per-ingester (table, date_column) that the wipe step targets.
_WIPE_MAP: Dict[str, Tuple[str, str]] = {
    "bhavcopy":         ("nidp.prices_eod",           "as_of_date"),
    "delivery":         ("nidp.delivery_data",        "as_of_date"),
    "index_close":      ("nidp.index_eod",            "as_of_date"),
    "fno_bhavcopy":     ("nidp.fno_bhavcopy",         "as_of_date"),
    "price_adjuster":   ("nidp.prices_eod_adjusted",  "as_of_date"),
}


def _pg_dsn() -> str:
    return (
        os.environ.get("NIDP_PG_DSN")
        or os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5433/nidp"
    )


# ─── Trading-day filter ────────────────────────────────────────────
async def _trading_days(
    conn: asyncpg.Connection, start: date, end: date,
) -> List[date]:
    """Mon-Fri minus nidp.nse_holidays. Inclusive of both endpoints."""
    days: List[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    try:
        rows = await conn.fetch(
            """SELECT holiday_date FROM nidp.nse_holidays
                WHERE holiday_date BETWEEN $1 AND $2""",
            start, end,
        )
        skip = {r["holiday_date"] for r in rows}
        return [d for d in days if d not in skip]
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return days


# ─── Wipe step ─────────────────────────────────────────────────────
async def _wipe_tables(
    conn: asyncpg.Connection, ingesters: List[str], start: date, end: date,
) -> Dict[str, int]:
    """For each ingester in the run, DELETE rows in the replay window."""
    out: Dict[str, int] = {}
    for ing in ingesters:
        if ing not in _WIPE_MAP:
            continue
        table, dcol = _WIPE_MAP[ing]
        try:
            res = await conn.execute(
                f"DELETE FROM {table} WHERE {dcol} BETWEEN $1 AND $2",
                start, end,
            )
            n = int(res.split()[-1]) if res else 0
            out[table] = n
            logger.info("wipe: %s — %d rows deleted", table, n)
        except Exception as e:                                            # noqa: BLE001
            logger.warning("wipe failed on %s: %s", table, e)
            out[table] = -1
    return out


# ─── Per-job runner ────────────────────────────────────────────────
async def _run_one_job(
    pool: asyncpg.Pool,
    backfill_id: str,
    target_date: date,
    ingester: str,
    politeness_ms: int,
) -> Tuple[bool, int, Optional[str], Optional[str]]:
    """Spawn `python -m nidp.services.<ing> --date YYYY-MM-DD`.

    Returns (success, rows_loaded, error, log_tail).
    """
    t0 = time.perf_counter()

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE audit.backfill_jobs
                  SET status='RUNNING', started_at=NOW(),
                      attempt = attempt + 1
                WHERE backfill_id=$1::uuid AND target_date=$2 AND ingester=$3""",
            backfill_id, target_date, ingester,
        )

    cmd = [
        sys.executable, "-m", f"nidp.services.{ingester}",
        "--date", target_date.isoformat(),
    ]
    env = os.environ.copy()
    env["NIDP_PG_DSN"]       = _pg_dsn()
    env["NIDP_POSTGRES_URL"] = _pg_dsn()
    env["POSTGRES_URL"]      = _pg_dsn()

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=env, cwd="/opt/nidp/repo/backend",
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, 0, "timeout after 180s", None

    output = (stdout or b"").decode(errors="replace")
    log_tail = "\n".join(output.splitlines()[-8:])[:1500]

    # Light-weight row-count detection — most ingesters log
    # "inserted N rows" or "rows=N". Best effort; non-fatal.
    rows = 0
    for tok in output.split():
        if "=" in tok and tok.startswith(("rows", "inserted", "ingested")):
            try:
                rows = int(tok.split("=")[1].rstrip(","))
                break
            except (ValueError, IndexError):
                continue

    success = proc.returncode == 0
    duration_ms = int((time.perf_counter() - t0) * 1000)

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE audit.backfill_jobs
                  SET status=$4, finished_at=NOW(),
                      rows_loaded=$5, duration_ms=$6,
                      error=$7, log_tail=$8
                WHERE backfill_id=$1::uuid AND target_date=$2 AND ingester=$3""",
            backfill_id, target_date, ingester,
            "DONE" if success else "FAILED",
            rows if rows > 0 else None, duration_ms,
            None if success else f"exit={proc.returncode}",
            log_tail,
        )

    # NSE politeness — sleep AFTER the call regardless of outcome.
    if politeness_ms > 0:
        await asyncio.sleep(politeness_ms / 1000.0)

    return success, rows, (None if success else f"exit={proc.returncode}"), log_tail


# ─── Orchestrator ──────────────────────────────────────────────────
async def run_backfill(
    start_date: date,
    end_date: date,
    ingesters: List[str],
    *,
    wipe_first: bool = True,
    politeness_ms: int = 4000,
    parallel: int = 1,
    auto_replay: bool = True,
    initiated_by: str = "cli",
) -> Dict[str, Any]:
    """Full backfill flow: wipe → walk trading days × ingesters →
    (optionally) auto-trigger a 90-day replay."""
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=2, max_size=max(parallel * 2, 4))

    # 1. Compute trading days
    async with pool.acquire() as conn:
        days = await _trading_days(conn, start_date, end_date)
    if not days:
        await pool.close()
        raise ValueError("no trading days in window")

    # 2. Insert backfill_runs row
    backfill_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit.backfill_runs
                 (backfill_id, start_date, end_date, ingesters,
                  wipe_first, politeness_ms, parallel, auto_replay,
                  jobs_total, initiated_by, config_json)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)""",
            backfill_id, start_date, end_date, ingesters,
            wipe_first, politeness_ms, parallel, auto_replay,
            len(days) * len(ingesters), initiated_by,
            json.dumps({
                "trading_days_count": len(days),
                "ingesters":          ingesters,
            }),
        )

        # Pre-create all jobs as PENDING so the UI can show the full grid.
        for d in days:
            for ing in ingesters:
                await conn.execute(
                    """INSERT INTO audit.backfill_jobs
                         (backfill_id, target_date, ingester)
                       VALUES ($1::uuid, $2, $3)
                       ON CONFLICT (backfill_id, target_date, ingester) DO NOTHING""",
                    backfill_id, d, ing,
                )

    # 3. Optional wipe
    if wipe_first:
        async with pool.acquire() as conn:
            await _wipe_tables(conn, ingesters, start_date, end_date)

    # 4. Walk days × ingesters
    sem = asyncio.Semaphore(parallel)
    jobs_done = 0
    jobs_failed = 0
    rows_total = 0
    errors: List[str] = []

    async def _bounded(d: date, ing: str) -> None:
        nonlocal jobs_done, jobs_failed, rows_total
        async with sem:
            success, rows, err, _tail = await _run_one_job(
                pool, backfill_id, d, ing, politeness_ms,
            )
            jobs_done += 1
            if not success:
                jobs_failed += 1
                if err:
                    errors.append(f"{d}/{ing}: {err}")
            rows_total += max(rows, 0)
            # Periodic counter update
            async with pool.acquire() as c2:
                await c2.execute(
                    """UPDATE audit.backfill_runs
                          SET jobs_done=$2, jobs_failed=$3, rows_loaded=$4
                        WHERE backfill_id=$1::uuid""",
                    backfill_id, jobs_done, jobs_failed, rows_total,
                )

    tasks = [_bounded(d, ing) for d in days for ing in ingesters]
    await asyncio.gather(*tasks)

    # 5. Finalize status
    failed_pct = jobs_failed / max(len(tasks), 1)
    if failed_pct == 0:
        final_status = "SUCCESS"
    elif failed_pct < 0.30:
        final_status = "PARTIAL"
    else:
        final_status = "FAILED"

    error_summary = (
        f"{jobs_failed} of {len(tasks)} jobs failed; " + "; ".join(errors[:5])
    )[:2000] if errors else None

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE audit.backfill_runs
                  SET status=$2, finished_at=NOW(),
                      jobs_done=$3, jobs_failed=$4, rows_loaded=$5,
                      error=$6
                WHERE backfill_id=$1::uuid""",
            backfill_id, final_status, jobs_done, jobs_failed, rows_total,
            error_summary,
        )

    result = {
        "backfill_id": backfill_id,
        "status":      final_status,
        "jobs_total":  len(tasks),
        "jobs_done":   jobs_done,
        "jobs_failed": jobs_failed,
        "rows_loaded": rows_total,
    }

    # 6. Optional auto-replay
    if auto_replay and final_status in ("SUCCESS", "PARTIAL"):
        try:
            from nidp.quality.replay.engine import ReplayConfig, ReplayEngine
            cfg = ReplayConfig(
                start_date=start_date,
                end_date=end_date,
                domains=["equity"],
                policy_version="v1",
                parallel=4,
                reset_data=True,
                initiated_by=f"backfill/{backfill_id[:8]}",
            )
            engine = ReplayEngine(pool, cfg)
            replay_result = await engine.run()
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE audit.backfill_runs
                          SET replay_id=$2::uuid
                        WHERE backfill_id=$1::uuid""",
                    backfill_id, engine.replay_id,
                )
            result["auto_replay"] = {
                "replay_id":   engine.replay_id,
                "pass_count":  replay_result.get("pass_count"),
                "review_count": replay_result.get("review_count"),
                "fail_count":  replay_result.get("fail_count"),
                "avg_overall_score": replay_result.get("avg_overall_score"),
            }
        except Exception as e:                                            # noqa: BLE001
            logger.exception("auto-replay after backfill failed")
            result["auto_replay_error"] = f"{type(e).__name__}: {str(e)[:300]}"

    await pool.close()
    return result


# ─── CLI ───────────────────────────────────────────────────────────
def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_bool(s: str) -> bool:
    return str(s).lower() in ("1", "true", "yes", "on", "y")


def main() -> None:
    p = argparse.ArgumentParser(
        prog="nidp.services.backfill",
        description="Historical NSE archive walker for replay readiness.",
    )
    p.add_argument("--start-date", required=True, type=_parse_date)
    p.add_argument("--end-date",   required=True, type=_parse_date)
    p.add_argument("--ingesters",  default=",".join(DEFAULT_INGESTERS),
                   help=f"Comma-separated (default: {','.join(DEFAULT_INGESTERS)})")
    p.add_argument("--wipe-first",    default="true")
    p.add_argument("--politeness-ms", type=int, default=4000)
    p.add_argument("--parallel",      type=int, default=1)
    p.add_argument("--auto-replay",   default="true")
    p.add_argument("--initiated-by",  default=os.environ.get("USER") or "cli")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    )
    ingesters = [i.strip() for i in args.ingesters.split(",") if i.strip()]
    result = asyncio.run(run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        ingesters=ingesters,
        wipe_first=_parse_bool(args.wipe_first),
        politeness_ms=args.politeness_ms,
        parallel=args.parallel,
        auto_replay=_parse_bool(args.auto_replay),
        initiated_by=args.initiated_by,
    ))
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] in ("SUCCESS", "PARTIAL") else 1)


if __name__ == "__main__":
    main()
