"""Candidate ledger (PRD §9): every universe stock on every session, its rank, scores, status and reason.

The ranking is the H#32 one (walkforward.top_k_picks, seed 20260919): the eligible pool of each day ordered by the M8
tbs_5_2 score, ties by the seeded draw. It is reproduced from the frozen out-of-fold file and must equal the frozen
picks file exactly, or the run stops. Status and reason are per configuration; v1 has configuration A only (no
portfolio limits), so the only reasons are eligibility, rank and entry availability."""
from __future__ import annotations

import numpy as np
import pandas as pd

import inputs as IN

SELECTION_RULE = "H32-M8-tbs_5_2-top5-v1 (walkforward.top_k_picks, seed 20260919, eligible pool, entry unknown at selection)"
TOP_K = IN.WF.TOP_K


def rank(ds: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    rows = ds.date >= IN.YEAR_START
    full = IN.WF.top_k_picks(ds, scores[f"{IN.MODEL}|{IN.LABEL}"], rows, IN.WF.SEED, k=10 ** 9)
    full["rank"] = full.groupby("date", sort=False).cumcount() + 1
    return full


def verify_picks(ranked: pd.DataFrame, picks: pd.DataFrame) -> dict:
    top = ranked[ranked["rank"] <= TOP_K]
    same_rows = top.index.equals(picks.index)
    same_vals = same_rows and (top.symbol.to_numpy() == picks.symbol.to_numpy()).all() and \
        np.array_equal(top.score.to_numpy(float), picks.score.to_numpy(float)) and \
        np.array_equal(top.tie.to_numpy(float), picks.tie.to_numpy(float))
    out = {"picks": int(len(picks)), "reproduced": int(len(top)), "identical": bool(same_vals)}
    if not same_vals:
        raise IN.InputError(f"the ranking does not reproduce the frozen picks: {out}")
    return out


def ineligible_reason(hist_n, value20, close) -> str:
    r = []
    if not hist_n >= IN.DS.MIN_HISTORY:
        r.append("HISTORY_LT_60")
    if not value20 >= IN.DS.MIN_VALUE20:
        r.append("VALUE20_LT_5CR")
    if not close >= IN.DS.MIN_CLOSE:
        r.append("CLOSE_LT_50")
    return ";".join(r) or "UNKNOWN"


def ledger(ds: pd.DataFrame, scores: pd.DataFrame, ranked: pd.DataFrame, iso, uni: pd.DataFrame, pred_ids: pd.DataFrame,
           dates, missing: pd.DataFrame, trades: dict) -> pd.DataFrame:
    """Rows for `dates`: every dataset row that day, plus universe symbols without a bar (from the DQ `missing` table).
    `trades` maps a dataset row index to its configuration-A trade record."""
    day = ds[ds.date.isin(dates)]
    out = day[["date", "symbol", "industry", "value20", "atr_pct", "eligible", "entry_status", "hist_n", "close"]].copy()
    out = out.join(ranked["rank"]).merge(uni[["symbol", "isin"]], on="symbol", how="left").set_index(day.index)
    tbs, dr, mv = (scores.reindex(day.index)[f"{m}|{lb}"] for m, lb in IN.LEDGER_SCORES)
    out["tbs_probability"] = tbs
    out["tbs_probability_calibrated_in_sample"] = np.where(tbs.notna(), iso.predict(tbs.fillna(0).to_numpy()), np.nan)
    out["direction_probability"], out["movement_probability"] = dr, mv
    out["tradeability_score"] = np.nan                                  # NULL in v1: H#32 had no tradeability model
    pid = pred_ids[(pred_ids.model == IN.MODEL) & (pred_ids.label == IN.LABEL)].set_index("row").prediction_id
    out["prediction_id"] = pid.reindex(day.index)
    status, reason = [], []
    for i, r in out.iterrows():
        if not r.eligible:
            status.append("REJECTED"), reason.append("NOT_ELIGIBLE:" + ineligible_reason(r.hist_n, r.value20, r.close))
        elif pd.isna(r.tbs_probability) or pd.isna(r["rank"]):
            status.append("REJECTED"), reason.append("NO_SCORE")
        elif r["rank"] > TOP_K:
            status.append("NOT_SELECTED"), reason.append("RANK_GT_5")
        elif r.entry_status != "OK":
            status.append("REJECTED"), reason.append(f"NO_ENTRY:{r.entry_status}")
        else:
            status.append("SELECTED"), reason.append("")
    out["selection_status"], out["rejection_reason"] = status, reason
    for col, key in (("entry_price", "actual_entry"), ("stop_price", "initial_stop"), ("target_price", "initial_target"),
                     ("position_size", "fill_quantity"), ("risk_per_trade", "initial_risk_inr")):
        out[col] = [trades[i][key] if i in trades and trades[i].get("status") == "CLOSED" else None for i in out.index]
    out["config"], out["selection_rule_version"] = "A", SELECTION_RULE
    miss = missing[missing.date.isin(dates)].merge(uni[["symbol", "industry", "isin"]], on="symbol", how="left")
    miss = miss.assign(selection_status="REJECTED", rejection_reason="NO_BAR_ON_D:" + miss.kind, config="A",
                       selection_rule_version=SELECTION_RULE)
    cols = ["date", "symbol", "isin", "industry", "rank", "prediction_id", "movement_probability", "tbs_probability",
            "tbs_probability_calibrated_in_sample", "direction_probability", "tradeability_score", "value20", "atr_pct",
            "selection_status", "rejection_reason", "risk_per_trade", "entry_price", "stop_price", "target_price",
            "position_size", "config", "selection_rule_version"]
    both = pd.concat([out.reset_index(drop=True), miss], ignore_index=True)
    return both.reindex(columns=cols).sort_values(["date", "rank", "symbol"], na_position="last").reset_index(drop=True)


def pick_correlation(store, picks_day: list, date: pd.Timestamp, lookback: int = 60) -> dict:
    """Pairwise correlation of the day's picks' daily returns over the `lookback` sessions to D (§9)."""
    rets = {}
    for s in picks_day:
        g = store.by_symbol.get(s)
        if g is None:
            continue
        r = (g.close / g.prev_close - 1).loc[:date].tail(lookback)
        rets[s] = r
    df = pd.DataFrame(rets)
    c = df.corr(min_periods=max(20, lookback // 2))
    vals = c.where(~np.eye(len(c), dtype=bool)).stack()
    return {"symbols": list(c.columns), "matrix": c.round(4).where(c.notna(), None).to_numpy().tolist(),
            "mean_pairwise": float(vals.mean()) if len(vals) else None, "max_pairwise": float(vals.max()) if len(vals) else None}
