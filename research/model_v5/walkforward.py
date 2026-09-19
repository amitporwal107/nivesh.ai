"""Roadmap v2 Phases 2-3, deliverable 2: the development walk-forward (M0-M9 on the four 2022 quarters), the isotonic
calibration fit and the final model fit that the locked test will use (PREREGISTRATION_P2_P3.md §2, §6-§7, FROZEN at
50fe02fd). Reads only the development dataset built by dataset.py (bars <= 2022-12-30, asserted again here).

Readings of the frozen text, fixed before any model was fitted (recorded in DEV_RESULTS.md for the owner checkpoint):
- Binary targets: hit_* labels as built; tbs_5_2 / tbs_10_4 = 1 if TARGET (criterion 6 is about the TARGET rate);
  net_pos_5_2 as built; dir_5_5d = 1 if UP vs DOWN or NONE (AMBIGUOUS rows excluded from fitting and scoring).
  net_ret_5_2 is the trading outcome, not a fitted label (M7 is a logistic model, so every label is a class).
- Training and scoring rows: eligible on D with an entry on s1. Selection for trading happens at D's close, before the
  open is known, so the top 5 are chosen among all eligible rows and a pick without an entry is a missed slot (counted).
- Embargo: a training row's labels end 5 sessions after D, so training rows stop 6 calendar sessions before the fold.
- M9: stage 1 = M8 on big_move = hit_high_10_5d or hit_low_10_5d; its out-of-fold predictions on the training window
  come from 4 contiguous time blocks with a 5-session purge on both sides; stage 2 = M8 on UP vs DOWN, fitted on rows
  that moved (dir_5_5d in {UP, DOWN}) with the stage-1 OOF prediction as a 45th feature; score = P1 x P2.
- M1 = one seeded random draw of scores; M5 and M6 give every stock (M5) or every stock in a sector (M6) the same
  score on a day, so their top 5 is decided by the seeded tie-break; this is reported, not hidden.
- Ranking uses the raw scores; isotonic calibration (fitted on the pooled 2022 out-of-fold predictions) is applied for
  probability reporting and criterion 6 only, because its flat steps would create ties.
- LogisticRegression max_iter = 2000 (a solver setting so that it converges, not a tuned hyperparameter).
- Bootstrap: 10,000 resamples of decision days, seed 20260919; "95% lower bound" = the 2.5th percentile; Holm on the
  one-sided bootstrap p-values at 0.025.
run (from this directory): /app/research/tpd3_forward/venv/bin/python walkforward.py <dataset .csv.gz>
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pickle
import subprocess
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402

SEED = 20260919
EMBARGO = 5
TOP_K = 5
SLEEVES = TOP_K * 5                      # at most 5 new trades a day, each held up to 5 sessions
BOOT_REPS = 10000
FOLDS = (("2022Q1", "2022-01-01", "2022-03-31"), ("2022Q2", "2022-04-01", "2022-06-30"),
         ("2022Q3", "2022-07-01", "2022-09-30"), ("2022Q4", "2022-10-01", "2022-12-22"))
LABELS = ("hit_high_5_1d", "hit_high_5_3d", "hit_high_5_5d", "hit_high_10_5d", "hit_close_5_5d", "hit_close_10_5d",
          "tbs_5_2", "tbs_10_4", "net_pos_5_2", "dir_5_5d")
PRIMARY = "tbs_5_2"
FEATURES = list(DS.FEATURES)
MARKET = ["mkt_ret1", "breadth"]
NET_COLS = {"opt": "net_ret_5_2_opt", "base": "net_ret_5_2", "cons": "net_ret_5_2_cons"}
PROBABILISTIC = ("M0", "M4", "M5", "M6", "M7", "M8", "M9")
TRADED = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")


# ---------- data ----------

def load(path: str) -> pd.DataFrame:
    ds = pd.read_csv(path, parse_dates=["date", "entry_date", "label_end_date", "tbs_5_2_exit_date", "tbs_10_4_exit_date"],
                     low_memory=False)
    return prepare(ds)


def prepare(ds: pd.DataFrame) -> pd.DataFrame:
    dev = DS.BLOCKS["dev"]
    if ds.label_end_date.max() > pd.Timestamp(dev.bar_end) or ds.date.max() > pd.Timestamp(dev.feat_end):
        raise DS.SealedDataError("the walk-forward reads the development block only")
    ds = ds.assign(eligible=ds.eligible.astype(bool))
    ds["tradable"] = ds.eligible & (ds.entry_status == "OK")
    return ds.sort_values(["date", "symbol"]).reset_index(drop=True)


def target(ds: pd.DataFrame, label: str) -> tuple[pd.Series, pd.Series]:
    """(y, usable) for a label: usable = tradable and the label is defined (dir: not AMBIGUOUS)."""
    if label in ("tbs_5_2", "tbs_10_4"):
        y, ok = (ds[label] == "TARGET").astype(float), ds[label].notna()
    elif label == "dir_5_5d":
        y, ok = (ds[label] == "UP").astype(float), ds[label].isin(["UP", "DOWN", "NONE"])
    elif label == "big_move_10_5d":
        y, ok = ((ds.hit_high_10_5d == 1) | (ds.hit_low_10_5d == 1)).astype(float), ds.hit_high_10_5d.notna()
    elif label == "up_given_move":
        y, ok = (ds.dir_5_5d == "UP").astype(float), ds.dir_5_5d.isin(["UP", "DOWN"])
    else:
        y, ok = ds[label].astype(float), ds[label].notna()
    return y, ok & ds.tradable


def fold_masks(ds: pd.DataFrame, cal: pd.DatetimeIndex, start: str, end: str) -> tuple[pd.Series, pd.Series]:
    first = cal[cal.searchsorted(pd.Timestamp(start))]
    last_train = cal[cal.get_loc(first) - EMBARGO - 1]
    return ds.date <= last_train, (ds.date >= pd.Timestamp(start)) & (ds.date <= pd.Timestamp(end))


# ---------- models ----------

def hgb():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                          early_stopping=False, random_state=SEED)


def logit(cols):
    num = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler())
    return make_pipeline(ColumnTransformer([("num", num, cols)]), LogisticRegression(C=1.0, max_iter=2000))


def sector_logit():
    return make_pipeline(ColumnTransformer([("ind", OneHotEncoder(handle_unknown="ignore"), ["industry"])]),
                         LogisticRegression(C=1.0, max_iter=2000))


FIT_LOG: list = []           # (n_train, columns dropped because they were never observed in the training rows)


def _fit_predict(model, Xtr, ytr, Xva):
    """Fit and score. A gradient-boosting fit drops a column that is entirely missing in its training rows (a feature
    needing 251 bars does not exist in 2021): the model could not split on it anyway, and scikit-learn's binner fails on
    it. Each drop is logged; the fitted model keeps its columns in feature_names_in_. The logistic pipelines' median
    imputer drops such a column itself."""
    if ytr.nunique() < 2:
        raise ValueError("a training set has a single class")
    if isinstance(model, HistGradientBoostingClassifier):
        empty = [c for c in Xtr.columns if Xtr[c].isna().all()]
        if empty:
            FIT_LOG.append((int(len(Xtr)), empty))
            Xtr, Xva = Xtr.drop(columns=empty), Xva.drop(columns=empty)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        model.fit(Xtr, ytr)
        return model, model.predict_proba(Xva)[:, 1]


def purged_oof(ds, cal, rows: pd.Series, label: str, blocks: int = 4) -> pd.Series:
    """Out-of-fold M8 predictions for `label` on `rows`: contiguous date blocks, 5-session purge on both sides."""
    y, ok = target(ds, label)
    use = rows & ok
    dates = np.sort(ds.loc[use, "date"].unique())
    out = pd.Series(np.nan, index=ds.index)
    for part in np.array_split(dates, blocks):
        lo, hi = pd.Timestamp(part[0]), pd.Timestamp(part[-1])
        lo_i, hi_i = cal.get_loc(lo), cal.get_loc(hi)
        purge_lo = cal[lo_i - EMBARGO - 1] if lo_i - EMBARGO - 1 >= 0 else cal[0] - pd.Timedelta(days=1)
        purge_hi = cal[hi_i + EMBARGO + 1] if hi_i + EMBARGO + 1 < len(cal) else cal[-1] + pd.Timedelta(days=1)
        held = use & (ds.date >= lo) & (ds.date <= hi)
        train = use & ((ds.date <= purge_lo) | (ds.date >= purge_hi))
        _, p = _fit_predict(hgb(), ds.loc[train, FEATURES], y[train], ds.loc[held, FEATURES])
        out[held] = p
    return out


def two_stage(ds, cal, train: pd.Series, score_rows: pd.Series):
    """M9 fitted on `train`; returns (score on score_rows, fitted stage-1 model, fitted stage-2 model)."""
    y1, ok1 = target(ds, "big_move_10_5d")
    oof = purged_oof(ds, cal, train, "big_move_10_5d")
    m1, p1 = _fit_predict(hgb(), ds.loc[train & ok1, FEATURES], y1[train & ok1], ds.loc[score_rows, FEATURES])
    y2, ok2 = target(ds, "up_given_move")
    t2 = train & ok2 & oof.notna()
    X2 = ds.loc[t2, FEATURES].assign(p_big=oof[t2])
    Xs = ds.loc[score_rows, FEATURES].assign(p_big=p1)
    m2, p2 = _fit_predict(hgb(), X2, y2[t2], Xs)
    return pd.Series(p1 * p2, index=ds.index[score_rows]), m1, m2


def model_scores(ds, cal, train: pd.Series, score_rows: pd.Series, rng, labels=LABELS) -> tuple[dict, dict]:
    """Scores of every model on `score_rows` after fitting on `train`: {(model, label): Series}, plus fitted models."""
    S, fitted = {}, {}
    idx = ds.index[score_rows]
    Xs = ds.loc[score_rows]
    y4, ok4 = target(ds, "hit_high_10_5d")
    m4, s4 = _fit_predict(hgb(), ds.loc[train & ok4, FEATURES], y4[train & ok4], Xs[FEATURES])
    fitted["M4"] = m4
    s9, m9a, m9b = two_stage(ds, cal, train, score_rows)
    fitted["M9_stage1"], fitted["M9_stage2"] = m9a, m9b
    r = pd.Series(rng.random(len(idx)), index=idx)
    for label in labels:
        y, ok = target(ds, label)
        tr = train & ok
        S[("M0", label)] = pd.Series(float(y[tr].mean()), index=idx)
        S[("M1", label)] = r
        S[("M2", label)] = Xs["ret20"]
        S[("M3", label)] = Xs["atr_pct"]
        S[("M4", label)] = pd.Series(s4, index=idx)
        m5, s5 = _fit_predict(logit(MARKET), ds.loc[tr, MARKET], y[tr], Xs[MARKET])
        m6, s6 = _fit_predict(sector_logit(), ds.loc[tr, ["industry"]], y[tr], Xs[["industry"]])
        m7, s7 = _fit_predict(logit(FEATURES), ds.loc[tr, FEATURES], y[tr], Xs[FEATURES])
        m8, s8 = _fit_predict(hgb(), ds.loc[tr, FEATURES], y[tr], Xs[FEATURES])
        for name, m, s in (("M5", m5, s5), ("M6", m6, s6), ("M7", m7, s7), ("M8", m8, s8)):
            S[(name, label)] = pd.Series(s, index=idx)
            fitted[f"{name}__{label}"] = m
        S[("M9", label)] = s9
    return S, fitted


# ---------- evaluation ----------

def prediction_metrics(y: np.ndarray, s: np.ndarray, probabilistic: bool) -> dict:
    s = np.asarray(s, float)
    if np.isnan(s).any():                            # a rule with a missing input ranks last
        s = np.where(np.isnan(s), np.nanmin(s) - 1, s)
    n, base = len(y), float(y.mean())
    out = {"n": int(n), "base_rate": base}
    if 0 < y.sum() < n and np.unique(s).size > 1:
        out["pr_auc"], out["roc_auc"] = float(average_precision_score(y, s)), float(roc_auc_score(y, s))
    else:
        out["pr_auc"], out["roc_auc"] = base, 0.5
    if probabilistic:
        out["brier"] = float(brier_score_loss(y, np.clip(s, 0, 1)))
    order = np.argsort(-s, kind="stable")
    for q in (0.01, 0.05, 0.10):
        k = max(1, int(round(q * n)))
        prec = float(y[order[:k]].mean())
        out[f"precision_top{int(q * 100)}"] = prec
        out[f"lift_top{int(q * 100)}"] = prec / base if base > 0 else float("nan")
    return out


def reliability(y: np.ndarray, p: np.ndarray, edges=(0, .02, .05, .1, .15, .2, .3, .4, .5, .7, 1.0001)) -> list:
    rows = []
    b = np.digitize(p, edges) - 1
    for i in range(len(edges) - 1):
        m = b == i
        if m.any():
            rows.append({"bucket": f"{edges[i]:.2f}-{min(edges[i + 1], 1):.2f}", "n": int(m.sum()),
                         "mean_pred": float(p[m].mean()), "realised": float(y[m].mean()),
                         "gap_pts": float(100 * abs(p[m].mean() - y[m].mean()))})
    return rows


def top_k_picks(ds: pd.DataFrame, score: pd.Series, rows: pd.Series, rng_seed: int, k: int = TOP_K) -> pd.DataFrame:
    """Top k per decision day among eligible rows (entry unknown at selection); ties broken by a seeded draw."""
    pool = ds.loc[rows & ds.eligible, ["date", "symbol", "entry_status", "industry", "tradable"]].copy()
    pool["score"] = score.reindex(pool.index)
    pool["tie"] = np.random.default_rng(rng_seed).random(len(pool))
    pool = pool.sort_values(["date", "score", "tie"], ascending=[True, False, True], na_position="last")
    return pool.groupby("date", sort=True).head(k)


def trading_metrics(ds: pd.DataFrame, picks: pd.DataFrame, cal: pd.DatetimeIndex, scenario: str = "base") -> dict:
    t = ds.loc[picks.index[picks.tradable.to_numpy(bool)]]
    r = t[NET_COLS[scenario]].to_numpy(float)
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    nan = float("nan")
    out = {"picks": int(len(picks)), "trades": int(len(t)), "missed_no_entry": int((~picks.tradable.astype(bool)).sum()),
           "mean_net": float(r.mean()) if len(r) else nan, "median_net": float(np.median(r)) if len(r) else nan,
           "win_rate": float((r > 0).mean()) if len(r) else nan,
           "profit_factor": float(wins / losses) if losses > 0 else nan,
           "target_rate": float((t.tbs_5_2 == "TARGET").mean()) if len(t) else nan,
           "stop_rate": float((t.tbs_5_2 == "STOP").mean()) if len(t) else nan}
    if not len(t):
        return out
    # Daily portfolio on a realised basis: each trade gets 1/SLEEVES of capital and books its net P&L on its exit day.
    days = cal[(cal >= picks.date.min()) & (cal <= t.tbs_5_2_exit_date.max())]
    pnl = t.groupby("tbs_5_2_exit_date")[NET_COLS[scenario]].sum().reindex(days, fill_value=0.0) / SLEEVES
    eq = (1 + pnl).cumprod()
    out["portfolio_return"] = float(eq.iloc[-1] - 1)
    out["max_drawdown"] = float((1 - eq / eq.cummax()).max())
    held = np.zeros(len(days))
    pos = {d: i for i, d in enumerate(days)}
    for e, x in zip(t.entry_date, t.tbs_5_2_exit_date):
        held[pos[e]:pos[x] + 1] += 1
    out["exposure"] = float(held.mean() / SLEEVES)
    out["turnover_trades_per_session"] = float(len(t) / max(1, picks.date.nunique()))
    return out


def cluster_bootstrap(ds, picks_a, picks_b=None, scenario="base", reps=BOOT_REPS, seed=SEED) -> dict:
    """Date-clustered bootstrap of mean net per trade (A) or of mean(A) - mean(B), resampling decision days."""
    col = NET_COLS[scenario]

    def per_day(p, days):
        t = ds.loc[p.index[p.tradable.to_numpy(bool)], ["date", col]]
        g = t.groupby("date")[col]
        return g.sum().reindex(days, fill_value=0).to_numpy(float), g.size().reindex(days, fill_value=0).to_numpy(float)

    days = sorted(set(picks_a.date) | (set(picks_b.date) if picks_b is not None else set()))
    sa, na = per_day(picks_a, days)
    draws = np.random.default_rng(seed).integers(0, len(days), size=(reps, len(days)))
    stat = sa[draws].sum(1) / np.maximum(na[draws].sum(1), 1)
    point = sa.sum() / max(na.sum(), 1)
    if picks_b is not None:
        sb, nb = per_day(picks_b, days)
        stat = stat - sb[draws].sum(1) / np.maximum(nb[draws].sum(1), 1)
        point -= sb.sum() / max(nb.sum(), 1)
    return {"point": float(point), "lo95": float(np.percentile(stat, 2.5)), "hi95": float(np.percentile(stat, 97.5)),
            "p_le_0": float((stat <= 0).mean())}


def holm(pvals: dict, alpha: float = 0.025) -> dict:
    """Holm step-down on one-sided bootstrap p-values; alpha 0.025 matches the 2.5th-percentile lower bound."""
    out, still = {}, True
    for i, k in enumerate(sorted(pvals, key=pvals.get)):
        thr = alpha / (len(pvals) - i)
        still = still and pvals[k] <= thr
        out[k] = {"p": pvals[k], "threshold": thr, "reject_null": bool(still)}
    return out


def conditional(ds, picks) -> dict:
    t = ds.loc[picks.index[picks.tradable.to_numpy(bool)]].copy()
    q = ds.loc[ds.tradable, "atr_pct"].quantile([1 / 3, 2 / 3]).to_numpy()
    t["vol_tercile"] = np.digitize(t.atr_pct, q)
    t["gap_bucket"] = pd.cut(t.gap_s1, [-np.inf, -0.01, 0, 0.01, np.inf], labels=["<-1%", "-1..0%", "0..1%", ">1%"])
    out = {}
    for col in ("mkt_above200", "industry", "vol_tercile", "slip_pct", "gap_bucket"):
        g = t.groupby(col, observed=True).net_ret_5_2
        out[col] = {str(k): {"n": int(v.size), "mean_net": float(v.mean()), "sum_net": float(v.sum())} for k, v in g}
    return out


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(path: str, out_dir: str = DS.OUT) -> str:
    dirty = _git("status", "--porcelain", "--", ".", os.path.join(DS.BACKEND, "nidp", "services", "tpd_model"))
    if dirty:
        raise RuntimeError(f"uncommitted changes; commit first:\n{dirty}")
    commit = _git("rev-parse", "HEAD")
    ds = load(path)
    cal, idx_close = DS.load_calendar(DS.BLOCKS["dev"])
    rng = np.random.default_rng(SEED)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    res = {"dataset": os.path.basename(path), "dataset_sha256": _sha256(path), "code_commit": commit, "seed": SEED,
           "folds": {}, "run_started": stamp}
    oof = {}
    for name, start, end in FOLDS:
        train, valid = fold_masks(ds, cal, start, end)
        S, _ = model_scores(ds, cal, train, valid, rng)
        res["folds"][name] = {"train_rows": int((train & ds.tradable).sum()), "valid_rows": int((valid & ds.tradable).sum()),
                              "last_train_date": str(ds.loc[train, "date"].max().date())}
        for k, s in S.items():
            oof.setdefault(k, []).append(s)
        print(name, res["folds"][name], dt.datetime.now().strftime("%H:%M:%S"), flush=True)
    oof = {k: pd.concat(v) for k, v in oof.items()}
    dev_rows = ds.date >= pd.Timestamp(FOLDS[0][1])

    # prediction quality (pooled 2022 out-of-fold) and isotonic calibration
    pred, calib, rel = {}, {}, {}
    for (m, label), s in oof.items():
        y, ok = target(ds, label)
        use = s.index[ok[s.index].to_numpy(bool)]
        yy, ss = y[use].to_numpy(), s[use].to_numpy(float)
        pred.setdefault(label, {})[m] = prediction_metrics(yy, ss, m in PROBABILISTIC)
        if m in PROBABILISTIC and m != "M0":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(ss, yy)
            calib[(m, label)] = iso
            if label == PRIMARY or m == "M8":
                rel.setdefault(label, {})[m] = {"raw": reliability(yy, ss), "calibrated_in_sample": reliability(yy, iso.predict(ss))}
    res["prediction"], res["reliability"] = pred, rel

    # trading: top 5 a day on each model's score for the primary label (M2/M3 rules, M4 its movement score)
    picks = {m: top_k_picks(ds, oof[(m, PRIMARY)], dev_rows, SEED) for m in TRADED}
    res["trading"] = {m: {sc: trading_metrics(ds, p, cal, sc) for sc in NET_COLS} for m, p in picks.items()}
    alle = ds.loc[dev_rows & ds.tradable]
    res["trading"]["ALL_ELIGIBLE"] = {"trades": int(len(alle)), "mean_net": float(alle.net_ret_5_2.mean()),
                                      "target_rate": float((alle.tbs_5_2 == "TARGET").mean())}
    ic = idx_close[(idx_close.index >= pd.Timestamp("2021-12-31")) & (idx_close.index <= pd.Timestamp("2022-12-30"))]
    res["benchmark_nifty500_buy_hold_2022"] = float(ic.iloc[-1] / ic.iloc[0] - 1)

    # H#32 criteria on the development out-of-fold run (descriptive: the decision is on the locked test only)
    m8 = picks["M8"]
    comps = {c: cluster_bootstrap(ds, m8, picks[c]) for c in ("M1", "M2", "M4")}
    tr8 = ds.loc[m8.index[m8.tradable.to_numpy(bool)]]
    y, ok = target(ds, PRIMARY)
    s8 = oof[("M8", PRIMARY)]
    use = s8.index[ok[s8.index].to_numpy(bool)]
    rel8 = reliability(y[use].to_numpy(), calib[("M8", PRIMARY)].predict(s8[use].to_numpy(float)))
    res["h32_dev_descriptive"] = {
        "c1_mean_net_boot": cluster_bootstrap(ds, m8),
        "c2_vs": comps, "c2_holm": holm({c: v["p_le_0"] for c, v in comps.items()}),
        "c3_mean_net_conservative": res["trading"]["M8"]["cons"]["mean_net"],
        "c4_halves_mean_net": [trading_metrics(ds, m8[m8.date < pd.Timestamp("2022-07-01")], cal)["mean_net"],
                               trading_metrics(ds, m8[m8.date >= pd.Timestamp("2022-07-01")], cal)["mean_net"]],
        "c5_net_pnl_by_sector": {"total": float(tr8.net_ret_5_2.sum()),
                                 "by_sector": tr8.groupby("industry").net_ret_5_2.sum().sort_values().to_dict()},
        "c6_calibration_in_sample_buckets_ge100": [r for r in rel8 if r["n"] >= 100],
    }
    res["conditional_M8"] = conditional(ds, m8)
    res["fold_fits_with_all_missing_columns"] = [{"n_train": n, "dropped": c} for n, c in FIT_LOG]
    FIT_LOG.clear()
    print("evaluation done", dt.datetime.now().strftime("%H:%M:%S"), flush=True)

    # final models on every development row (D <= 2022-12-22), frozen for the locked test
    _, fitted = model_scores(ds, cal, pd.Series(True, index=ds.index), ds.date == ds.date.max(), np.random.default_rng(SEED))
    mdir = os.path.join(out_dir, f"models_{stamp}")
    os.makedirs(mdir, exist_ok=True)
    files = {}
    for key, obj in list(fitted.items()) + [(f"iso__{m}__{label}", v) for (m, label), v in calib.items()]:
        p = os.path.join(mdir, f"{key}.pkl")
        with open(p, "wb") as fh:
            pickle.dump(obj, fh)
        files[f"{key}.pkl"] = _sha256(p)
    res["models_dir"], res["model_files"] = mdir, files
    res["final_fits_with_all_missing_columns"] = [{"n_train": n, "dropped": c} for n, c in FIT_LOG]

    oof_df = pd.DataFrame({f"{m}|{label}": s for (m, label), s in oof.items()})
    oof_df = ds.loc[oof_df.index, ["date", "symbol"]].join(oof_df)
    oof_path = os.path.join(out_dir, f"dev_oof_{stamp}.csv.gz")
    oof_df.to_csv(oof_path, index=False, compression={"method": "gzip", "mtime": 0})
    res["oof_file"], res["oof_sha256"] = os.path.basename(oof_path), _sha256(oof_path)
    for m, p in picks.items():
        p.to_csv(os.path.join(out_dir, f"dev_picks_{m}_{stamp}.csv"))
    res["run_finished"] = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out = os.path.join(out_dir, f"dev_results_{stamp}.json")
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(out, _sha256(out))
    return out


if __name__ == "__main__":
    main(sys.argv[1])
