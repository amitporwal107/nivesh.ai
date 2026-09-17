"""Pre-registered backtest of short-term mean reversion E1–E5 (PREREGISTRATION.md in this folder, incl. its addendum).

    cd <worktree>/backend && PYTHONPATH=. <research venv python> ../docs/ai_research/tpd3/mean_reversion/backtest_mean_reversion.py --segment development
    cd <worktree>/backend && PYTHONPATH=. <research venv python> ../docs/ai_research/tpd3/mean_reversion/backtest_mean_reversion.py --segment holdout

The holdout run needs mr_development_result.json, runs only the variants that passed development, claims holdout_lock.json
(refusing a second run) and uses CIs at 1 - 0.05/k. With no variant passing development it refuses to run.
Read-only inputs; outputs are written next to this file.
"""
import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from nidp.services.tpd_model.backtest import corporate_actions_from_archive, suspected_actions, universe_by_session
from nidp.services.tpd_model.mean_reversion import (MIN_ADV20, VARIANTS, apply_cooldown, boot_ci, claim_holdout, dependence,
                                                    indicators, matched_edges, signals, summarize, verdict)
from nidp.services.tpd_model.panel_source import select_nse_eq

OUT = Path(__file__).resolve().parent
INPUTS = OUT.parent / "entry_setups"                      # the same Nifty and cap-bucket pulls as the breakout study
F = Path("/app/research/tpd3_forward")
COST = 0.0025
EXTRA_SLIPPAGE = 0.0020
UNIVERSE_START = pd.Timestamp("2024-10-24")
SEGMENTS = {"development": (pd.Timestamp("2024-10-24"), pd.Timestamp("2025-12-31"), pd.Timestamp("2025-05-31")),
            "holdout": (pd.Timestamp("2026-01-01"), None, pd.Timestamp("2026-04-30"))}
NEWS_KEYWORDS = r"insolvency|CIRP|NCLT|resolution professional|SEBI order|show cause|forensic audit|resignation of (the )?(statutory )?auditor|auditor.{0,20}resign|default"

ap = argparse.ArgumentParser()
ap.add_argument("--segment", choices=list(SEGMENTS), required=True)
a = ap.parse_args()
t0 = time.time()
log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)
script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

run_variants, level = VARIANTS, 0.95
if a.segment == "holdout":
    dev_path = OUT / "mr_development_result.json"
    if not dev_path.exists():
        sys.exit("holdout refused: run --segment development first")
    dev = json.loads(dev_path.read_text())
    run_variants = [v for v in VARIANTS if dev["verdicts"][v]["passed"]]
    if not run_variants:
        sys.exit("holdout refused: no variant passed development; the holdout stays unused (PREREGISTRATION.md)")
    level = 1 - 0.05 / len(run_variants)
    claim_holdout(OUT / "holdout_lock.json", script_sha256=script_sha, variants=run_variants)
    log(f"holdout claimed for {run_variants} at CI level {level:.4f}")

# ---------------------------------------------------------------- data
raw = pd.read_csv(F / "exports" / "panel.csv.gz", parse_dates=["as_of_date"])
panel = select_nse_eq(raw, set(pd.read_csv(F / "exports" / "etfs.csv")["symbol"]))
del raw
sessions = list(pd.DatetimeIndex(sorted(panel["as_of_date"].unique())))
sidx = {d: i for i, d in enumerate(sessions)}
members = universe_by_session(panel, [d.date() for d in sessions if d >= UNIVERSE_START])
rank = {(s, pd.Timestamp(d)): i for d, syms in members.items() for i, s in enumerate(syms)}
log(f"panel {len(panel):,} rows, {len(sessions)} sessions; universe for {len(members)} sessions")

factors, known = corporate_actions_from_archive(pd.read_csv(F / "inputs" / "tpd_ca_history.csv"))
excl = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
excl["ex_date"] = pd.to_datetime(excl["ex_date"])
ex_i = excl.assign(ei=excl["ex_date"].map(sidx)).dropna(subset=["ei"])
ca_block = {(s, int(e) + d) for s, e in zip(ex_i["symbol"], ex_i["ei"]) for d in range(-5, 21)}      # ex in [T-20, T+5]

nifty = pd.read_csv(INPUTS / "nifty50_yahoo_daily.csv", parse_dates=["as_of_date"]).sort_values("as_of_date")
nifty["nifty_ret5"] = nifty["close"] / nifty["close"].shift(5) - 1
nifty["nifty_above_ema50"] = nifty["close"] > nifty["close"].ewm(span=50, adjust=False).mean()
nifty = nifty.rename(columns={"close": "nifty_close"})[["as_of_date", "nifty_close", "nifty_ret5", "nifty_above_ema50"]]
sectors = pd.read_csv(F / "exports" / "sectors.csv")[["symbol", "sector"]].drop_duplicates("symbol")
caps = pd.read_csv(INPUTS / "cap_bucket_latest.csv", header=None, names=["symbol", "cap_bucket", "cap_as_of"])[["symbol", "cap_bucket"]]
close_ts = pd.DatetimeIndex([d + pd.Timedelta(hours=15, minutes=30) for d in sessions]).tz_localize("Asia/Kolkata").tz_convert("UTC")


def to_session(ts: pd.Series) -> np.ndarray:
    return np.searchsorted(close_ts.values, ts.values.astype("datetime64[ns]"), side="left")


# material negative results prints → sessions
fin = pd.read_csv(F / "exports" / "financials.csv.gz", usecols=["symbol", "period_end", "period_type", "consolidated", "pat_cr", "broadcast_at"])
fin = fin[(fin["period_type"] == "quarterly") & fin["pat_cr"].notna()].copy()
fin["period_end"] = pd.to_datetime(fin["period_end"]) + pd.offsets.MonthEnd(0)
fin["broadcast_at"] = pd.to_datetime(fin["broadcast_at"], utc=True, errors="coerce")
fin["cons"] = fin["consolidated"].astype(str).str.lower().isin(["t", "true", "1"])
fin = fin.sort_values(["symbol", "period_end", "cons", "broadcast_at"], ascending=[True, True, False, True]).drop_duplicates(["symbol", "period_end", "cons"])
basis = fin[fin["cons"] == fin.groupby(["symbol", "period_end"])["cons"].transform("max")].copy()
prior = fin[["symbol", "period_end", "cons", "pat_cr"]].assign(period_end=lambda d: d["period_end"] + pd.offsets.DateOffset(years=1) + pd.offsets.MonthEnd(0))
basis = basis.merge(prior.rename(columns={"pat_cr": "pat_prior"}), on=["symbol", "period_end", "cons"], how="left")
basis = basis[basis["broadcast_at"].notna() & basis["pat_prior"].notna()]
neg = basis[(basis["pat_prior"] > 0) & ((basis["pat_cr"] / basis["pat_prior"] - 1 <= -0.25) | (basis["pat_cr"] <= 0))].copy()
neg["si"] = to_session(neg["broadcast_at"])
neg = neg[neg["si"] < len(sessions)]
neg_block = {(s, int(i) + k) for s, i in zip(neg["symbol"], neg["si"]) for k in range(0, 5)}               # print in T-4..T
log(f"negative results prints mapped: {len(neg):,}")

# ---------------------------------------------------------------- indicators, signals, forward outcomes
x = pd.concat([indicators(g) for _, g in panel.groupby("symbol", sort=False)], ignore_index=True)
x["sess_i"] = x["as_of_date"].map(sidx)
x = x.merge(nifty, on="as_of_date", how="left").merge(sectors, on="symbol", how="left").merge(caps, on="symbol", how="left")
x["uni_rank"] = [rank.get((s, d)) for s, d in zip(x["symbol"], x["as_of_date"])]
x["in_universe"] = x["uni_rank"].notna()
med = x[x["in_universe"] & x["sector"].notna()].groupby(["as_of_date", "sector"])["ret20"].median().rename("sector_med20")
x = x.merge(med, on=["as_of_date", "sector"], how="left")
x["rs20_sector"] = x["ret20"] - x["sector_med20"]
x = signals(x).sort_values(["symbol", "as_of_date"]).reset_index(drop=True)
g = x.groupby("symbol", sort=False)
x["open1"] = g["open"].shift(-1)
for k in (1, 3, 5):
    x[f"close{k}"] = g["close"].shift(-k)
x["hi5"] = pd.concat([g["high"].shift(-k) for k in range(1, 6)], axis=1).max(axis=1, skipna=False)
x["lo5"] = pd.concat([g["low"].shift(-k) for k in range(1, 6)], axis=1).min(axis=1, skipna=False)
x["fwd_ok"] = g["sess_i"].shift(-5) == x["sess_i"] + 5
x["t5_date"] = g["as_of_date"].shift(-5)
for k in (1, 3, 5):
    x[f"net{k}"] = x[f"close{k}"] / x["open1"] - 1 - COST
x["mfe5"] = x["hi5"] / x["open1"] - 1
x["mae5"] = x["lo5"] / x["open1"] - 1
x["ca_window"] = [(s, i) in ca_block for s, i in zip(x["symbol"], x["sess_i"])]
x["neg_catalyst"] = [(s, i) in neg_block for s, i in zip(x["symbol"], x["sess_i"])]
x["regime_ok"] = ~((~x["nifty_above_ema50"].fillna(False).astype(bool)) & (x["nifty_ret5"] < -0.03))
x["eligible"] = (x["in_universe"] & (x["adv20"] >= MIN_ADV20) & x["fwd_ok"] & ~x["ca_window"] & ~x["locked"] & x["nifty_close"].notna()
                 & x["regime_ok"] & x["open1"].notna())
x["band"] = np.select([x["uni_rank"] < 200, x["uni_rank"] < 500], [1, 2], 3)

first, last, half_split = SEGMENTS[a.segment]
seg = x["eligible"] & (x["as_of_date"] >= first)
if last is not None:
    seg &= x["t5_date"] <= last
S = x[seg].copy()
S["atr_q"] = S.groupby("as_of_date")["atr14_pct"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if s.notna().sum() >= 5 else np.nan)
pool = S[~S["neg_catalyst"]]
log(f"segment {a.segment}: T {S['as_of_date'].min().date()} → {S['as_of_date'].max().date()}; eligible rows {len(S):,}; "
    f"after negative-catalyst removal {len(pool):,}")

# ---------------------------------------------------------------- per variant
def stats_block(trades: pd.DataFrame, variant: str, lvl: float) -> tuple[dict, dict]:
    s = summarize(trades)
    if s["trades"] == 0:
        return s, verdict({"trades": 0, "mean_net": None, "ci": [None, None], "b1_mean": b1_mean, "edge_b2": None, "half1_mean": None, "half2_mean": None,
                           "b3_edge": None, "b3_ci": [None, None], "max_symbol_share": None, "mean_without_top_sector": None,
                           "mean_without_top5_dates": None, "mean_net_extra_slippage": None})
    s["ci"] = boot_ci(trades, "net5", lvl)
    nonsig = pool[~pool[variant]]
    same = nonsig.groupby("symbol")["net5"].agg(["mean", "count"])
    same = same[same["count"] >= 20]["mean"]
    b2 = trades.merge(same.rename("same_mean"), left_on="symbol", right_index=True, how="inner")
    s["b2"] = {"trades_with_same_stock_baseline": int(len(b2)), "edge": float((b2["net5"] - b2["same_mean"]).mean()) if len(b2) else None}
    me = matched_edges(trades, nonsig)
    s["b3"] = {"trades_matched": int(len(me)), "sector_cells": int((me["cell"] == "sector").sum()) if len(me) else 0,
               "left_out": int(len(trades) - len(me)), "edge": float(me["edge"].mean()) if len(me) else None,
               "ci": boot_ci(me.rename(columns={"edge": "e"}), "e", lvl) if len(me) else [None, None]}
    h1, h2 = trades[trades["as_of_date"] <= half_split], trades[trades["as_of_date"] > half_split]
    s["half1"], s["half2"] = summarize(h1), summarize(h2)
    s["dependence"] = dependence(trades)
    s["mean_net_extra_slippage"] = float((trades["net5"] - EXTRA_SLIPPAGE).mean())
    s["b1_mean"] = b1_mean
    s["by_cap_bucket_current"] = {k: summarize(v) for k, v in trades.groupby(trades["cap_bucket"].fillna("UNKNOWN"))}
    s["by_sector"] = {k: summarize(v) for k, v in trades.groupby(trades["sector"].fillna("UNKNOWN")) if len(v) >= 30}
    s["by_band"] = {int(k): summarize(v) for k, v in trades.groupby("band")}
    vd = verdict({"trades": s["trades"], "mean_net": s["mean_net"], "ci": s["ci"], "b1_mean": b1_mean, "edge_b2": s["b2"]["edge"],
                  "half1_mean": s["half1"].get("mean_net"), "half2_mean": s["half2"].get("mean_net"), "b3_edge": s["b3"]["edge"], "b3_ci": s["b3"]["ci"],
                  "max_symbol_share": s["dependence"]["max_symbol_share"], "mean_without_top_sector": s["dependence"]["mean_without_top_sector"],
                  "mean_without_top5_dates": s["dependence"]["mean_without_top5_dates"], "mean_net_extra_slippage": s["mean_net_extra_slippage"]})
    return s, vd


b1 = summarize(pool)
b1_mean = b1["mean_net"]
b1["ci"] = boot_ci(pool, "net5", level)
result = {"segment": a.segment, "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(), "script_sha256": script_sha,
          "preregistration_sha256": hashlib.sha256((OUT / "PREREGISTRATION.md").read_bytes()).hexdigest(), "ci_level": level,
          "cost_round_trip": COST, "extra_slippage": EXTRA_SLIPPAGE,
          "signal_days": [str(S["as_of_date"].min().date()), str(S["as_of_date"].max().date())], "half_split": str(half_split.date()),
          "rows": {"eligible": int(len(S)), "negative_catalyst_removed": int(S["neg_catalyst"].sum()), "pool": int(len(pool))},
          "baseline_b1_any_eligible_stock_day": b1, "variants": {}, "verdicts": {}, "negative_catalyst_signals": {}}
keep = ["symbol", "as_of_date", "variant", "open1", "close5", "net1", "net3", "net5", "mfe5", "mae5", "sector", "cap_bucket", "band", "atr_q",
        "close", "sma20", "r3", "r5", "clv", "rvol", "rsi2", "rsi2_prev", "rs20_sector", "adv20"]
all_trades = []
for v in run_variants:
    fired = pool[pool[v]]
    trades = fired.loc[apply_cooldown(fired, v)].copy()
    trades["variant"] = v
    s, vd = stats_block(trades, v, level)
    s["fired_before_cooldown"] = int(len(fired))
    result["variants"][v], result["verdicts"][v] = s, vd
    negf = S[S["neg_catalyst"] & S[v]]
    result["negative_catalyst_signals"][v] = summarize(negf.loc[apply_cooldown(negf, v)]) if len(negf) else {"trades": 0}
    all_trades.append(trades[keep])
    log(f"{v}: fired {len(fired):,}, trades {len(trades):,}, mean net5 {s.get('mean_net', float('nan')):+.4f}, "
        f"{'PASSED' if vd['passed'] else 'not validated'} {vd['failed']}")

if a.segment == "holdout":
    ann = pd.read_csv(F / "exports" / "announcements.csv", usecols=["symbol", "broadcast_at", "subject"])
    ann = ann[ann["subject"].astype(str).str.contains(NEWS_KEYWORDS, case=False, regex=True)].copy()
    ann["broadcast_at"] = pd.to_datetime(ann["broadcast_at"], utc=True, errors="coerce")
    ann = ann[ann["broadcast_at"].notna()]
    ann["si"] = to_session(ann["broadcast_at"])
    news = {(s, int(i) + k) for s, i in zip(ann["symbol"], ann["si"]) for k in range(0, 5)}
    result["news_flagged_trades_descriptive"] = {}
    for tr in all_trades:
        v = tr["variant"].iloc[0] if len(tr) else None
        if v is None:
            continue
        flagged = tr[[(s, sidx[d]) in news for s, d in zip(tr["symbol"], tr["as_of_date"])]]
        result["news_flagged_trades_descriptive"][v] = summarize(flagged) if len(flagged) else {"trades": 0}

name = f"mr_{a.segment}_result.json"
(OUT / name).write_text(json.dumps(result, indent=2, default=str))
pd.concat(all_trades, ignore_index=True).to_csv(OUT / f"mr_{a.segment}_trades.csv.gz", index=False, float_format="%.6g")
log(f"wrote {name} and mr_{a.segment}_trades.csv.gz")
print("B1 any eligible stock-day:", b1["trades"], f"{b1['mean_net']:+.4f}", b1["ci"])
for v in run_variants:
    s, vd = result["variants"][v], result["verdicts"][v]
    print(f"{v}: n={s['trades']} mean={s.get('mean_net', float('nan')):+.4f} ci={s.get('ci')} b2={s.get('b2', {}).get('edge')} "
          f"b3={s.get('b3', {}).get('edge')} ci={s.get('b3', {}).get('ci')} -> {'PASSED' if vd['passed'] else 'not validated'} {vd['failed']}")
