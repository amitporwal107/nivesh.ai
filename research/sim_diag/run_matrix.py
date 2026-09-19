"""The single pre-registered run of the comparison matrix (deliverable D5).

Pre-registration: docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md, frozen at ffa0a139. Nothing in this
file chooses anything: it runs the eight matrix configurations, the four secondary rows, the whole-candidate pool and
the random control on the frozen H#32 inputs, and writes the numbers with a sha256 manifest.

It refuses to run on a dirty tree, checks every input against its recorded hash, and checks that configuration A
reproduces the D3 baseline exactly before anything else is reported.

Output: /app/research/sim_diag/matrix_<stamp>/ (data, not in git).
Development bars only (<= 2022-12-30, the guarded loader); the sealed 2023-24 block is never read.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
import subprocess
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit as AU  # noqa: E402
import candidates as CD  # noqa: E402
import dq as DQ  # noqa: E402
import inputs as IN  # noqa: E402
import matrix as MX  # noqa: E402
import panel as P  # noqa: E402
import tradesim as TS  # noqa: E402

from nidp.services.tpd_model.risk import engine as EN  # noqa: E402

OUT_ROOT = "/app/research/sim_diag"
BASELINE_RUN = os.path.join(OUT_ROOT, "run_20260920T003043")      # the D1-D4 run configuration A must reproduce
REPLAY = (pd.Timestamp("2022-10-03"), pd.Timestamp("2022-11-01"))
REPLAY_SESSIONS = 20
CAPITAL = 500000.0
BASELINE_TAG = {"D": "D|risk0.5|posmax", "F": "F|risk0.5|pos8"}      # the §4b baselines; the others are sensitivity


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()


def _plain(x):
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (dt.date, pd.Timestamp)):
        return str(pd.Timestamp(x).date())
    if isinstance(x, pd.Series):
        return {str(k): _plain(v) for k, v in x.items()}
    return x


def _clean(o):
    """NaN and infinity are not JSON. A metric that does not exist for a run is written as null, never as NaN."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _dump(obj, path):
    with open(path, "w") as fh:
        json.dump(_clean(obj), fh, indent=1, default=_plain, allow_nan=False)


def check_baseline(a: pd.DataFrame, path: str = BASELINE_RUN, strict: bool = True) -> dict:
    """Acceptance §9: configuration A must reproduce the D3 run trade for trade. `strict=False` only checks the trades
    both runs hold (used by the smoke run, which simulates a subset)."""
    prev = pd.read_csv(os.path.join(path, "trades_A.csv"), float_precision="round_trip")
    prev = prev[prev.status == "CLOSED"].copy()
    prev["decision_date"] = pd.to_datetime(prev.decision_date)
    key = ["symbol", "decision_date"]
    j = a[key + ["net_ret", "exit_date", "exit_reason"]].merge(
        prev[key + ["net_ret", "exit_date", "exit_reason"]], on=key, suffixes=("_now", "_d3"), how="outer", indicator=True)
    both = j[j._merge == "both"]
    out = {"d3_trades": int(len(prev)), "now_trades": int(len(a)), "matched": int(len(both)),
           "only_now": int((j._merge == "left_only").sum()), "only_d3": int((j._merge == "right_only").sum()),
           "max_abs_net_ret_diff": float((both.net_ret_now - both.net_ret_d3).abs().max()),
           "exit_reason_mismatches": int((both.exit_reason_now != both.exit_reason_d3).sum()),
           "exit_date_mismatches": int((pd.to_datetime(both.exit_date_now) != pd.to_datetime(both.exit_date_d3)).sum())}
    out["strict"] = strict
    out["pass"] = bool((not strict or (out["only_now"] == 0 and out["only_d3"] == 0)) and out["max_abs_net_ret_diff"] < 1e-12
                       and out["exit_reason_mismatches"] == 0 and out["exit_date_mismatches"] == 0)
    return out


def scope_metrics(name: str, trades: list, tr: pd.DataFrame, dates, cal, industry: dict, names: dict,
                  a_tr: pd.DataFrame, *, extremes: bool) -> dict:
    """One configuration's numbers on one scope (the whole year, or the replay window)."""
    dates = set(pd.DatetimeIndex(dates))
    sub = tr[tr.decision_date.isin(dates)]
    rej = MX.rejections([t for t in trades if pd.Timestamp(t["decision_date"]) in dates])
    m = MX.metrics(name, sub, rej, cal, industry)
    m["tax"] = MX.tax_annex(m["net_inr"])
    if name != "A":
        m["paired_vs_A"] = MX.paired_diff(a_tr[a_tr.decision_date.isin(dates)], sub)
    if extremes:
        m["extremes"] = MX.extremes(sub, names)
    return m


def main(smoke: bool = False) -> str:
    """smoke=True is a plumbing check, never a result: it runs the replay window only, on a possibly dirty tree, and
    labels its output folder and results file accordingly."""
    dirty = _git("status", "--porcelain", "--", HERE, IN.MV5, os.path.join(TS.BACKEND, "nidp", "services", "tpd_model"))
    if dirty and not smoke:
        raise RuntimeError(f"uncommitted changes; commit first:\n{dirty}")
    if smoke:
        print("=" * 70 + "\nSMOKE RUN - plumbing check on the replay window only. NOT a result.\n" + "=" * 70, flush=True)
    commit = _git("rev-parse", "HEAD")
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out = os.path.join(OUT_ROOT, f"{'smoke' if smoke else 'matrix'}_{stamp}")
    os.makedirs(out)
    t0 = time.time()
    log = lambda *a: print(f"{time.time() - t0:7.1f}s", *a, flush=True)  # noqa: E731

    # ---- frozen inputs ----
    fz = IN.load_frozen()
    ds, scores, picks, cal = fz["ds"], fz["scores"], fz["picks"], fz["cal"]
    uni = IN.universe_isin()
    industry, names = dict(zip(uni.symbol, uni.industry)), dict(zip(uni.symbol, uni.name))
    log("inputs verified", fz["files"])
    raw = IN.load_bars_raw(set(uni.symbol))
    bars = IN.bars_like_dataset(raw, cal)
    match = IN.check_bars_match_dataset(bars, ds)
    if not match["pass"]:
        raise IN.InputError(f"re-read bars do not reproduce the dataset: {match}")
    bars = P.enrich(bars)
    store = P.BarStore(bars, cal)
    ranked = CD.rank(ds, scores)
    pick_check = CD.verify_picks(ranked, picks)
    log("bars and picks reproduced", match, pick_check)

    year_dates = cal[(cal >= IN.YEAR_START) & (cal <= pd.Timestamp(IN.DEV.feat_end))]
    replay_dates = cal[(cal >= REPLAY[0]) & (cal <= REPLAY[1])]
    if len(replay_dates) != REPLAY_SESSIONS:
        raise RuntimeError(f"replay window has {len(replay_dates)} sessions, expected {REPLAY_SESSIONS}")
    if smoke:
        year_dates = replay_dates
        picks = picks[picks.date.isin(replay_dates)]
        ranked = ranked[ranked.date.isin(replay_dates)]
    cm = TS.CC.load_cost_model(IN.DS.COST_MODEL)

    # ---- data-quality maps for RC-1 (the same inputs the D4 audit used) ----
    dqflags = DQ.bar_flags(bars)
    raw_dups = raw[raw.duplicated(["symbol", "date"], keep=False)]
    fl = dqflags.set_index(["symbol", "date"])
    dq_fail = fl.ohlc_invalid.to_dict()
    for (sy, dd) in zip(raw_dups.symbol, raw_dups.date):
        dq_fail[(sy, dd)] = True
    dq_flag = {}
    for k, r in fl[fl.any_flag].iterrows():
        dq_flag[k] = [c for c in DQ.FLAG_COLS if r[c]] + ([r.special_session] if isinstance(r.special_session, str) else [])
    log("data-quality flags built")

    def with_rc1(fr: pd.DataFrame, trades: list) -> pd.DataFrame:
        rc = MX.rc1_column(trades, dq_fail, dq_flag)
        return fr.merge(rc, on=["symbol", "decision_date"], how="left", validate="1:1")

    # ---- trade-isolated runs on the frozen picks ----
    raw_trades, frames = {}, {}
    for name, spec in list(MX.MATRIX.items()) + list(MX.SECONDARY.items()):
        t = MX.simulate_rows(spec, picks, store, ds, cm)
        raw_trades[name], frames[name] = t, with_rc1(MX.frame(t), t)
        log(f"run {name}: {len(frames[name])} trades of {len(t)} picks")
    base = check_baseline(frames["A"], strict=not smoke)
    log("configuration A vs D3:", base)
    if not base["pass"]:
        raise RuntimeError(f"configuration A does not reproduce the D3 baseline: {base}")

    # ---- S5: every eligible candidate under A's rules (the rank bands and the random control read this) ----
    pool_trades = MX.simulate_rows(MX.POOL, ranked[["symbol", "date"]], store, ds, cm)
    pool = MX.frame(pool_trades)
    log(f"pool run: {len(pool)} trades of {len(ranked)} candidates")
    pool = with_rc1(pool, pool_trades)
    frames["S5_POOL"], raw_trades["S5_POOL"] = pool, pool_trades
    pool_reason = {(pd.Timestamp(t["decision_date"]), t["symbol"]): (t.get("entry_rejection_reason") or t.get("status"))
                   for t in pool_trades if t.get("status") != "CLOSED"}
    draws = {"year": MX.random_picks(ranked[ranked.date.isin(year_dates)]),
             "replay": MX.random_picks(ranked[ranked.date.isin(replay_dates)])}
    log("random draws built")

    # ---- D and F: the portfolio loop ----
    prepared = EN.prepare_bars(bars[["symbol", "date", "open", "high", "low", "close", "volume", "value20", "prev_close"]])
    log("engine bars prepared")
    sig_year = MX.signals(picks, ds)
    sig_replay = sig_year[pd.to_datetime(sig_year.date).isin(replay_dates)]
    engine = {}
    for letter, cid in MX.PORTFOLIO.items():
        for risk in MX.RISK_LEVELS:
            for pos in (MX.F_POSITIONS if letter == "F" else (None,)):
                tag = f"{letter}|risk{risk}|pos{pos or 'max'}"
                for scope, sg in (("year", sig_year), ("replay", sig_replay)):
                    res, tr, meta = MX.run_portfolio(letter, cid, sg, prepared, cm, industry, industry,
                                                     risk_pct=risk, positions=pos)
                    engine[(tag, scope)] = (res, tr, meta)
                log(f"engine {tag}: year {len(engine[(tag, 'year')][1])} trades, replay {len(engine[(tag, 'replay')][1])}")

    def engine_block(scope, dates):
        """Every D/F variant's metrics for one scope; the pre-registered baselines are D at 0.5% and F at 0.5%/8."""
        rows = []
        a = frames["A"][frames["A"].decision_date.isin(set(pd.DatetimeIndex(dates)))]
        for (tag, sc), (res, tr, meta) in engine.items():
            if sc != scope or tr.empty:
                continue
            m = MX.metrics(tag, tr, MX.engine_rejections(res), cal, industry, portfolio=True,
                           equity=res.equity, capital=CAPITAL)
            m |= meta
            m["tax"] = MX.tax_annex(m["net_inr"])
            m["paired_vs_A"] = MX.paired_diff(a, tr)
            rows.append(m)
        return rows

    # ---- metrics for both scopes ----
    scopes = {}
    for scope, dates in (("year", year_dates), ("replay", replay_dates)):
        runs, secondary = {}, {}
        for name in MX.MATRIX:
            runs[name] = scope_metrics(name, raw_trades[name], frames[name], dates, cal, industry, names,
                                       frames["A"], extremes=True)
        for name in MX.SECONDARY:
            secondary[name] = scope_metrics(name, raw_trades[name], frames[name], dates, cal, industry, names,
                                            frames["A"], extremes=False)
        secondary["S5_POOL"] = scope_metrics("S5_POOL", pool_trades, pool, dates, cal, industry, names,
                                             frames["A"], extremes=False)
        rows = engine_block(scope, dates)
        for letter in MX.PORTFOLIO:
            tag = BASELINE_TAG[letter]
            m = next((dict(r) for r in rows if r["config"] == tag), None)
            if m is None:
                raise RuntimeError(f"the pre-registered baseline {tag} produced no trades in scope {scope}")
            m["config"], m["variant"] = letter, tag
            m["extremes"] = MX.extremes(engine[(tag, scope)][1], names)
            runs[letter] = m
        rc = MX.random_control(draws[scope], pool, runs["A"]["net_per_trade"])
        gf = MX.random_frame(draws[scope], pool)
        g_rej = {}
        for draw in draws[scope]:
            for d, syms in draw.items():
                for sym in syms:
                    r = pool_reason.get((pd.Timestamp(d), sym))
                    if r is not None:
                        g_rej[r] = g_rej.get(r, 0) + 1
        runs["G"] = MX.metrics("G", gf, g_rej, cal, industry, exposure=False)
        runs["G"]["extremes"] = MX.extremes(gf, names)
        runs["G"] |= {"distribution": rc, "tax": MX.tax_annex(runs["G"]["net_inr"]),
                      "note": ("200 random 5-a-day selections from the same eligible pool under configuration A's "
                               "execution rules; the totals pool all 200 seeds, so only the per-trade figures and the "
                               "distribution are meaningful"),
                      "paired_vs_A": MX.paired_diff(frames["A"][frames["A"].decision_date.isin(set(pd.DatetimeIndex(dates)))],
                                                    gf.drop_duplicates(["decision_date", "symbol"]))}
        scopes[scope] = {"sessions": int(len(dates)), "runs": runs, "secondary": secondary,
                         "portfolio_variants": rows, "random_control": rc,
                         "rank_bands": MX.rank_bands(pool[pool.decision_date.isin(set(pd.DatetimeIndex(dates)))], ranked)}
        log(f"metrics for {scope} done")

    # ---- write ----
    files = {}

    def save(obj, name):
        path = os.path.join(out, name)
        if isinstance(obj, pd.DataFrame):
            obj.to_csv(path, index=False, **({"compression": {"method": "gzip", "mtime": 0}} if name.endswith(".gz") else {}))
        else:
            _dump(obj, path)
        files[name] = IN.sha256(path)

    for name, fr in frames.items():
        save(fr, f"trades_{name}.csv{'.gz' if name == 'S5_POOL' else ''}")
    for (tag, scope), (res, tr, meta) in engine.items():
        if scope == "year" and not tr.empty:
            save(tr, f"trades_engine_{tag.replace('|', '_').replace('.', '')}.csv")
    for letter in MX.PORTFOLIO:
        tag = f"{letter}|risk0.5|pos{8 if letter == 'F' else 'max'}"
        res = engine[(tag, "year")][0]
        save(res.equity.assign(date=res.equity.date.astype(str)), f"equity_{letter}.csv")
        save([d for d in res.decisions if d["decision_status"] == "REJECTED"][:5000], f"rejections_{letter}.json")
    results = {"run": stamp, "smoke": smoke, "code_commit": commit, "prereg": MX.PREREG, "cost_model": cm.cost_model_id,
               "capital_inr": CAPITAL, "inputs": fz["files"], "prediction_commit": fz["commit"],
               "bars_vs_dataset": match, "picks_reproduced": pick_check, "baseline_vs_d3": base,
               "replay_dates": [str(d.date()) for d in replay_dates],
               "specs": {k: str(v) for k, v in (list(MX.MATRIX.items()) + list(MX.SECONDARY.items()) + [("S5_POOL", MX.POOL)])},
               "exits": {k: str(v) for k, v in MX.EXITS.items()},
               "scopes": scopes, "files": files}
    _dump(results, os.path.join(out, "matrix_results.json"))
    _dump({"matrix_results.json": IN.sha256(os.path.join(out, "matrix_results.json")), **files},
          os.path.join(out, "manifest.json"))
    log("wrote", out)
    return out


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv[1:])
