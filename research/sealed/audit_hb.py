"""Extreme-trade audit of the sealed H-B run — required before its verdict is accepted (lesson of the H-A run).
Writes /app/research/sealed/HB_AUDIT.md. Diagnostics only; never changes the registered result."""
import json, os, numpy as np, pandas as pd
S = "/app/research/sealed"; RES = f"{S}/HB_validation_2021_2022.json"; OUT = f"{S}/HB_AUDIT.md"
if not os.path.exists(RES):
    open(OUT, "w").write("# H-B audit\n\nNo H-B result file — the sealed run did not execute (see /app/research/overnight/chain.log).\n"); raise SystemExit(0)
res = json.load(open(RES)); E = pd.read_csv(f"{S}/HB_validation_entries.csv", parse_dates=["date"]); A = pd.read_csv(f"{S}/HB_validation_all_signals.csv", parse_dates=["date"])
etfs = set(pd.read_csv(f"{S}/etf_symbols_name_contains_ETF.csv", header=None)[0])
E["etf"] = E.symbol.isin(etfs); E["net"] = E.hb_ret - E.rt
def nw(x, lags=5):
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu; s = (e @ e) / n
    for L in range(1, lags + 1): s += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(s, 0) / n); return 100 * mu, 100 * (mu - 1.96 * se), 100 * (mu + 1.96 * se), mu / se
lines = ["# H-B sealed run — extreme-trade audit", "", f"Registered verdict: **{res['verdict']}** · primary {res['primary'].get('mean_session_net_pct', float('nan')):+.3f}%/session "
         f"(CI {res['primary'].get('ci95_nw_pct')}, t {res['primary'].get('t_nw', float('nan')):.2f}) · candidates {res['candidates']} · statuses {res['status_counts']}", ""]
if len(E):
    cols = ["date", "symbol", "etf", "gap", "E", "hb_exit", "hb_reason", "hb_ret"]
    def fmt(d):
        d = d[cols].assign(date=d.date.dt.date, gap=(100 * d.gap).round(2), hb_ret=(100 * d.hb_ret).round(2))
        head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)
        return head + "\n" + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in d.itertuples(index=False))
    lines += ["## 10 best trades", fmt(E.sort_values("hb_ret", ascending=False).head(10)), "", "## 10 worst trades", fmt(E.sort_values("hb_ret").head(10)), ""]
    tot = E.net.sum()
    lines += [f"ETF entries: {int(E.etf.sum())} of {len(E)} ({100 * E.etf.mean():.1f}%); ETF share of total net P&L: {100 * E.loc[E.etf, 'net'].sum() / tot:.1f}%" if tot else "total net P&L is 0",
              f"Implausible rows: |return| > 25%: {int((E.hb_ret.abs() > 0.25).sum())}; duplicate symbol-days: {int(E.duplicated(['symbol', 'date']).sum())}",
              f"Exit reasons: {E.hb_reason.value_counts().to_dict()}", ""]
    for lab, k in [("registered (as run)", E), ("DIAGNOSTIC: ETF entries dropped", E[~E.etf])]:
        if len(k):
            s = k.groupby("date").net.mean(); mu, lo, hi, t = nw(s.values); s2 = (k.hb_ret - 2 * k.rt).groupby(k.date).mean(); m2, _, _, t2 = nw(s2.values)
            liq = {b: nw(g.groupby("date").net.mean().values) for b, g in k.groupby("bucket")}
            lines.append(f"- {lab}: {mu:+.3f}%/session CI [{lo:+.3f}, {hi:+.3f}] t {t:+.2f} · 2x costs {m2:+.3f}% (t {t2:+.2f}) · " + " · ".join(f"{b} {v[0]:+.3f}% (t {v[3]:+.2f})" for b, v in liq.items()))
lines += ["", "Section 8 (H-A vs H-B on the same signals): " + json.dumps(res.get("section8", {}), default=float), "",
          "**The verdict is accepted only if the best trades are real, executable prices and the result does not depend on ETFs.**"]
open(OUT, "w").write("\n".join(lines) + "\n"); print("\n".join(lines))
