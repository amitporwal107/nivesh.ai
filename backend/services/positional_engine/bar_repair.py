"""Repair of the scanner's bar store (`stock_ohlcv`) and the rows derived from it. Used by
scripts/repair_scanner_bars.py; the plan is read-only, `apply` and `restore` write.

What is wrong (study N1): `stock_ohlcv` holds NSE-holiday dates whose bars copy the session before (the ingester
stamped the requested date on the file NSE serves for a holiday URL: the previous session's), and lacks real sessions
the job never fetched. Every row derived from those bars (stock_technical_features, positional_signals) inherits it.

Phantom date (deleted by apply): a stored date that is NOT a warehouse session (nidp.prices_eod) AND whose every bar
equals the same symbol's bar on the previous stored date. A non-session date that is not a 100% copy is reported as
"unverified" and never deleted.

Missing session (back-filled by apply): a warehouse session in the window with no stored bars. It is ingested through
bhavcopy_ingester.ingest, which refuses a file that does not carry that session's trade date.

Recompute (apply): the day's features and signals are replaced (one transaction) for the recompute dates: by default
only the latest scored date (what the desk, ideas and watchlist read), or every scored date from --recompute-from.
Derived rows ON a phantom date are deleted (a non-session has no scan).

Idempotent: apply recomputes a date only when this run changed bars or the date's rows are not from the current
ENGINE_VERSION, so a second apply finds nothing to do and writes nothing. A snapshot of every row apply will delete
or replace is written to disk before the first write; `restore` puts those rows back and removes the back-filled
sessions, and is itself idempotent.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import ENGINE_VERSION, bar_quality

logger = logging.getLogger(__name__)

FEATURE_WINDOW_DAYS = 400   # a stored score is affected when a changed date lies this close before it
SNAPSHOT_VERSION = 1
DERIVED = (("stock_technical_features", "as_of_date"), ("positional_signals", "signal_date"))
TABLES = (("stock_ohlcv", "bar_date"),) + DERIVED

Ingest = Callable[[date], Awaitable[dict]]
Score = Callable[[date], Awaitable[Tuple[dict, List[dict]]]]


# ── adapters ──────────────────────────────────────────────────────────────
class PgStore:
    """stock_ohlcv and its derived tables in the app database."""

    def __init__(self, pool):
        self.pool = pool

    async def dates(self, start: date, end: date) -> List[date]:
        async with self.pool.acquire() as conn:
            return await bar_quality.store_dates(conn, start, end)

    async def bounds(self) -> Tuple[Optional[date], Optional[date]]:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("SELECT min(bar_date) lo, max(bar_date) hi FROM stock_ohlcv")
        return r["lo"], r["hi"]

    async def bars_on(self, d: date) -> Dict[str, tuple]:
        async with self.pool.acquire() as conn:
            return await bar_quality.bars_on(conn, d)

    async def derived_counts(self) -> Dict[str, Dict[date, dict]]:
        out: Dict[str, Dict[date, dict]] = {}
        async with self.pool.acquire() as conn:
            for table, col in DERIVED:
                rows = await conn.fetch(
                    f"SELECT {col} d, count(*) n, array_agg(DISTINCT engine_version) v FROM {table} GROUP BY 1")
                out[table] = {r["d"]: {"rows": r["n"], "versions": sorted(x for x in r["v"] if x)} for r in rows}
        return out

    async def rows(self, table: str, col: str, dates: Iterable[date]) -> List[dict]:
        ds = sorted(set(dates))
        if not ds:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT to_jsonb(t)::text j FROM {table} t WHERE {col} = ANY($1::date[])", ds)
        return [json.loads(r["j"]) for r in rows]

    async def delete_dates(self, dates: Iterable[date]) -> Dict[str, int]:
        ds = sorted(set(dates))
        out = {t: 0 for t, _ in TABLES}
        if not ds:
            return out
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for table, col in TABLES:
                    status = await conn.execute(f"DELETE FROM {table} WHERE {col} = ANY($1::date[])", ds)
                    out[table] = int(status.split()[-1])
        return out

    async def replace_scored(self, d: date, scored_rows: List[dict]) -> None:
        from . import pipeline
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await pipeline.write_scored(conn, d, scored_rows, replace=True)

    async def restore(self, snap: dict) -> Dict[str, int]:
        """Put the snapshot back in one transaction: the back-filled sessions are removed, and every snapshotted date
        of every table is deleted and re-inserted from the snapshot rows (exact types via jsonb_populate_record)."""
        out: Dict[str, int] = {}
        backfilled = [date.fromisoformat(d) for d in snap["backfill_dates"]]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if backfilled:
                    status = await conn.execute("DELETE FROM stock_ohlcv WHERE bar_date = ANY($1::date[])", backfilled)
                    out["stock_ohlcv_backfill_deleted"] = int(status.split()[-1])
                for table, col in TABLES:
                    ds = [date.fromisoformat(d) for d in snap["dates"][table]]
                    if ds:
                        await conn.execute(f"DELETE FROM {table} WHERE {col} = ANY($1::date[])", ds)
                    rows = snap["rows"][table]
                    if rows:
                        await conn.executemany(
                            f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, $1::jsonb)",
                            [(json.dumps(r),) for r in rows])
                    out[f"{table}_restored"] = len(rows)
        return out


class DaasWarehouse:
    """The warehouse's sessions and row counts through the data platform (session_calendar)."""

    async def sessions(self, start: date, end: date, extra: Iterable[date] = ()) -> Set[date]:
        from . import session_calendar
        return await session_calendar.warehouse_sessions(start, end, extra)

    async def rows(self, d: date) -> int:
        from . import session_calendar
        return await session_calendar.warehouse_rows(d)


# ── plan (read-only) ─────────────────────────────────────────────────────
async def plan_repair(store, wh, start: Optional[date] = None, end: Optional[date] = None, *,
                      recompute_from: Optional[date] = None) -> dict:
    """Everything apply would do, worked out from reads only."""
    if start is None or end is None:
        lo, hi = await store.bounds()
        start, end = start or lo, end or hi
    dates = await store.dates(start, end)
    sessions = await wh.sessions(start, end, dates)
    stored = set(dates)

    phantom, unverified = [], []
    for i, d in enumerate(dates):
        if d in sessions:
            continue
        prev = dates[i - 1] if i else None
        rows_d = await store.bars_on(d)
        rows_p = await store.bars_on(prev) if prev else {}
        identical = sum(1 for s, b in rows_d.items() if rows_p.get(s) == b)
        entry = {"date": d, "prev_date": prev, "rows": len(rows_d), "identical": identical}
        (phantom if prev and rows_d and identical == len(rows_d) else unverified).append(entry)

    missing = [{"date": d, "warehouse_rows": await wh.rows(d)} for d in sorted(sessions - stored)]

    derived = await store.derived_counts()
    phantom_dates = {p["date"] for p in phantom}
    on_phantom = {t: {d: derived.get(t, {}).get(d, {}).get("rows", 0) for d in sorted(phantom_dates)}
                  for t, _ in DERIVED}
    feature_dates = sorted(set(derived.get("stock_technical_features", {}))
                           | set(derived.get("positional_signals", {})))
    real = [d for d in feature_dates if d not in phantom_dates]
    recompute = [d for d in real if d >= recompute_from] if recompute_from else real[-1:]
    changed = sorted(phantom_dates | {m["date"] for m in missing})
    affected = [d for d in real if any(d - timedelta(days=FEATURE_WINDOW_DAYS) < c <= d for c in changed)]
    versions = {d: sorted(set(derived.get("stock_technical_features", {}).get(d, {}).get("versions", []))
                          | set(derived.get("positional_signals", {}).get(d, {}).get("versions", [])))
                for d in recompute}
    return {
        "window": [start, end],
        "store_dates": len(dates),
        "warehouse_sessions": len(sessions),
        "phantom": phantom,
        "unverified_extra": unverified,
        "missing": missing,
        "derived_on_phantom": on_phantom,
        "derived_rows_by_date": {t: {d: v["rows"] for d, v in derived.get(t, {}).items()} for t, _ in DERIVED},
        "scored_dates": len(real),
        "recompute_dates": recompute,
        "recompute_versions": versions,
        "affected_dates": len(affected),
        "affected_not_recomputed": [d for d in affected if d not in recompute],
    }


def apply_actions(plan: dict) -> dict:
    """The writes an apply would make from this plan (also what a second apply must find empty)."""
    phantom = [p["date"] for p in plan["phantom"]]
    missing = [m["date"] for m in plan["missing"]]
    bars_change = bool(phantom or missing)
    recompute = [d for d in plan["recompute_dates"]
                 if bars_change or plan["recompute_versions"].get(d) != [ENGINE_VERSION]]
    return {"delete_dates": phantom, "backfill_dates": missing, "recompute_dates": recompute}


# ── apply / restore ──────────────────────────────────────────────────────
def write_snapshot(path: str, snap: dict) -> None:
    """Write the snapshot; never overwrite an existing file (an earlier snapshot is the only way back)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(snap, f, default=lambda o: o.isoformat() if isinstance(o, (date, datetime)) else str(o))
        f.flush()
        os.fsync(f.fileno())


def read_snapshot(path: str) -> dict:
    with open(path) as f:
        snap = json.load(f)
    if snap.get("version") != SNAPSHOT_VERSION or "rows" not in snap or "dates" not in snap:
        raise ValueError(f"{path} is not a scanner bar-repair snapshot (version {SNAPSHOT_VERSION})")
    return snap


async def apply_repair(store, wh, ingest: Ingest, score: Score, snapshot_path: str, *,
                       start: Optional[date] = None, end: Optional[date] = None,
                       recompute_from: Optional[date] = None) -> dict:
    plan = await plan_repair(store, wh, start, end, recompute_from=recompute_from)
    act = apply_actions(plan)
    if not any(act.values()):
        return {"changed": False, "reason": "nothing to repair: no phantom date, no missing session, "
                                            f"recompute dates already on {ENGINE_VERSION}", "actions": act}

    snap_dates = {"stock_ohlcv": act["delete_dates"]}
    for table, _ in DERIVED:
        snap_dates[table] = sorted(set(act["delete_dates"]) | set(act["recompute_dates"]))
    snap = {
        "version": SNAPSHOT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "backfill_dates": act["backfill_dates"],
        "dates": snap_dates,
        "rows": {t: await store.rows(t, c, snap_dates[t]) for t, c in TABLES},
    }
    write_snapshot(snapshot_path, snap)
    logger.info("snapshot written: %s (%s)", snapshot_path,
                ", ".join(f"{t}={len(r)}" for t, r in snap["rows"].items()))

    deleted = await store.delete_dates(act["delete_dates"])
    backfill = [await ingest(d) for d in act["backfill_dates"]]
    recomputed: Dict[str, dict] = {}
    if all(r.get("status") == "written" for r in backfill):
        for d in act["recompute_dates"]:
            summary, rows = await score(d)
            if summary.get("ok"):
                await store.replace_scored(d, rows)
                recomputed[d.isoformat()] = {"scored": len(rows), "actionable": sum(1 for r in rows if r["actionable"])}
            else:
                recomputed[d.isoformat()] = {"error": summary.get("error"), "reason": summary.get("reason")}
    else:
        recomputed = {"skipped": "a missing session was not back-filled; rerun apply once it can be"}
    after = await plan_repair(store, wh, start, end, recompute_from=recompute_from)
    return {"changed": True, "snapshot": snapshot_path, "actions": act, "deleted": deleted,
            "backfill": backfill, "recomputed": recomputed,
            "after": {"phantom": len(after["phantom"]), "missing": len(after["missing"]),
                      "unverified_extra": len(after["unverified_extra"]),
                      "pending": apply_actions(after)}}


async def restore_snapshot(store, path: str) -> dict:
    return await store.restore(read_snapshot(path))


# ── rerun comparison (read-only) ─────────────────────────────────────────
def _rank(rows: List[dict]) -> List[str]:
    """Signals in the picks route's order (routes/positional.py _fetch_picks): final score, then risk/reward."""
    return [r["symbol"] for r in sorted(rows, key=lambda r: (-r["final_score"], -r["risk_reward"], r["symbol"]))]


def scored_view(scored_rows: List[dict]) -> Tuple[Dict[str, dict], List[dict]]:
    """(features by symbol, signals) from pipeline.score_universe rows, rounded as the tables store them."""
    feats, sigs = {}, []
    for r in scored_rows:
        s, f = r["scores"], r["features"]
        feats[r["nse_symbol"]] = {"final_score": round(float(s["final_score"]), 4), "stage": s["stage"],
                                  "sma_200": f.get("sma_200"), "return_20d_pct": f.get("return_20d_pct"),
                                  "atr_14": f.get("atr_14")}
        if r["actionable"]:
            sigs.append({"symbol": r["nse_symbol"], "final_score": round(float(s["final_score"]), 4),
                         "risk_reward": round(float(r["trade_plan"]["risk_reward"]), 2), "stage": s["stage"]})
    return feats, sigs


def compare_runs(before_feats: Dict[str, dict], before_sigs: List[dict],
                 after_feats: Dict[str, dict], after_sigs: List[dict], *, top: int = 20) -> dict:
    """How rankings and signals change from `before` to `after`: top-N entries/exits and rank shifts, actionable
    adds/removals, stage changes and final-score deltas over the symbols scored in both."""
    rb, ra = _rank(before_sigs), _rank(after_sigs)
    tb, ta = rb[:top], ra[:top]
    common = sorted(set(before_feats) & set(after_feats))
    deltas = [abs(after_feats[s]["final_score"] - before_feats[s]["final_score"]) for s in common]
    sb, sa = {r["symbol"] for r in before_sigs}, {r["symbol"] for r in after_sigs}
    return {
        "scored": {"before": len(before_feats), "after": len(after_feats), "both": len(common)},
        "actionable": {"before": len(before_sigs), "after": len(after_sigs),
                       "added": len(sa - sb), "removed": len(sb - sa)},
        f"top{top}": {
            "before": tb, "after": ta,
            "entered": [s for s in ta if s not in tb], "exited": [s for s in tb if s not in ta],
            "rank_shifts": [{"symbol": s, "from": tb.index(s) + 1, "to": ta.index(s) + 1}
                            for s in ta if s in tb and tb.index(s) != ta.index(s)],
        },
        "stage_changes": sum(1 for s in common if before_feats[s]["stage"] != after_feats[s]["stage"]),
        "final_score_delta": {
            "identical": sum(1 for x in deltas if x < 1e-4),
            "changed_gt_0_01": sum(1 for x in deltas if x > 0.01),
            "mean_abs": round(sum(deltas) / len(deltas), 6) if deltas else None,
            "max_abs": round(max(deltas), 4) if deltas else None,
        },
    }
