"""Pre-registered backtest of entry setups A–D (+E modifier), PREREGISTRATION.md incl. the addendum.

    cd <worktree>/backend && PYTHONPATH=. <venv python> <this file>

Read-only inputs; writes entry_setups_result.json and trades.pkl.gz next to this file. The vectorised bracket and trade-plan
code below is checked against the tested scalar functions in entry_setups.py on a random sample before any result is written.
"""
import gzip, json, os, pickle, sys, time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nidp.services.tpd_model.backtest import corporate_actions_from_archive, suspected_actions, universe_by_session
from nidp.services.tpd_model.entry_setups import (MIN_ADV20, evaluate_setups, entry_quality, indicators, simulate_bracket,
                                                  trade_plan)
from nidp.services.tpd_model.panel_source import select_nse_eq

OUT = Path(__file__).parent
F = Path("/app/research/tpd3_forward")
COST = 0.0025
FIRST_T = pd.Timestamp("2024-09-02")
HALF_SPLIT = pd.Timestamp("2025-09-01")
TRADES = {"5%": (0.05, 1.5), "10%": (0.10, 2.5)}
SETUPS = ["a", "b", "c", "d"]
BUY_STOP = {"a", "d"}
t0 = time.time()
log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)

# ---------------------------------------------------------------- data
raw = pd.read_csv(F / "exports" / "panel.csv.gz", parse_dates=["as_of_date"])
panel = select_nse_eq(raw, set(pd.read_csv(F / "exports" / "etfs.csv")["symbol"]))
del raw
sessions = list(pd.DatetimeIndex(sorted(panel["as_of_date"].unique())))
sidx = {d: i for i, d in enumerate(sessions)}
log(f"panel {len(panel):,} rows, {panel['symbol'].nunique()} symbols, {len(sessions)} sessions {sessions[0].date()}..{sessions[-1].date()}")

members = universe_by_session(panel, [d.date() for d in sessions if d >= FIRST_T])
in_universe = {(s, pd.Timestamp(d)) for d, syms in members.items() for s in syms}
log(f"universe built for {len(members)} sessions")

factors, known = corporate_actions_from_archive(pd.read_csv(F / "inputs" / "tpd_ca_history.csv"))
excl = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
excl["ex_date"] = pd.to_datetime(excl["ex_date"])

nifty = pd.read_csv(OUT / "nifty50_yahoo_daily.csv", parse_dates=["as_of_date"]).sort_values("as_of_date")
nifty["n_ret20"] = nifty["close"] / nifty["close"].shift(20) - 1
nifty["n_ret5"] = nifty["close"] / nifty["close"].shift(5) - 1
nifty["n_ema50"] = nifty["close"].ewm(span=50, adjust=False).mean()
nifty["nifty_above_ema50"] = nifty["close"] > nifty["n_ema50"]
nifty = nifty.rename(columns={"close": "nifty_close", "n_ret5": "nifty_ret5"})[["as_of_date", "nifty_close", "n_ret20", "nifty_ret5", "nifty_above_ema50"]]

sectors = pd.read_csv(F / "exports" / "sectors.csv")[["symbol", "sector"]].drop_duplicates("symbol")
caps = pd.read_csv(OUT / "cap_bucket_latest.csv", header=None, names=["symbol", "cap_bucket", "cap_as_of"])[["symbol", "cap_bucket"]]

# ---------------------------------------------------------------- results filings → material positive prints per session
fin = pd.read_csv(F / "exports" / "financials.csv.gz", usecols=["symbol", "period_end", "period_type", "consolidated", "pat_cr", "broadcast_at"])
fin = fin[(fin["period_type"] == "quarterly") & fin["pat_cr"].notna()].copy()
fin["period_end"] = pd.to_datetime(fin["period_end"])
fin["broadcast_at"] = pd.to_datetime(fin["broadcast_at"], utc=True, errors="coerce")
fin["cons"] = fin["consolidated"].astype(str).str.lower().isin(["t", "true", "1"])
fin = fin.sort_values(["symbol", "period_end", "cons", "broadcast_at"], ascending=[True, True, False, True])
fin = fin.drop_duplicates(["symbol", "period_end", "cons"], keep="first")
has_cons = fin.groupby(["symbol", "period_end"])["cons"].transform("max")
basis = fin[fin["cons"] == has_cons].copy()                                  # consolidated where it exists, else standalone
prior = fin[["symbol", "period_end", "cons", "pat_cr"]].copy()
prior["period_end"] = prior["period_end"] + pd.offsets.DateOffset(years=1)
prior["period_end"] = prior["period_end"] + pd.offsets.MonthEnd(0)
basis["period_end_m"] = basis["period_end"] + pd.offsets.MonthEnd(0)
basis = basis.merge(prior.rename(columns={"period_end": "period_end_m", "pat_cr": "pat_prior"}), on=["symbol", "period_end_m", "cons"], how="left")
basis = basis[basis["broadcast_at"].notna()]
pos = ((basis["pat_prior"] > 0) & (basis["pat_cr"] / basis["pat_prior"] - 1 >= 0.25)) | ((basis["pat_prior"] <= 0) & (basis["pat_cr"] > 0))
prints = basis[pos & basis["pat_prior"].notna()].copy()
close_ts = pd.DatetimeIndex([d + pd.Timedelta(hours=15, minutes=30) for d in sessions]).tz_localize("Asia/Kolkata").tz_convert("UTC")
pos_i = np.searchsorted(close_ts.values, prints["broadcast_at"].values.astype("datetime64[ns]"), side="left")
prints = prints[pos_i < len(sessions)].assign(sess_i=pos_i[pos_i < len(sessions)])
event_today = set(zip(prints["symbol"], prints["sess_i"]))
event_recent = {(s, i + k) for s, i in event_today for k in range(1, 5)}
log(f"results filings: {len(basis):,} with timestamps, {len(prints):,} material positive prints")

# ---------------------------------------------------------------- indicators and setups
ind = pd.concat([indicators(g) for _, g in panel.groupby("symbol", sort=False)], ignore_index=True)
ind["sess_i"] = ind["as_of_date"].map(sidx)
ind = ind.merge(nifty, on="as_of_date", how="left").merge(sectors, on="symbol", how="left").merge(caps, on="symbol", how="left")
ind["rs20_nifty"] = ind["ret20"] - ind["n_ret20"]
ind["in_universe"] = [(s, d) in in_universe for s, d in zip(ind["symbol"], ind["as_of_date"])]
sec_med = ind[ind["in_universe"] & ind["sector"].notna()].groupby(["as_of_date", "sector"])["ret20"].median().rename("sector_med20")
ind = ind.merge(sec_med, on=["as_of_date", "sector"], how="left")
ind["rs20_sector"] = ind["ret20"] - ind["sector_med20"]
ind["event_positive_today"] = [(s, i) in event_today for s, i in zip(ind["symbol"], ind["sess_i"])]
ind["event_recent"] = [(s, i) in event_recent for s, i in zip(ind["symbol"], ind["sess_i"])]
x = evaluate_setups(ind).sort_values(["symbol", "as_of_date"]).reset_index(drop=True)
log(f"indicators and setups on {len(x):,} rows")

# forward five sessions, required to be the actual next five market sessions
g = x.groupby("symbol", sort=False)
for k in range(1, 6):
    for c in ("open", "high", "low", "close"):
        x[f"{c}{k}"] = g[c].shift(-k)
    x[f"si{k}"] = g["sess_i"].shift(-k)
x["fwd_ok"] = np.all([x[f"si{k}"] == x["sess_i"] + k for k in range(1, 6)], axis=0)

# corporate-action window [T-1, T+5] → drop T in [ex-5, ex+1]
ex_i = excl.assign(ei=excl["ex_date"].map(sidx)).dropna(subset=["ei"])
ca_block = {(s, int(e) + d) for s, e in zip(ex_i["symbol"], ex_i["ei"]) for d in range(-5, 2)}
ca_lookback = {(s, int(e) + d) for s, e in zip(ex_i["symbol"], ex_i["ei"]) for d in range(2, 61)}
x["ca_window"] = [(s, i) in ca_block for s, i in zip(x["symbol"], x["sess_i"])]
x["ca_in_lookback"] = [(s, i) in ca_lookback for s, i in zip(x["symbol"], x["sess_i"])]

x["regime_ok"] = ~((~x["nifty_above_ema50"].fillna(False).astype(bool)) & (x["nifty_ret5"] < -0.03))
base_mask = (x["in_universe"] & (x["as_of_date"] >= FIRST_T) & x["fwd_ok"] & ~x["ca_window"] & x["atr14"].notna() & x["ema50"].notna()
             & x["hh20"].notna() & x["nifty_close"].notna())
eligible = base_mask & x["filters_ok"] & x["regime_ok"] & ~x["no_chase"]
E = x[base_mask].copy()
log(f"base rows {base_mask.sum():,}; eligible after filters {eligible.sum():,}; nifty missing on {x.loc[x['in_universe'] & (x['as_of_date'] >= FIRST_T), 'nifty_close'].isna().sum()} universe rows")

# ---------------------------------------------------------------- trades
O = lambda d: np.column_stack([d[f"open{k}"] for k in range(1, 6)])
H = lambda d: np.column_stack([d[f"high{k}"] for k in range(1, 6)])
L = lambda d: np.column_stack([d[f"low{k}"] for k in range(1, 6)])
C = lambda d: np.column_stack([d[f"close{k}"] for k in range(1, 6)])


def bracket_vec(entry, stop, target, o, h, l, c):
    n = len(entry); done = np.zeros(n, bool); exitp = c[:, 4].copy(); outcome = np.full(n, "time", object); day = np.full(n, 5)
    for i in range(5):
        if i > 0:
            gp = ~done & (o[:, i] <= stop); exitp[gp] = o[gp, i]; outcome[gp] = "stop"; day[gp] = i + 1; done |= gp
        st = ~done & (l[:, i] <= stop); exitp[st] = stop[st]; outcome[st] = "stop"; day[st] = i + 1; done |= st
        tg = ~done & (h[:, i] >= target); exitp[tg] = target[tg]; outcome[tg] = "target"; day[tg] = i + 1; done |= tg
    return exitp, outcome, day


def plan_vec(entry, structure, atr, target_pct, mult):
    stop = np.maximum(structure, entry - mult * atr)
    below = stop < entry
    stop_pct = np.where(below, (entry - stop) / entry, np.nan)
    rr = target_pct / stop_pct
    ok = below & (rr >= 2.0) & ((entry - stop) >= 0.5 * atr)
    return stop, stop_pct, rr, ok


def build(d, setup, trade):
    tp, mult = TRADES[trade]
    d = d.copy()
    if setup in BUY_STOP:
        d["filled"] = d["high1"] >= d["high"]
        d["entry"] = np.maximum(d["open1"], d["high"])
    else:
        d["filled"] = True
        d["entry"] = d["open1"]
    structure = d[f"stop_{setup}"].to_numpy() if setup != "base" else np.full(len(d), -np.inf)
    d["stop"], d["stop_pct"], d["rr"], d["plan_ok"] = plan_vec(d["entry"].to_numpy(), structure, d["atr14"].to_numpy(), tp, mult)
    d["setup"], d["trade"] = setup, trade
    return d


def outcomes(d, trade):
    tp, _ = TRADES[trade]
    e = d["entry"].to_numpy(); s = d["stop"].to_numpy(); t = e * (1 + tp)
    o, h, l, c = O(d), H(d), L(d), C(d)
    exitp, outcome, day = bracket_vec(e, s, t, o, h, l, c)
    d = d.assign(exit=exitp, outcome=outcome, exit_day=day, net=exitp / e - 1 - COST,
                 hit5_1d=h[:, 0] >= e * 1.05, hit10_1d=h[:, 0] >= e * 1.10, hit5_5d=h.max(1) >= e * 1.05, hit10_5d=h.max(1) >= e * 1.10,
                 mfe5=h.max(1) / e - 1, mae5=l.min(1) / e - 1, gap=d["open1"] / d["close"] - 1, slippage=e / d["close"] - 1)
    d["gap_through_stop"] = (d["outcome"] == "stop") & (d["exit"] < d["stop"] - 1e-9)
    return d


frames, raw_counts = [], {}
for s in SETUPS:
    fired_raw = E[E[f"setup_{s}_raw"]]
    raw_counts[s] = {"fired_before_no_chase": int(len(fired_raw)), "no_chase_watchlist": int(fired_raw["no_chase"].sum()),
                     "fired": int(E[f"setup_{s}"].sum()),
                     "after_liquidity_extension_regime": int((E[f"setup_{s}"] & E["filters_ok"] & E["regime_ok"]).sum())}
    cand = E[E[f"setup_{s}"] & E["filters_ok"] & E["regime_ok"]]
    for tr in TRADES:
        b = build(cand, s, tr)
        raw_counts[s][f"filled_{tr}"] = int(b["filled"].sum())
        raw_counts[s][f"plan_ok_{tr}"] = int((b["filled"] & b["plan_ok"]).sum())
        frames.append(outcomes(b[b["filled"] & b["plan_ok"]], tr))
base_frames = []
bcand = E[E["filters_ok"] & E["regime_ok"] & ~E["no_chase"]]
for tr in TRADES:
    b = build(bcand, "base", tr)
    base_frames.append(outcomes(b[b["plan_ok"]], tr))
trades = pd.concat(frames, ignore_index=True)
base = pd.concat(base_frames, ignore_index=True)
log(f"setup trades {len(trades):,}; baseline trades {len(base):,}")

# ---------------------------------------------------------------- consistency checks against the tested scalar functions
rng = np.random.default_rng(11)
for name, df in (("setups", trades), ("baseline", base)):
    samp = df.iloc[rng.choice(len(df), size=min(3000, len(df)), replace=False)]
    for r in samp.itertuples(index=False):
        tp, mult = TRADES[r.trade]
        structure = getattr(r, f"stop_{r.setup}") if r.setup != "base" else -np.inf
        p = trade_plan(r.entry, structure, r.atr14, tp, mult)
        assert p["ok"] and abs(p["stop"] - r.stop) < 1e-9, (name, r.symbol, r.as_of_date, p, r.stop)
        fwd = pd.DataFrame({"open": [getattr(r, f"open{k}") for k in range(1, 6)], "high": [getattr(r, f"high{k}") for k in range(1, 6)],
                            "low": [getattr(r, f"low{k}") for k in range(1, 6)], "close": [getattr(r, f"close{k}") for k in range(1, 6)]})
        sb = simulate_bracket(r.entry, r.stop, r.entry * (1 + tp), fwd, COST)
        assert sb["outcome"] == r.outcome and abs(sb["net"] - r.net) < 1e-9 and sb["exit_day"] == r.exit_day, (name, r.symbol, sb, r.outcome, r.net)
log("vectorised plan and bracket match trade_plan/simulate_bracket on 6,000 sampled trades")

# ---------------------------------------------------------------- EQS and TOS
eqs = trades.apply(lambda r: entry_quality(r.to_dict()), axis=1)
trades["eqs"] = [q["eqs"] for q in eqs]
pred = pd.read_pickle("/app/.claude/workspace/ten-percent-days-3/evidence/early_window/v4/early_window_v4_predictions.pkl")
pred = pred[pred["head"].isin(["p_up5_1d", "p_up10_1d"])][["head", "symbol", "as_of_date", "p_tpd3"]].copy()
pred["as_of_date"] = pd.to_datetime(pred["as_of_date"]).astype("datetime64[ns]")
pred["p_rank"] = pred.groupby(["head", "as_of_date"])["p_tpd3"].rank(pct=True)
pred["trade"] = pred["head"].map({"p_up5_1d": "5%", "p_up10_1d": "10%"})
trades = trades.merge(pred[["trade", "symbol", "as_of_date", "p_tpd3", "p_rank"]], on=["trade", "symbol", "as_of_date"], how="left")
conf = np.where(trades["deliverable_pct"].notna(), 1.0, 0.8)
trades["tos"] = trades["p_rank"] * trades["eqs"] / 100 * np.minimum(1, trades["rr"] / 3) * conf * (1 - np.minimum(0.5, trades["atr_pct"] * 5))


# ---------------------------------------------------------------- statistics
def boot(d, n=2000, seed=7):
    by = d.groupby("as_of_date")["net"].agg(["sum", "count"])
    if len(by) < 2:
        return [None, None]
    r = np.random.default_rng(seed)
    idx = r.integers(0, len(by), size=(n, len(by)))
    s, c = by["sum"].to_numpy(), by["count"].to_numpy()
    stats = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))]


def summary(d):
    if len(d) == 0:
        return {"trades": 0}
    return {"trades": int(len(d)), "dates": int(d["as_of_date"].nunique()), "symbols": int(d["symbol"].nunique()),
            "mean_net": float(d["net"].mean()), "median_net": float(d["net"].median()), "win_rate": float((d["net"] > 0).mean()),
            "target_rate": float((d["outcome"] == "target").mean()), "stop_rate": float((d["outcome"] == "stop").mean()),
            "time_exit_rate": float((d["outcome"] == "time").mean()),
            "p_up5_1d": float(d["hit5_1d"].mean()), "p_up10_1d": float(d["hit10_1d"].mean()),
            "p_up5_5d": float(d["hit5_5d"].mean()), "p_up10_5d": float(d["hit10_5d"].mean()),
            "mfe5_mean": float(d["mfe5"].mean()), "mfe5_median": float(d["mfe5"].median()),
            "mae5_mean": float(d["mae5"].mean()), "mae5_median": float(d["mae5"].median()),
            "gap_mean": float(d["gap"].mean()), "slippage_mean": float(d["slippage"].mean()),
            "stop_pct_median": float(d["stop_pct"].median()), "rr_median": float(d["rr"].median()),
            "stops_gapped_through": int(d["gap_through_stop"].sum()),
            "gap_through_loss_beyond_stop_mean": float((d.loc[d["gap_through_stop"], "exit"] / d.loc[d["gap_through_stop"], "stop"] - 1).mean()) if d["gap_through_stop"].any() else None}


result = {"generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(), "preregistration": "PREREGISTRATION.md (incl. addendum)",
          "cost_round_trip": COST, "signal_days": [str(E["as_of_date"].min().date()), str(E["as_of_date"].max().date())],
          "rows": {"base_rows": int(base_mask.sum()), "eligible": int(eligible.sum()), "ca_window_dropped": int((x["in_universe"] & (x["as_of_date"] >= FIRST_T) & x["ca_window"]).sum()),
                   "base_rows_with_ca_in_lookback": int(E["ca_in_lookback"].sum())},
          "setup_counts": raw_counts, "baseline": {}, "setups": {}, "verdicts": {}}
for tr in TRADES:
    bd = base[base["trade"] == tr]
    result["baseline"][tr] = {**summary(bd), "ci95": boot(bd)}
for s in SETUPS:
    for tr in TRADES:
        d = trades[(trades["setup"] == s) & (trades["trade"] == tr)]
        h1, h2 = d[d["as_of_date"] < HALF_SPLIT], d[d["as_of_date"] >= HALF_SPLIT]
        bmean = result["baseline"][tr].get("mean_net")
        st = {**summary(d), "ci95": boot(d), "half1": summary(h1), "half2": summary(h2),
              "with_E": summary(d[d["setup_e"]]), "without_E": summary(d[~d["setup_e"]]),
              "by_cap_bucket_current": {k: summary(v) for k, v in d.groupby(d["cap_bucket"].fillna("UNKNOWN"))},
              "by_sector": {k: summary(v) for k, v in d.groupby(d["sector"].fillna("UNKNOWN")) if len(v) >= 30}}
        ci = st["ci95"]
        checks = {"n_ge_200": st["trades"] >= 200,
                  "mean_gt_0": st["trades"] > 0 and st["mean_net"] > 0,
                  "ci_lower_gt_0": ci[0] is not None and ci[0] > 0,
                  "beats_baseline": st["trades"] > 0 and bmean is not None and st["mean_net"] > bmean,
                  "half1_gt_0": h1.shape[0] > 0 and h1["net"].mean() > 0,
                  "half2_gt_0": h2.shape[0] > 0 and h2["net"].mean() > 0}
        result["setups"][f"{s}_{tr}"] = st
        result["verdicts"][f"{s}_{tr}"] = {"checks": checks, "verdict": "validated" if all(checks.values()) else "not validated"}

allq = {}
for tr in TRADES:
    d = trades[trades["trade"] == tr].copy()
    d["eqs_q"] = pd.qcut(d["eqs"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    allq[tr] = {"eqs_quintiles": {int(k): {**summary(v), "eqs_range": [float(v["eqs"].min()), float(v["eqs"].max())]} for k, v in d.groupby("eqs_q", observed=True)}}
    t = d[d["tos"].notna()].copy()
    if len(t) >= 50:
        t["tos_q"] = pd.qcut(t["tos"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        allq[tr]["tos_quintiles_jan_aug_2025"] = {int(k): summary(v) for k, v in t.groupby("tos_q", observed=True)}
        allq[tr]["p_rank_quintiles_jan_aug_2025"] = {int(k): summary(v) for k, v in t.assign(pq=pd.qcut(t["p_rank"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])).groupby("pq", observed=True)}
    allq[tr]["with_prediction"] = int(len(t))
result["quality_scores"] = allq

NO_WRITE = bool(os.environ.get("ENTRY_SETUPS_NO_WRITE"))    # set by exploratory_sensitivity.py, which re-runs this file to reuse its frames
if not NO_WRITE:
    (OUT / "entry_setups_result.json").write_text(json.dumps(result, indent=2, default=str))
keep = ["symbol", "as_of_date", "setup", "trade", "entry", "stop", "stop_pct", "rr", "exit", "exit_day", "outcome", "net", "hit5_1d", "hit10_1d",
        "hit5_5d", "hit10_5d", "mfe5", "mae5", "gap", "slippage", "gap_through_stop", "setup_e", "eqs", "p_tpd3", "p_rank", "tos", "sector", "cap_bucket",
        "close", "high", "low", "atr14", "rvol", "clv", "hh20", "ema20", "ema50", "rs20_nifty", "rs20_sector", "adv20"]
if not NO_WRITE:
    with gzip.open(OUT / "trades.pkl.gz", "wb") as fh:
        pickle.dump(trades[keep], fh)
log("wrote entry_setups_result.json and trades.pkl.gz")
for k, v in result["verdicts"].items():
    s = result["setups"][k]
    print(f"{k:6s} n={s.get('trades', 0):5d} mean={s.get('mean_net', float('nan')):+.4f} ci={s['ci95']} -> {v['verdict']} {[c for c, ok in v['checks'].items() if not ok]}")
for tr in TRADES:
    print("baseline", tr, result["baseline"][tr]["trades"], f"{result['baseline'][tr]['mean_net']:+.4f}", result["baseline"][tr]["ci95"])
