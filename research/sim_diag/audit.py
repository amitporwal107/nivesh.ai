"""Trade audit (PRD §14), root causes RC-1 (§15), Mode A signal diagnostics (§7), configuration-A exposure audit and
the scorecard (§13, metrics only: no grades without a frozen rubric)."""
from __future__ import annotations

import numpy as np
import pandas as pd

RC1_ORDER = ("DATA_FAILURE", "SIMULATION_FAILURE", "RISK_FAILURE", "LIQUIDITY_FAILURE", "ENTRY_FAILURE", "VOLATILITY_TRAP",
             "STOP_FAILURE", "DIRECTION_FAILURE", "TARGET_FAILURE", "SIGNAL_FAILURE", "COST_FAILURE", "ALLOCATION_FAILURE")
STOPPED = ("STOP_HIT", "GAP_THROUGH_STOP")
RC1_VERSION = "RC-1 (PRD v1.0 §15)"
SEED_RANDOM = 20260920
RANDOM_SEEDS = 200


def rc1(t: dict, data_fail: bool, data_flags: bool, unexplained: bool) -> list:
    """Every RC-1 rule the losing trade matches, in the frozen order (the first is the primary cause).

    Readings: "reached later" = a bar after the exit bar within s1..s5 (an ambiguous exit bar is flagged separately);
    moves are measured from the intended entry (the raw s1 open); "loss" = net ₹ <= 0."""
    out = []
    base = float(t["intended_entry"])
    tgt = float(t["initial_target"]) / base - 1 if t.get("initial_target") is not None else None
    stopped = t["exit_reason"] in STOPPED
    expired = t["exit_reason"] == "TIME_EXIT"
    if data_fail or data_flags:
        out.append("DATA_FAILURE")
    if unexplained:
        out.append("SIMULATION_FAILURE")
    if t.get("initial_risk_inr") and -float(t["net_inr"]) > 1.5 * float(t["initial_risk_inr"]):
        out.append("RISK_FAILURE")
    if t["fill_status"] == "PARTIAL":
        out.append("LIQUIDITY_FAILURE")
    if float(t["next_session_open"]) > float(t["signal_close"]) * 1.02 and float(t["net_inr"]) < 0:
        out.append("ENTRY_FAILURE")
    if stopped and tgt is not None and t["high_after_exit_pct"] is not None and t["high_after_exit_pct"] >= tgt - 1e-12:
        out.append("VOLATILITY_TRAP")
    if stopped and t["stop_distance_atr"] is not None and t["stop_distance_atr"] < 1.0:
        out.append("STOP_FAILURE")
    if stopped and tgt is not None and t["path_max_high_pct"] < tgt and t["close_last_pct"] < 0:
        out.append("DIRECTION_FAILURE")
    if expired and tgt is not None and 0.025 <= t["path_max_high_pct"] < tgt:
        out.append("TARGET_FAILURE")
    if expired and t["path_max_high_pct"] < 0.02 and t["path_min_low_pct"] > -0.02:
        out.append("SIGNAL_FAILURE")
    if float(t["gross_inr"]) > 0 and float(t["net_inr"]) <= 0:
        out.append("COST_FAILURE")
    return out


def raw_bar_check(t: dict, raw_sym: pd.DataFrame) -> tuple[str, str]:
    """Third, plain re-derivation of a configuration-A trade from the RAW bars (duplicates kept): the entry is the s1
    open, no earlier bar reached a level, and the exit bar offered the exit level. Returns (PASS|FAIL, reason)."""
    if t.get("status") != "CLOSED":
        return "FAIL", "not closed"
    stop, tgt = float(t["initial_stop"]), float(t["initial_target"])
    bars = raw_sym[(raw_sym.date >= pd.Timestamp(t["entry_date"])) & (raw_sym.date <= pd.Timestamp(t["exit_date"]))]
    if bars.duplicated("date").any():
        return "FAIL", "duplicate raw bars inside the trade"
    if not len(bars) or bars.date.iloc[0] != pd.Timestamp(t["entry_date"]):
        return "FAIL", "no raw s1 bar"
    if abs(bars.open.iloc[0] - float(t["intended_entry"])) > 1e-9:
        return "FAIL", "entry is not the raw s1 open"
    for _, b in bars.iloc[:-1].iterrows():
        if b.low <= stop * (1 + 1e-12) or b.high >= tgt * (1 - 1e-12):
            return "FAIL", f"a level was reached earlier on {b.date.date()}"
    x = bars.iloc[-1]
    lvl = float(t["exit_level"])
    reason = t["exit_detail"]
    if reason in ("GAP_THROUGH", "GAP_OVER_TARGET") and abs(x.open - lvl) > 1e-9:
        return "FAIL", "gap exit is not the raw open"
    if reason == "TIME" and abs(x.close - lvl) > 1e-9:
        return "FAIL", "time exit is not the raw close"
    if reason in ("STOP", "TARGET") and not (x.low - 1e-9 <= lvl <= x.high + 1e-9):
        return "FAIL", "exit level outside the raw bar"
    return "PASS", ""


def audit_rows(trades: list, ranks: dict, probs: dict, dq_fail: dict, dq_flag: dict, recon: dict, raw_by_symbol: dict) -> pd.DataFrame:
    rows = []
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        key = (t["symbol"], pd.Timestamp(t["decision_date"]))
        bars = [(t["symbol"], pd.Timestamp(d)) for d in t["bars_used"]] + [key]
        fail = any(dq_fail.get(k) for k in bars)
        flags = sorted({f for k in bars for f in dq_flag.get(k, [])})
        rec = recon.get(key, {})
        unexplained = any(c in (rec.get("classes") or "") for c in ("UNEXPLAINED", "LOCKED_LOWER_HEURISTIC"))
        causes = rc1(t, fail, bool(flags), unexplained) if float(t["net_inr"]) <= 0 else []
        no_flag = [c for c in causes if c != "DATA_FAILURE" or fail]
        raw_status, raw_reason = raw_bar_check(t, raw_by_symbol[t["symbol"]])
        rows.append({
            "trade_id": f"A-{pd.Timestamp(t['decision_date']):%Y%m%d}-{t['symbol']}", "config": t["config"],
            "signal_date": t["decision_date"], "entry_date": t["entry_date"], "symbol": t["symbol"], "model_rank": ranks.get(key),
            "movement_probability": probs.get(key, {}).get("movement"), "tbs_probability": probs.get(key, {}).get("tbs"),
            "entry_method": t["entry_method"], "signal_close": float(t["signal_close"]), "gap_pct": t["gap_pct"],
            "intended_entry": float(t["intended_entry"]), "actual_entry": float(t["actual_entry"]),
            "slippage_bps_in": t["slippage_bps_in"], "initial_stop": float(t["initial_stop"]),
            "initial_target": float(t["initial_target"]), "quantity": t["fill_quantity"],
            "initial_risk_inr": float(t["initial_risk_inr"]), "stop_distance_atr": t["stop_distance_atr"],
            "mfe_pct": t["mfe_pct"], "mae_pct": t["mae_pct"], "path_max_high_pct": t["path_max_high_pct"],
            "path_min_low_pct": t["path_min_low_pct"], "close_last_pct": t["close_last_pct"],
            "exit_date": t["exit_date"], "exit_session": t["exit_session"], "exit_level": float(t["exit_level"]),
            "exit_price": float(t["exit_price"]), "exit_reason": t["exit_reason"], "exit_detail": t["exit_detail"],
            "intrabar_ambiguous": t["intrabar_ambiguous"], "gross_inr": float(t["gross_inr"]),
            "slippage_inr": float(t["slippage_inr"]), "charges_inr": float(t["charges_inr"]), "net_inr": float(t["net_inr"]),
            "gross_ret": t["gross_ret"], "net_ret": t["net_ret"], "r_multiple": t["r_multiple"],
            "dq_status": "FAIL" if fail else ("FLAGGED" if flags else "PASS"), "dq_flags": ";".join(flags),
            "execution_status": "FILLED" if t["fill_status"] == "FILLED" else t["fill_status"],
            "risk_status": "OVER_1.5R" if "RISK_FAILURE" in causes else "WITHIN_PLAN",
            "reconciliation": "AGREE" if rec.get("ok") else (rec.get("classes") or "NOT_COMPARED"),
            "raw_bar_check": raw_status, "raw_bar_check_reason": raw_reason,
            "rc1_primary": causes[0] if causes else ("WIN" if float(t["net_inr"]) > 0 else "UNCLASSIFIED"),
            "rc1_primary_excl_unreviewed_flags": no_flag[0] if no_flag else ("WIN" if float(t["net_inr"]) > 0 else "UNCLASSIFIED"),
            "rc1_all": ";".join(causes), "review_status": "AUTO_CHECKED" if raw_status == "PASS" else "NEEDS_REVIEW",
        })
    return pd.DataFrame(rows)


# ---------------- Mode A (signal; no execution rules) ----------------
def forward_paths(bars: pd.DataFrame, cal: pd.DatetimeIndex, rows: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """Vectorised forward path from the s1 open for each (symbol, date) row: r1..rk (close / s1 open - 1), r_last (last
    available close), mfe / mae (best high / worst low over s1..sk), s1_low (entry-day low vs the open)."""
    wide = {c: bars.pivot(index="symbol", columns="date", values=c).reindex(columns=cal) for c in ("open", "high", "low", "close")}
    si = wide["open"].index.get_indexer(rows.symbol)
    ci = cal.get_indexer(rows.date)
    cols = ci[:, None] + np.arange(1, k + 1)
    ok = (si >= 0) & (cols[:, -1] < len(cal))
    cols = np.where(ok[:, None], cols, 0)
    O, H, L, C = (wide[c].to_numpy(float)[si[:, None], cols] for c in ("open", "high", "low", "close"))
    o = O[:, 0]
    out = pd.DataFrame(index=rows.index)
    with np.errstate(invalid="ignore", divide="ignore"):
        for j in range(k):
            out[f"r{j + 1}"] = C[:, j] / o - 1
        last = pd.DataFrame(C).ffill(axis=1).to_numpy()[:, -1]
        out["r_last"] = last / o - 1
        out["mfe"] = np.nanmax(H, axis=1) / o - 1
        out["mae"] = np.nanmin(L, axis=1) / o - 1
        out["s1_low"] = L[:, 0] / o - 1
    out.loc[~ok | np.isnan(o)] = np.nan
    return out


def _band(rank: pd.Series) -> pd.Series:
    return pd.cut(rank, [0, 5, 10, 20, np.inf], labels=["1-5", "6-10", "11-20", "21+"])


def _stats(p: pd.DataFrame) -> dict:
    r = p.r_last.dropna()
    return {"n": int(len(r)), "mean_r5": float(r.mean()) if len(r) else None, "up_rate": float((r > 0).mean()) if len(r) else None,
            "median_mfe": float(p.mfe.median()) if len(r) else None, "median_mae": float(p.mae.median()) if len(r) else None,
            "hit_plus5": float((p.mfe >= 0.05).mean()) if len(r) else None,
            "stop_touch_s1": float((p.s1_low <= -0.02).mean()) if len(r) else None}


def mode_a(pool: pd.DataFrame, paths: pd.DataFrame, dates=None) -> dict:
    """pool = the ranked eligible rows (rank, score, date, atr_pct, tradable). Paths only for tradable rows (an entry
    exists); ranks keep their place among all eligible rows, as at selection."""
    p = pool.join(paths)
    if dates is not None:
        p = p[p.date.isin(dates)]
    t = p[p.tradable.astype(bool)]
    res = {"bands": {str(b): _stats(g) for b, g in t.groupby(_band(t["rank"]), observed=False)}, "all": _stats(t)}
    dec = t.groupby("date")["score"].rank(pct=True, method="first")
    t = t.assign(decile=np.ceil(dec * 10).clip(1, 10).astype(int))
    res["deciles"] = {int(d): _stats(g) for d, g in t.groupby("decile")}
    # random 5 a day from the same eligible pool, 200 seeds
    rng = np.random.default_rng(SEED_RANDOM)
    means = []
    elig = p[["date", "tradable", "r_last"]]
    for _ in range(RANDOM_SEEDS):
        pick = elig.assign(u=rng.random(len(elig))).sort_values(["date", "u"]).groupby("date").head(5)
        r = pick.loc[pick.tradable.astype(bool), "r_last"].dropna()
        means.append(float(r.mean()))
    top = res["bands"]["1-5"]["mean_r5"]
    res["random"] = {"seeds": RANDOM_SEEDS, "seed": SEED_RANDOM, "mean_of_means": float(np.mean(means)),
                     "p05": float(np.percentile(means, 5)), "p95": float(np.percentile(means, 95)),
                     "top5_percentile": float((np.array(means) < top).mean() * 100) if top is not None else None}
    # volatility-matched: each top-5 pick vs the same day's non-top-5 tradable stocks in its ATR decile
    t = t.assign(atr_dec=t.groupby("date").atr_pct.transform(lambda s: np.ceil(s.rank(pct=True, method="first") * 10)))
    diffs = []
    for (d, a), g in t.groupby(["date", "atr_dec"]):
        picks, rest = g[g["rank"] <= 5], g[g["rank"] > 5]
        if len(picks) and len(rest):
            diffs += list(picks.r_last - rest.r_last.mean())
    diffs = pd.Series(diffs).dropna()
    res["volatility_matched"] = {"n": int(len(diffs)), "mean_excess_r5": float(diffs.mean()) if len(diffs) else None,
                                 "share_beating_matched": float((diffs > 0).mean()) if len(diffs) else None}
    rho = t.groupby("date").apply(lambda g: g.score.corr(g.atr_pct, method="spearman"), include_groups=False)
    res["score_vs_atr_spearman_mean"] = float(rho.mean())
    res["top5_atr_decile_mean"] = float(t.loc[t["rank"] <= 5, "atr_dec"].mean())
    return res


# ---------------- configuration-A exposure audit (the fixed-notional runs have no allocation) ----------------
def exposure(trades: pd.DataFrame, cal: pd.DatetimeIndex, industry: dict) -> pd.DataFrame:
    rows = []
    for d in cal[(cal >= trades.entry_date.min()) & (cal <= trades.exit_date.max())]:
        o = trades[(trades.entry_date <= d) & (trades.exit_date >= d)]
        sec = o.symbol.map(industry).value_counts()
        rows.append({"date": d, "open_trades": int(len(o)), "capital_in_use_inr": float(o.buy_value.sum()),
                     "new_trades": int((trades.entry_date == d).sum()), "exits": int((trades.exit_date == d).sum()),
                     "max_same_industry": int(sec.max()) if len(sec) else 0,
                     "top_industry": sec.index[0] if len(sec) else None,
                     "same_symbol_overlaps": int(o.symbol.duplicated().sum())})
    return pd.DataFrame(rows)


def longest_losing_streak(net: pd.Series) -> int:
    best = cur = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


def scorecard(dq: dict, trades: pd.DataFrame, audit: pd.DataFrame, modea: dict, recon: dict, expo: pd.DataFrame,
              rejected_entries: int) -> dict:
    tr = trades
    net = tr.sort_values(["exit_date", "symbol"]).net_inr.astype(float)
    cum = net.cumsum()
    gross = tr.gross_inr.astype(float)
    costs = tr.charges_inr.astype(float) + tr.slippage_inr.astype(float)
    turnover = tr.buy_value.astype(float).sum() + tr.sell_value.astype(float).sum()
    return {
        "A_data_quality": dq,
        "B_signal": {"top5_up_rate": modea["bands"]["1-5"]["up_rate"], "top5_mean_r5": modea["bands"]["1-5"]["mean_r5"],
                     "target_before_stop_rate": float((tr.exit_reason == "TARGET_HIT").mean()),
                     "target_hit_rate_5s": float((tr.path_max_high_pct >= 0.05 - 1e-12).mean()),
                     "stop_hit_rate": float(tr.exit_reason.isin(STOPPED).mean()),
                     "median_mfe": float(tr.mfe_pct.median()), "median_mae": float(tr.mae_pct.median()),
                     "bands": modea["bands"], "random": modea["random"], "volatility_matched": modea["volatility_matched"],
                     "deciles_mean_r5": {k: v["mean_r5"] for k, v in modea["deciles"].items()}},
        "C_execution": {"entry_slippage_bps_mean": float(tr.slippage_bps_in.mean()),
                        "slippage_inr": float(tr.slippage_inr.astype(float).sum()),
                        "charges_inr": float(tr.charges_inr.astype(float).sum()),
                        "gap_through_stops": int((tr.exit_reason == "GAP_THROUGH_STOP").sum()),
                        "gap_over_targets": int((tr.exit_detail == "GAP_OVER_TARGET").sum()),
                        "fill_rejections": rejected_entries, "ambiguous_bars": int(tr.intrabar_ambiguous.sum()),
                        "cost_pct_of_turnover": float(costs.sum() / turnover),
                        "cost_per_trade_pct": float((costs / tr.buy_value.astype(float)).mean()),
                        "cost_pct_of_abs_gross": float(costs.sum() / abs(gross.sum())) if gross.sum() else None,
                        "reconciliation": recon},
        "D_risk_allocation": {"trades": int(len(tr)), "net_inr": float(net.sum()), "gross_inr": float(gross.sum()),
                              "mean_net_ret": float(tr.net_ret.mean()), "mean_gross_ret": float(tr.gross_ret.mean()),
                              "realised_loss_over_planned_max": float((-tr.net_inr.astype(float) / tr.initial_risk_inr.astype(float)).max()),
                              "losses_over_1_5R": int((audit.rc1_all.str.contains("RISK_FAILURE")).sum()),
                              "largest_loss_inr": float(net.min()), "largest_win_inr": float(net.max()),
                              "longest_losing_streak": longest_losing_streak(net),
                              "max_drawdown_inr": float((cum.cummax().clip(lower=0) - cum).max()),
                              "max_concurrent_trades": int(expo.open_trades.max()),
                              "max_capital_in_use_inr": float(expo.capital_in_use_inr.max()),
                              "max_same_industry_open": int(expo.max_same_industry.max()),
                              "same_symbol_overlap_days": int((expo.same_symbol_overlaps > 0).sum())},
    }
