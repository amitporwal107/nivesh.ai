#!/usr/bin/env python3
"""repair_scanner_bars.py: repair the AI scanner's bar store (stock_ohlcv) and the rows derived from it
(services/positional_engine/bar_repair.py has the rules).

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.repair_scanner_bars                 # --dry-run (default): reads only
    ... --snapshot-only --snapshot /app/data/scanner_bars_preflight_<date>.json [--expect ...]                    # preflight: the snapshot only, no DB write
    ... --verify-snapshot /app/data/scanner_bars_preflight_<date>.json [--expect ...]                             # read-only check of a snapshot
    ... --apply --snapshot /app/data/scanner_bars_snapshot_<date>.json --expect stock_ohlcv=N,stock_technical_features=N,positional_signals=N
    ... --restore /app/data/scanner_bars_snapshot_<date>.json

(/app/data is the persistent mount on staging, /opt/nivesh-staging/data/app on the host: a snapshot there survives a
container rebuild. /app/backend is the repository checkout; do not write snapshots into it.)

--dry-run (default), --snapshot-only and --verify-snapshot open every database session read-only
(default_transaction_read_only), so a database write anywhere on their path would fail instead of landing. The dry
run reads (SELECTs, data-platform reads, NSE files held in memory) and prints:
  1. phantom dates (stored, not a warehouse session, every bar a copy of the previous stored date) with row counts;
     non-session dates that are not a 100% copy are listed as "unverified" and are never deleted;
  2. missing sessions with their warehouse rows, and the NSE file for each (trade date checked, rows compared with
     the warehouse, closes matched);
  3. the derived rows: stock_technical_features / positional_signals on phantom dates (deleted by --apply), the date
     --apply recomputes (the latest scored date only), and the older scored dates it leaves as recorded, on the price
     basis they were computed with; other stores keyed on the scan date;
  4. the data-quality report (bar_quality) before and as it would be after;
  5. symbols with a split/bonus step of 20% or more in the window, and a sample of adjusted closes against the
     warehouse's adj_close;
  6. a scanner rerun preview for the latest scored date, in memory: a replay of the old engine on the stored bars
     (fidelity check), the fixed engine on the stored bars ("code change only") and on the corrected bars ("code +
     repair"), each compared with the stored rows; and the exceptions: symbols scored on raw prices (no warehouse
     factors) and symbols not scored after a history cut, by name and reason;
  7. the per-table row counts the snapshot must hold, as the --expect value for --apply.

--apply (needs --snapshot PATH, a file that must not exist yet; --expect strongly advised):
  a. fetches the missing sessions' NSE files (trade date checked) and scores the recompute date on the corrected
     bars, in memory; computes the before/after rankings; nothing is written yet;
  b. writes the snapshot of every row it will delete or replace, reads it back and verifies it (non-empty, every
     affected table and date covered, per-date counts equal to the plan and to --expect); a failure stops here;
  c. ONE transaction on one connection: re-checks those counts, deletes the phantom dates from stock_ohlcv,
     stock_technical_features and positional_signals, inserts the back-filled bars, replaces the recompute date's
     features and signals. All of it commits or none of it does;
  d. reruns the data-quality check, writes <snapshot>.before_after.json (pre- and post-repair rankings and signals,
     split into "code change only" and "code + repair"), and writes the date's run record (Mongo job_runs, job
     positional_engine) so the API publishes its basis.
  A second --apply finds nothing to do and writes nothing. --recompute-from DATE exists but is not the documented
  path (owner decision 2026-10-27: the latest date only).
--restore PATH verifies the snapshot, then in one transaction puts every snapshotted row back and removes the
  back-filled sessions. Restoring twice gives the same state. The run record that apply wrote for the recomputed
  date is marked "rolled_back", so the API stops publishing its data checks for the restored rows.
--fingerprint OUT (read-only) writes, per table and date, the row count and an md5 of the rows (to_jsonb, ordered by
  symbol): taken before apply and after restore, --compare-fingerprints A B proves the restore is exact.

Exit codes: 0 done (or nothing to do); 1 refused or failed (the reason is printed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)     # one INFO line per data-platform read otherwise
log = logging.getLogger("repair_scanner_bars")

CA_STEP = 0.2            # the study's measure: a cumulative_adj_factor step of 20% or more
CA_SAMPLE = 8


def _plain(o):
    """JSON-ready: dates (also as dict keys) become ISO strings."""
    if isinstance(o, dict):
        return {(k.isoformat() if isinstance(k, date) else k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_plain(v) for v in o]
    return o.isoformat() if isinstance(o, date) else o


def show(title: str, payload) -> None:
    print(f"\n== {title}")
    print(json.dumps(_plain(payload), indent=1, default=str))


# ── dry-run sections ─────────────────────────────────────────────────────
async def missing_session_sources(plan: dict) -> Dict[str, dict]:
    """For each missing session: the NSE file's trade date, its EQ/BE rows, and its closes against the warehouse."""
    from services.positional_engine import bhavcopy_ingester as bi
    from services.copilot_tools import daas_client

    out: Dict[str, dict] = {}
    for m in plan["missing"]:
        d = m["date"]
        rec: dict = {"warehouse_rows": m["warehouse_rows"]}
        blob = bi._fetch(bi.BHAV_URL_FMT.format(ddmmyyyy=d.strftime("%d%m%Y")))
        if not blob:
            out[d.isoformat()] = {**rec, "nse_file": "not published / not reachable"}
            continue
        try:
            bars = bi.parse_bhavcopy_csv(blob, d)
        except bi.BhavcopyDateMismatch as e:
            out[d.isoformat()] = {**rec, "nse_file": f"refused: {e}"}
            continue
        wh: Dict[str, float] = {}
        for series in ("EQ", "BE"):
            status, body = await daas_client.get_raw("/prices/eod", {"on": d.isoformat(), "series": series, "limit": 5000})
            if status != 200:
                raise RuntimeError(f"warehouse /prices/eod {d} {series}: HTTP {status}")
            for r in body.get("data") or []:
                if r.get("close_price") is not None:
                    wh[str(r["symbol"]).upper()] = float(r["close_price"])
        both = [b for b in bars if b["nse_symbol"] in wh]
        mism = [b["nse_symbol"] for b in both if abs(b["close"] - wh[b["nse_symbol"]]) > 0.005]
        out[d.isoformat()] = {**rec, "nse_file": "trade date matches", "nse_eq_be_rows": len(bars),
                              "in_both": len(both), "close_mismatches": len(mism), "mismatch_sample": mism[:5],
                              "only_in_nse_file": len(bars) - len(both)}
    return out


async def other_stores(plan: dict) -> dict:
    """Stores keyed on a scan date that the repair does not rewrite: counts only."""
    from services import pg_client
    from deps import db

    phantom = [p["date"] for p in plan["phantom"]]
    out: dict = {}
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        for table, col in (("positional_outcomes", "signal_date"), ("positional_backtest_labels", "scan_date"),
                           ("chartink_scan_hits", "scan_date")):
            out[table] = {"rows": await conn.fetchval(f"SELECT count(*) FROM {table}"),
                          "on_phantom_dates": await conn.fetchval(
                              f"SELECT count(*) FROM {table} WHERE {col} = ANY($1::date[])", phantom)}
    ids = [d.isoformat() for d in phantom]
    out["mongo.ai_watchlist_days"] = {
        "docs": await db["ai_watchlist_days"].count_documents({}),
        "on_phantom_dates": await db["ai_watchlist_days"].count_documents({"_id": {"$in": ids}}),
        "note": "a stored day is never rewritten (services/ai_watchlist_store); not touched by --apply",
    }
    return out


async def corporate_actions(store_symbols: List[str], start: date, end: date, phantom: Set[date]) -> dict:
    """Symbols with a >= 20% split/bonus factor step in the window, and adjusted closes against the warehouse."""
    from services.copilot_tools import daas_client
    from services.positional_engine import ohlcv_store, price_adjustment

    factors = await price_adjustment.load_factors(store_symbols, start, end)
    steps = []
    for sym, per in factors.items():
        ds = sorted(per)
        for a, b in zip(ds, ds[1:]):
            if abs(per[b] / per[a] - 1) >= CA_STEP:
                steps.append({"symbol": sym, "ex_date": b, "price_ratio": round(per[a] / per[b], 4)})
    syms = sorted({s["symbol"] for s in steps})
    sample = (["KOTAKBANK"] if "KOTAKBANK" in syms else []) + [s for s in syms if s != "KOTAKBANK"][:CA_SAMPLE - 1]
    wh = await daas_client.get_adjusted_prices_bulk(sample, start.isoformat(), end.isoformat(), timeout=60.0)
    checks = []
    for sym in sample:
        bars = [b for b in await ohlcv_store.load_bars(sym, end_date=end, lookback_bars=400) if b["bar_date"] not in phantom]
        adj, info = price_adjustment.adjust_bars(bars, factors.get(sym))
        ref = {str(r["as_of_date"])[:10]: float(r["adj_close"]) for r in wh.get(sym, []) if r.get("adj_close")}
        diffs = [abs(b["close"] / ref[b["bar_date"].isoformat()] - 1) for b in adj if b["bar_date"].isoformat() in ref]
        step = next(s for s in steps if s["symbol"] == sym)
        pre = next((b for b in reversed(bars) if b["bar_date"] < step["ex_date"]), None)
        pre_adj = next((b for b in adj if pre and b["bar_date"] == pre["bar_date"]), None)
        checks.append({"symbol": sym, "ex_date": step["ex_date"], "dates_compared": len(diffs),
                       "max_rel_diff": round(max(diffs), 6) if diffs else None, "price_basis": info["price_basis"],
                       "break_truncated_at": info["break_truncated_at"],
                       "day_before_ex": {"date": pre["bar_date"] if pre else None, "raw_close": pre["close"] if pre else None,
                                         "adjusted_close": round(pre_adj["close"], 4) if pre_adj else None,
                                         "warehouse_adj_close": ref.get(pre["bar_date"].isoformat()) if pre else None}})
    return {"symbols_with_step": len(syms), "steps": len(steps),
            "price_ratio_histogram": dict(Counter(s["price_ratio"] for s in steps).most_common(12)),
            "symbols": syms, "store_symbols_with_factors": len(factors), "store_symbols": len(store_symbols),
            "adjusted_vs_warehouse_sample": checks}


async def stored_view(pool, d: date):
    """(features by symbol, signals) as stored for `d`, rounded as the tables store them."""
    async with pool.acquire() as conn:
        frows = await conn.fetch("SELECT nse_symbol, final_score::float8 fs, stage, sma_200::float8 s200,"
                                 " return_20d_pct::float8 r20, atr_14::float8 atr FROM stock_technical_features"
                                 " WHERE as_of_date = $1", d)
        srows = await conn.fetch("SELECT nse_symbol, final_score::float8 fs, risk_reward::float8 rr, stage"
                                 " FROM positional_signals WHERE signal_date = $1", d)
    feats = {r["nse_symbol"]: {"final_score": round(r["fs"], 4), "stage": r["stage"], "sma_200": r["s200"],
                               "return_20d_pct": r["r20"], "atr_14": r["atr"]} for r in frows}
    sigs = [{"symbol": r["nse_symbol"], "final_score": round(r["fs"], 4), "risk_reward": round(r["rr"], 2),
             "stage": r["stage"]} for r in srows]
    return feats, sigs


async def fetch_missing_bars(plan: dict, upto: date) -> Dict[str, List[dict]]:
    """The missing sessions' bars from their NSE files (calendar and trade date checked), by symbol. Writes nothing."""
    from services.positional_engine import bhavcopy_ingester as bi

    extra: Dict[str, List[dict]] = {}
    for m in plan["missing"]:
        if m["date"] > upto:
            continue
        res, bars = await bi.fetch_session(m["date"])
        if res["status"] != "ok":
            raise RuntimeError(f"NSE file for {m['date']}: {res['status']} ({res.get('reason')})")
        for b in bars:
            extra.setdefault(b["nse_symbol"], []).append(b)
    return extra


def score_fn():
    """bar_repair.Score: the fixed engine on the corrected bars (stock_ohlcv without the phantom dates, plus the
    fetched missing sessions), in memory."""
    from services.positional_engine import bar_repair, pipeline

    async def score(d: date, phantom: Set[date], extra: Dict[str, List[dict]]):
        loader = bar_repair.corrected_loader(phantom, extra) if (phantom or extra) else None
        return await pipeline.score_universe(d, load_bars=loader)
    return score


def before_after_fn(pool, top: int):
    """bar_repair.BeforeAfter: stored rows (pre), the fixed engine on the stored bars (code change only), and the
    rows the repair writes (post)."""
    from services.positional_engine import bar_repair, pipeline

    async def before_after(d: date, rows: List[dict]) -> dict:
        stored = await stored_view(pool, d)
        _summary, rows_c = await pipeline.score_universe(d)
        return bar_repair.before_after_record(d, stored, bar_repair.scored_view(rows_c), bar_repair.scored_view(rows),
                                              top=top)
    return before_after


async def quality_lite(pool, wh, start: date, end: date, skip=()) -> dict:
    from services.positional_engine import bar_quality

    sessions = await wh.sessions(start, end, [])
    report = await bar_quality.check_store(pool, start, end, sessions, skip_dates=skip)
    clean, problems = bar_quality.is_clean(report)
    return {"ok": True, "clean": clean, "problems": problems,
            "counts": {k: v.get("count") for k, v in report.items() if isinstance(v, dict)}}


def exceptions_view(summary: dict) -> dict:
    exc = summary.get("exceptions") or {}
    return {"raw_prices": {"count": len(exc.get("raw_prices") or []), "symbols": exc.get("raw_prices") or []},
            "not_scored_after_truncation": {"count": len(exc.get("not_scored_after_truncation") or []),
                                            "symbols": exc.get("not_scored_after_truncation") or []},
            "truncated_but_scored": {"count": sum(1 for t in exc.get("truncated") or [] if t["bars_left"] >= 60),
                                     "symbols": [t for t in exc.get("truncated") or [] if t["bars_left"] >= 60]}}


async def rerun_preview(plan: dict, top: int) -> dict:
    """Recompute the latest scored date in memory three times and compare with what is stored. Writes nothing."""
    from services import pg_client
    from services.positional_engine import bar_repair, pipeline

    scored_dates = sorted(plan["derived_rows_by_date"]["stock_technical_features"])
    phantom = {p["date"] for p in plan["phantom"]}
    latest = max(d for d in scored_dates if d not in phantom)
    pool = await pg_client.get_pool()
    stored_f, stored_s = await stored_view(pool, latest)

    # (A) the old engine: stored bars, no adjustment. Checks that an in-memory replay reproduces the table.
    _sum_a, rows_a = await pipeline.score_universe(latest, adjust=False)
    fa, sa = bar_repair.scored_view(rows_a)
    # (C) code change only: the fixed engine on the stored bars (what a deploy alone changes).
    sum_c, rows_c = await pipeline.score_universe(latest)
    fc_, sc_ = bar_repair.scored_view(rows_c)
    # (B) code + repair: the fixed engine on the corrected bars.
    sum_b, rows_b = await score_fn()(latest, phantom, await fetch_missing_bars(plan, latest))
    if not sum_b.get("ok"):
        return {"date": latest, "error": sum_b}
    fb, sb = bar_repair.scored_view(rows_b)

    ca = [r for r in rows_b if r["price_adjustment"]["factor_steps"] or r["price_adjustment"]["break_truncated_at"]]
    ca_detail = []
    for r in sorted(ca, key=lambda r: r["nse_symbol"])[:12]:
        s = r["nse_symbol"]
        ca_detail.append({"symbol": s, "price_adjustment": r["price_adjustment"],
                          "stored": {k: stored_f.get(s, {}).get(k) for k in ("stage", "final_score", "sma_200", "return_20d_pct")},
                          "rerun": {k: fb[s].get(k) for k in ("stage", "final_score", "sma_200", "return_20d_pct")}})
    return {
        "date": latest,
        "replay_as_stored_vs_table": bar_repair.compare_runs(stored_f, stored_s, fa, sa, top=top),
        "adjusted_unrepaired_vs_table": bar_repair.compare_runs(stored_f, stored_s, fc_, sc_, top=top),
        "corrected_vs_table": bar_repair.compare_runs(stored_f, stored_s, fb, sb, top=top),
        "corrected_vs_replay": bar_repair.compare_runs(fa, sa, fb, sb, top=top),
        "corrected_run": {k: sum_b.get(k) for k in ("universe", "scored", "actionable", "price_basis",
                                                    "break_truncated", "skipped_short_after_break", "macro_multiplier")},
        "exceptions_code_plus_repair": exceptions_view(sum_b),
        "exceptions_code_change_only": {k: v["count"] for k, v in exceptions_view(sum_c).items()},
        "symbols_with_adjustment": len(ca),
        "adjusted_symbols_detail": ca_detail,
        "note": "Rankings change; that is not evidence the new ranking predicts better (separate validation needed).",
    }


async def dry_run(a, store, wh) -> int:
    from services import pg_client
    from services.positional_engine import bar_repair

    plan = await bar_repair.plan_repair(store, wh, recompute_from=a.recompute_from)
    start, end = plan["window"]
    phantom = {p["date"] for p in plan["phantom"]}
    show("window", {"start": start, "end": end, "store_dates": plan["store_dates"],
                    "warehouse_sessions": plan["warehouse_sessions"]})
    show("phantom dates (deleted by --apply)", {"count": len(plan["phantom"]),
                                                 "rows": sum(p["rows"] for p in plan["phantom"]),
                                                 "dates": plan["phantom"]})
    show("non-session dates that are NOT a 100% copy (never deleted)", plan["unverified_extra"])
    show("missing sessions (back-filled by --apply)", {"count": len(plan["missing"]), "dates": plan["missing"],
                                                        "nse_file_check": await missing_session_sources(plan)})
    act = bar_repair.apply_actions(plan)
    show("derived rows", {
        "on_phantom_dates_deleted_by_apply": plan["derived_on_phantom"],
        "scored_dates": plan["scored_dates"],
        "recompute_dates": plan["recompute_dates"],
        "recompute_rows_replaced": {t: {d: plan["derived_rows_by_date"][t].get(d, 0) for d in act["recompute_dates"]}
                                    for t in plan["derived_rows_by_date"]},
        "affected_dates": plan["affected_dates"],
        "affected_not_recomputed": {"count": len(plan["affected_not_recomputed"]),
                                    "first": plan["affected_not_recomputed"][:1],
                                    "last": plan["affected_not_recomputed"][-1:],
                                    "note": "left as recorded: computed by engine v1.0 on the previously stored "
                                            "(raw, unrepaired) price basis"},
        "other_stores": await other_stores(plan),
    })
    pool = await pg_client.get_pool()
    from services.positional_engine import bar_quality
    sessions = await wh.sessions(start, end, [])
    before = await bar_quality.check_store(pool, start, end, sessions)
    after = await bar_quality.check_store(pool, start, end, sessions, skip_dates=phantom)
    show("data quality: as stored", before)
    show("data quality: phantom dates removed (missing sessions still listed until back-filled)",
         {k: after[k] for k in ("dates", "rows", "missing_sessions", "extra_dates", "copied_sessions", "duplicate_bars")})
    async with pool.acquire() as conn:
        syms = [r["nse_symbol"] for r in await conn.fetch(
            "SELECT DISTINCT nse_symbol FROM stock_ohlcv WHERE bar_date BETWEEN $1 AND $2", start, end)]
    show("corporate actions in the window", await corporate_actions(syms, start, end, phantom))
    if not a.skip_preview:
        show(f"scanner rerun preview (in memory, top {a.top})", await rerun_preview(plan, a.top))
    expect = {t: sum(v.values()) for t, v in bar_repair.expected_counts(plan, act).items()}
    show("--apply would", {"delete_dates": act["delete_dates"], "backfill_dates": act["backfill_dates"],
                           "recompute_dates": act["recompute_dates"],
                           "snapshot_rows_by_table": expect,
                           "expect_arg": ",".join(f"{t}={n}" for t, n in expect.items()),
                           "note": "snapshot first and verified, then one transaction; a second --apply finds nothing to do"})
    return 0


async def dedicated_pool(pool, *, read_only: bool):
    """Swap the app's pool (10 s statement timeout) for this run's own: 300 s per statement, so the snapshot read and
    the one transaction are not cut short; read-only sessions for every mode that must not write."""
    import asyncpg
    from services import pg_client

    settings = {"default_transaction_read_only": "on"} if read_only else {}
    own = await asyncpg.create_pool(pg_client._last_url, min_size=1, max_size=5, command_timeout=300,
                                    statement_cache_size=0, server_settings=settings)
    await pool.close()
    pg_client._pool = own
    async with own.acquire() as conn:
        if read_only and await conn.fetchval("SHOW default_transaction_read_only") != "on":
            raise RuntimeError("could not open a read-only session")
    return own


async def read_only_pool(pool):
    return await dedicated_pool(pool, read_only=True)


def parse_expect(text: Optional[str]) -> Optional[Dict[str, int]]:
    """"stock_ohlcv=36361,stock_technical_features=28280,positional_signals=9412" -> dict. ValueError when malformed."""
    if not text:
        return None
    out: Dict[str, int] = {}
    for part in text.split(","):
        table, _, n = part.partition("=")
        if table.strip() not in ("stock_ohlcv", "stock_technical_features", "positional_signals") or not n.strip().isdigit():
            raise ValueError(f"bad --expect part {part!r}")
        out[table.strip()] = int(n)
    return out


async def record_recompute(out: dict) -> None:
    """After a committed apply: the recomputed date's run record (job_runs), so the API publishes its basis."""
    from deps import db
    from services.positional_engine import ENGINE_VERSION, scan_meta
    import uuid

    for d_iso, summ in (out.get("recomputed") or {}).items():
        run_id = uuid.uuid4().hex
        now = scan_meta.utcnow()
        counts = {"date": d_iso, "engine_version": ENGINE_VERSION, "scored": summ.get("scored"),
                  "actionable": summ.get("actionable"), "price_basis": summ.get("price_basis"),
                  "exceptions": summ.get("exceptions"), "quality": out.get("quality_after"),
                  "calendar": None, "source": "repair_scanner_bars --apply", "snapshot": out.get("snapshot")}
        try:
            await scan_meta.start(db, run_id, session=d_iso, now=now)
            await scan_meta.finish(db, run_id, now=scan_meta.utcnow(), status=scan_meta.OK, exit_code=0,
                                   counts=counts, error=None, calendar_ready=None, calendar_missing_year=None)
            log.info("run record %s written for %s", run_id, d_iso)
        except Exception as e:  # noqa: BLE001 — the data is committed; the API then reports "not checked"
            log.error("run record for %s not written (%s): the API will show its data checks as not run", d_iso, e)


async def mark_rolled_back(snapshot: str) -> int:
    """After a restore: the run records apply wrote from this snapshot stop being published (status rolled_back)."""
    from deps import db
    from services.positional_engine import scan_meta

    res = await db[scan_meta.RUNS].update_many(
        {"job": scan_meta.JOB, "counts.snapshot": snapshot, "status": {"$ne": "rolled_back"}},
        {"$set": {"status": "rolled_back", "rolled_back_at": scan_meta.utcnow().isoformat()}})
    return res.modified_count


async def fingerprint(pool, path: str) -> dict:
    """Per table and date: [rows, md5 of the rows' to_jsonb text ordered by symbol]. Reads only; the file is new."""
    from services.positional_engine import bar_repair

    out: dict = {"tables": {}}
    async with pool.acquire() as conn:
        for table, col in bar_repair.TABLES:
            rows = await conn.fetch(f"SELECT {col} d, count(*) n, md5(string_agg(to_jsonb(t)::text, '|' ORDER BY nse_symbol)) h"
                                    f" FROM {table} t GROUP BY 1 ORDER BY 1")
            out["tables"][table] = {r["d"].isoformat(): [r["n"], r["h"]] for r in rows}
    out["totals"] = {t: sum(v[0] for v in d.values()) for t, d in out["tables"].items()}
    bar_repair.write_json_new(path, out)
    return {"fingerprint": path, "totals": out["totals"], "dates": {t: len(d) for t, d in out["tables"].items()}}


def compare_fingerprints(a_path: str, b_path: str) -> dict:
    with open(a_path) as f:
        a = json.load(f)["tables"]
    with open(b_path) as f:
        b = json.load(f)["tables"]
    diff = {t: sorted(d for d in set(a.get(t, {})) | set(b.get(t, {})) if a.get(t, {}).get(d) != b.get(t, {}).get(d))
            for t in sorted(set(a) | set(b))}
    return {"identical": not any(diff.values()), "differing_dates": diff}


async def main(a) -> int:
    from services import pg_client
    from services.positional_engine import bar_repair, bhavcopy_ingester

    if a.compare_fingerprints:
        out = compare_fingerprints(*a.compare_fingerprints)
        show("compare-fingerprints", out)
        return 0 if out["identical"] else 1
    try:
        expect = parse_expect(a.expect)
    except ValueError as e:
        log.error("%s: nothing done", e)
        return 1
    # Argument checks first: a refused command never opens a connection.
    if (a.apply or a.snapshot_only) and not a.snapshot:
        log.error("needs --snapshot PATH (written and verified before any change): nothing done")
        return 1
    for path in (a.snapshot if (a.apply or a.snapshot_only) else None, a.fingerprint):
        if path and os.path.exists(path):
            log.error("%s already exists; choose a new path: nothing done", path)
            return 1
    pool = await pg_client.get_pool()
    if pool is None:
        log.error("no database pool: nothing done")
        return 1
    read_only = not (a.apply or a.restore)    # dry run, snapshot-only, verify-snapshot, fingerprint
    pool = await dedicated_pool(pool, read_only=read_only)
    if read_only:
        log.info("database sessions are read-only")
    store, wh = bar_repair.PgStore(pool), bar_repair.DaasWarehouse()

    if a.fingerprint:
        show("fingerprint (read-only)", await fingerprint(pool, a.fingerprint))
        return 0

    if a.verify_snapshot:
        try:
            snap = bar_repair.read_snapshot(a.verify_snapshot)
        except (OSError, ValueError) as e:
            show("verify-snapshot", {"ok": False, "problems": [str(e)]})
            return 1
        plan = await bar_repair.plan_repair(store, wh, recompute_from=a.recompute_from)
        pending = [d.isoformat() for d in bar_repair.apply_actions(plan)["delete_dates"]]
        if pending == snap["dates"]["stock_ohlcv"] and pending:
            check = bar_repair.verify_snapshot(snap, plan)
            check["against"] = "the current store (not yet applied)"
        else:
            check = bar_repair.verify_snapshot(snap)
            check["against"] = ("the counts recorded in the snapshot only: the store no longer holds its phantom dates "
                                "(applied already, or changed since)")
        check["problems"] += bar_repair.check_expect(check["rows"], expect)
        check["ok"] = not check["problems"]
        show("verify-snapshot", {"snapshot": a.verify_snapshot, "created_at": snap.get("created_at"),
                                 "dates": snap["dates"], "backfill_dates": snap["backfill_dates"], **check})
        return 0 if check["ok"] else 1

    if a.restore:
        out = await bar_repair.restore_snapshot(store, a.restore)
        if out.get("restored"):
            try:
                out["run_records_rolled_back"] = await mark_rolled_back(a.restore)
            except Exception as e:  # noqa: BLE001 — the data is restored; the stale record is reported, not hidden
                log.error("restored, but the run record for %s could not be marked rolled_back (%s): the API may still "
                          "publish its data checks", a.restore, e)
        show("restore", out)
        return 0 if out.get("restored") else 1

    if a.apply or a.snapshot_only:
        if a.snapshot_only:
            out = await bar_repair.snapshot_only(store, wh, a.snapshot, recompute_from=a.recompute_from, expect=expect)
            show("snapshot-only (no database write)", out)
            return 0 if out["verification"]["ok"] else 1
        lo, hi = await store.bounds()

        async def post_check():
            return await quality_lite(pool, wh, lo, hi)
        out = await bar_repair.apply_repair(store, wh, bhavcopy_ingester.fetch_session, score_fn(), a.snapshot,
                                            recompute_from=a.recompute_from, expect=expect,
                                            before_after=before_after_fn(pool, a.top), post_check=post_check)
        show("apply", out)
        if out.get("changed"):
            await record_recompute(out)
            return 0
        return 1 if out.get("refused") else 0
    return await dry_run(a, store, wh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Repair the AI scanner's bar store (dry run by default)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read only and print what --apply would change (default)")
    mode.add_argument("--snapshot-only", action="store_true", help="preflight: write and verify the snapshot; no DB write")
    mode.add_argument("--verify-snapshot", metavar="SNAPSHOT", help="read-only check of a snapshot file")
    mode.add_argument("--apply", action="store_true", help="make the changes in one transaction (needs --snapshot)")
    mode.add_argument("--restore", metavar="SNAPSHOT", help="put a snapshot back (one transaction)")
    mode.add_argument("--fingerprint", metavar="OUT", help="read-only: per table and date, rows and an md5 of them")
    mode.add_argument("--compare-fingerprints", nargs=2, metavar=("A", "B"), help="compare two fingerprint files")
    ap.add_argument("--snapshot", help="--apply / --snapshot-only: write the snapshot here (must not exist)")
    ap.add_argument("--expect", help="per-table rows the snapshot must hold, from the reviewed dry run "
                                     "(table=n,...; the dry run prints it)")
    ap.add_argument("--recompute-from", type=date.fromisoformat,
                    help="not the documented path: recompute every scored date from this one (default: latest only)")
    ap.add_argument("--top", type=int, default=20, help="ranking depth compared in the preview and the before/after record")
    ap.add_argument("--skip-preview", action="store_true", help="dry run: skip the in-memory scanner rerun")
    sys.exit(asyncio.run(main(ap.parse_args())))
