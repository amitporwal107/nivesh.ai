"""Runs the simulation framework's D1 (ledgers + data quality), D3 (configuration A vs labels.py on every 2022 trade)
and D4 (the 20-session replay with its trade audit) once, from committed code, on the frozen H#32 inputs.

Output: /app/research/sim_diag/run_<stamp>/ (data, not in git) with a manifest of every file's sha256.
Reads development bars only (<= 2022-12-30, the guarded loader); the sealed 2023-24 block is never touched."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from decimal import Decimal

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import inputs as IN  # noqa: E402
import tradesim as TS  # noqa: E402
import panel as P  # noqa: E402
import candidates as CD  # noqa: E402
import dq as DQ  # noqa: E402
import reconcile as RC  # noqa: E402
import audit as AU  # noqa: E402

OUT_ROOT = "/app/research/sim_diag"
REPLAY = (pd.Timestamp("2022-10-03"), pd.Timestamp("2022-11-01"))
REPLAY_SESSIONS = 20
CUTOFF_EXTRA_DATES, CUTOFF_SEED = 12, 20260920


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()


def _plain(x):
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, (dt.date, pd.Timestamp)):
        return str(pd.Timestamp(x).date())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _dump(obj, path):
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1, default=_plain)


def trade_frame(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        r = {k: _plain(v) for k, v in t.items() if k not in ("fills", "bars_used")}
        r["bars_used"] = ";".join(str(d) for d in t.get("bars_used", []))
        if t.get("fills"):
            r["buy_value"], r["sell_value"] = str(t["fills"][0]["value"]), str(t["fills"][1]["value"])
        rows.append(r)
    return pd.DataFrame(rows)


def main() -> str:
    dirty = _git("status", "--porcelain", "--", HERE, IN.MV5, os.path.join(TS.BACKEND, "nidp", "services", "tpd_model"))
    if dirty:
        raise RuntimeError(f"uncommitted changes; commit first:\n{dirty}")
    commit = _git("rev-parse", "HEAD")
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out = os.path.join(OUT_ROOT, f"run_{stamp}")
    os.makedirs(out)
    log = lambda *a: print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)  # noqa: E731

    fz = IN.load_frozen()
    ds, scores, picks, cal = fz["ds"], fz["scores"], fz["picks"], fz["cal"]
    uni = IN.universe_isin()
    log("frozen inputs verified", fz["files"])
    raw = IN.load_bars_raw(set(uni.symbol))
    bars = IN.bars_like_dataset(raw, cal)
    match = IN.check_bars_match_dataset(bars, ds)
    log("bars vs dataset", match)
    if not match["pass"]:
        raise IN.InputError(f"re-read bars do not reproduce the dataset: {match}")
    bars = P.enrich(bars)
    store = P.BarStore(bars, cal)
    preds = IN.predictions_ledger(ds, scores, fz["commit"])
    ranked = CD.rank(ds, scores)
    pick_check = CD.verify_picks(ranked, picks)
    log("picks reproduced", pick_check)

    year_dates = cal[(cal >= IN.YEAR_START) & (cal <= pd.Timestamp(IN.DEV.feat_end))]
    replay_dates = cal[(cal >= REPLAY[0]) & (cal <= REPLAY[1])]
    if len(replay_dates) != REPLAY_SESSIONS:
        raise RuntimeError(f"replay window has {len(replay_dates)} sessions, expected {REPLAY_SESSIONS}")

    # ---- configuration A: every pick through the trade simulator ----
    cm = TS.CC.load_cost_model(IN.DS.COST_MODEL)
    trades, by_row, entry_agree = [], {}, []
    for idx, p in picks.iterrows():
        w = store.window(p.symbol, p.date, float(ds.at[idx, "atr_pct"]))
        t = TS.simulate(TS.CONFIG_A, w, cm)
        t["row"] = idx
        trades.append(t)
        by_row[idx] = t
        sim_entry = "OK" if t["status"] == "CLOSED" else t.get("entry_rejection_reason")
        lab_entry = ds.at[idx, "entry_status"]
        entry_agree.append(sim_entry == lab_entry or (sim_entry == "LOCKED_UPPER" and lab_entry == "LOCKED_UPPER_OPEN"))
    closed = [t for t in trades if t["status"] == "CLOSED"]
    no_entry = []                                  # picks without an entry: was the s1 lock real (high == low) or the test?
    for t in trades:
        if t["status"] != "CLOSED":
            s1 = store.sessions_after(pd.Timestamp(t["decision_date"]), 1)[0]
            b = store.row(t["symbol"], s1)
            no_entry.append({"symbol": t["symbol"], "decision_date": str(t["decision_date"]), "status": t["status"],
                             "reason": t.get("entry_rejection_reason") or t.get("exit_reason"),
                             "labels_entry_status": ds.at[t["row"], "entry_status"],
                             "s1": str(s1.date()), "s1_full_day_lock": None if b is None else bool(b.high == b.low),
                             "s1_ohlc": None if b is None else [float(b.open), float(b.high), float(b.low), float(b.close)]})
    log("config A simulated", len(trades), "closed", len(closed), "entry status agree", sum(entry_agree))

    # ---- D3 reconciliation ----
    either = [t for t in trades if t["status"] == "CLOSED" or ds.at[t["row"], "entry_status"] == "OK"]
    rec_rows = [dict(RC.compare(t, ds.loc[t["row"]], store.bar(t["symbol"], store.sessions_after(pd.Timestamp(t["decision_date"]), 1)[0])),
                     row=t["row"]) for t in either]
    rec = pd.DataFrame(rec_rows)
    rec_summary = RC.summarise(rec) | {"entry_status_agree": int(sum(entry_agree)), "picks": int(len(trades))}
    log("reconciliation", rec_summary)
    rec_map = {(r.symbol, pd.Timestamp(r.decision_date)): r._asdict() for r in rec.itertuples(index=False)}

    # ---- D1 data quality ----
    flags = DQ.bar_flags(bars)
    rawc = DQ.raw_checks(raw, cal)
    raw_dups = raw[raw.duplicated(["symbol", "date"], keep=False)]
    missing = DQ.missing_table(bars, uni, year_dates)
    rng = np.random.default_rng(CUTOFF_SEED)
    others = [d for d in year_dates if d not in set(replay_dates)]
    cutoff_dates = list(replay_dates) + sorted(rng.choice(others, CUTOFF_EXTRA_DATES, replace=False))
    members = set(uni.symbol)
    cutoff = {}
    for T in cutoff_dates:
        cutoff[pd.Timestamp(T)] = DQ.feature_cutoff(bars, cal, members, ds, pd.Timestamp(T))
    log("feature cutoff checked", len(cutoff), "violations", sum(c["violations"] for c in cutoff.values()))
    tr_df = trade_frame(trades)
    used = []
    for t in closed:
        for d in t["bars_used"]:
            used.append((t["symbol"], pd.Timestamp(t["decision_date"]), pd.Timestamp(d)))
        used.append((t["symbol"], pd.Timestamp(t["decision_date"]), pd.Timestamp(t["decision_date"])))
    used = pd.DataFrame(used, columns=["symbol", "decision_date", "date"])
    sessions = {}
    for D in year_dates:
        sessions[D] = DQ.session_report(D, flags, missing, raw_dups, uni, ds[ds.date == D],
                                        used.loc[used.decision_date == D, ["symbol", "date"]].drop_duplicates(),
                                        picks[picks.date == D], cutoff.get(D), rawc["symbols_with_several_instruments"], store)
    log("session reports", pd.Series([s["status"] for s in sessions.values()]).value_counts().to_dict())
    fl = flags.set_index(["symbol", "date"])
    dq_fail = fl.ohlc_invalid.to_dict()
    flag_cols = DQ.FLAG_COLS
    dq_flag = {}
    for k, r in fl[fl.any_flag].iterrows():
        dq_flag[k] = [c for c in flag_cols if r[c]] + ([r.special_session] if isinstance(r.special_session, str) else [])
    for (s, d) in zip(raw_dups.symbol, raw_dups.date):
        dq_fail[(s, d)] = True

    # ---- D4 audit (every 2022 trade; the replay is the hand-checked subset) ----
    ranks = {(r.symbol, r.date): int(r.rank) for r in ranked.itertuples()}
    tb = scores[f"{IN.MODEL}|{IN.LABEL}"]
    mv = scores["M4|hit_high_10_5d"]
    probs = {(ds.at[i, "symbol"], ds.at[i, "date"]): {"tbs": float(tb.at[i]), "movement": float(mv.at[i])} for i in picks.index}
    raw_by_symbol = {s: g.sort_values("date") for s, g in raw.groupby("symbol")}
    aud = AU.audit_rows(closed, ranks, probs, dq_fail, dq_flag, rec_map, raw_by_symbol)
    ctr = tr_df[tr_df.status == "CLOSED"].copy()
    for c in ("entry_date", "exit_date", "decision_date"):
        ctr[c] = pd.to_datetime(ctr[c])
    for c in ("buy_value", "sell_value", "net_inr", "gross_inr", "charges_inr", "slippage_inr", "initial_risk_inr"):
        ctr[c] = ctr[c].astype(float)
    industry = dict(zip(uni.symbol, uni.industry))
    expo = AU.exposure(ctr, cal, industry)
    pool = ranked.join(ds[["atr_pct"]])
    paths = AU.forward_paths(bars, cal, pool[["symbol", "date"]])
    modea_year, modea_replay = AU.mode_a(pool, paths), AU.mode_a(pool, paths, replay_dates)
    log("audit + mode A done")

    in_replay = ctr.decision_date.isin(replay_dates)
    aud["signal_date"] = pd.to_datetime(aud.signal_date)
    aud_replay = aud[aud.signal_date.isin(replay_dates)]
    rejected_year = int((tr_df.status != "CLOSED").sum())
    rejected_replay = int(((tr_df.status != "CLOSED") & pd.to_datetime(tr_df.decision_date).isin(replay_dates)).sum())

    def dq_summary(dates):
        ss = [sessions[d] for d in dates]
        return {"sessions": len(ss), "status": pd.Series([s["status"] for s in ss]).value_counts().to_dict(),
                "fail_reasons": sorted({r for s in ss for r in s["fail_reasons"]}),
                "valid_bar_pct_min": min(s["valid_bar_pct"] for s in ss),
                "missing_bar_symbol_days": sum(len(s["missing"]) for s in ss),
                "special_sessions": sorted({s["date"] for s in ss if s["special_session"]}),
                "corporate_action_flags": sum(len(s["flags_universe"].get("ca_move", [])) + len(s["flags_universe"].get("ca_volume", [])) for s in ss),
                "cutoff_dates_checked": sum(1 for s in ss if s["feature_cutoff"]),
                "cutoff_violations": sum(s["feature_cutoff"]["violations"] for s in ss if s["feature_cutoff"]),
                "raw": rawc}

    rec_replay = RC.summarise(rec[pd.to_datetime(rec.decision_date).isin(replay_dates)])
    score_year = AU.scorecard(dq_summary(year_dates), ctr, aud, modea_year, rec_summary, expo, rejected_year)
    score_replay = AU.scorecard(dq_summary(replay_dates), ctr[in_replay], aud_replay, modea_replay, rec_replay,
                                expo[(expo.date >= replay_dates[0]) & (expo.date <= ctr[in_replay].exit_date.max())], rejected_replay)

    # ---- ledgers ----
    files = {}

    def save(df_or_obj, name, **kw):
        path = os.path.join(out, name)
        if isinstance(df_or_obj, pd.DataFrame):
            df_or_obj.to_csv(path, index=False, **({"compression": {"method": "gzip", "mtime": 0}} if name.endswith(".gz") else {}), **kw)
        else:
            _dump(df_or_obj, path)
        files[name] = IN.sha256(path)

    save(preds, "predictions.csv.gz")
    cand_year = CD.ledger(ds, scores, ranked, fz["iso"], uni, preds, year_dates, missing, by_row)
    save(cand_year, "candidates_2022.csv.gz")
    save(cand_year[cand_year.date.isin(replay_dates)], "candidates_replay.csv")
    save(tr_df, "trades_A.csv")
    fills = [{"trade_id": f"A-{pd.Timestamp(t['decision_date']):%Y%m%d}-{t['symbol']}", **{k: _plain(v) for k, v in f.items()}}
             for t in closed for f in t["fills"]]
    save(pd.DataFrame(fills), "fills_A.csv")
    rb = []
    for t in closed:
        if pd.Timestamp(t["decision_date"]) in set(replay_dates):
            g = raw_by_symbol[t["symbol"]]
            ds_ = [pd.Timestamp(t["decision_date"])] + [pd.Timestamp(d) for d in t["bars_used"]]
            rb.append(g[g.date.isin(ds_)].assign(trade_id=f"A-{pd.Timestamp(t['decision_date']):%Y%m%d}-{t['symbol']}"))
    save(pd.concat(rb), "bars_used_replay.csv")
    save(rec, "reconciliation_A.csv")
    save(aud, "audit_A_2022.csv")
    save(aud_replay, "audit_replay.csv")
    save(expo, "exposure_A.csv")
    save({str(d.date()): s for d, s in sessions.items() if d in set(replay_dates)}, "dq_sessions_replay.json")
    save({str(d.date()): {k: s[k] for k in ("status", "fail_reasons", "special_session", "missing", "flags_universe")}
          for d, s in sessions.items()}, "dq_sessions_2022.json")
    corr = {str(D.date()): CD.pick_correlation(store, list(picks[picks.date == D].symbol), D) for D in replay_dates}
    save(corr, "pick_correlations_replay.json")
    save({"year": modea_year, "replay": modea_replay}, "mode_a.json")
    save({"year": score_year, "replay": score_replay}, "scorecard.json")
    results = {"run": stamp, "code_commit": commit, "inputs": fz["files"], "prediction_commit": fz["commit"],
               "cost_model": cm.cost_model_id, "costs_retroactive": True, "config": "A (H#32 convention, frozen)",
               "intrabar_policy": TS.CONFIG_A.policy, "rc1": AU.RC1_VERSION, "replay_dates": [str(d.date()) for d in replay_dates],
               "bars_vs_dataset": match, "picks_reproduced": pick_check, "no_entry_picks": no_entry,
               "reconciliation_2022": rec_summary,
               "reconciliation_replay": rec_replay,
               "rc1_primary_2022": aud.rc1_primary.value_counts().to_dict(),
               "rc1_primary_excl_flags_2022": aud.rc1_primary_excl_unreviewed_flags.value_counts().to_dict(),
               "rc1_primary_replay": aud_replay.rc1_primary.value_counts().to_dict(),
               "raw_bar_check_replay": aud_replay.raw_bar_check.value_counts().to_dict(),
               "raw_bar_check_2022": aud.raw_bar_check.value_counts().to_dict(),
               "files": files}
    _dump(results, os.path.join(out, "results.json"))
    _dump({"results.json": IN.sha256(os.path.join(out, "results.json")), **files}, os.path.join(out, "manifest.json"))
    log("wrote", out)
    return out


if __name__ == "__main__":
    main()
