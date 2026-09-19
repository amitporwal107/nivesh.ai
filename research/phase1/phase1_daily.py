"""Phase 1 — daily screeners A (volatility expansion), B (breakout, 20-day) and B55 (55-day), evaluated once on the
discovery period per PHASE1_PREREGISTRATION.md: labels, O/E versus a volatility-only baseline, and next-day economics."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import phase1_common as C

LABELS = ["L5_1", "L10_1", "L5_5", "L10_5", "D5_1"]
BASE_X = ["log_atr", "log_tr", "log_value20"]


def screens(d: pd.DataFrame) -> dict:
    e = d.eligible
    A = e & (d.atr_pct > d.atr_med) & (d.rvol >= 1.5) & (d.range10_pct <= 0.30) & (d.tr_ratio >= 1.5)
    common_b = e & (d.rvol >= 1.5) & (d.close_pos >= 0.75) & (d.close > d.ema20) & (d.close > d.ema50) & (d.rs20 > 0)
    return {"A": A, "B": common_b & (d.close > d.hi20), "B55": common_b & (d.close > d.hi55)}


def baseline_expected(d: pd.DataFrame, label: str) -> pd.Series:
    """Monthly-refit logistic on [log ATR%, log TR%, log value20], trained only on labels known before the month."""
    date_col = "label5_date" if label.endswith("_5") else "label1_date"
    u = d[d.eligible & d[label].notna()].copy()
    exp = pd.Series(np.nan, index=d.index)
    for m in pd.period_range(u.date.min(), u.date.max(), freq="M"):
        start = m.start_time
        tr = u[u[date_col] < start]
        te = d.index[d.eligible & (d.date >= start) & (d.date <= m.end_time)]
        if len(tr) < 5000 or tr[label].nunique() < 2 or not len(te):
            continue
        lr = LogisticRegression(C=1e6, max_iter=500).fit(tr[BASE_X], tr[label])
        exp.loc[te] = lr.predict_proba(d.loc[te, BASE_X])[:, 1]
    return exp


def oe(sig: pd.DataFrame, label: str, draws: int = 2000) -> dict:
    s = sig[sig[label].notna() & sig[f"exp_{label}"].notna()]
    if not len(s):
        return {"n": 0}
    by = s.groupby("date").agg(o=(label, "sum"), e=(f"exp_{label}", "sum"))
    r = np.random.default_rng(11)
    idx = np.arange(len(by))
    bs = [by.o.values[k].sum() / by.e.values[k].sum() for k in (r.integers(0, len(idx), len(idx)) for _ in range(draws))]
    return {"n": int(len(s)), "observed_rate": float(s[label].mean()), "expected_rate": float(s[f"exp_{label}"].mean()),
            "O_over_E": float(by.o.sum() / by.e.sum()), "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}


def main():
    d = C.build_panel()
    d["log_atr"], d["log_tr"] = np.log(d.atr_pct.clip(lower=1e-4)), np.log(d.tr_pct.clip(lower=1e-4))
    d["log_value20"] = np.log(d.value20.clip(lower=1))
    for lab in LABELS:
        d[f"exp_{lab}"] = baseline_expected(d, lab)
    ev = d[d.eligible & d.label1_date.notna()]
    report = {"data": {"rows": int(len(d)), "first_date": str(d.date.min().date()), "last_date": str(d.date.max().date()),
                       "symbols": int(d.symbol.nunique()), "eligible_stock_days": int(len(ev)),
                       "first_eligible": str(ev.date.min().date()), "sessions": int(ev.date.nunique())},
              "base_rates": {lab: float(ev[lab].mean()) for lab in LABELS}, "screens": {}}
    for name, mask in screens(d).items():
        sig = d[mask & d.label1_date.notna()].copy()
        per = sig.groupby("date").size()
        r = {"signals": int(len(sig)), "sessions_with_signal": int(per.size), "signals_per_session_median": float(per.median()) if len(per) else 0,
             "signals_per_session_max": int(per.max()) if len(per) else 0,
             "labels": {lab: {"rate": float(sig[lab].mean()), "base_rate": report["base_rates"][lab], **oe(sig, lab)} for lab in LABELS},
             "mfe1_mean_pct": float(100 * sig.mfe1.mean()), "mae1_mean_pct": float(100 * sig.mae1.mean()),
             "net1": C.session_stats(sig, "net1"), "net5": C.session_stats(sig[sig.net5.notna()], "net5")}
        r["net1_by_bucket"] = {b: C.session_stats(g, "net1") for b, g in sig.groupby("bucket")}
        r["net1_by_regime"] = {("up" if k == 1 else "down"): C.session_stats(g, "net1") for k, g in sig.dropna(subset=["regime_up"]).groupby("regime_up")}
        half = np.where(sig.date < pd.Timestamp("2025-10-01"), "2024-11..2025-09", "2025-10..2026-09")
        r["net1_by_half"] = {h: C.session_stats(g, "net1") for h, g in sig.groupby(half)}
        report["screens"][name] = r
        sig[["date", "symbol", "close", "value20", "bucket", "rvol", "atr_pct", "tr_ratio", "range10_pct", "rs20"] + LABELS
            + [f"exp_{l}" for l in LABELS] + ["mfe1", "mae1", "net1", "net5"]].to_csv(f"{C.OUT}/signals_{name}.csv", index=False)
    C.write("phase1_daily_results.json", report)
    print(pd.io.json.dumps(report, double_precision=4)[:200], "...")


if __name__ == "__main__":
    main()
