"""W3 walk-forward runner: point-in-time rows from read-only exports -> 12 monthly folds x 4 heads + comparators.

Evaluation against the locked bars lives in evaluate.py; this module only produces out-of-sample predictions,
and refuses to start unless thresholds_lock.json is present.

    python -m nidp.services.tpd_model.backtest --exports <dir> --ca-csv <tpd_ca_history.csv> --out <dir>

<dir> holds panel.csv.gz (prices_eod EQ + NSE delivery), etfs.csv, events.csv (results meetings) — the
COPY ... TO STDOUT exports used for W2c.
"""
from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import time
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nidp.services.price_adjuster.factors import build_events

from .design import HEADS, MODEL_COLUMNS, OWN_HISTORY_COUNT, design_matrix
from .features import compute_features
from .labels import build_labels
from .panel_source import select_nse_eq
from .report import LOCK_PATH, load_lock
from .walkforward import SingleFeatureLogit, fit_gbm, month_folds, scored_rows, training_rows

logger = logging.getLogger(__name__)

WARMUP_BARS = 60
PRICE_EVENT_TYPES = {"SPLIT", "BONUS", "RIGHTS", "DEMERGER", "CAPITAL_REDUCTION", "MERGER"}
# NSE circuit rules make a 40% overnight gap impossible for a traded stock; an open that far from the prior
# close is an unrecorded split, bonus or consolidation.
SUSPECT_GAP = (0.6, 1.6)


def universe_by_session(panel: pd.DataFrame, sessions: list[date], n: int = 1000, lookback: int = 126,
                        min_bars: int = 100) -> dict[date, list[str]]:
    """pit_universe for many target sessions at once: rolling median turnover over the `lookback` market
    sessions before each date, `min_bars` present, top `n`, ties by symbol."""
    wide = panel.pivot_table(index="as_of_date", columns="symbol", values="turnover", aggfunc="first").sort_index()
    roll = wide.rolling(lookback, min_periods=1)
    median = roll.median().shift(1)
    count = wide.notna().astype(float).rolling(lookback, min_periods=1).sum().shift(1)
    out = {}
    for D in sessions:
        t = pd.Timestamp(D)
        m = median.loc[t][count.loc[t] >= min_bars].dropna()
        ranked = pd.DataFrame({"symbol": m.index, "median": m.to_numpy()}).sort_values(
            ["median", "symbol"], ascending=[False, True], kind="mergesort")
        out[D] = ranked["symbol"].head(n).tolist()
    return out


def corporate_actions_from_archive(ca: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(price factors for features, label exclusions). Factors come from price_adjuster.factors so the model
    adjusts exactly as the production adjuster does (SPLIT/BONUS; rights need a subscription price and are
    skipped there). Labels are excluded around every price-changing action, including the skipped ones."""
    recs = []
    for r in ca.to_dict("records"):
        r = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()}
        r["ex_date"] = pd.Timestamp(r["ex_date"]).date()
        recs.append(r)
    events = build_events(recs, prev_close_lookup=lambda *_: None)
    factors = pd.DataFrame([{"symbol": e.symbol, "ex_date": pd.Timestamp(e.ex_date), "factor": e.pret_factor}
                            for e in events if e.action_type in ("SPLIT", "BONUS")],
                           columns=["symbol", "ex_date", "factor"])
    excl = ca[ca["action_type"].isin(PRICE_EVENT_TYPES)][["symbol", "ex_date"]].copy()
    excl["ex_date"] = pd.to_datetime(excl["ex_date"])
    return factors, excl.drop_duplicates().reset_index(drop=True)


def suspected_actions(panel: pd.DataFrame, known: pd.DataFrame) -> pd.DataFrame:
    p = panel.sort_values(["symbol", "as_of_date"], kind="mergesort")
    prev_close = p.groupby("symbol")["close"].shift(1)
    gap = p["open"] / prev_close
    hit = p[(gap <= SUSPECT_GAP[0]) | (gap >= SUSPECT_GAP[1])][["symbol", "as_of_date"]]
    hit = hit.rename(columns={"as_of_date": "ex_date"})
    known_keys = set(zip(known["symbol"], pd.to_datetime(known["ex_date"])))
    keep = [(s, d) not in known_keys for s, d in zip(hit["symbol"], hit["ex_date"])]
    return hit[keep].reset_index(drop=True)


def assemble_rows(features: pd.DataFrame, labels: pd.DataFrame, universe: dict, sessions: list[date],
                  warmup: int = WARMUP_BARS, labels5: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """One modelling row per (symbol, T): features at T, membership of the universe for the target session,
    horizon ends in market sessions, and float labels (NaN where excluded). `labels5` (build_labels(pct=5)) adds
    the v4 one-day 5% labels y_p_up5_1d / y_p_down5_1d."""
    idx = pd.DatetimeIndex(sorted(sessions))
    pos = {t: i for i, t in enumerate(idx)}
    f = features[features["nbars"] >= warmup].copy()
    i = f["as_of_date"].map(pos)
    f["target_session"] = [idx[k + 1] if k + 1 < len(idx) else pd.NaT for k in i]
    f["horizon_end_1d"] = f["target_session"]
    f["horizon_end_5d"] = [idx[k + 5] if k + 5 < len(idx) else pd.NaT for k in i]
    member = [pd.notna(t) and sym in universe.get(t.date(), ()) for sym, t in zip(f["symbol"], f["target_session"])]
    f = f[member]
    lab = labels[["symbol", "as_of_date", "up_1d", "down_1d", "up_5d", "down_5d"]].copy()
    for src, head in (("up_1d", "p_up10_1d"), ("down_1d", "p_down10_1d"), ("up_5d", "p_up10_5d"), ("down_5d", "p_down10_5d")):
        lab[f"y_{head}"] = lab[src].map(lambda v: np.nan if v is None or (isinstance(v, float) and np.isnan(v)) else float(v))
    lab = lab.drop(columns=["up_1d", "down_1d", "up_5d", "down_5d"])
    if labels5 is not None:
        l5 = labels5[["symbol", "as_of_date", "up_1d", "down_1d"]].copy()
        for src, head in (("up_1d", "p_up5_1d"), ("down_1d", "p_down5_1d")):
            l5[f"y_{head}"] = l5[src].map(lambda v: np.nan if v is None or (isinstance(v, float) and np.isnan(v)) else float(v))
        lab = lab.merge(l5.drop(columns=["up_1d", "down_1d"]), on=["symbol", "as_of_date"], how="left")
    out = f.merge(lab, on=["symbol", "as_of_date"], how="left")
    return out.sort_values(["as_of_date", "symbol"], kind="mergesort").reset_index(drop=True)


def run_walkforward(rows: pd.DataFrame, sessions: list[date], first: date = date(2025, 9, 1),
                    last: date = date(2026, 8, 31), lock_path: Path = LOCK_PATH, heads=HEADS,
                    cap_months: int = 18, columns: tuple = MODEL_COLUMNS, return_models: bool = False):
    """`columns` selects the model version's inputs (v2: MODEL_COLUMNS, v3: MODEL_COLUMNS_V3)."""
    load_lock(lock_path)  # no lock, no run
    out, models = [], {}
    for fold in month_folds(sessions, first, last, cap_months):
        up = training_rows(rows, fold, "p_up10_1d")["y_p_up10_1d"].mean()
        dn = training_rows(rows, fold, "p_down10_1d")["y_p_down10_1d"].mean()
        priors = {"p_up10_1d": float(up), "p_down10_1d": float(dn)}
        sc = scored_rows(rows, fold)
        Xsc = design_matrix(sc, priors, columns)
        for head in heads:
            t0 = time.time()
            tr = training_rows(rows, fold, head)
            y = tr[f"y_{head}"].astype(int)
            Xtr = design_matrix(tr, priors, columns)
            gbm = fit_gbm(Xtr, y)
            models.setdefault(fold.month, {})[head] = gbm
            atr = SingleFeatureLogit("log_atr_pct").fit(Xtr, y)
            own = SingleFeatureLogit(f"lr_{OWN_HISTORY_COUNT[head]}").fit(Xtr, y)
            horizon = "horizon_end_1d" if head.endswith("_1d") else "horizon_end_5d"
            out.append(pd.DataFrame({
                "head": head, "month": fold.month, "symbol": sc["symbol"].to_numpy(),
                "as_of_date": sc["as_of_date"].to_numpy(), "target_session": sc["target_session"].to_numpy(),
                "y": sc[f"y_{head}"].to_numpy(), "p_tpd3": gbm.predict_proba(Xsc.astype(np.float64))[:, 1],
                "p_base_rate": float(y.mean()), "p_atr_only": atr.predict(Xsc), "p_own_history_only": own.predict(Xsc),
                "train_rows": len(tr), "train_events": int(y.sum()), "train_start": pd.Timestamp(fold.train_start),
                "train_end_max_horizon": tr[horizon].max(),
            }))
            logger.info("fold %s %s: %d train rows, %d events, %d scored, %.1fs",
                        fold.month, head, len(tr), int(y.sum()), len(sc), time.time() - t0)
    preds = pd.concat(out, ignore_index=True)
    return {"predictions": preds, "models": models} if return_models else preds


_G: dict = {}


def _features_for(args):
    T, D = args
    f = compute_features(_G["panel"], T, events=_G["events"], actions=_G["factors"], target_session=D)
    return f.reset_index().assign(as_of_date=pd.Timestamp(T))


def feature_cache(panel, events, factors, pairs, workers: int = 3) -> pd.DataFrame:
    _G.update(panel=panel, events=events, factors=factors)
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        parts = []
        for k, part in enumerate(pool.imap(_features_for, pairs, chunksize=4)):
            parts.append(part)
            if k % 50 == 0:
                logger.info("features: %d/%d sessions", k + 1, len(pairs))
    return pd.concat(parts, ignore_index=True)


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exports", type=Path, required=True)
    ap.add_argument("--ca-csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    lock, sha = load_lock()
    a.out.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(a.exports / "panel.csv.gz", parse_dates=["as_of_date"])
    panel = select_nse_eq(raw, set(pd.read_csv(a.exports / "etfs.csv")["symbol"]))
    events = pd.read_csv(a.exports / "events.csv", parse_dates=["event_date"])
    events["intimated_at"] = pd.to_datetime(events["intimated_at"], utc=True).dt.tz_convert("Asia/Kolkata")
    sessions = sorted(panel["as_of_date"].dt.date.unique())

    factors, known = corporate_actions_from_archive(pd.read_csv(a.ca_csv))
    suspects = suspected_actions(panel, known)
    exclusions = pd.concat([known, suspects], ignore_index=True)
    labels = build_labels(panel, exclusions)

    last_T = max(i for i, d in enumerate(sessions) if d <= date.fromisoformat(lock["oos_window"]["last"]))
    pairs = [(sessions[i], sessions[i + 1]) for i in range(WARMUP_BARS - 1, last_T)]
    cache = a.out / "features.pkl"
    if cache.exists():
        feats = pd.read_pickle(cache)
    else:
        t0 = time.time()
        feats = feature_cache(panel, events, factors, pairs, a.workers)
        feats.to_pickle(cache)
        logger.info("features for %d sessions in %.0fs", len(pairs), time.time() - t0)
    universe = universe_by_session(panel, [D for _, D in pairs])
    rows = assemble_rows(feats, labels, universe, sessions)
    preds = run_walkforward(rows, sessions, date.fromisoformat(lock["oos_window"]["first"]),
                            date.fromisoformat(lock["oos_window"]["last"]))
    preds.to_pickle(a.out / "predictions.pkl")
    rows.to_pickle(a.out / "rows.pkl")
    (a.out / "run_manifest.json").write_text(json.dumps({
        "lock_sha256": sha, "sessions": [str(sessions[0]), str(sessions[-1])], "feature_sessions": len(pairs),
        "rows": len(rows), "predictions": len(preds), "known_price_actions": len(known), "suspected_actions": len(suspects),
        "factor_actions": len(factors),
    }, indent=1))
    logger.info("done: %d rows, %d predictions", len(rows), len(preds))


if __name__ == "__main__":
    main()
