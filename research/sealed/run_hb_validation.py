"""SEALED validation test of H-B (PRIMARY endpoint, TRACK1_SCOPE_v2 + v1 sections 4-5, 8) on 2021-01-01 .. 2022-12-31. RUN ONCE.

Candidates (entry condition only, as fetched by hb_fetch.py): EQ (not -BE; ETFs INCLUDED as registered), 20-session value >= Rs 5 cr,
gap <= -3% vs previous close on Kite's adjusted daily series, open-at-a-lower-band excluded.
Per candidate day (5-minute bars): O = open of the 09:15 bar (must equal Kite's daily open, else DATA_ERROR);
P945 = close of the 09:40 bar; VWAP945 over the six completed bars 09:15..09:40, TP = (H+L+C)/3; confirm if P945 >= O x 0.995
and P945 > VWAP945. Cap: at most 5 confirmed entries per session, deepest gap first, ties -> higher value.
Entry E = open of the 09:45 bar. Exits from the 09:45 bar: bar opens <= E x 0.98 -> exit at that open; opens >= E x 1.03 -> exit at
that open; both touched -> stop; low <= stop -> stop; high >= target -> target; else official close (Kite daily close).
Missing 09:15..09:45 bars -> UNRESOLVED (never inferred, excluded from the primary). Cost model v1 round trip; 2x reported.
Success: mean per-session net > 0 and 95% NW (5 lags) lower bound > 0 (= one-sided alpha 0.025).
Abandon: (1) CI includes 0; (2) 2021 vs 2022 sign; (3) only Rs 5-25 cr; (4) median entries per session (all sessions) < 1;
(5) mean <= 0 at 2x costs. Section-8 comparisons with H-A (open->close) on the same signals are reported.
"""
import glob, hashlib, json, os, subprocess, datetime as dt
import numpy as np, pandas as pd
OUT = "/app/research/sealed"; RESULT = f"{OUT}/HB_validation_2021_2022.json"
if os.path.exists(RESULT): raise SystemExit(f"REFUSED: {RESULT} exists — the sealed test runs once.")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPEC = os.path.join(REPO, "docs/ai_research/tpd3/track1/TRACK1_SCOPE_v2.md")
HB = f"{OUT}/hb_5min_2021_2022"
st = pd.read_csv(f"{HB}/status.csv")
LO, HI, START = pd.Timestamp("2020-11-01"), pd.Timestamp("2022-12-31"), pd.Timestamp("2021-01-01")
parts = []
for f in sorted(glob.glob("/app/research/kite_history/day_2021/part-*.csv.gz")):
    for ch in pd.read_csv(f, usecols=["symbol", "date", "open", "close", "volume"], chunksize=500_000):
        ch["date"] = pd.to_datetime(ch.date); parts.append(ch[(ch.date >= LO) & (ch.date <= HI)])
K = pd.concat(parts).drop_duplicates(["symbol", "date"]); K = K[~K.symbol.str.endswith("-BE")].sort_values(["symbol", "date"])
assert K.date.max() <= HI
cal = sorted(K.date.unique()); prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}
K["value"] = K.volume * K.close; g = K.groupby("symbol", sort=False)
K["prev_date"] = g.date.shift(1); K["p0"] = g.close.shift(1)
K["value20"] = g.value.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
K = K[(K.date >= START) & (K.prev_date == K.date.map(prev_of))]; K["gap"] = K.open / K.p0 - 1
C = K[(K.gap <= -0.03) & (K.value20 >= 5e7)].copy()
C = C[~np.any([np.abs(C.gap + b) <= 0.0025 for b in (0.05, 0.10, 0.20)], axis=0)].copy()
C["dkey"] = C.date.dt.strftime("%Y-%m-%d")
fetched = st[st.status.isin(["OK", "EMPTY"])]
coverage = len(set(zip(fetched.symbol, fetched.date.astype(str))) & set(zip(C.symbol, C.dkey))) / len(C)
if coverage < 0.99: raise SystemExit(f"REFUSED: H-B 5-minute data covers only {coverage:.2%} of candidates — complete the fetch first.")
B = pd.concat(pd.read_csv(f, sep="\t", names=["symbol", "ts", "o", "h", "l", "c", "v"]) for f in sorted(glob.glob(f"{HB}/bars-*.tsv.gz")))
B["ts"] = pd.to_datetime(B.ts); B["dkey"] = B.ts.dt.strftime("%Y-%m-%d"); B["hm"] = B.ts.dt.strftime("%H:%M")
B = B.drop_duplicates(["symbol", "ts"]).sort_values(["symbol", "ts"])
bars = {k: x for k, x in B.groupby(["symbol", "dkey"], sort=False)}
OBS = ["09:15", "09:20", "09:25", "09:30", "09:35", "09:40"]
rows = []
for r in C.itertuples():
    x = bars.get((r.symbol, r.dkey)); rec = {"symbol": r.symbol, "date": r.date, "gap": r.gap, "value20": r.value20, "ha_ret": r.close / r.open - 1}
    if x is None or not set(OBS + ["09:45"]).issubset(set(x.hm)):
        rec["status"] = "UNRESOLVED_MISSING_BARS"; rows.append(rec); continue
    xo = x[x.hm.isin(OBS)]; O = x[x.hm == "09:15"].o.iloc[0]
    if abs(O / r.open - 1) > 1e-6: rec["status"] = "DATA_ERROR_OPEN"; rows.append(rec); continue
    vol = xo.v.sum()
    if vol <= 0: rec["status"] = "UNRESOLVED_NO_VOLUME"; rows.append(rec); continue
    vwap = ((xo.h + xo.l + xo.c) / 3 * xo.v).sum() / vol; p945 = xo[xo.hm == "09:40"].c.iloc[0]
    rec.update(O=O, p945=p945, vwap945=vwap, low_0915_0945=xo.l.min(), mae_pre=xo.l.min() / O - 1, recovery=p945 / xo.l.min() - 1, vwap_dist=p945 / vwap - 1)
    if not (p945 >= O * 0.995 and p945 > vwap):
        rec["status"] = "NO_ENTRY_" + ("BOTH" if p945 < O * 0.995 and p945 <= vwap else "DRAWDOWN" if p945 < O * 0.995 else "BELOW_VWAP"); rows.append(rec); continue
    post = x[x.hm >= "09:45"]; E = post.o.iloc[0]; S, T = E * 0.98, E * 1.03; exit_px, reason = None, None
    for b in post.itertuples():
        if b.o <= S: exit_px, reason = b.o, "STOP_GAP"; break
        if b.o >= T: exit_px, reason = b.o, "TARGET_GAP"; break
        if b.l <= S and b.h >= T: exit_px, reason = S, "STOP"; break
        if b.l <= S: exit_px, reason = S, "STOP"; break
        if b.h >= T: exit_px, reason = T, "TARGET"; break
    if exit_px is None: exit_px, reason = r.close, "TIME"
    rec.update(status="CONFIRMED", E=E, exit_reason=reason, hb_ret=exit_px / E - 1, hb_close_only=r.close / E - 1,
               mfe=post.h.max() / E - 1, mae=post.l.min() / E - 1)
    rows.append(rec)
R = pd.DataFrame(rows)
R["rt"] = np.select([R.value20 >= 1e9, R.value20 >= 2.5e8], [0.0020, 0.0030], 0.0040)
R["bucket"] = np.where(R.value20 >= 2.5e8, ">Rs25cr", "Rs5-25cr")
conf = R[R.status == "CONFIRMED"].sort_values(["date", "gap", "value20"], ascending=[True, True, False])
entries = conf.groupby("date").head(5).copy()
def nw(x, lags=5):
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu; s = (e @ e) / n
    for L in range(1, lags + 1): s += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(s, 0) / n); return mu, mu - 1.96 * se, mu + 1.96 * se, mu / se
def arm(df, col, mult=1.0):
    if not len(df): return {"trades": 0}
    net = df[col] - mult * df.rt; s = net.groupby(df.date).mean().sort_index(); mu, lo, hi, t = nw(s.values)
    rng = np.random.default_rng(20260919); boot = np.percentile([rng.choice(s.values, len(s)).mean() for _ in range(5000)], [2.5, 97.5])
    srt = s.sort_values(ascending=False); tot = s.sum()
    return {"trades": int(len(df)), "sessions": int(len(s)), "mean_session_net_pct": 100 * mu, "ci95_nw_pct": [100 * lo, 100 * hi], "t_nw": t,
            "bootstrap95_pct": [100 * boot[0], 100 * boot[1]], "median_session_pct": 100 * s.median(), "std_session_pct": 100 * s.std(),
            "median_trade_net_pct": 100 * net.median(), "win_sessions_pct": 100 * (s > 0).mean(),
            "worst10_sessions_pct": [round(100 * v, 3) for v in s.sort_values().head(10).values],
            "top5_share_pct": 100 * srt.head(5).sum() / tot if tot > 0 else None, "top10_share_pct": 100 * srt.head(10).sum() / tot if tot > 0 else None,
            "max_positions_in_session": int(df.groupby("date").size().max())}
res = {"test": "H-B sealed validation 2021-2022 (PRIMARY; TRACK1_SCOPE_v2)", "run_at": dt.datetime.now().isoformat(timespec="seconds"),
       "git_sha": subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
       "spec_sha256": hashlib.sha256(open(SPEC, "rb").read()).hexdigest(), "cost_model": "v1 (accepted as-is by the owner)",
       "universe": "conditional on the available Kite historical universe; ETFs included as registered",
       "candidates": int(len(R)), "status_counts": R.status.value_counts().to_dict(), "data_coverage_pct": 100 * coverage}
res["primary"] = arm(entries, "hb_ret"); res["cost_2x"] = arm(entries, "hb_ret", 2.0)
res["by_year"] = {str(y): arm(x, "hb_ret") for y, x in entries.groupby(entries.date.dt.year)}
res["by_liquidity"] = {b: arm(x, "hb_ret") for b, x in entries.groupby("bucket")}
res["exit_reasons_pct"] = (100 * entries.exit_reason.value_counts(normalize=True)).round(2).to_dict()
per = entries.groupby("date").size().reindex([d for d in cal if d >= START], fill_value=0)
res["entries_per_session"] = {"median_all_sessions": float(per.median()), "median_sessions_with_entries": float(per[per > 0].median()) if (per > 0).any() else 0.0,
                              "sessions_with_entries_pct": 100 * (per > 0).mean()}
resolved = R[~R.status.str.startswith(("UNRESOLVED", "DATA_ERROR"))]
rej = resolved[resolved.status.str.startswith("NO_ENTRY")]
res["section8"] = {"ha_signals_resolved": int(len(resolved)), "confirmed_pct_of_signals": 100 * (resolved.status == "CONFIRMED").mean(),
                   "ha_close_only_on_rejected_signals_pct": 100 * (rej.ha_ret - rej.rt).mean() if len(rej) else None,
                   "ha_close_only_on_confirmed_signals_pct": 100 * (conf.ha_ret - conf.rt).mean() if len(conf) else None,
                   "hb_close_only_on_entries_pct": 100 * (entries.hb_close_only - entries.rt).mean() if len(entries) else None,
                   "mean_mae_before_confirmation_pct": 100 * conf.mae_pre.mean() if len(conf) else None}
p = res["primary"]; y = res["by_year"]; lq = res["by_liquidity"]
res["abandon_checks"] = {"1_ci_includes_zero": (p.get("ci95_nw_pct", [0])[0] <= 0),
    "2_years_disagree_in_sign": ("2021" in y and "2022" in y and np.sign(y["2021"].get("mean_session_net_pct", 0)) != np.sign(y["2022"].get("mean_session_net_pct", 0))),
    "3_only_in_Rs5_25cr": (lq.get("Rs5-25cr", {}).get("ci95_nw_pct", [0])[0] > 0) and (lq.get(">Rs25cr", {}).get("ci95_nw_pct", [0])[0] <= 0),
    "4_median_entries_below_1_all_sessions": res["entries_per_session"]["median_all_sessions"] < 1,
    "5_mean_le_0_at_2x_costs": res["cost_2x"].get("mean_session_net_pct", 0) <= 0}
res["success_rule_met"] = p.get("mean_session_net_pct", 0) > 0 and p.get("ci95_nw_pct", [0])[0] > 0
res["verdict"] = "PASS" if res["success_rule_met"] and not any(res["abandon_checks"].values()) else "FAIL"
json.dump(res, open(RESULT, "w"), indent=1, default=float)
R.to_csv(f"{OUT}/HB_validation_all_signals.csv", index=False); entries.to_csv(f"{OUT}/HB_validation_entries.csv", index=False)
print(json.dumps(res, indent=1, default=float))
