"""Short-term mean reversion E1–E5 — RESEARCH ONLY, not imported by any route, page or job.

User instruction 2026-09-17 after entry setups A–D failed; rules fixed in
docs/ai_research/tpd3/mean_reversion/PREREGISTRATION.md before this code was written:

    indicators(one symbol's daily bars)   → SMA20, r3, r5, CLV, RVOL, RSI2, ret20, ATR14%, ADV20
    signals(indicators + rs20_sector)     → mr_e1 … mr_e5 (liquidity and eligibility are the caller's)
    apply_cooldown(frame, flag)           → a signal blocks that symbol's next 5 sessions
    summarize / boot_ci / matched_edges / dependence / verdict → the registered statistics and pass rule
    claim_holdout(lock)                   → the one-time holdout run

Everything at T uses data through the close of T; trades enter at the T+1 open.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VARIANTS = ["mr_e1", "mr_e2", "mr_e3", "mr_e4", "mr_e5"]
COOLDOWN = 5
MIN_ADV20 = 5e7


def indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("as_of_date").reset_index(drop=True).copy()
    c, o, h, l, v = g["close"], g["open"], g["high"], g["low"], g["volume"]
    g["sma20"] = c.rolling(20, min_periods=20).mean()
    g["r3"] = c / c.shift(3) - 1
    g["r5"] = c / c.shift(5) - 1
    g["ret20"] = c / c.shift(20) - 1
    rng = h - l
    g["clv"] = ((c - l) / rng).where(rng > 0)
    g["rvol"] = v / v.shift(1).rolling(20, min_periods=20).mean()
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    g["rsi2"] = rsi.where(loss > 0, 100.0).where(d.notna() | (g.index > 0))
    g["rsi2_prev"] = g["rsi2"].shift(1)
    g["low_prev"] = l.shift(1)
    prev_c = c.shift(1)
    tr = pd.concat([rng, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    g["atr14_pct"] = tr.rolling(14, min_periods=14).mean() / c
    g["adv20"] = (c * v).shift(1).rolling(20, min_periods=20).mean()
    g["locked"] = rng <= 0
    return g


def signals(x: pd.DataFrame) -> pd.DataFrame:
    """Row-wise only (every lag is built per symbol in indicators). Needs rs20_sector."""
    x = x.copy()
    above = x["close"] > x["sma20"]
    d3 = (x["r3"] <= -0.04) & above
    d5 = (x["r5"] <= -0.05) & above
    stab = (x["clv"] >= 0.25) & (x["rvol"] <= 1.5)
    x["mr_e1"] = d3 & stab
    x["mr_e2"] = d5 & stab
    x["mr_e3"] = d3 & (x["rsi2_prev"] <= 10) & (x["rsi2"] > x["rsi2_prev"])
    x["mr_e4"] = d3 & (x["rs20_sector"] > 0)
    x["mr_e5"] = d3 & (x["low"] < x["low_prev"]) & (x["close"] > x["open"]) & (x["clv"] >= 0.60)
    for k in VARIANTS:
        x[k] = x[k].fillna(False).astype(bool) & ~x["locked"]
    return x


def apply_cooldown(df: pd.DataFrame, flag: str, sessions: int = COOLDOWN) -> pd.Index:
    """Index labels of the signals kept: per symbol in session order, a kept signal at i blocks i+1..i+sessions."""
    kept = []
    f = df[df[flag]].sort_values(["symbol", "sess_i"], kind="mergesort")
    last_sym, last_i = None, None
    for idx, sym, i in zip(f.index, f["symbol"], f["sess_i"]):
        if sym != last_sym:
            last_sym, last_i = sym, None
        if last_i is None or i - last_i > sessions:
            kept.append(idx); last_i = i
    return pd.Index(kept)


def summarize(t: pd.DataFrame) -> dict:
    if len(t) == 0:
        return {"trades": 0}
    n = t["net5"]
    gains, losses = n[n > 0].sum(), -n[n < 0].sum()
    per_date = t.groupby("as_of_date")["net5"].mean().sort_index().cumsum()
    curve = np.r_[0.0, per_date.to_numpy()]
    return {"trades": int(len(t)), "dates": int(t["as_of_date"].nunique()), "symbols": int(t["symbol"].nunique()),
            "mean_net": float(n.mean()), "median_net": float(n.median()), "win_rate": float((n > 0).mean()),
            "profit_factor": float(gains / losses) if losses > 0 else None,
            "return_volatility": float(n.std(ddof=1)) if len(t) > 1 else None,
            "max_drawdown": float((curve - np.maximum.accumulate(curve)).min()),
            "mfe5_mean": float(t["mfe5"].mean()), "mae5_mean": float(t["mae5"].mean()),
            "net_by_horizon": {h: float(t[f"net{h}"].mean()) for h in ("1", "3", "5")}}


def boot_ci(t: pd.DataFrame, col: str, level: float, n: int = 2000, seed: int = 7) -> list:
    by = t.groupby("as_of_date")[col].agg(["sum", "count"])
    if len(by) < 2:
        return [None, None]
    idx = np.random.default_rng(seed).integers(0, len(by), size=(n, len(by)))
    s, c = by["sum"].to_numpy(), by["count"].to_numpy()
    stats = s[idx].sum(1) / c[idx].sum(1)
    a = (1 - level) / 2 * 100
    return [float(np.percentile(stats, a)), float(np.percentile(stats, 100 - a))]


def matched_edges(trades: pd.DataFrame, pool: pd.DataFrame, min_cell: int = 3) -> pd.DataFrame:
    """Per trade: net5 minus the mean net5 of pool rows (eligible, non-signal) on the same date, sector, turnover band and ATR
    quintile; falls back to date x band x ATR quintile; left out when both cells hold fewer than min_cell rows."""
    full = pool.groupby(["as_of_date", "sector", "band", "atr_q"])["net5"].agg(["mean", "count"])
    part = pool.groupby(["as_of_date", "band", "atr_q"])["net5"].agg(["mean", "count"])
    out = []
    for r in trades.itertuples(index=False):
        key = (r.as_of_date, r.sector, r.band, r.atr_q)
        if isinstance(r.sector, str) and key in full.index and full.loc[key, "count"] >= min_cell:
            out.append((r.as_of_date, r.symbol, r.net5 - full.loc[key, "mean"], "sector"))
            continue
        k2 = (r.as_of_date, r.band, r.atr_q)
        if k2 in part.index and part.loc[k2, "count"] >= min_cell:
            out.append((r.as_of_date, r.symbol, r.net5 - part.loc[k2, "mean"], "fallback"))
    return pd.DataFrame(out, columns=["as_of_date", "symbol", "edge", "cell"])


def dependence(t: pd.DataFrame) -> dict:
    share = t["symbol"].value_counts(normalize=True)
    top_sector = t.groupby(t["sector"].fillna("UNKNOWN"))["net5"].sum().idxmax()
    no_sector = t[t["sector"].fillna("UNKNOWN") != top_sector]
    top_dates = t.groupby("as_of_date")["net5"].sum().nlargest(5).index
    no_dates = t[~t["as_of_date"].isin(top_dates)]
    return {"max_symbol_share": float(share.max()), "top_symbol": str(share.idxmax()), "top_sector": str(top_sector),
            "mean_without_top_sector": float(no_sector["net5"].mean()) if len(no_sector) else None,
            "mean_without_top5_dates": float(no_dates["net5"].mean()) if len(no_dates) else None}


def verdict(v: dict) -> dict:
    def pos(x):
        return x is not None and x > 0
    checks = {
        "1_trades_ge_200": v["trades"] >= 200,
        "2_mean_net_gt_0": pos(v["mean_net"]),
        "3_ci_lower_gt_0": v["ci"][0] is not None and v["ci"][0] > 0,
        "4_beats_b1_and_same_stock": v["mean_net"] is not None and v["b1_mean"] is not None and v["mean_net"] > v["b1_mean"] and pos(v["edge_b2"]),
        "5_both_halves_gt_0": pos(v["half1_mean"]) and pos(v["half2_mean"]),
        "6_matched_edge_ci_lower_gt_0": pos(v["b3_edge"]) and v["b3_ci"][0] is not None and v["b3_ci"][0] > 0,
        "7_no_dependence": v["max_symbol_share"] is not None and v["max_symbol_share"] <= 0.10 and pos(v["mean_without_top_sector"]) and pos(v["mean_without_top5_dates"]),
        "8_survives_extra_slippage": pos(v["mean_net_extra_slippage"]),
    }
    return {"passed": all(checks.values()), "checks": {k: bool(ok) for k, ok in checks.items()},
            "failed": [k for k, ok in checks.items() if not ok]}


class HoldoutAlreadyRun(RuntimeError):
    pass


def claim_holdout(lock: Path, script_sha256: str, variants: list[str]) -> dict:
    rec = {"claimed_at": datetime.now(timezone.utc).isoformat(), "script_sha256": script_sha256, "variants": list(variants)}
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise HoldoutAlreadyRun(f"holdout already run: {lock.read_text()}")
    with os.fdopen(fd, "w") as fh:
        json.dump(rec, fh, indent=2)
    return rec
