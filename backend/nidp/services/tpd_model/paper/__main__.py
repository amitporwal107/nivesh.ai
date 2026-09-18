"""Paper Trade Simulation Engine v1 — command line.

    python -m nidp.services.tpd_model.paper run --sample forward --snapshots <snapshots_v4> --exports <dir> --ca-csv <csv> --out <dir> [--apply]
    python -m nidp.services.tpd_model.paper run --sample replay  --replay-pkl <pkl> --replay-lock <json> --exports <dir> --ca-csv <csv> --out <dir> [--apply]

A run recomputes everything from the frozen predictions and the price panel (results are reproducible from stored
snapshots) and writes one psql transaction. Without --apply nothing touches a database; --out always receives an audit
copy: the SQL, each portfolio's evaluation JSON and a trades CSV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import bench, evaluate, sim, sources, store
from .engine import RULES_PATH, PredictionSet, lifecycle, load_rules, rank_universe, simulate
from .market import build_market, load_panel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("paper")
logging.getLogger("nidp.services.price_adjuster").setLevel(logging.ERROR)     # one line per skipped RIGHTS event; those surface as CORPORATE_ACTION_REVIEW instead
IST = timezone(timedelta(hours=5, minutes=30))
CLOSE = time(15, 30)
PORTFOLIOS = ("P5-NEXT", "P10-NEXT")


def registration() -> tuple[str, str, datetime]:
    """(rules sha256, commit sha, commit time) of the committed rules file; refuses a dirty or uncommitted rules file."""
    rel = RULES_PATH
    repo = rel.parents[5]
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", str(rel)], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(f"rules file has uncommitted changes: {dirty}")
    out = subprocess.run(["git", "-C", str(repo), "log", "--diff-filter=A", "--format=%H %cI", "--", str(rel)], capture_output=True, text=True).stdout.split()
    if len(out) < 2:
        raise SystemExit("rules file is not committed: register it before any run")
    return hashlib.sha256(rel.read_bytes()).hexdigest(), out[0], datetime.fromisoformat(out[1])


def at_close(d) -> datetime:
    return datetime.combine(pd.Timestamp(d).date(), CLOSE, tzinfo=IST)


def f(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) or np.isinf(v) else v


def build(sets: list[PredictionSet], market, rules: dict, names: pd.DataFrame, idx: pd.DataFrame, registered_at: datetime) -> dict:
    alloc = rules["allocation"]["capital_inr"] / rules["positions_per_portfolio"]
    cost = rules["costs"]["base_round_trip_pct"]
    rows = {k: [] for k in ("snaps", "trades", "obs", "exits", "events", "univ", "bench")}
    results = {p: [] for p in PORTFOLIOS}
    bench_frames = {p: [] for p in PORTFOLIOS}
    for n_set, ps in enumerate(sets):
        if market.t(ps.prediction_date) is None:
            log.warning("%s %s: prediction date not a session in the panel; skipped", ps.sample, ps.prediction_date)
            continue
        nxt = market.dates[market.t(ps.prediction_date) + 1] if market.t(ps.prediction_date) + 1 < len(market.dates) else None
        if nxt is not None and nxt.date() != ps.next_session:
            raise SystemExit(f"{ps.prediction_date}: the model's next session {ps.next_session} is not the panel's next session {nxt.date()}")
        for port in PORTFOLIOS:
            cfg = rules["portfolios"][port]
            u = rank_universe(ps, market, port, rules, names)
            key = lambda r: [ps.sample, ps.prediction_date, r["symbol"], port, ps.model_version, ps.feature_version]
            for r in u.to_dict("records"):
                rows["snaps"].append([ps.sample, 1, ps.prediction_date, ps.prediction_timestamp, ps.data_cutoff, ps.next_session, r["symbol"],
                                      r.get("isin") if isinstance(r.get("isin"), str) else None, port, cfg["target_pct"], sim.WINDOW,
                                      round(float(r["p_head"]), 5), None, None, None, f(r["p_opposite"]), f(r["p_other"]), int(r["model_rank"]),
                                      None if pd.isna(r["rank"]) else int(r["rank"]), r["selection_status"], r["exclusion_reason"],
                                      ps.model_version, ps.feature_version, ps.snapshot_sha256, rules["rules_id"], ps.counts, r["eligibility"]])
            out, arr = simulate(ps, market, u, rules)
            sess = out["session_dates"].iloc[0] if len(out) else []
            nsess = len(sess)
            # universe outcomes (every eligible row once its entry session exists)
            if nsess:
                for j, r in enumerate(out.to_dict("records")):
                    rows["univ"].append(key(r) + [r["status"], r["reason"], r["flags"], f(r["entry_price"]), f(r["gap"]), f(r["atr_14"]),
                                                  f(r["stop_loss_price"]), r["stop_method"], f(r["target_price"]), nsess, sess,
                                                  [f(v) for v in arr["r_open"][j, :nsess]], [f(v) for v in arr["r_high"][j, :nsess]],
                                                  [f(v) for v in arr["r_low"][j, :nsess]], [f(v) for v in arr["r_close"][j, :nsess]],
                                                  r["model_label_hit"], int(r["TARGET_STOP|exit_session_index"]) or None,
                                                  f(r["TARGET_STOP|gross_return"]), r["TARGET_STOP|exit_reason"], r["size_group"],
                                                  r["sector"] if isinstance(r["sector"], str) else None])
            # trades, observations, exits, events (selected rows)
            sel = out[out["selection_status"] == "SELECTED"]
            for j in sel.index:
                r = out.loc[j]
                st = lifecycle(r, nsess) if nsess else "PENDING_ENTRY"
                entered = r["status"] in ("ENTERED", "CORPORATE_ACTION_REVIEW") and not np.isnan(r["entry_price"])
                e1 = r["EOD-1|state"] == "CLOSED"
                g1 = f(r["EOD-1|gross_return"]) if e1 else None
                ts_closed = r["TARGET_STOP|state"] == "CLOSED"
                mfe_all = f(arr["mfe"][j, nsess - 1]) if entered and nsess else None
                mae_all = f(arr["mae"][j, nsess - 1]) if entered and nsess else None
                rows["trades"].append(key(r) + [
                    ps.next_session, sess[0] if entered else None, at_close(sess[0]) if entered else None, f(r["entry_price"]),
                    market.source[market.t(sess[0]), market.i(r["symbol"])] if entered else None,
                    ("ADJUSTED_PREV_CLOSE" if "CA_EX_ON_ENTRY" in r["flags"] else "UNADJUSTED_NO_ACTION") if entered else None,
                    f(r["prev_close_adj"]), f(r["gap"]), 0.0 if entered else None, alloc / r["entry_price"] if entered else None, alloc,
                    cfg["target_pct"], f(r["risk_percent"] * 100) if entered else None, sim.WINDOW, f(r["atr_14"]), f(r["support_level"]),
                    f(r["resistance_level"]), f(r["stop_loss_price"]), r["stop_method"], f(r["target_1_price"]), f(r["target_2_price"]),
                    f(r["risk_percent"]), f(r["reward_percent"]), f(r["risk_reward_ratio"]), st, r["reason"], r["flags"], nsess,
                    sess[0] if e1 and entered else None, f(market.close[market.t(sess[0]), market.i(r["symbol"])]) if e1 and entered else None,
                    "close of s1 (EOD-1 headline)" if e1 and entered else None, g1, cost / 100 * alloc if e1 and entered else None,
                    None if g1 is None else g1 - cost / 100, mfe_all, mae_all, f(arr["max_drawdown"][j, nsess - 1]) if entered and nsess else None,
                    bool(mfe_all is not None and mfe_all >= r["target_price"] / r["entry_price"] - 1 - 1e-12) if entered and nsess else None,
                    bool(str(r["TARGET_STOP|exit_reason"]).startswith("target")) if entered and ts_closed else None, ps.counts])
                # events
                pre = "replay: " if ps.sample == "replay" else ""
                t_pred = ps.data_cutoff if ps.sample == "replay" else ps.prediction_timestamp
                t_sel = ps.data_cutoff if ps.sample == "replay" else max(ps.prediction_timestamp, registered_at)
                ev = [("PREDICTED", None, t_pred, f"{pre}in the frozen EOD ranked list, model rank {int(r['model_rank'])}"),
                      ("SELECTED", "PREDICTED", t_sel, f"{pre}rank {int(r['rank'])} of the eligible universe for {port}"),
                      ("PENDING_ENTRY", "SELECTED", t_sel, f"{pre}entry at the official open of {ps.next_session}")]
                if nsess:
                    if entered:
                        fl = (" · " + ", ".join(r["flags"])) if r["flags"] else ""
                        ev.append(("ENTERED", "PENDING_ENTRY", at_close(sess[0]), f"{pre}filled at the official open ₹{r['entry_price']:.2f}{fl}"))
                        if r["status"] == "CORPORATE_ACTION_REVIEW":
                            ev.append(("CORPORATE_ACTION_REVIEW", "ENTERED", at_close(sess[0]), f"{pre}{r['reason']}"))
                        if nsess >= 2:
                            ev.append(("MONITORING", "ENTERED", at_close(sess[1]), f"{pre}daily bars recorded from {sess[1]}"))
                        if nsess >= sim.WINDOW:
                            ev.append(("EXITED", "MONITORING", at_close(sess[-1]), f"{pre}observation window closed; every mode has exited"))
                            ev.append(("EVALUATED", "EXITED", at_close(sess[-1]), f"{pre}returns, MFE/MAE and benchmarks computed"))
                    else:
                        ev.append((r["status"], "PENDING_ENTRY", at_close(sess[0]), f"{pre}{r['reason']}"))
                for to, fr, at, note in ev:
                    rows["events"].append(key(r) + [to, fr, at, note])
                if not entered:
                    continue
                for t_ in range(nsess):
                    ti, ii = market.t(sess[t_]), market.i(r["symbol"])
                    has = not np.isnan(arr["close"][j, t_])
                    rows["obs"].append(key(r) + [
                        sess[t_], t_, f(arr["open"][j, t_]), f(arr["high"][j, t_]), f(arr["low"][j, t_]), f(arr["close"][j, t_]),
                        None if not has else int(arr["volume"][j, t_]), f(arr["adj_factor"][j, t_]), f(arr["r_close"][j, t_]),
                        f(arr["r_open"][j, t_]), f(arr["r_high"][j, t_]), f(arr["r_low"][j, t_]), f(arr["high_watermark"][j, t_]),
                        f(arr["drawdown_from_entry"][j, t_]), f(arr["mfe"][j, t_]), f(arr["mae"][j, t_]),
                        bool(f(arr["mfe"][j, t_]) is not None and arr["mfe"][j, t_] >= r["target_price"] / r["entry_price"] - 1 - 1e-12),
                        bool(f(arr["mae"][j, t_]) is not None and arr["mae"][j, t_] <= r["stop_loss_price"] / r["entry_price"] - 1 + 1e-12),
                        ",".join(m for m in sim.MODES if r[f"{m}|state"] == "CLOSED" and int(r[f"{m}|exit_session_index"]) == t_ + 1) or None,
                        "OK" if has else ("THIN_SESSION" if pd.Timestamp(sess[t_]) in market.thin else "NO_BAR")])
                for m in sim.MODES:
                    gs = f(r[f"{m}|gross_return"])
                    k = int(r[f"{m}|exit_session_index"])
                    closed = r[f"{m}|state"] == "CLOSED"
                    xp = None
                    if closed and gs is not None:
                        xp = r["entry_price"] * (1 + gs) * (arr["adj_factor"][j, 0] / arr["adj_factor"][j, k - 1])
                    rows["exits"].append(key(r) + [m, r[f"{m}|state"], sess[k - 1] if closed and k else None, f(xp), r[f"{m}|exit_reason"],
                                                   k if closed else None, gs, cost, None if gs is None else gs - cost / 100,
                                                   None if gs is None else gs - 0.005, None if gs is None else gs - 0.010,
                                                   f(r[f"{m}|mfe"]), f(r[f"{m}|mae"]), bool(r[f"{m}|target_hit"]), bool(r[f"{m}|stop_hit"])])
            if nsess:
                br = bench.benchmark_rows(out, port, str(ps.next_session), sess, idx, cost)
                for b in br:
                    rows["bench"].append([ps.sample, port, ps.prediction_date, ps.next_session, b["benchmark"], b["mode"], b["state"], b["n"],
                                          b["members"], f(b["gross_mean"]), f(b["net_mean"]), f(b["target_hit_rate"]), f(b["positive_rate"]),
                                          b["source"], rules["rules_id"]])
                bench_frames[port].append(pd.DataFrame(br).assign(entry_session=ps.next_session))
                results[port].append(evaluate.SessionResult(ps.prediction_date, ps.next_session, sess, out, arr, ps.counts))
        if n_set % 20 == 0:
            log.info("%s: %d/%d prediction sets processed", sets[0].sample, n_set + 1, len(sets))
    return {"rows": rows, "results": results, "bench": {p: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for p, v in bench_frames.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sample", choices=("forward", "replay"), required=True)
    r.add_argument("--snapshots", type=Path)
    r.add_argument("--replay-pkl", type=Path)
    r.add_argument("--replay-lock", type=Path)
    r.add_argument("--exports", type=Path, required=True)
    r.add_argument("--ca-csv", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    rules = load_rules()
    sha, git_sha, registered_at = registration()
    log.info("rules %s sha %s registered %s (commit %s)", rules["rules_id"], sha[:12], registered_at.isoformat(), git_sha[:8])
    if a.sample == "forward":
        sets, refused = sources.forward_sets(a.snapshots, registered_at)
        for x in refused:
            log.warning("snapshot refused: %s", x)
    else:
        sets, refused = sources.replay_sets(a.replay_pkl, a.replay_lock), []
    if not sets:
        log.info("no prediction sets: nothing to do")
        return 0
    panel = load_panel(a.exports)
    market = build_market(panel, pd.read_csv(a.ca_csv))
    names = pd.read_csv(a.exports / "company_names.csv")
    lo, hi = min(s.next_session for s in sets), market.dates[-1].date()
    nse = pd.DataFrame(store.query_csv(f"SELECT as_of_date, open_price, close_price, source FROM nidp.index_eod WHERE index_name = 'Nifty 50' "
                                       f"AND as_of_date BETWEEN '{lo}' AND '{hi}' ORDER BY 1"))
    idx = sources.nifty_bars(nse if len(nse) else pd.DataFrame(columns=["as_of_date", "open_price", "close_price", "source"]), lo, hi,
                             fetch_yahoo=True)
    built = build(sets, market, rules, names, idx, registered_at)
    evals = []
    a.out.mkdir(parents=True, exist_ok=True)
    for port in PORTFOLIOS:
        res = built["results"][port]
        payload = evaluate.evaluate(res, built["bench"][port], rules, a.sample, port, all_recorded=len(res))
        payload["refused_snapshots"] = refused
        payload["computed_from"] = {"rules_sha256": sha, "registered_at": registered_at.isoformat(), "panel_last_session": str(hi),
                                    "prediction_sets": len(sets)}
        key = json.dumps({"rules": sha, "sets": [(s.snapshot_sha256, str(s.prediction_date)) for s in sets],
                          "observed": [(str(x.entry_session), len(x.sessions)) for x in res], "panel": str(hi)}, sort_keys=True)
        evals.append({"sample": a.sample, "portfolio": port, "rules_id": rules["rules_id"], "as_of_session": str(hi),
                      "inputs_sha256": hashlib.sha256(key.encode()).hexdigest(), "payload": payload})
        (a.out / f"evaluation_{a.sample}_{port}.json").write_text(json.dumps(payload, indent=1, default=str))
    idx_rows = [["Nifty 50", d.date(), float(v["open_price"]), float(v["close_price"]), v["source"]] for d, v in idx.iterrows()]
    rows = built["rows"]
    sql = store.run_sql(store.rules_sql(rules["rules_id"], sha, git_sha, registered_at.isoformat(), rules), rows["snaps"], rows["trades"],
                        rows["obs"], rows["exits"], rows["events"], rows["univ"], rows["bench"], idx_rows, evals)
    (a.out / f"run_{a.sample}.sql").write_text(sql)
    pd.DataFrame(rows["trades"], columns=store.TRADE_COLS).to_csv(a.out / f"trades_{a.sample}.csv", index=False)
    log.info("%s: %d snapshot rows, %d trades, %d observations, %d exits, %d events, %d universe outcomes, %d benchmark rows",
             a.sample, len(rows["snaps"]), len(rows["trades"]), len(rows["obs"]), len(rows["exits"]), len(rows["events"]), len(rows["univ"]),
             len(rows["bench"]))
    if a.apply:
        notes = store.apply(sql)
        log.info("applied to nidp_staging%s", (": " + notes.strip()) if notes.strip() else "")
    else:
        log.info("dry run: nothing written to a database (SQL at %s)", a.out / f"run_{a.sample}.sql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
