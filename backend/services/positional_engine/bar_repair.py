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

Recompute (apply): the latest scored date's features and signals are replaced (owner decision 2026-10-27: the latest
date only; --recompute-from exists but is not the documented path). The older scored dates stay as recorded, on the
price basis they were computed with. Derived rows ON a phantom date are deleted (a non-session has no scan).

ONE transaction (owner decision 2026-10-27). Apply first does every read, NSE fetch and computation: the missing
sessions are fetched and parsed (trade date checked) and the recompute is scored in memory on the corrected bars. It
then writes the snapshot of every row it will delete or replace, reads it back and verifies it (non-empty, every
affected table and date covered, per-date row counts equal to the plan; optionally equal to `expect`, the reviewed dry
run's counts). Only then does it open one transaction on one connection that re-checks those counts, deletes the
phantom dates, inserts the back-filled bars and replaces the recompute date's rows: all of it commits or none of it.

Idempotent: apply recomputes a date only when this run changes bars or the date's rows are not from the current
ENGINE_VERSION, so a second apply finds nothing to do and writes nothing. `restore` verifies the snapshot, then in one
transaction puts its rows back and removes the back-filled sessions; restoring twice gives the same state.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import ENGINE_VERSION, bar_quality

logger = logging.getLogger(__name__)

FEATURE_WINDOW_DAYS = 400   # a stored score is affected when a changed date lies this close before it
SNAPSHOT_VERSION = 1
DERIVED = (("stock_technical_features", "as_of_date"), ("positional_signals", "signal_date"))
TABLES = (("stock_ohlcv", "bar_date"),) + DERIVED

#: fetch(d) -> (result, bars): bhavcopy_ingester.fetch_session; result["status"] == "ok" or a refusal. Writes nothing.
Fetch = Callable[[date], Awaitable[Tuple[dict, List[dict]]]]
#: score(d, phantom_dates, extra_bars_by_symbol) -> (summary, scored rows), in memory on the corrected bars.
Score = Callable[[date, Set[date], Dict[str, List[dict]]], Awaitable[Tuple[dict, List[dict]]]]
#: before_after(d, scored rows) -> the pre/post record for d (computed before the transaction, written after commit).
BeforeAfter = Callable[[date, List[dict]], Awaitable[dict]]


class RepairAborted(RuntimeError):
    """Raised inside the transaction when the rows found differ from the verified snapshot: everything rolls back."""


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

    async def apply_txn(self, delete_dates: List[date], bars: List[dict], replacements: Dict[date, List[dict]],
                        expected: Dict[str, Dict[str, int]]) -> Dict[str, int]:
        """Every write of the repair in ONE transaction on one connection: re-check the snapshotted row counts, delete
        the phantom dates (bars and their scores), insert the back-filled bars, replace each recompute date's features
        and signals. Any error, or a count that differs from the snapshot, rolls all of it back."""
        from . import ohlcv_store, pipeline
        out: Dict[str, int] = {}
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for table, col in TABLES:
                    for d_iso, n in expected[table].items():
                        found = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1",
                                                    date.fromisoformat(d_iso))
                        if found != n:
                            raise RepairAborted(f"{table} {d_iso}: {found} rows now, {n} in the verified snapshot")
                ds = sorted(set(delete_dates))
                for table, col in TABLES:
                    status = await conn.execute(f"DELETE FROM {table} WHERE {col} = ANY($1::date[])", ds) if ds else "DELETE 0"
                    out[f"{table}_deleted"] = int(status.split()[-1])
                out["stock_ohlcv_inserted"] = await ohlcv_store.write_bars(conn, bars) if bars else 0
                for d, rows in sorted(replacements.items()):
                    await pipeline.write_scored(conn, d, rows, replace=True)
                out["features_written"] = sum(len(r) for r in replacements.values())
                out["signals_written"] = sum(1 for r in replacements.values() for x in r if x["actionable"])
        return out

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


def expected_counts(plan: dict, act: dict) -> Dict[str, Dict[str, int]]:
    """{table: {ISO date: rows}} that apply deletes or replaces, from the plan: the snapshot must hold exactly these."""
    phantom_rows = {p["date"]: p["rows"] for p in plan["phantom"]}
    out: Dict[str, Dict[str, int]] = {"stock_ohlcv": {d.isoformat(): phantom_rows[d] for d in act["delete_dates"]}}
    for table, _ in DERIVED:
        per = plan["derived_rows_by_date"].get(table, {})
        out[table] = {d.isoformat(): per.get(d, 0) for d in sorted(set(act["delete_dates"]) | set(act["recompute_dates"]))}
    return out


# ── snapshot ─────────────────────────────────────────────────────────────
def _json_default(o):
    return o.isoformat() if isinstance(o, (date, datetime)) else str(o)


def write_json_new(path: str, payload: dict) -> None:
    """Write `payload` to a NEW file (never overwrite: an earlier snapshot may be the only way back), fsynced."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, default=_json_default)
        f.flush()
        os.fsync(f.fileno())


write_snapshot = write_json_new


def read_snapshot(path: str) -> dict:
    """The snapshot at `path`; raises ValueError when it is empty, unreadable or not a repair snapshot."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise ValueError(f"{path}: missing or empty")
    with open(path) as f:
        try:
            snap = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}: not readable JSON ({e})") from e
    if not isinstance(snap, dict) or snap.get("version") != SNAPSHOT_VERSION or not all(
            k in snap for k in ("rows", "dates", "expected", "backfill_dates")):
        raise ValueError(f"{path} is not a scanner bar-repair snapshot (version {SNAPSHOT_VERSION})")
    return snap


def verify_snapshot(snap: dict, plan: Optional[dict] = None) -> dict:
    """Check a snapshot: non-empty; every affected table present; for every table and date, the rows it holds equal
    the counts recorded from the plan when it was written; and, given a fresh `plan` (before apply), that the store
    still matches it. Returns {ok, rows: {table: n}, problems: [...]}."""
    problems: List[str] = []
    rows = {t: len(snap["rows"].get(t) or []) for t, _ in TABLES}
    if not sum(rows.values()):
        problems.append("the snapshot holds no rows")
    for table, col in TABLES:
        if table not in snap["rows"] or table not in snap["expected"] or table not in snap["dates"]:
            problems.append(f"{table}: not in the snapshot")
            continue
        held = Counter(str(r.get(col))[:10] for r in snap["rows"][table])
        exp = snap["expected"][table]
        if sorted(exp) != sorted(snap["dates"][table]):
            problems.append(f"{table}: snapshot dates {sorted(snap['dates'][table])} differ from the plan's {sorted(exp)}")
        for d_iso, n in sorted(exp.items()):
            if held.get(d_iso, 0) != n:
                problems.append(f"{table} {d_iso}: {held.get(d_iso, 0)} rows in the snapshot, the plan says {n}")
        stray = sorted(set(held) - set(exp))
        if stray:
            problems.append(f"{table}: rows for dates the plan does not change: {stray}")
    if plan is not None:
        act = apply_actions(plan)
        fresh = expected_counts(plan, act)
        if fresh != snap["expected"]:
            problems.append(f"the store has changed since the snapshot was written: now {fresh}, snapshot {snap['expected']}")
        if [d.isoformat() for d in act["backfill_dates"]] != snap["backfill_dates"]:
            problems.append(f"missing sessions now {[d.isoformat() for d in act['backfill_dates']]}, "
                            f"snapshot {snap['backfill_dates']}")
    return {"ok": not problems, "rows": rows, "problems": problems}


def check_expect(rows: Dict[str, int], expect: Optional[Dict[str, int]]) -> List[str]:
    """Differences between the snapshot's per-table rows and the reviewed dry run's (`--expect`)."""
    if not expect:
        return []
    return [f"{t}: snapshot {rows.get(t, 0)}, expected {n}" for t, n in sorted(expect.items()) if rows.get(t, 0) != n]


async def build_snapshot(store, plan: dict, act: dict) -> dict:
    snap_dates = {"stock_ohlcv": act["delete_dates"]}
    for table, _ in DERIVED:
        snap_dates[table] = sorted(set(act["delete_dates"]) | set(act["recompute_dates"]))
    return {
        "version": SNAPSHOT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "backfill_dates": [d.isoformat() for d in act["backfill_dates"]],
        "recompute_dates": [d.isoformat() for d in act["recompute_dates"]],
        "dates": {t: [d.isoformat() for d in ds] for t, ds in snap_dates.items()},
        "expected": expected_counts(plan, act),
        "rows": {t: await store.rows(t, c, snap_dates[t]) for t, c in TABLES},
    }


async def snapshot_only(store, wh, snapshot_path: str, *, start: Optional[date] = None, end: Optional[date] = None,
                        recompute_from: Optional[date] = None, expect: Optional[Dict[str, int]] = None) -> dict:
    """Preflight: write the snapshot apply would write, read it back and verify it. No database write."""
    plan = await plan_repair(store, wh, start, end, recompute_from=recompute_from)
    act = apply_actions(plan)
    write_json_new(snapshot_path, await build_snapshot(store, plan, act))
    check = verify_snapshot(read_snapshot(snapshot_path), plan)
    check["problems"] += check_expect(check["rows"], expect)
    check["ok"] = not check["problems"]
    return {"snapshot": snapshot_path, "actions": act, "verification": check}


def corrected_loader(phantom: Set[date], extra: Dict[str, List[dict]]):
    """A bar loader for pipeline.score_universe: stock_ohlcv without the phantom dates, plus the missing sessions'
    bars (already fetched and trade-date checked), last `n` bars. Reads only."""
    from . import ohlcv_store

    async def load(symbol: str, end: date, n: int) -> List[dict]:
        bars = await ohlcv_store.load_bars(symbol, end_date=end, lookback_bars=n + len(phantom))
        bars = [b for b in bars if b["bar_date"] not in phantom] + [b for b in extra.get(symbol, []) if b["bar_date"] <= end]
        bars.sort(key=lambda b: b["bar_date"])
        return bars[-n:]
    return load


async def apply_repair(store, wh, fetch: Fetch, score: Score, snapshot_path: str, *,
                       start: Optional[date] = None, end: Optional[date] = None,
                       recompute_from: Optional[date] = None, expect: Optional[Dict[str, int]] = None,
                       before_after: Optional[BeforeAfter] = None,
                       post_check: Optional[Callable[[], Awaitable[dict]]] = None) -> dict:
    plan = await plan_repair(store, wh, start, end, recompute_from=recompute_from)
    act = apply_actions(plan)
    if not any(act.values()):
        return {"changed": False, "reason": "nothing to repair: no phantom date, no missing session, "
                                            f"recompute dates already on {ENGINE_VERSION}", "actions": act}

    # 1. Every NSE fetch, before anything is written.
    bars: List[dict] = []
    fetched: Dict[str, dict] = {}
    for d in act["backfill_dates"]:
        res, got = await fetch(d)
        fetched[d.isoformat()] = res
        if res.get("status") != "ok":
            return {"changed": False, "refused": f"missing session {d} could not be fetched: {res.get('status')} "
                                                 f"({res.get('reason')}); nothing written", "fetch": fetched, "actions": act}
        bars += got
    extra: Dict[str, List[dict]] = {}
    for b in bars:
        extra.setdefault(b["nse_symbol"], []).append(b)

    # 2. Every computation: the recompute on the corrected bars, and the before/after record.
    phantom = set(act["delete_dates"])
    replacements: Dict[date, List[dict]] = {}
    summaries: Dict[str, dict] = {}
    for d in act["recompute_dates"]:
        summary, rows = await score(d, phantom, extra)
        if not summary.get("ok"):
            return {"changed": False, "refused": f"recompute of {d} failed: {summary.get('error')} "
                                                 f"({summary.get('reason')}); nothing written", "actions": act}
        replacements[d] = rows
        summaries[d.isoformat()] = {k: summary.get(k) for k in ("scored", "actionable", "price_basis", "exceptions",
                                                                 "engine_version")}
    records = {d.isoformat(): await before_after(d, rows) for d, rows in replacements.items()} if before_after else {}

    # 3. The snapshot: written, read back from disk, verified. A failure stops here with nothing written.
    write_json_new(snapshot_path, await build_snapshot(store, plan, act))
    check = verify_snapshot(read_snapshot(snapshot_path), plan)
    check["problems"] += check_expect(check["rows"], expect)
    check["ok"] = not check["problems"]
    if not check["ok"]:
        return {"changed": False, "refused": "snapshot verification failed; nothing written", "snapshot": snapshot_path,
                "verification": check, "actions": act}
    logger.info("snapshot written and verified: %s %s", snapshot_path, check["rows"])

    # 4. ONE transaction: all of it or none of it.
    snap_expected = read_snapshot(snapshot_path)["expected"]
    written = await store.apply_txn(act["delete_dates"], bars, replacements, snap_expected)

    after = await plan_repair(store, wh, start, end, recompute_from=recompute_from)
    out = {"changed": True, "snapshot": snapshot_path, "verification": check, "actions": act, "fetch": fetched,
           "written": written, "recomputed": summaries,
           "after": {"phantom": len(after["phantom"]), "missing": len(after["missing"]),
                     "unverified_extra": len(after["unverified_extra"]), "pending": apply_actions(after)}}
    if post_check:
        out["quality_after"] = await post_check()
    if records:
        path = snapshot_path + ".before_after.json"
        write_json_new(path, {"snapshot": snapshot_path, "committed_at": datetime.now(timezone.utc).isoformat(),
                              "dates": records})
        out["before_after"] = {"path": path, "comparison": {d: r["comparison"] for d, r in records.items()}}
    return out


async def restore_snapshot(store, path: str) -> dict:
    """Verify the snapshot, then put it back in one transaction (PgStore.restore)."""
    snap = read_snapshot(path)
    check = verify_snapshot(snap)
    if not check["ok"]:
        return {"restored": False, "refused": "snapshot verification failed; nothing written", "verification": check}
    return {"restored": True, "verification": check, **(await store.restore(snap))}


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


def ranking_view(feats: Dict[str, dict], sigs: List[dict]) -> dict:
    """Rankings and signals of one run as stored in a before/after record."""
    return {
        "scored": len(feats),
        "signals_ranked": [{"rank": i + 1, **r} for i, r in enumerate(
            sorted(sigs, key=lambda r: (-r["final_score"], -r["risk_reward"], r["symbol"])))],
        "scores": {s: {"final_score": f["final_score"], "stage": f["stage"]} for s, f in sorted(feats.items())},
    }


def before_after_record(d: date, stored: Tuple[Dict[str, dict], List[dict]], code_only: Tuple[Dict[str, dict], List[dict]],
                        repaired: Tuple[Dict[str, dict], List[dict]], *, top: int = 20) -> dict:
    """The pre- and post-repair rankings and signals for one recomputed date, with the effect of the code change kept
    apart from the effect of the data repair (owner decision 2026-10-27)."""
    return {
        "date": d.isoformat(),
        "pre_repair_stored": ranking_view(*stored),
        "code_change_only": ranking_view(*code_only),
        "post_repair": ranking_view(*repaired),
        "comparison": {
            "code_change_only": compare_runs(*stored, *code_only, top=top),
            "code_plus_repair": compare_runs(*stored, *repaired, top=top),
            "repair_only": compare_runs(*code_only, *repaired, top=top),
        },
        "note": "A record of what changed, not evidence that the new ranking predicts better: that needs its own "
                "out-of-sample validation.",
    }
