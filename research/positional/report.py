"""Metrics (PRD §15.4 + PREREGISTRATION.md §8) and the frozen decision rule (§7)."""
from __future__ import annotations

import collections
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase1"))
import phase1_common as C  # noqa: E402

T_MIN, MIN_TRADES = 2.4, 100


def daily_returns(equity: pd.DataFrame, capital: float) -> pd.Series:
    eq = equity.set_index("date").equity.astype(float)
    return eq.diff().fillna(eq.iloc[0] - capital) / capital


def ols_alpha(r: pd.Series, m: pd.Series, lags: int = 5) -> dict:
    """r = a + b*m; Newey-West t for a (daily alpha, in % per session)."""
    x = pd.concat([r, m], axis=1).dropna()
    if len(x) < 30:
        return {"n": len(x)}
    y, xm = x.iloc[:, 0].to_numpy(), x.iloc[:, 1].to_numpy()
    X = np.column_stack([np.ones(len(y)), xm])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ beta
    n = len(y)
    xtx_inv = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None]) / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None]) / n
        S += w * (G + G.T)
    V = n * xtx_inv @ S @ xtx_inv
    se = np.sqrt(np.diag(V))
    return {"n": n, "alpha_pct": 100 * beta[0], "beta": beta[1], "alpha_t": beta[0] / se[0] if se[0] else None}


def metrics(res, capital: float, idx: pd.DataFrame) -> dict:
    t = res.trades
    closed = t[t.realised] if len(t) else t
    r = daily_returns(res.equity, capital)
    ir = idx.set_index(idx.date.dt.date).idx_close.pct_change()
    ir = ir.reindex(r.index)
    eq = res.equity.set_index("date").equity.astype(float)
    peak = np.maximum.accumulate(np.maximum(eq.to_numpy(), capital))
    net = closed.net_pnl.astype(float) if len(closed) else pd.Series(dtype=float)
    wins, losses = net[net > 0], net[net <= 0]
    streak = best = 0
    for v in net:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    half = len(r) // 2
    val = (lambda s: float(s.sum()))
    turnover = (float((closed.qty * closed.entry_price.astype(float)).sum() + (closed.qty * closed.exit_price.astype(float)).sum())
                / capital) if len(closed) else 0.0
    rej = collections.Counter(x for dcs in res.decisions if dcs["decision_status"] == "REJECTED"
                              for x in dcs["rejection_reasons"][:1])
    return {
        "trades_closed": int(len(closed)), "trades_open_at_end": int((~t.realised).sum()) if len(t) else 0,
        "net_return_pct": 100 * float(eq.iloc[-1] - capital) / capital,
        "max_drawdown_pct": float(100 * np.max((peak - eq.to_numpy()) / peak)),
        "sharpe": float(r.mean() / r.std() * np.sqrt(250)) if r.std() > 0 else None,
        "nw_daily": C.nw(r.to_numpy()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        "win_rate_pct": float(100 * (net > 0).mean()) if len(net) else None,
        "avg_win_inr": float(wins.mean()) if len(wins) else None, "avg_loss_inr": float(losses.mean()) if len(losses) else None,
        "largest_loss_inr": float(net.min()) if len(net) else None, "longest_losing_streak": best,
        "turnover_x_capital": turnover, "transaction_costs_inr": float(closed.costs.astype(float).sum()) if len(closed) else 0.0,
        "exposure_utilisation_pct": float(100 * (res.equity.market_value.astype(float) / capital).mean()),
        "mean_r": float(closed.r_multiple.mean()) if len(closed) else None,
        "gap_through_pct": float(100 * (closed.exit_reason == "GAP_THROUGH").mean()) if len(closed) else None,
        "exit_reasons": dict(collections.Counter(closed.exit_reason)) if len(closed) else {},
        "binding_constraints": dict(collections.Counter(closed.binding_constraint)) if len(closed) else {},
        "rejections_first_reason": dict(rej),
        "risk_events": dict(collections.Counter(e["event_type"] for e in res.events)),
        "halves_net_inr": [val(r.iloc[:half] * capital), val(r.iloc[half:] * capital)],
        "market": ols_alpha(r, ir),
        "retroactive_costs": bool(len(t) and t.retroactive_costs.any()),
        "ledger_digest": res.ledger_digest,
    }


def verdict(m: dict, m_stress: dict, random_mean_r: list) -> dict:
    """PREREGISTRATION.md §7, applied once. The final verdict waits for the extreme-trade audit."""
    nwt = m["nw_daily"].get("t")
    c = {
        "c1_net_positive_nw_t": bool(m["net_return_pct"] > 0 and nwt is not None and nwt >= T_MIN),
        "c2_beats_all_random": bool(m["mean_r"] is not None and random_mean_r and
                                    m["mean_r"] > max(x for x in random_mean_r if x is not None)),
        "c3_alpha_t": bool(m["market"].get("alpha_t") is not None and m["market"]["alpha_t"] >= T_MIN),
        "c4_both_halves": bool(all(h > 0 for h in m["halves_net_inr"])),
        "c5_stress_2x_slippage": bool(m_stress["net_return_pct"] > 0),
        "c6_min_trades": bool(m["trades_closed"] >= MIN_TRADES),
    }
    if all(c.values()):
        v = "VALIDATION_CANDIDATE"
    elif c["c2_beats_all_random"] and not (c["c1_net_positive_nw_t"] and c["c5_stress_2x_slippage"]):
        v = "MONITORING_ONLY"
    else:
        v = "CLOSED"
    rr = [x for x in random_mean_r if x is not None]
    return {"criteria": c, "provisional_verdict": v,
            "random_mean_r": {"n": len(rr), "max": max(rr) if rr else None, "p99": float(np.percentile(rr, 99)) if rr else None,
                              "median": float(np.median(rr)) if rr else None,
                              "arm_percentile": float(100 * np.mean([x < m["mean_r"] for x in rr])) if rr and m["mean_r"] is not None else None}}
