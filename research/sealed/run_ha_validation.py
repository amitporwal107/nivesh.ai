"""SEALED validation test of H-A (TRACK1_SCOPE_v2.md) on 2021-01-01 .. 2022-12-31. RUN ONCE.

H-A: EQ, 20-session traded value >= Rs 5 cr (Kite volume x close, sessions ending the previous session), gap =
open / previous close - 1 <= -3% on Kite's adjusted daily series, open-at-a-lower-band excluded (|g + b| <= 0.25pp,
b = 5/10/20%), at most 5 per session (deepest gap first, ties -> higher traded value), enter at the open, exit at the
close. Cost model v1 round trip by value (0.20/0.30/0.40%); 2x reported. Session = unit of analysis (Newey-West,
5 lags, as in every prior analysis). Success: mean > 0 and 95% NW lower bound > 0 (= one-sided alpha 0.025).
Rows dated 2023-01-01 or later are dropped at load: the final-test slice stays sealed.
"""
import glob, hashlib, json, os, subprocess, datetime as dt
import numpy as np, pandas as pd
OUT = "/app/research/sealed"; os.makedirs(OUT, exist_ok=True)
RESULT = f"{OUT}/HA_validation_2021_2022.json"
if os.path.exists(RESULT):
    raise SystemExit(f"REFUSED: {RESULT} exists — the sealed test runs once.")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPEC = os.path.join(REPO, "docs/ai_research/tpd3/track1/TRACK1_SCOPE_v2.md")
LO, HI, START = pd.Timestamp("2020-11-01"), pd.Timestamp("2022-12-31"), pd.Timestamp("2021-01-01")
parts = []
for f in sorted(glob.glob("/app/research/kite_history/day_2021/part-*.csv.gz")):
    for ch in pd.read_csv(f, usecols=["symbol", "date", "open", "high", "low", "close", "volume"], chunksize=500_000):
        ch["date"] = pd.to_datetime(ch.date); parts.append(ch[(ch.date >= LO) & (ch.date <= HI)])
K = pd.concat(parts).drop_duplicates(["symbol", "date"])
K = K[~K.symbol.str.endswith("-BE")].sort_values(["symbol", "date"])
assert K.date.max() <= HI, "sealed final-test rows leaked"
cal = sorted(K.date.unique()); prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}
K["value"] = K.volume * K.close
g = K.groupby("symbol", sort=False)
K["prev_date"] = g.date.shift(1); K["p0"] = g.close.shift(1)
K["value20"] = g.value.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
K = K[K.date >= START]
K = K[K.prev_date == K.date.map(prev_of)]                       # traded on the previous market session
K["gap"] = K.open / K.p0 - 1
S = K[(K.gap <= -0.03) & (K.value20 >= 5e7)].copy()
at_band = np.any([np.abs(S.gap + b) <= 0.0025 for b in (0.05, 0.10, 0.20)], axis=0)
n_signals, n_at_band = len(S), int(at_band.sum())
S = S[~at_band]
S = S.sort_values(["date", "gap", "value20"], ascending=[True, True, False]).groupby("date").head(5)
S["ret"] = S.close / S.open - 1
S["rt"] = np.select([S.value20 >= 1e9, S.value20 >= 2.5e8], [0.0020, 0.0030], 0.0040)
S["bucket"] = np.where(S.value20 >= 2.5e8, ">Rs25cr", "Rs5-25cr")
def nw(x, lags=5):
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu; s = (e @ e) / n
    for L in range(1, lags + 1): s += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(s, 0) / n); return mu, mu - 1.96 * se, mu + 1.96 * se, mu / se
def arm(df, mult=1.0):
    net = df.ret - mult * df.rt; s = net.groupby(df.date).mean().sort_index()
    mu, lo, hi, t = nw(s.values)
    rng = np.random.default_rng(20260919); boot = np.percentile([rng.choice(s.values, len(s)).mean() for _ in range(5000)], [2.5, 97.5])
    srt = s.sort_values(ascending=False); tot = s.sum()
    return {"trades": int(len(df)), "sessions": int(len(s)), "mean_session_net_pct": 100 * mu, "ci95_nw_pct": [100 * lo, 100 * hi], "t_nw": t,
            "bootstrap95_pct": [100 * boot[0], 100 * boot[1]], "median_session_pct": 100 * s.median(), "std_session_pct": 100 * s.std(),
            "mean_trade_gross_pct": 100 * df.ret.mean(), "median_trade_net_pct": 100 * net.median(), "win_trades_pct": 100 * (net > 0).mean(),
            "win_sessions_pct": 100 * (s > 0).mean(), "worst10_sessions_pct": [round(100 * v, 3) for v in s.sort_values().head(10).values],
            "top5_share_of_total_pct": 100 * srt.head(5).sum() / tot if tot > 0 else None,
            "top10_share_of_total_pct": 100 * srt.head(10).sum() / tot if tot > 0 else None, "max_positions_in_session": int(df.groupby("date").size().max())}
res = {"test": "H-A sealed validation 2021-2022 (TRACK1_SCOPE_v2)", "run_at": dt.datetime.now().isoformat(timespec="seconds"),
       "git_sha": subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
       "spec_sha256": hashlib.sha256(open(SPEC, "rb").read()).hexdigest(),
       "cost_model": "v1 (charges 0.10% accepted as-is by the owner 2026-09-19, precondition satisfied)",
       "universe": "conditional on the available Kite historical universe (today's names only; delisted names absent)",
       "kite_symbols_in_slice": int(K.symbol.nunique()), "market_sessions_in_slice": int(sum(1 for d in cal if d >= START)),
       "signals_before_exclusion": n_signals, "excluded_open_at_band": n_at_band}
res["primary"] = arm(S); res["cost_2x"] = arm(S, 2.0)
res["by_year"] = {str(y): arm(x) for y, x in S.groupby(S.date.dt.year)}
res["by_liquidity"] = {b: arm(x) for b, x in S.groupby("bucket")}
per = S.groupby("date").size().reindex([d for d in cal if d >= START], fill_value=0)
res["entries_per_session"] = {"median_all_sessions": float(per.median()), "median_sessions_with_entries": float(per[per > 0].median()),
                              "sessions_with_entries_pct": 100 * (per > 0).mean()}
p = res["primary"]; y = res["by_year"]; lq = res["by_liquidity"]
res["abandon_checks"] = {
    "1_ci_includes_zero": p["ci95_nw_pct"][0] <= 0,
    "2_years_disagree_in_sign": ("2021" in y and "2022" in y) and (np.sign(y["2021"]["mean_session_net_pct"]) != np.sign(y["2022"]["mean_session_net_pct"])),
    "3_only_in_Rs5_25cr": (lq.get("Rs5-25cr", {}).get("ci95_nw_pct", [0])[0] > 0) and (lq.get(">Rs25cr", {}).get("ci95_nw_pct", [0])[0] <= 0),
    "4_median_entries_below_1_all_sessions": res["entries_per_session"]["median_all_sessions"] < 1,
    "5_mean_le_0_at_2x_costs": res["cost_2x"]["mean_session_net_pct"] <= 0}
res["success_rule_met"] = p["mean_session_net_pct"] > 0 and p["ci95_nw_pct"][0] > 0
res["verdict"] = "PASS" if res["success_rule_met"] and not any(res["abandon_checks"].values()) else "FAIL"
json.dump(res, open(RESULT, "w"), indent=1, default=float)
S.to_csv(f"{OUT}/HA_validation_trades.csv", index=False)
print(json.dumps(res, indent=1, default=float))
