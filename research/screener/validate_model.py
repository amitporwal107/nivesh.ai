"""Validate the v4 model's forward predictions for one session against what actually happened.

Predictions: nidp.tpd_paper_prediction_snapshots (sample 'forward'), made the evening before `session`.
Outcome (the model's own label, engine.py): the session's HIGH >= previous close x (1 + target%) — P5-NEXT 5%,
P10-NEXT 10%. Outcomes come from the official NSE bhavcopy (any past session); before it is published, from a Kite
quote snapshot of the model's scored universe (latest session only; archived).

Reports per target: the 5 selected picks (hits, and their close-to-close return: movement is not direction),
precision and lift at top 10/20/50 by movement probability, recall of the top 50, AUC, Brier score and a decile
calibration table. Appends one row per target to validation/ledger.csv — an out-of-sample record that only grows.

usage: python validate_model.py --session YYYY-MM-DD
"""
import argparse
import glob
import io
import json
import os
import subprocess

import numpy as np
import pandas as pd

import screener as S

PSQL = ["docker", "exec", "-i", "nidp-postgres-staging", "psql", "-U", "nidp_staging", "-d", "nidp_staging", "-v", "ON_ERROR_STOP=1"]


def predictions(session: str) -> pd.DataFrame:
    sql = ("COPY (SELECT prediction_date, next_trading_session, symbol, portfolio_type, target_pct, movement_probability, "
           "model_rank, selection_status, model_version FROM nidp.tpd_paper_prediction_snapshots "
           f"WHERE sample = 'forward' AND next_trading_session = '{session}') TO STDOUT WITH CSV HEADER")
    out = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True, check=True).stdout
    return pd.read_csv(io.StringIO(out))


def outcomes(symbols: list[str], session: str) -> tuple[pd.DataFrame, str]:
    """Official bhavcopy for the session (any past session); before it is published, a Kite quote snapshot of the
    latest session (refused if Kite is on a different session)."""
    try:
        return S.snapshot_from_bhavcopy(session, symbols), f"bhavcopy {session}"
    except Exception as e:
        print(f"bhavcopy {session} not available ({type(e).__name__}: {str(e)[:80]}); using Kite")
    d = os.path.join(S.ROOT, "snapshots", session)
    old = sorted(glob.glob(os.path.join(d, "MODEL_UNIVERSE_*.csv.gz")))
    if old:
        return pd.read_csv(old[-1]), old[-1]
    snap = S.build_snapshot(S.kite_quotes(symbols), pd.DataFrame({"symbol": symbols}))
    got = str(pd.to_datetime(snap.last_trade_time, errors="coerce").max())[:10]
    if got != session:
        raise SystemExit(f"REFUSED: Kite serves the {got} session, not {session}; outcomes must come from the same session.")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"MODEL_UNIVERSE_{pd.Timestamp.now(tz='Asia/Kolkata'):%H%M%S}.csv.gz")
    snap.to_csv(path, index=False)
    return snap, path


def auc(score: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = score[y], score[~y]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.r_[pos, neg]).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def evaluate(p: pd.DataFrame, target: float) -> dict:
    """p: one portfolio type with columns movement_probability, selection_status, high_pct, daily_change_pct."""
    p = p.dropna(subset=["high_pct"]).sort_values("movement_probability", ascending=False).reset_index(drop=True)
    y = (p.high_pct >= target - 1e-9).to_numpy()
    base = float(y.mean()) if len(y) else None
    res = {"n_scored_with_outcome": int(len(p)), "hits": int(y.sum()), "base_rate": base,
           "mean_predicted": float(p.movement_probability.mean()) if len(p) else None}
    sel = p[p.selection_status == "SELECTED"]
    res["selected"] = [{"symbol": r.symbol, "prob": round(r.movement_probability, 4), "high_pct": round(r.high_pct, 2),
                        "close_pct": round(r.daily_change_pct, 2), "hit": bool(r.high_pct >= target - 1e-9)} for r in sel.itertuples()]
    res["selected_hits"] = int(sum(s["hit"] for s in res["selected"]))
    for k in (10, 20, 50):
        pk = float(y[:k].mean()) if len(y) >= k else None
        res[f"precision_top{k}"] = pk
        res[f"lift_top{k}"] = (pk / base) if pk is not None and base else None
    res["recall_top50"] = float(y[:50].sum() / y.sum()) if y.sum() else None
    res["auc"] = auc(p.movement_probability.to_numpy(), y)
    res["brier"] = float(np.mean((p.movement_probability.to_numpy() - y) ** 2)) if len(p) else None
    dec = pd.qcut(p.movement_probability.rank(method="first"), 10, labels=False) if len(p) >= 10 else None
    if dec is not None:
        g = pd.DataFrame({"d": dec, "pred": p.movement_probability, "y": y}).groupby("d").agg(pred=("pred", "mean"), actual=("y", "mean"), n=("y", "size"))
        res["calibration_deciles"] = [{"decile": int(i) + 1, "mean_pred": round(r.pred, 4), "actual": round(r.actual, 4), "n": int(r.n)} for i, r in g.iterrows()]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, help="the session the predictions were made for (YYYY-MM-DD)")
    session = ap.parse_args().session
    P = predictions(session)
    if P.empty:
        raise SystemExit(f"no forward predictions for {session}")
    snap, path = outcomes(sorted(P.symbol.unique()), session)
    M = P.merge(snap[["symbol", "high_pct", "daily_change_pct", "traded_value_cr", "last_trade_time"]], on="symbol", how="left")
    stale = M.last_trade_time.notna() & (M.last_trade_time.astype(str).str[:10] != session)
    M.loc[stale, ["high_pct", "daily_change_pct"]] = np.nan  # no trade in this session: outcome unknown, not a miss
    report = {"session": session, "outcomes_snapshot": path, "model_version": sorted(P.model_version.unique()),
              "no_outcome": int(M.high_pct.isna().sum() // max(1, M.portfolio_type.nunique())), "by_target": {}}
    ledger = []
    for pt, g in M.groupby("portfolio_type"):
        target = float(g.target_pct.iloc[0])
        r = evaluate(g, target)
        report["by_target"][pt] = r
        ledger.append({"session": session, "portfolio_type": pt, "target_pct": target, **{k: r[k] for k in (
            "n_scored_with_outcome", "hits", "base_rate", "mean_predicted", "selected_hits", "precision_top10", "lift_top10",
            "precision_top50", "lift_top50", "recall_top50", "auc", "brier")}})
    out = os.path.join(S.ROOT, "validation")
    os.makedirs(out, exist_ok=True)
    json.dump(report, open(os.path.join(out, f"{session}.json"), "w"), indent=1, default=float)
    L = os.path.join(out, "ledger.csv")
    old = pd.read_csv(L) if os.path.exists(L) else pd.DataFrame()
    new = pd.concat([old[old.session != session] if len(old) else old, pd.DataFrame(ledger)], ignore_index=True)
    new.sort_values(["session", "portfolio_type"]).to_csv(L, index=False)
    for pt, r in report["by_target"].items():
        print(f"\n== {pt} ({session}): {r['hits']} of {r['n_scored_with_outcome']} touched +{int(float(P[P.portfolio_type == pt].target_pct.iloc[0]))}% "
              f"(base {100 * r['base_rate']:.1f}%); mean predicted {100 * r['mean_predicted']:.1f}%")
        print(f"   selected 5: {r['selected_hits']} hits — " + ", ".join(f"{s['symbol']} high {s['high_pct']:+.1f}% close {s['close_pct']:+.1f}%" for s in r["selected"]))
        print("   " + " | ".join(f"top{k}: {100 * r[f'precision_top{k}']:.0f}% (lift {r[f'lift_top{k}']:.1f}x)" for k in (10, 20, 50)
                                if r[f"precision_top{k}"] is not None and r[f"lift_top{k}"] is not None)
              + f" | recall@50 {100 * (r['recall_top50'] or 0):.0f}% | AUC {r['auc']:.3f} | Brier {r['brier']:.4f}")
    print(f"\nreport: {os.path.join(out, session + '.json')} | ledger: {L}")


if __name__ == "__main__":
    main()
