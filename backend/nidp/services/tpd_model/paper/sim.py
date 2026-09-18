"""Entry, levels, path and exit modes for one session's ranked universe (rules_v1.json: entry, target_stop, sessions,
modes, costs). Vectorised over the rows of a session; every function is pure.

Returns are measured on the entry basis: for session t, return = raw_t * mult_t / (entry * mult_s1) - 1, so a split or
bonus ex-dated inside the window leaves the path continuous (TC-P5).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MODES = ("EOD-1", "EOD-3", "EOD-5", "FIXED", "TARGET_STOP")
MODE_SESSION = {"EOD-1": 1, "EOD-3": 3, "EOD-5": 5, "FIXED": 6, "TARGET_STOP": 6}
WINDOW = 6
BANDS = (0.02, 0.05, 0.10, 0.20)
BAND_TOL = 0.0025
GAP_FLAG = 0.05
CAPACITY_FRAC = 0.01
STOP_CAP = 0.08
PRICE_EPS = 0.005


def at_band(gap: np.ndarray, sign: int) -> np.ndarray:
    """True where `gap` sits within BAND_TOL of +band (sign=+1) or -band (sign=-1) for a standard band."""
    out = np.zeros(gap.shape, dtype=bool)
    for b in BANDS:
        out |= np.abs(gap - sign * b) <= BAND_TOL
    return out


@dataclass
class SessionInputs:
    """Arrays for n rows over the WINDOW sessions from the entry session (NaN where there is no bar)."""
    open: np.ndarray          # (n, 6)
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    mult: np.ndarray          # (n, 6) corporate-action multiplier of each bar
    turnover_s1: np.ndarray   # (n,)
    prev_close_raw: np.ndarray  # (n,) the prediction date's close
    prev_mult: np.ndarray     # (n,) the prediction date bar's multiplier
    sessions_present: int     # how many of the 6 sessions exist in the calendar so far (0..6)
    s1_thin: bool
    suspect: np.ndarray       # (n, 6) unexplained jump on that bar
    unfactored: np.ndarray    # (n, 6) known price event without a factor ex-dated that session


def resolve_entries(x: SessionInputs, allocation: float) -> pd.DataFrame:
    """Status, reason and flags of each row's entry at the s1 official open (rules entry.exceptions)."""
    n = len(x.prev_close_raw)
    status = np.array(["PENDING_ENTRY"] * n, dtype=object)
    reason = np.array([None] * n, dtype=object)
    flags = [[] for _ in range(n)]
    entry = np.full(n, np.nan)
    gap = np.full(n, np.nan)
    prev_adj = x.prev_close_raw * x.prev_mult / x.mult[:, 0] if x.sessions_present else np.full(n, np.nan)
    if x.sessions_present == 0:
        return pd.DataFrame({"status": status, "reason": reason, "flags": flags, "entry_price": entry, "prev_close_adj": prev_adj, "gap": gap})
    o, h, l = x.open[:, 0], x.high[:, 0], x.low[:, 0]
    has = ~np.isnan(x.close[:, 0])
    for k in range(n):
        if not has[k]:
            if x.s1_thin:
                status[k], reason[k] = "DATA_ERROR", "NO_BAR_ON_THIN_SESSION"
            else:
                status[k], reason[k] = "SUSPENDED", "NO_BAR"
            continue
        if not (o[k] > 0):
            status[k], reason[k] = "ENTRY_UNAVAILABLE", "MISSING_OPEN"
            continue
        g = o[k] / prev_adj[k] - 1.0
        gap[k] = g
        if abs(o[k] - h[k]) < PRICE_EPS and at_band(np.array([g]), +1)[0]:
            status[k], reason[k] = "ENTRY_UNAVAILABLE", "UPPER_CIRCUIT_OPEN"
            continue
        status[k] = "ENTERED"
        entry[k] = o[k]
        if abs(o[k] - l[k]) < PRICE_EPS and at_band(np.array([g]), -1)[0]:
            flags[k].append("LOWER_CIRCUIT_OPEN")
        if abs(g) >= GAP_FLAG:
            flags[k].append("GAP_RECORDED")
        if x.mult[k, 0] != x.prev_mult[k]:
            flags[k].append("CA_EX_ON_ENTRY")
        t1 = x.turnover_s1[k]
        if not np.isnan(t1) and allocation > CAPACITY_FRAC * t1:
            flags[k].append("ILLIQUID_OPEN")
    return pd.DataFrame({"status": status, "reason": reason, "flags": flags, "entry_price": entry, "prev_close_adj": prev_adj, "gap": gap})


def levels(entry: np.ndarray, atr_raw: np.ndarray, support_raw: np.ndarray, resist_raw: np.ndarray, k: float, target_pct: float,
           cap: float = STOP_CAP) -> pd.DataFrame:
    """Pre-registered target/stop levels (rules target_stop). NaN rows stay NaN."""
    stop_atr = entry - k * atr_raw
    use_sup = (support_raw < entry) & (support_raw < stop_atr)
    stop = np.where(use_sup, support_raw, stop_atr)
    method = np.where(use_sup, "SUPPORT", "ATR").astype(object)
    floor = entry * (1.0 - cap)
    capped = stop < floor
    stop = np.where(capped, floor, stop)
    method = np.where(capped, "CAP_8PCT", method).astype(object)
    target = entry * (1.0 + target_pct / 100.0)
    risk = (entry - stop) / entry
    reward = np.full(entry.shape, target_pct / 100.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rr = np.where(risk > 0, reward / risk, np.nan)
    nan = np.isnan(entry)
    method = np.where(nan, None, method).astype(object)
    return pd.DataFrame({"atr_14": atr_raw, "support_level": support_raw, "resistance_level": resist_raw, "stop_loss_price": stop,
                         "stop_method": method, "target_price": target, "target_1_price": entry * 1.05, "target_2_price": entry * 1.10,
                         "risk_percent": risk, "reward_percent": reward, "risk_reward_ratio": rr})


def path_returns(x: SessionInputs, entry: np.ndarray) -> dict[str, np.ndarray]:
    """(n, 6) returns from entry for open/high/low/close, on the entry basis."""
    basis = entry[:, None] * x.mult[:, :1] / x.mult          # entry in each session's raw rupees
    return {"adj_factor": x.mult / x.mult[:, :1], "r_open": x.open / basis - 1, "r_high": x.high / basis - 1,
            "r_low": x.low / basis - 1, "r_close": x.close / basis - 1}


def running(r: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """To-date statistics per session: MFE/MAE from intraday extremes, close high watermark, drawdowns."""
    mfe = np.fmax.accumulate(np.where(np.isnan(r["r_high"]), -np.inf, r["r_high"]), axis=1)
    mae = np.fmin.accumulate(np.where(np.isnan(r["r_low"]), np.inf, r["r_low"]), axis=1)
    closes = np.where(np.isnan(r["r_close"]), -np.inf, r["r_close"])
    hwm = np.maximum(np.maximum.accumulate(closes, axis=1), 0.0)       # the entry itself is the first peak
    dd_entry = np.minimum(r["r_close"], 0.0)
    dd_peak = np.where(np.isnan(r["r_close"]), np.nan, hwm - r["r_close"])
    maxdd = np.fmax.accumulate(np.where(np.isnan(dd_peak), -np.inf, dd_peak), axis=1)
    fix = lambda a: np.where(np.isinf(a), np.nan, a)
    return {"mfe": fix(mfe), "mae": fix(mae), "high_watermark": hwm, "drawdown_from_entry": dd_entry, "max_drawdown": fix(maxdd)}


def exits(r: dict[str, np.ndarray], target_ret: np.ndarray, stop_ret: np.ndarray, sessions_present: int) -> dict[str, pd.DataFrame]:
    """Every mode's exit (rules modes + target_stop). A mode whose horizon has not closed yet is 'OPEN'."""
    n = r["r_close"].shape[0]
    out = {}
    run = running(r)
    for mode in ("EOD-1", "EOD-3", "EOD-5", "FIXED"):
        s = MODE_SESSION[mode]
        closed = sessions_present >= s
        gross = r["r_close"][:, s - 1] if closed else np.full(n, np.nan)
        state = (np.where(np.isnan(gross), "NO_BAR_AT_EXIT", "CLOSED") if closed else np.full(n, "OPEN")).astype(object)
        k = min(s, max(sessions_present, 1))
        out[mode] = pd.DataFrame({
            "state": state, "exit_session_index": np.full(n, s if closed else 0), "gross_return": gross,
            "exit_reason": np.where(closed, f"close of s{s}", None).astype(object),
            "exit_at": np.where(closed, "close", None).astype(object),
            "mfe": run["mfe"][:, k - 1] if sessions_present else np.full(n, np.nan),
            "mae": run["mae"][:, k - 1] if sessions_present else np.full(n, np.nan),
            "target_hit": (np.nanmax(np.where(np.isnan(r["r_high"][:, :k]), -np.inf, r["r_high"][:, :k]), axis=1) >= target_ret) if sessions_present else np.zeros(n, bool),
            "stop_hit": (np.nanmin(np.where(np.isnan(r["r_low"][:, :k]), np.inf, r["r_low"][:, :k]), axis=1) <= stop_ret) if sessions_present else np.zeros(n, bool),
        })
    # TARGET_STOP: first barrier; gaps through a level exit at that session's open; a session touching both counts the stop
    m = min(sessions_present, WINDOW)
    gross = np.full(n, np.nan)
    idx = np.zeros(n, dtype=int)
    reason = np.array([None] * n, dtype=object)
    at = np.array([None] * n, dtype=object)
    done = np.zeros(n, dtype=bool)
    for t in range(m):
        ro, rh, rl = r["r_open"][:, t], r["r_high"][:, t], r["r_low"][:, t]
        valid = ~np.isnan(rh)
        if t >= 1:
            gd = valid & ~done & (ro <= stop_ret)
            gross[gd], idx[gd], reason[gd], at[gd] = ro[gd], t + 1, "stop (gap)", "open"; done |= gd
            gu = valid & ~done & (ro >= target_ret)
            gross[gu], idx[gu], reason[gu], at[gu] = ro[gu], t + 1, "target (gap)", "open"; done |= gu
        hs = valid & ~done & (rl <= stop_ret)
        gross[hs], idx[hs], reason[hs], at[hs] = stop_ret[hs], t + 1, "stop", "stop"; done |= hs
        ht = valid & ~done & (rh >= target_ret)
        gross[ht], idx[ht], reason[ht], at[ht] = target_ret[ht], t + 1, "target", "target"; done |= ht
    horizon = m >= WINDOW
    last = r["r_close"][:, WINDOW - 1] if horizon else np.full(n, np.nan)
    fin = ~done & horizon
    gross[fin], idx[fin], reason[fin], at[fin] = last[fin], WINDOW, "horizon close", "close"
    state = np.where(done | fin, np.where(np.isnan(gross), "NO_BAR_AT_EXIT", "CLOSED"), "OPEN").astype(object)
    kk = np.where(idx > 0, idx, max(m, 1))
    mfe = np.array([run["mfe"][j, kk[j] - 1] if m else np.nan for j in range(n)])
    mae = np.array([run["mae"][j, kk[j] - 1] if m else np.nan for j in range(n)])
    out["TARGET_STOP"] = pd.DataFrame({"state": state, "exit_session_index": idx, "gross_return": gross, "exit_reason": reason, "exit_at": at,
                                       "mfe": mfe, "mae": mae,
                                       "target_hit": np.array([r_ is not None and r_.startswith("target") for r_ in reason]),
                                       "stop_hit": np.array([r_ is not None and r_.startswith("stop") for r_ in reason])})
    return out


def net(gross: np.ndarray, cost_pct: float) -> np.ndarray:
    return gross - cost_pct / 100.0
