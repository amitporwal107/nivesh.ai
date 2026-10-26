#!/usr/bin/env python3
"""repair_scanner_bars.py: repair the AI scanner's bar store (stock_ohlcv) and the rows derived from it
(services/positional_engine/bar_repair.py has the rules).

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.repair_scanner_bars                 # --dry-run (default): reads only
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.repair_scanner_bars --apply --snapshot /app/data/scanner_bars_snapshot_<date>.json
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.repair_scanner_bars --restore /app/data/scanner_bars_snapshot_<date>.json

(/app/data is the persistent mount on staging, /opt/nivesh-staging/data/app on the host: a snapshot there survives a
container rebuild. /app/backend is the repository checkout; do not write snapshots into it.)

--dry-run (default) is strictly read-only (SELECTs, data-platform GETs/bulk reads, NSE file downloads held in memory),
and enforced: every database connection it opens is read-only (default_transaction_read_only), so a write anywhere on
the path would fail instead of landing. It prints:
  1. phantom dates (stored, not a warehouse session, every bar a copy of the previous stored date) with row counts;
     non-session dates that are not a 100% copy are listed as "unverified" and are never deleted;
  2. missing sessions with their warehouse rows, and the NSE file for each (trade date checked, rows compared with
     the warehouse, closes matched);
  3. the derived rows: stock_technical_features / positional_signals on phantom dates (deleted by --apply), the dates
     --apply recomputes, and the affected dates it leaves as recorded; other stores keyed on the scan date;
  4. the data-quality report (bar_quality) before and as it would be after;
  5. symbols with a split/bonus step of 20% or more in the window, and a sample of adjusted closes against the
     warehouse's adj_close;
  6. a scanner rerun preview for the latest scored date, computed in memory (no writes): a replay on the bars as
     stored (fidelity check against the stored rows), a run on the stored bars adjusted (what a deploy alone changes)
     and a run on the corrected, adjusted bars (deploy + repair), each compared with the stored rows.

--apply (needs --snapshot PATH, a file that must not exist yet) writes the snapshot first, then:
  - deletes the phantom dates from stock_ohlcv, stock_technical_features and positional_signals (one transaction);
  - back-fills the missing sessions through the fixed ingester (refused unless the NSE file carries that date);
  - replaces the recompute dates' features and signals (default: the latest scored date; --recompute-from DATE for
    more) with a run of the fixed engine, one transaction per date. Skipped if a back-fill was refused.
  A second --apply finds nothing to do and writes nothing.
--restore PATH puts every snapshotted row back and removes the back-filled sessions (one transaction).

Exit codes: 0 done (dry run printed, or apply/restore finished); 1 refused or failed (message logged).
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


async def rerun_preview(plan: dict, top: int) -> dict:
    """Recompute the latest scored date in memory twice and compare with what is stored. Writes nothing."""
    from services import pg_client
    from services.positional_engine import bar_repair, bhavcopy_ingester as bi, ohlcv_store, pipeline

    scored_dates = sorted(plan["derived_rows_by_date"]["stock_technical_features"])
    phantom = {p["date"] for p in plan["phantom"]}
    latest = max(d for d in scored_dates if d not in phantom)

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        frows = await conn.fetch("SELECT nse_symbol, final_score::float8 fs, stage, sma_200::float8 s200,"
                                 " return_20d_pct::float8 r20, atr_14::float8 atr FROM stock_technical_features"
                                 " WHERE as_of_date = $1", latest)
        srows = await conn.fetch("SELECT nse_symbol, final_score::float8 fs, risk_reward::float8 rr, stage"
                                 " FROM positional_signals WHERE signal_date = $1", latest)
    stored_f = {r["nse_symbol"]: {"final_score": round(r["fs"], 4), "stage": r["stage"], "sma_200": r["s200"],
                                  "return_20d_pct": r["r20"], "atr_14": r["atr"]} for r in frows}
    stored_s = [{"symbol": r["nse_symbol"], "final_score": round(r["fs"], 4), "risk_reward": round(r["rr"], 2),
                 "stage": r["stage"]} for r in srows]

    # (A) the bars as stored, no adjustment: the old engine. Checks that the in-memory replay reproduces the table.
    sum_a, rows_a = await pipeline.score_universe(latest, adjust=False)
    fa, sa = bar_repair.scored_view(rows_a)

    # (C) the bars as stored, adjusted: what the fixed engine scores after a deploy, before the data repair.
    sum_c, rows_c = await pipeline.score_universe(latest)
    fc_, sc_ = bar_repair.scored_view(rows_c)

    # (B) corrected bars: phantom dates dropped, missing sessions from their NSE files (trade date checked), adjusted.
    extra: Dict[str, List[dict]] = {}
    for m in plan["missing"]:
        if m["date"] > latest:
            continue
        blob = bi._fetch(bi.BHAV_URL_FMT.format(ddmmyyyy=m["date"].strftime("%d%m%Y")))
        if not blob:
            raise RuntimeError(f"NSE file for {m['date']} not reachable: the corrected preview needs it")
        for b in bi.parse_bhavcopy_csv(blob, m["date"]):
            extra.setdefault(b["nse_symbol"], []).append(b)

    async def corrected(symbol: str, end: date, n: int) -> List[dict]:
        bars = await ohlcv_store.load_bars(symbol, end_date=end, lookback_bars=n + len(phantom))
        bars = [b for b in bars if b["bar_date"] not in phantom] + [b for b in extra.get(symbol, []) if b["bar_date"] <= end]
        bars.sort(key=lambda b: b["bar_date"])
        return bars[-n:]

    sum_b, rows_b = await pipeline.score_universe(latest, load_bars=corrected)
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
        "symbols_with_adjustment": len(ca),
        "adjusted_symbols_detail": ca_detail,
    }


async def dry_run(a, store, wh) -> int:
    from services import pg_client
    from services.positional_engine import bar_quality, bar_repair

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
                                    "last": plan["affected_not_recomputed"][-1:]},
        "other_stores": await other_stores(plan),
    })
    pool = await pg_client.get_pool()
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
    show("--apply would", {"delete_dates": act["delete_dates"], "backfill_dates": act["backfill_dates"],
                           "recompute_dates": act["recompute_dates"],
                           "note": "snapshot first; a second --apply finds nothing to do"})
    return 0


async def read_only_pool(pool):
    """Swap the app's pool for one whose every session is read-only: the dry run cannot write, by construction."""
    import asyncpg
    from services import pg_client

    ro = await asyncpg.create_pool(pg_client._last_url, min_size=1, max_size=5, command_timeout=120,
                                   statement_cache_size=0,
                                   server_settings={"default_transaction_read_only": "on"})
    await pool.close()
    pg_client._pool = ro
    async with ro.acquire() as conn:
        if await conn.fetchval("SHOW default_transaction_read_only") != "on":
            raise RuntimeError("could not open a read-only session")
    return ro


async def main(a) -> int:
    from services import pg_client
    from services.positional_engine import bar_repair, bhavcopy_ingester, pipeline

    pool = await pg_client.get_pool()
    if pool is None:
        log.error("no database pool: nothing done")
        return 1
    if not (a.apply or a.restore):
        pool = await read_only_pool(pool)
        log.info("dry run: database sessions are read-only")
    store, wh = bar_repair.PgStore(pool), bar_repair.DaasWarehouse()
    if a.restore:
        out = await bar_repair.restore_snapshot(store, a.restore)
        show("restored", out)
        return 0
    if a.apply:
        if not a.snapshot:
            log.error("--apply needs --snapshot PATH (written before any change): nothing done")
            return 1
        if os.path.exists(a.snapshot):
            log.error("snapshot %s already exists; choose a new path: nothing done", a.snapshot)
            return 1
        out = await bar_repair.apply_repair(store, wh, bhavcopy_ingester.ingest, pipeline.score_universe,
                                            a.snapshot, recompute_from=a.recompute_from)
        show("apply", out)
        return 0
    return await dry_run(a, store, wh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Repair the AI scanner's bar store (dry run by default)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read only and print what --apply would change (default)")
    mode.add_argument("--apply", action="store_true", help="make the changes (needs --snapshot)")
    mode.add_argument("--restore", metavar="SNAPSHOT", help="put a snapshot back")
    ap.add_argument("--snapshot", help="--apply: write the rows it deletes or replaces here first (must not exist)")
    ap.add_argument("--recompute-from", type=date.fromisoformat,
                    help="recompute every scored date from this one (default: the latest scored date only)")
    ap.add_argument("--top", type=int, default=20, help="dry run: ranking depth compared in the preview")
    ap.add_argument("--skip-preview", action="store_true", help="dry run: skip the in-memory scanner rerun")
    sys.exit(asyncio.run(main(ap.parse_args())))
