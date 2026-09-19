"""Extreme-trade audit of the sealed H-B run — required before its verdict is accepted (lesson of the H-A run).
Writes /app/research/sealed/HB_AUDIT.md. Diagnostics only; never changes the registered result."""
import glob, json, os, numpy as np, pandas as pd
S = "/app/research/sealed"; RES = f"{S}/HB_validation_2021_2022.json"; OUT = f"{S}/HB_AUDIT.md"
if not os.path.exists(RES):
    open(OUT, "w").write("# H-B audit\n\nNo H-B result file — the sealed run did not execute (see /app/research/overnight/chain.log).\n"); raise SystemExit(0)
res = json.load(open(RES)); E = pd.read_csv(f"{S}/HB_validation_entries.csv", parse_dates=["date"]); A = pd.read_csv(f"{S}/HB_validation_all_signals.csv", parse_dates=["date"])
etfs = set(pd.read_csv(f"{S}/etf_symbols_name_contains_ETF.csv", header=None)[0]) | set(pd.read_csv(f"{S}/etf_symbols_kite_20260919.csv", header=None)[0])
E["etf"] = E.symbol.isin(etfs); E["net"] = E.hb_ret - E.rt
def nw(x, lags=5):
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu; s = (e @ e) / n
    for L in range(1, lags + 1): s += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(s, 0) / n); return 100 * mu, 100 * (mu - 1.96 * se), 100 * (mu + 1.96 * se), mu / se
lines = ["# H-B sealed run — extreme-trade audit", "", f"Registered verdict: **{res['verdict']}** · primary {res['primary'].get('mean_session_net_pct', float('nan')):+.3f}%/session "
         f"(CI {res['primary'].get('ci95_nw_pct')}, t {res['primary'].get('t_nw', float('nan')):.2f}) · candidates {res['candidates']} · statuses {res['status_counts']}", ""]
if len(E):
    cols = ["date", "symbol", "etf", "gap", "O", "p945", "E", "exit_reason", "hb_ret", "hb_close_only"]
    def fmt(d):
        d = d[cols].assign(date=d.date.dt.date, gap=(100 * d.gap).round(2), hb_ret=(100 * d.hb_ret).round(2), hb_close_only=(100 * d.hb_close_only).round(2))
        head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)
        return head + "\n" + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in d.itertuples(index=False))
    lines += ["## 10 best trades", fmt(E.sort_values("hb_ret", ascending=False).head(10)), "", "## 10 worst trades", fmt(E.sort_values("hb_ret").head(10)), ""]
    tot = E.net.sum()
    lines += [f"ETF entries: {int(E.etf.sum())} of {len(E)} ({100 * E.etf.mean():.1f}%); ETF share of total net P&L: {100 * E.loc[E.etf, 'net'].sum() / tot:.1f}%" if tot else "total net P&L is 0",
              f"Implausible rows: |return| > 25%: {int((E.hb_ret.abs() > 0.25).sum())}; duplicate symbol-days: {int(E.duplicated(['symbol', 'date']).sum())}",
              f"Exit reasons: {E.exit_reason.value_counts().to_dict()}", ""]
    for lab, k in [("registered (as run)", E), ("DIAGNOSTIC: ETF entries dropped", E[~E.etf])]:
        if len(k):
            s = k.groupby("date").net.mean(); mu, lo, hi, t = nw(s.values); s2 = (k.hb_ret - 2 * k.rt).groupby(k.date).mean(); m2, _, _, t2 = nw(s2.values)
            liq = {b: nw(g.groupby("date").net.mean().values) for b, g in k.groupby("bucket")}
            lines.append(f"- {lab}: {mu:+.3f}%/session CI [{lo:+.3f}, {hi:+.3f}] t {t:+.2f} · 2x costs {m2:+.3f}% (t {t2:+.2f}) · " + " · ".join(f"{b} {v[0]:+.3f}% (t {v[3]:+.2f})" for b, v in liq.items()))
    # Executability: entry and exit must lie inside Kite's daily [low, high]; entry bar must have traded.
    D = pd.concat(ch[ch.symbol.isin(set(E.symbol))] for f in sorted(glob.glob("/app/research/kite_history/day_2021/part-*.csv.gz"))
                  for ch in pd.read_csv(f, usecols=["symbol", "date", "high", "low", "close"], chunksize=500_000))
    D["date"] = pd.to_datetime(D.date); D = D.drop_duplicates(["symbol", "date"])
    X = E.merge(D, on=["symbol", "date"], how="left"); X["exitp"] = X.E * (1 + X.hb_ret); tol = 1e-6
    bad_e = ((X.E < X.low * (1 - tol)) | (X.E > X.high * (1 + tol))).sum(); bad_x = ((X.exitp < X.low * (1 - tol)) | (X.exitp > X.high * (1 + tol))).sum()
    B = pd.concat(pd.read_csv(f, sep="\t", names=["symbol", "ts", "o", "h", "l", "c", "v"]) for f in sorted(glob.glob(f"{S}/hb_5min_2021_2022/bars-*.tsv.gz")))
    B["ts"] = pd.to_datetime(B.ts); B = B[B.ts.dt.strftime("%H:%M") == "09:45"].drop_duplicates(["symbol", "ts"]); B["date"] = B.ts.dt.normalize()
    V = E.merge(B[["symbol", "date", "v"]], on=["symbol", "date"], how="left")
    lines += [f"Executability: entries outside the daily [low, high]: {int(bad_e)}; exits outside it: {int(bad_x)}; daily bar missing: {int(X.high.isna().sum())}; "
              f"09:45 entry bars with zero volume: {int((V.v == 0).sum())}; missing 09:45 bar: {int(V.v.isna().sum())}", ""]
    # Decomposition: is it the entry or the stop/target grid?  (hb_close_only = 09:45 entry held to the official close)
    for lab, col in [("09:45 entry held to close, no stop/target (cap as registered)", "hb_close_only")]:
        s = (E[col] - E.rt).groupby(E.date).mean(); mu, lo, hi, t = nw(s.values)
        lines.append(f"- DIAGNOSTIC {lab}: {mu:+.3f}%/session CI [{lo:+.3f}, {hi:+.3f}] t {t:+.2f}")
    C = A[A.status == "CONFIRMED"].copy(); C["net"] = C.hb_ret - C.rt; C["etf"] = C.symbol.isin(etfs)
    for lab, k in [("all confirmed entries, NO 5-position cap", C), ("all confirmed, no cap, ETFs dropped", C[~C.etf])]:
        s = k.groupby("date").net.mean(); mu, lo, hi, t = nw(s.values)
        lines.append(f"- DIAGNOSTIC {lab}: {len(k)} trades, {s.size} sessions, {mu:+.3f}%/session CI [{lo:+.3f}, {hi:+.3f}] t {t:+.2f}")
    R = A[A.status.isin(["NO_ENTRY_BELOW_VWAP", "NO_ENTRY_BOTH", "NO_ENTRY_DRAWDOWN"])]
    lines += [f"- Confirmed signals: exit mix {C.exit_reason.value_counts(normalize=True).round(3).to_dict()}; mean gross {100 * C.hb_ret.mean():+.3f}%, mean MFE {100 * C.mfe.mean():+.3f}%, mean MAE {100 * C.mae.mean():+.3f}%",
              f"- H-A open->close (gross): confirmed {100 * C.ha_ret.mean():+.3f}% vs rejected {100 * R.ha_ret.mean():+.3f}% (n {len(C)} / {len(R)})", ""]
lines += ["", "Section 8 (H-A vs H-B on the same signals): " + json.dumps(res.get("section8", {}), default=float), "",
          "**The verdict is accepted only if the best trades are real, executable prices and the result does not depend on ETFs.**"]
open(OUT, "w").write("\n".join(lines) + "\n"); print("\n".join(lines))
