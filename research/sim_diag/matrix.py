"""Comparison matrix (deliverable D5), exactly as pre-registered in
docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md (frozen at ffa0a139).

Eight runs on one selection, one universe and one set of frozen predictions, each changing ONE thing against
configuration A (the reconciled H#32 baseline): B the stop/target, C the entry, D risk sizing, E costs, F the full
risk engine, G random selection, H no stop or target at all. Four secondary rows (S1-S4) and the whole-pool run (S5)
sit below them.

Nothing here selects a rule. Every number is descriptive, on development data that has already been used; a
configuration that looks better is a candidate for a fresh pre-registration, never a result (owner policy, TPD model
success gates 2026-09-19).

Runs A, B, C, E, G, H and S1-S5 are trade-isolated (tradesim, fixed 50,000 a trade). Runs D and F go through the
portfolio loop in tpd_model/risk/engine.py, which sizes on risk and can refuse a candidate.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal as D

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit as AU  # noqa: E402
import tradesim as TS  # noqa: E402

sys.path.insert(0, TS.BACKEND)
from nidp.services.tpd_model.risk import config as RCFG  # noqa: E402
from nidp.services.tpd_model.risk import engine as EN  # noqa: E402

PREREG = "PREREGISTRATION_SIM_MATRIX.md @ ffa0a139"
SEED_RANDOM, RANDOM_SEEDS, BOOT_REPS, TOP_K = 20260920, 200, 2000, 5
STOPPED = ("STOP_HIT", "GAP_THROUGH_STOP")

# ---- §4: the matrix. Every parameter is the pre-registered one; `frozen` marks that. ----
MATRIX = {
    "A": TS.CONFIG_A,
    "B": TS.Spec("B", stop="ATR", target="R_MULTIPLE", atr_mult=D("1.5"), target_r=D("2"), frozen=True),
    "C": TS.Spec("C", entry="OPEN_CONFIRMATION", confirm_buffer_pct=D("0.1"), frozen=True),
    "E": TS.Spec("E", costs_on=False, frozen=True),
    "H": TS.Spec("H", stop="NONE", target="NONE", frozen=True),
}
SECONDARY = {
    "S1_STRUCTURE": TS.Spec("S1_STRUCTURE", stop="STRUCTURE", target="R_MULTIPLE", structure_buffer_pct=D("0.1"),
                            stop_bounds_pct=(D("1"), D("8")), target_r=D("2"), frozen=True),
    "S2_VOL_ADJ": TS.Spec("S2_VOL_ADJ", stop="VOL_ADJ", target="R_MULTIPLE", vol_mult=D("1.5"),
                          stop_bounds_pct=(D("1"), D("8")), target_r=D("2.5"), frozen=True),
    "S3_LIMIT": TS.Spec("S3_LIMIT", entry="LIMIT_ENTRY", limit_discount_pct=D("0.5"), frozen=True),
    "S4_VWAP": TS.Spec("S4_VWAP", entry="VWAP_PROXY", frozen=True),
}
POOL = TS.Spec("S5_POOL", frozen=True)                      # configuration A's rules, on every eligible candidate
PORTFOLIO = {"D": "SIM-MATRIX-D", "F": "SIM-MATRIX-F"}
RISK_LEVELS = (D("0.5"), D("1.0"), D("2.0"))                # §4b sensitivity; the baseline is 0.5% with 8 positions
F_POSITIONS = (8, 5)
EXITS = {"breakeven_at_r": D("1000000"), "trail_at_r": D("1000000"), "trail_atr_mult": D("2"), "max_sessions": 5,
         "cost_estimate_pct_for_sizing": D("0.5")}          # breakeven and trailing are off: the matrix has neither


# ---------------- trade-isolated runs ----------------

def simulate_rows(spec: TS.Spec, rows: pd.DataFrame, store, ds: pd.DataFrame, cm) -> list:
    """Every row of `rows` (a dataset slice with symbol and date) under one specification."""
    out = []
    for idx, r in rows.iterrows():
        w = store.window(r.symbol, r.date, float(ds.at[idx, "atr_pct"]))
        t = TS.simulate(spec, w, cm)
        t["row"] = idx
        out.append(t)
    return out


def frame(trades: list) -> pd.DataFrame:
    """Closed trades as a float frame with the columns every metric below uses."""
    rows = []
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        rows.append({
            "config": t["config"], "symbol": t["symbol"], "decision_date": pd.Timestamp(t["decision_date"]),
            "entry_date": pd.Timestamp(t["entry_date"]), "exit_date": pd.Timestamp(t["exit_date"]),
            "exit_reason": t["exit_reason"], "exit_detail": t["exit_detail"], "qty": int(t["fill_quantity"]),
            "entry_method": t["entry_method"], "order_kind": t["order_kind"], "exit_session": int(t["exit_session"]),
            "signal_close": float(t["signal_close"]), "next_session_open": float(t["next_session_open"]),
            "gap_pct": float(t["gap_pct"]), "intended_entry": float(t["intended_entry"]),
            "entry_price": float(t["actual_entry"]), "exit_level": float(t["exit_level"]),
            "exit_price": float(t["exit_price"]), "fill_status": t["fill_status"],
            "stop": None if t["initial_stop"] is None else float(t["initial_stop"]),
            "target": None if t["initial_target"] is None else float(t["initial_target"]),
            "risk_reward_ratio": t["risk_reward_ratio"], "target_distance_atr": t["target_distance_atr"],
            "close_last_pct": t["close_last_pct"], "path_min_low_pct": t["path_min_low_pct"],
            "high_after_exit_pct": t["high_after_exit_pct"],
            "buy_value": float(t["fills"][0]["value"]), "sell_value": float(t["fills"][1]["value"]),
            "gross_inr": float(t["gross_inr"]), "slippage_inr": float(t["slippage_inr"]),
            "charges_inr": float(t["charges_inr"]), "net_inr": float(t["net_inr"]),
            "gross_ret": float(t["gross_ret"]), "net_ret": float(t["net_ret"]),
            "initial_risk_inr": None if t["initial_risk_inr"] is None else float(t["initial_risk_inr"]),
            "r_multiple": t["r_multiple"], "stop_distance_atr": t["stop_distance_atr"],
            "mfe_pct": t["mfe_pct"], "mae_pct": t["mae_pct"], "path_max_high_pct": t["path_max_high_pct"],
            "intrabar_ambiguous": bool(t["intrabar_ambiguous"]), "flags": t["flags"], "row": t.get("row"),
        })
    return pd.DataFrame(rows)


def rejections(trades: list) -> dict:
    r = [t for t in trades if t.get("status") != "CLOSED"]
    out = {}
    for t in r:
        k = t.get("entry_rejection_reason") or t.get("exit_reason") or t.get("status")
        out[k] = out.get(k, 0) + 1
    return out


# ---------------- metrics (§5), defined before the run ----------------

def _pf(net: pd.Series) -> float:
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    return float(pos / neg) if neg > 0 else None


def metrics(name: str, tr: pd.DataFrame, rejected: dict, cal, industry: dict, *, portfolio: bool = False,
            equity: pd.DataFrame = None, capital: float = None, exposure: bool = True) -> dict:
    """One run's numbers. `gross_ret` is pre-slippage for the trade-isolated runs and post-slippage for the engine
    runs (the engine's fills carry slippage inside the price), so only the NET figures compare across the two."""
    net = tr.sort_values(["exit_date", "symbol"]).net_inr
    cum = net.cumsum()
    m = {
        "config": name, "trades": int(len(tr)), "no_entry": int(sum(rejected.values())), "no_entry_reasons": rejected,
        "win_rate": float((tr.net_inr > 0).mean()),
        "gross_per_trade": float(tr.gross_ret.mean()), "net_per_trade": float(tr.net_ret.mean()),
        "cost_drag": float(tr.gross_ret.mean() - tr.net_ret.mean()),
        "cost_basis": ("gross is measured after slippage (it is inside the engine's fills), so the cost drag here is "
                       "statutory charges only" if portfolio else
                       "gross is measured before slippage, so the cost drag here is slippage plus statutory charges"),
        "slippage_per_trade": float((tr.slippage_inr / tr.buy_value).mean()) if tr.slippage_inr.notna().any() else None,
        "charges_per_trade": float((tr.charges_inr / tr.buy_value).mean()),
        "gross_inr": float(tr.gross_inr.sum()), "slippage_inr": float(tr.slippage_inr.sum()),
        "charges_inr": float(tr.charges_inr.sum()), "net_inr": float(tr.net_inr.sum()),
        "expectancy_inr": float(tr.net_inr.mean()), "profit_factor": _pf(tr.net_inr),
        "largest_win_inr": float(tr.net_inr.max()), "largest_loss_inr": float(tr.net_inr.min()),
        "longest_losing_streak": AU.longest_losing_streak(net),
        "exit_mix": tr.exit_reason.value_counts().to_dict(),
        "stop_hit_rate": float(tr.exit_reason.isin(STOPPED).mean()),
        "target_hit_rate": float((tr.exit_reason == "TARGET_HIT").mean()),
        "median_stop_distance_atr": float(tr.stop_distance_atr.median()) if tr.stop_distance_atr.notna().any() else None,
        "ambiguous_bars": int(tr.intrabar_ambiguous.sum()),
        "gap_through_stops": int((tr.exit_reason == "GAP_THROUGH_STOP").sum()),
        "lock_affected_trades": int(tr["flags"].fillna("").str.contains("LOCKED_LOWER").sum()),
        "median_mfe": float(tr.mfe_pct.median()), "median_mae": float(tr.mae_pct.median()),
    }
    if "rc1_primary" in tr.columns:
        m["rc1_primary"] = tr.rc1_primary.value_counts().to_dict()
        m["rc1_primary_excl_unreviewed_flags"] = tr.rc1_primary_excl_unreviewed_flags.value_counts().to_dict()
        m["rc1_net_by_cause"] = {k: float(v) for k, v in tr.groupby("rc1_primary").net_inr.sum().items()}
    if portfolio:
        eq = equity.equity.astype(float)
        m |= {"max_drawdown_inr": float((eq.cummax() - eq).max()),
              "max_drawdown_pct": float((eq.cummax() - eq).max() / capital * 100),
              "final_equity_inr": float(eq.iloc[-1]), "return_on_capital_pct": float((eq.iloc[-1] / capital - 1) * 100),
              "max_positions_open": int(equity.positions.max())}
    else:
        m |= {"worst_cumulative_net_inr": float(cum.min()),
              "worst_peak_to_trough_inr": float((cum.cummax().clip(lower=0) - cum).max())}
        if exposure:
            # the 200 random selections of run G live in parallel universes, so a capital figure over their union
            # would be meaningless; it is left out rather than reported wrong
            expo = AU.exposure(tr.assign(symbol=tr.symbol), pd.DatetimeIndex(cal), industry)
            m |= {"peak_capital_required_inr": float(expo.capital_in_use_inr.max()),
                  "max_concurrent_trades": int(expo.open_trades.max())}
        else:
            m |= {"peak_capital_required_inr": None, "max_concurrent_trades": None}
    return m


def tax_annex(net_inr: float) -> dict:
    """Illustrative only (§5a): the trades are 2022, the cost model is 2026. Tax applies only to a positive net."""
    if net_inr <= 0:
        return {"applies": False, "note": "no positive net to tax; losses are not modelled (no set-off, no carry-forward)"}
    return {"applies": True, "stcg_2022_15pct_plus_cess": net_inr * 0.15 * 1.04,
            "stcg_current_20pct_plus_cess": net_inr * 0.20 * 1.04,
            "note": "illustrative: no surcharge, no set-off, no carry-forward"}


# ---------------- paired comparison against A (§5, descriptive) ----------------

def paired_diff(a: pd.DataFrame, x: pd.DataFrame, reps: int = BOOT_REPS, seed: int = SEED_RANDOM) -> dict:
    """Mean difference in net per trade on the trades both runs entered, with a date-clustered bootstrap interval."""
    key = ["symbol", "decision_date"]
    j = a[key + ["net_ret"]].merge(x[key + ["net_ret"]], on=key, suffixes=("_a", "_x"))
    if j.empty:
        return {"n_common": 0}
    j = j.assign(diff=j.net_ret_x - j.net_ret_a)
    by_date = {d: g["diff"].to_numpy() for d, g in j.groupby("decision_date")}
    dates = np.array(sorted(by_date))
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for i in range(reps):
        pick = rng.choice(len(dates), len(dates), replace=True)
        means[i] = np.concatenate([by_date[dates[k]] for k in pick]).mean()
    return {"n_common": int(len(j)), "mean_diff": float(j["diff"].mean()),
            "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
            "share_better": float((j["diff"] > 0).mean()), "reps": reps}


# ---------------- G: random selection (§4a) ----------------

def random_picks(pool: pd.DataFrame, k: int = TOP_K, seeds: int = RANDOM_SEEDS, base: int = SEED_RANDOM) -> list:
    """`seeds` draws of k symbols a session from the eligible pool, each seed its own generator, symbols sorted first
    so the draw cannot depend on row order. Returns a list of {date: [symbols]}."""
    by_date = {d: np.array(sorted(g.symbol.unique())) for d, g in pool.groupby("date")}
    dates = sorted(by_date)
    out = []
    for s in range(seeds):
        rng = np.random.default_rng(base + s)
        out.append({d: list(rng.choice(by_date[d], size=min(k, len(by_date[d])), replace=False)) for d in dates})
    return out


def random_control(draws: list, pool_trades: pd.DataFrame, a_net_per_trade: float, *, seed_base: int = SEED_RANDOM) -> dict:
    """Each seed's mean net per trade, from the pool run's already-simulated outcomes, and A's place in them."""
    lookup = pool_trades.set_index(["decision_date", "symbol"]).net_ret
    means, counts = [], []
    for draw in draws:
        keys = [(pd.Timestamp(d), s) for d, syms in draw.items() for s in syms]
        vals = lookup.reindex(keys).dropna()
        means.append(float(vals.mean()))
        counts.append(int(len(vals)))
    means = np.array(means)
    return {"seeds": len(draws), "seed_base": seed_base,
            "picks_per_session": max((len(v) for d in draws for v in d.values()), default=0),
            "mean_trades_per_seed": float(np.mean(counts)),
            "mean_of_means": float(means.mean()), "p05": float(np.percentile(means, 5)),
            "p50": float(np.percentile(means, 50)), "p95": float(np.percentile(means, 95)),
            "min": float(means.min()), "max": float(means.max()),
            "a_percentile": float((means < a_net_per_trade).mean() * 100)}


def random_frame(draws: list, pool_trades: pd.DataFrame) -> pd.DataFrame:
    """Every drawn trade of every seed, pooled (a stock drawn by several seeds appears several times). The pooled
    frame answers "what does random selection do under A's execution rules"; the per-seed spread is random_control."""
    keys = pd.DataFrame([(pd.Timestamp(d), sym, s) for s, draw in enumerate(draws) for d, syms in draw.items() for sym in syms],
                        columns=["decision_date", "symbol", "seed"])
    return keys.merge(pool_trades, on=["decision_date", "symbol"], how="inner").assign(config="G")


# ---------------- S5: rank bands under execution ----------------

def rank_bands(pool_trades: pd.DataFrame, ranked: pd.DataFrame) -> dict:
    t = pool_trades.join(ranked["rank"], on="row")
    out = {}
    for b, g in t.groupby(AU._band(t["rank"]), observed=False):
        out[str(b)] = {"trades": int(len(g)), "net_per_trade": float(g.net_ret.mean()),
                       "gross_per_trade": float(g.gross_ret.mean()), "win_rate": float((g.net_inr > 0).mean()),
                       "stop_hit_rate": float(g.exit_reason.isin(STOPPED).mean())}
    return out


def rc1_column(trades: list, dq_fail: dict, dq_flag: dict) -> pd.DataFrame:
    """The frozen RC-1 rule set (audit.rc1) applied to every closed trade of one configuration, with the same
    data-quality inputs the D4 audit used, so a configuration's causes are comparable with the audited baseline.

    As in the audit: RC-1 explains LOSSES, so a trade with a positive net is WIN and is not classified further, and
    the primary cause is the FIRST rule the trade matches in the frozen order. `unexplained` (SIMULATION_FAILURE) is
    raised for the circuit-lock heuristic's false positives, the one simulator defect D3 found (owner decision D7)."""
    rows = []
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        d = pd.Timestamp(t["decision_date"])
        used = [pd.Timestamp(x) for x in t["bars_used"]] + [d]
        fail = any(dq_fail.get((t["symbol"], x), False) for x in used)
        flags = sorted({f for x in used for f in dq_flag.get((t["symbol"], x), [])})
        unexplained = "LOCKED_LOWER_PARTIAL" in (t.get("flags") or "")
        net = float(t["net_inr"])
        causes = AU.rc1(t, fail, bool(flags), unexplained) if net <= 0 else []
        no_flag = [c for c in causes if c != "DATA_FAILURE" or fail]
        rows.append({"symbol": t["symbol"], "decision_date": d,
                     "rc1_primary": causes[0] if causes else ("WIN" if net > 0 else "UNCLASSIFIED"),
                     "rc1_primary_excl_unreviewed_flags": no_flag[0] if no_flag else ("WIN" if net > 0 else "UNCLASSIFIED"),
                     "rc1_all": ";".join(causes), "dq_flags": ";".join(flags),
                     "dq_status": "FAIL" if fail else ("FLAGGED" if flags else "PASS")})
    return pd.DataFrame(rows)


# ---------------- extreme-trade audit (§9) ----------------

def extremes(tr: pd.DataFrame, names: dict, n: int = 10) -> dict:
    cols = ["symbol", "decision_date", "entry_date", "exit_date", "exit_reason", "qty", "buy_value", "gross_inr",
            "charges_inr", "net_inr", "net_ret", "flags"]
    def rows(df):
        d = df[cols].copy()
        d["company"] = d.symbol.map(names)
        d["etf_like"] = d.symbol.str.contains("ETF") | d.company.fillna("").str.upper().str.contains("ETF")
        for c in ("decision_date", "entry_date", "exit_date"):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
        return d.to_dict("records")
    top, bottom = tr.nlargest(n, "net_inr"), tr.nsmallest(n, "net_inr")
    share = float(pd.concat([top, bottom]).net_inr.abs().sum() / tr.net_inr.abs().sum())
    company = tr.symbol.map(names).fillna("").str.upper()
    return {"largest_gains": rows(top), "largest_losses": rows(bottom),
            "etf_like_trades": int((tr.symbol.str.contains("ETF") | company.str.contains("ETF")).sum()),
            "share_of_absolute_pnl_in_extremes": share}


# ---------------- D and F: the portfolio loop ----------------

def signals(picks: pd.DataFrame, ds: pd.DataFrame, stop_pct: float = 2.0, target_pct: float = 5.0) -> pd.DataFrame:
    """One MOO signal per pick. Sizing uses the decision close and a stop `stop_pct` below it; the engine then resets
    both levels to the same percentages of the price it actually fills at (matching configuration A)."""
    rows = []
    for idx, p in picks.iterrows():
        close = float(ds.at[idx, "close"])
        rows.append({"signal_id": f"{pd.Timestamp(p.date):%Y%m%d}-{p.symbol}", "date": p.date, "symbol": p.symbol,
                     "arm": "M8", "order_type": "MOO", "trigger": None, "valid_sessions": 1,
                     "stop": close * (1 - stop_pct / 100), "reference_price": close,
                     "atr": float(ds.at[idx, "atr_pct"]) / 100 * close, "rank": float(p.score),
                     "stop_pct": stop_pct, "target_pct": target_pct, "model_version": "M8|tbs_5_2"})
    return pd.DataFrame(rows)


def engine_frame(res, name: str, industry: dict) -> pd.DataFrame:
    t = res.trades
    if t.empty:
        return pd.DataFrame()
    buy = t.qty.astype(float) * t.entry_price.astype(float)
    return pd.DataFrame({
        "config": name, "symbol": t.symbol, "decision_date": pd.to_datetime(t.signal_id.str[:8], format="%Y%m%d"),
        "entry_date": pd.to_datetime(t.entry_date), "exit_date": pd.to_datetime(t.exit_date),
        "exit_reason": t.exit_reason.replace({"STOP": "STOP_HIT", "STOP_SAME_DAY": "STOP_HIT",
                                              "GAP_THROUGH": "GAP_THROUGH_STOP", "TARGET": "TARGET_HIT",
                                              "TARGET_SAME_DAY": "TARGET_HIT", "GAP_OVER_TARGET": "TARGET_HIT",
                                              "TIME": "TIME_EXIT", "OPEN_AT_END": "OPEN_AT_END"}),
        "exit_detail": t.exit_reason, "qty": t.qty.astype(int), "buy_value": buy,
        "sell_value": t.qty.astype(float) * t.exit_price.astype(float),
        "gross_inr": t.gross_pnl.astype(float), "slippage_inr": np.nan, "charges_inr": t.costs.astype(float),
        "net_inr": t.net_pnl.astype(float),
        "gross_ret": t.exit_price.astype(float) / t.entry_price.astype(float) - 1,
        "net_ret": t.net_pnl.astype(float) / buy,
        "initial_risk_inr": t.qty.astype(float) * (t.entry_price.astype(float) - t.initial_stop.astype(float)),
        "r_multiple": t.r_multiple, "stop_distance_atr": np.nan, "mfe_pct": np.nan, "mae_pct": np.nan,
        "path_max_high_pct": np.nan, "intrabar_ambiguous": False, "flags": "", "row": np.nan,
        "sector": t.symbol.map(industry), "realised": t.realised,
    })


def engine_rejections(res) -> dict:
    out = {}
    for d in res.decisions:
        if d["decision_status"] == "REJECTED":
            k = d["rejection_reasons"][0] if d["rejection_reasons"] else "UNKNOWN"
            out[k] = out.get(k, 0) + 1
    return out


def run_portfolio(name: str, config_id: str, sig: pd.DataFrame, prepared, cm, sectors: dict, industry: dict,
                  *, risk_pct: D = None, positions: int = None) -> tuple:
    cfg = RCFG.load_config(config_id)
    changes = {}
    if risk_pct is not None:
        changes["risk_per_trade_pct"] = risk_pct
    if positions is not None:
        changes["max_open_positions"] = positions
    if changes:
        cfg = RCFG.with_changes(cfg, **changes)
    res = EN.run(sig, None, cfg, cm, sectors, EXITS, allow_retroactive_costs=True, prepared=prepared)
    tr = engine_frame(res, name, industry)
    amb = sum(1 for e in res.ledger.records("event") if e["event_type"] == "INTRABAR_AMBIGUOUS")
    blocked = sum(1 for e in res.ledger.records("event") if e["event_type"] == "EXIT_BLOCKED")
    return res, tr, {"config_id": cfg.config_id, "risk_per_trade_pct": str(cfg.risk_per_trade_pct),
                     "max_open_positions": cfg.max_open_positions, "ambiguous_bars": amb, "exit_blocked_events": blocked,
                     "unrealised_at_end": int((~tr.realised).sum()) if len(tr) else 0}
