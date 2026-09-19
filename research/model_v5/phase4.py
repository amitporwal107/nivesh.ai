"""Phase 4 development runs: groups A and B (PREREGISTRATION_P4_AB.md §4-§7, FROZEN at ac54c1b4) and groups C and D
(PREREGISTRATION_P4_CD.md §4-§5, FROZEN at 88455a35, which reuses this procedure unchanged with its own group set).

Arms B0 (44 v4 features), A (+16 regime) and B (+14 relative strength) use the M8 specification on the identical H#32
development rows, folds, embargo, eligibility, costs and seed; the M7 logistic runs as a secondary, descriptive model.
Before any arm result is computed, B0's out-of-fold tbs_5_2 predictions must equal the H#32 development file to 1e-12
(§4); otherwise the run stops. Keep/drop per group follows §7 exactly (K1 Holm across 4 tests at 0.025 one-sided,
K2 trading not worse pooled and in >= 3 of 4 folds, K3 no fold PR-AUC loss > 0.01).
Readings fixed before the run: the AUC bootstrap resamples 2022 decision days and weights rows by multiplicity; the
"lower bound after Holm" is the Holm decision on one-sided bootstrap p-values (share of resampled differences <= 0).
run (from this directory): /app/research/tpd3_forward/venv/bin/python phase4.py <dataset .csv.gz> <H#32 dev_oof .csv.gz> [ab|cd]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import features_p4 as FP  # noqa: E402
import features_p4cd as FC  # noqa: E402
import walkforward as WF  # noqa: E402

EXPERIMENTS = {"ab": {"groups": {"A": FP.GROUP_A, "B": FP.GROUP_B}, "prefix": "p4ab",
                      "preregistration": "PREREGISTRATION_P4_AB.md (FROZEN ac54c1b4)"},
               "cd": {"groups": {"C": FC.GROUP_C, "D": FC.GROUP_D}, "prefix": "p4cd",
                      "preregistration": "PREREGISTRATION_P4_CD.md (FROZEN 88455a35)"}}


def arms_for(experiment: str) -> dict:
    groups = EXPERIMENTS[experiment]["groups"]
    return {"B0": list(DS.FEATURES), **{g: list(DS.FEATURES) + list(cols) for g, cols in groups.items()}}


ARMS = arms_for("ab")
GROUPS = ("A", "B")
PRIMARY = {"tbs_5_2": "pr_auc", "up_given_move": "roc_auc"}
SECONDARY = ("dir_5_5d", "net_pos_5_2", "hit_high_10_5d")
AUC_REPS = 2000
TRADE_REPS = 10000
REPRO_TOL = 1e-12
PRED_FOLD_LOSS = 0.01


def join_features(ds: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    out = ds.merge(feats, on=["symbol", "date"], how="left", validate="1:1", indicator=True)
    if (out._merge != "both").any():
        raise RuntimeError(f"{int((out._merge != 'both').sum())} dataset rows have no Phase 4 feature row")
    out = out.drop(columns="_merge")
    if not (out[["date", "symbol"]].to_numpy() == ds[["date", "symbol"]].to_numpy()).all():
        raise RuntimeError("row order changed while joining features")
    return out


def fold_scores(ds, cal, cols, label, kind="hgb") -> pd.Series:
    """Out-of-fold scores over the four 2022 folds for one feature set and label."""
    parts = []
    for _, start, end in WF.FOLDS:
        train, valid = WF.fold_masks(ds, cal, start, end)
        y, ok = WF.target(ds, label)
        tr = train & ok
        model = WF.hgb() if kind == "hgb" else WF.logit(cols)
        _, s = WF._fit_predict(model, ds.loc[tr, cols], y[tr], ds.loc[valid, cols])
        parts.append(pd.Series(s, index=ds.index[valid]))
    return pd.concat(parts)


def check_reproduction(ds, b0_tbs: pd.Series, oof_path: str) -> float:
    ref = pd.read_csv(oof_path, usecols=["date", "symbol", "M8|tbs_5_2"], parse_dates=["date"])
    mine = ds.loc[b0_tbs.index, ["date", "symbol"]].assign(mine=b0_tbs.to_numpy())
    m = mine.merge(ref, on=["date", "symbol"], how="outer", validate="1:1", indicator=True)
    if (m._merge != "both").any():
        raise RuntimeError("B0 and the H#32 out-of-fold file cover different rows")
    diff = float((m.mine - m["M8|tbs_5_2"]).abs().max())
    if not diff <= REPRO_TOL:
        raise RuntimeError(f"B0 does not reproduce H#32 M8 (max |diff| {diff}); stopping before any arm result")
    return diff


def metric(name, y, s, w=None) -> float:
    return float(average_precision_score(y, s, sample_weight=w) if name == "pr_auc" else roc_auc_score(y, s, sample_weight=w))


def boot_auc_diff(y, s_arm, s_base, dates, name, reps=AUC_REPS, seed=WF.SEED) -> dict:
    """Paired date-clustered bootstrap of metric(arm) - metric(base): resample decision days, weight rows by multiplicity."""
    y, s_arm, s_base = np.asarray(y), np.asarray(s_arm, float), np.asarray(s_base, float)
    ud, inv = np.unique(np.asarray(dates), return_inverse=True)
    rng = np.random.default_rng(seed)
    d = np.empty(reps)
    for i in range(reps):
        w = np.bincount(rng.integers(0, len(ud), len(ud)), minlength=len(ud))[inv]
        m = w > 0
        d[i] = metric(name, y[m], s_arm[m], w[m]) - metric(name, y[m], s_base[m], w[m])
    point = metric(name, y, s_arm) - metric(name, y, s_base)
    return {"point": point, "lo95": float(np.percentile(d, 2.5)), "hi95": float(np.percentile(d, 97.5)),
            "p_le_0": float((d <= 0).mean())}


def decide(k1_holm: dict, trade: dict, folds_pr: dict, groups=GROUPS) -> dict:
    """§7 per group. k1_holm: {(group, label): holm row}; trade: {arm: {"pooled": x, "folds": [...]}};
    folds_pr: {arm: [PR-AUC per fold]}."""
    out = {}
    for g in groups:
        k1 = any(k1_holm[(g, lab)]["reject_null"] for lab in PRIMARY)
        better_folds = sum(a >= b for a, b in zip(trade[g]["folds"], trade["B0"]["folds"]))
        k2 = trade[g]["pooled"] >= trade["B0"]["pooled"] and better_folds >= 3
        k3 = all(a >= b - PRED_FOLD_LOSS for a, b in zip(folds_pr[g], folds_pr["B0"]))
        out[g] = {"K1": bool(k1), "K2": bool(k2), "K2_folds_not_worse": int(better_folds), "K3": bool(k3),
                  "verdict": "KEPT" if (k1 and k2 and k3) else "DROPPED"}
    return out


def audit_trades(ds, picks, bars, names, widen=0.004) -> dict:
    """Extreme-trade audit (owner rule): 10 best and 10 worst trades against the raw bars."""
    t = ds.loc[picks.index[picks.tradable.to_numpy(bool)]]
    pick = pd.concat([t.nlargest(10, "net_ret_5_2"), t.nsmallest(10, "net_ret_5_2")])
    b = bars.set_index(["symbol", "date"]).sort_index()
    fails = []
    for r in pick.itertuples():
        eb, xb = b.loc[(r.symbol, r.entry_date)], b.loc[(r.symbol, r.tbs_5_2_exit_date)]
        iss = []
        if not (eb.low * (1 - widen) <= r.entry_px <= eb.high * (1 + widen)):
            iss.append("A entry outside the bar")
        if not (xb.low * (1 - widen) <= r.tbs_5_2_exit_px <= xb.high * (1 + widen)):
            iss.append("B exit outside the bar")
        if eb.volume <= 0 or xb.volume <= 0:
            iss.append("C zero volume")
        w = b.loc[r.symbol]
        w = w[(w.index >= r.date) & (w.index <= r.tbs_5_2_exit_date)].close.to_numpy()
        if len(w) > 1 and (np.abs(w[1:] / w[:-1] - 1) > 0.20).any():
            iss.append("D close-to-close move above 20%")
        if "ETF" in str(names.get(r.symbol, "")).upper():
            iss.append("E ETF")
        if iss:
            fails.append({"symbol": r.symbol, "date": str(r.date.date()), "net": float(r.net_ret_5_2), "issues": iss})
    return {"checked": int(len(pick)), "failures": fails, "status": "INVALID" if fails else "CLEAN"}


def updown_top5pct(ds, score: pd.Series) -> dict:
    d = ds.loc[score.index]
    ok = d.tradable & d.dir_5_5d.isin(["UP", "DOWN", "NONE"])
    s = score[ok]
    top = d.loc[s.index[s >= s.quantile(0.95)]]
    up, dn = float((top.dir_5_5d == "UP").mean()), float((top.dir_5_5d == "DOWN").mean())
    return {"n": int(len(top)), "up": up, "down": dn, "up_share_of_moves": up / (up + dn) if up + dn else float("nan")}


def evaluate(ds, cal, S: dict, bars, names: dict, auc_reps: int = AUC_REPS, trade_reps: int = TRADE_REPS,
             arms: dict = ARMS, groups=GROUPS) -> dict:
    """§6-§7 on the fitted out-of-fold scores S = {(arm, label, kind): Series}. Returns the result sections plus
    "_picks" (the top-5 picks per arm), which the caller writes out."""
    # prediction quality: pooled and per fold
    fold_of = pd.Series(np.nan, index=ds.index, dtype=object)
    for name, start, end in WF.FOLDS:
        fold_of[(ds.date >= pd.Timestamp(start)) & (ds.date <= pd.Timestamp(end))] = name
    pred, folds_pr, boots = {}, {}, {}
    for (arm, label, kind), s in S.items():
        y, ok = WF.target(ds, label)
        use = s.index[ok[s.index].to_numpy(bool)]
        name = PRIMARY.get(label, "pr_auc")
        row = {"pooled_" + name: metric(name, y[use].to_numpy(), s[use].to_numpy()),
               "pooled_roc_auc": metric("roc_auc", y[use].to_numpy(), s[use].to_numpy()),
               "base_rate": float(y[use].mean()), "n": int(len(use)),
               "folds": {f: metric(name, y[use][fold_of[use] == f].to_numpy(), s[use][fold_of[use] == f].to_numpy()) for f, _, _ in WF.FOLDS}}
        pred.setdefault(kind, {}).setdefault(label, {})[arm] = row
        if kind == "hgb" and label == "tbs_5_2":
            folds_pr[arm] = [row["folds"][f] for f, _, _ in WF.FOLDS]
    res = {"prediction": pred}

    for g in groups:
        for label, name in PRIMARY.items():
            y, ok = WF.target(ds, label)
            sa, sb = S[(g, label, "hgb")], S[("B0", label, "hgb")]
            use = sa.index[ok[sa.index].to_numpy(bool)]
            boots[(g, label)] = boot_auc_diff(y[use].to_numpy(), sa[use].to_numpy(), sb[use].to_numpy(),
                                              ds.loc[use, "date"].to_numpy(), name, reps=auc_reps)
            print("bootstrap", g, label, boots[(g, label)], flush=True)
    holm = WF.holm({k: v["p_le_0"] for k, v in boots.items()})
    res["k1_bootstrap"] = {f"{g}|{lab}": v for (g, lab), v in boots.items()}
    res["k1_holm"] = {f"{g}|{lab}": v for (g, lab), v in holm.items()}

    # trading: top 5 a day on each arm's tbs_5_2 score
    dev_rows = ds.date >= pd.Timestamp(WF.FOLDS[0][1])
    picks = {arm: WF.top_k_picks(ds, S[(arm, "tbs_5_2", "hgb")], dev_rows, WF.SEED) for arm in arms}
    trade = {}
    for arm, p in picks.items():
        per_fold = []
        for f, start, end in WF.FOLDS:
            q = p[(p.date >= pd.Timestamp(start)) & (p.date <= pd.Timestamp(end))]
            per_fold.append(WF.trading_metrics(ds, q, cal)["mean_net"])
        full = {sc: WF.trading_metrics(ds, p, cal, sc) for sc in WF.NET_COLS}
        trade[arm] = {"pooled": full["base"]["mean_net"], "folds": per_fold, "scenarios": full}
    res["trading"] = trade
    res["trade_diff_boot"] = {g: WF.cluster_bootstrap(ds, picks[g], picks["B0"], reps=trade_reps) for g in groups}
    res["updown_top5pct_dir"] = {arm: updown_top5pct(ds, S[(arm, "dir_5_5d", "hgb")]) for arm in arms}

    res["decision"] = decide(holm, trade, folds_pr, groups)
    res["audit"] = {arm: audit_trades(ds, p, bars, names) for arm, p in picks.items()}

    res["_picks"] = picks
    return res


def main(dataset_path: str, oof_path: str, experiment: str = "ab", out_dir: str = DS.OUT) -> str:
    exp = EXPERIMENTS[experiment]
    arms, groups = arms_for(experiment), tuple(exp["groups"])
    dirty = WF._git("status", "--porcelain", "--", ".", os.path.join(DS.BACKEND, "nidp", "services", "tpd_model"))
    if dirty:
        raise RuntimeError(f"uncommitted changes; commit first:\n{dirty}")
    commit = WF._git("rev-parse", "HEAD")
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    blk = DS.BLOCKS["dev"]
    ds = WF.load(dataset_path)
    cal, _ = DS.load_calendar(blk)
    uni, _ = DS.universe()
    raw = DS.load_bars(set(uni.symbol), blk)
    bars = raw[raw.date.isin(cal)].sort_values(["symbol", "date"]).reset_index(drop=True)
    industry = dict(zip(uni.symbol, uni.industry))
    if experiment == "ab":
        feats = FP.build(bars, FP.load_index(blk), cal, industry, blk)
    else:
        feats = FC.build(bars, ds[["symbol", "date", "atr_pct"]], cal, industry, blk)
    ds = join_features(ds, feats)
    res = {"preregistration": exp["preregistration"], "experiment": experiment, "code_commit": commit, "run_started": stamp,
           "dataset": os.path.basename(dataset_path), "dataset_sha256": WF._sha256(dataset_path),
           "h32_oof": os.path.basename(oof_path), "h32_oof_sha256": WF._sha256(oof_path),
           "arms": {k: len(v) for k, v in arms.items()}}

    # §4 reproducibility gate first
    S = {("B0", "tbs_5_2", "hgb"): fold_scores(ds, cal, arms["B0"], "tbs_5_2")}
    res["b0_reproduction_max_abs_diff"] = check_reproduction(ds, S[("B0", "tbs_5_2", "hgb")], oof_path)
    print("B0 reproduces H#32:", res["b0_reproduction_max_abs_diff"], flush=True)
    WF.FIT_LOG.clear()

    for arm, cols in arms.items():
        for label in (*PRIMARY, *SECONDARY):
            if (arm, label, "hgb") not in S:
                S[(arm, label, "hgb")] = fold_scores(ds, cal, cols, label)
        for label in PRIMARY:
            S[(arm, label, "logit")] = fold_scores(ds, cal, cols, label, kind="logit")
        print("arm", arm, "fitted", dt.datetime.now().strftime("%H:%M:%S"), flush=True)
    res["fits_with_all_missing_columns"] = [{"n_train": n, "dropped": c} for n, c in WF.FIT_LOG]

    res.update(evaluate(ds, cal, S, bars, dict(zip(uni.symbol, uni.name)), arms=arms, groups=groups))
    picks = res.pop("_picks")

    oof = pd.DataFrame({f"{arm}|{label}|{kind}": s for (arm, label, kind), s in S.items()})
    oof = ds.loc[oof.index, ["date", "symbol"]].join(oof)
    oof_out = os.path.join(out_dir, f"{exp['prefix']}_oof_{stamp}.csv.gz")
    oof.to_csv(oof_out, index=False, compression={"method": "gzip", "mtime": 0})
    res["oof_file"], res["oof_sha256"] = os.path.basename(oof_out), WF._sha256(oof_out)
    for arm, p in picks.items():
        p.to_csv(os.path.join(out_dir, f"{exp['prefix']}_picks_{arm}_{stamp}.csv"))
    res["run_finished"] = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out = os.path.join(out_dir, f"{exp['prefix']}_results_{stamp}.json")
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(json.dumps(res["decision"]), flush=True)
    print(out, WF._sha256(out))
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "ab")
