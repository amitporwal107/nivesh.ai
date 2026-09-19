"""Positional study — end-of-day signals E1, E2, E3 and D1 (docs/ai_research/tpd3/positional/PREREGISTRATION.md §3-§4,
FROZEN at fe60155f). The panel is Phase 1's (`phase1_common.build_panel`: discovery period only, asserted), so every
indicator has the Phase 1 definition. A signal dated t uses bars up to and including t only; the panel's outcome
columns (L5_1 ... net5, which look forward) are never read here — test_positional checks that truncating the panel after
t leaves the signals at t unchanged.

Implementation notes (readings of the frozen text, recorded in RESULTS.md):
- E2 "t is the first up day": t is an up day (close > previous close and close > open) and t-1 was not
  (close(t-1) <= close(t-2)).
- E2 volume: the average of t-4..t-1 is compared with the 20-day average volume of §3 (the 20 sessions before t).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase1"))
sys.path.insert(0, os.path.join(HERE, "..", "pit_audit"))
import phase1_common as C  # noqa: E402

STOP_MAX, STOP_MIN = 0.08, 0.01
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ARMS = ("E1", "E2", "E3", "D1")


def clamp_stop(structural, ref):
    """§3: never more than 8% and never less than 1% below the reference entry."""
    return np.minimum(np.maximum(structural, ref * (1 - STOP_MAX)), ref * (1 - STOP_MIN))


def add_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    d["low10"] = g.low.transform(lambda s: s.rolling(10).min())                 # 10 sessions ending t
    d["low5"] = g.low.transform(lambda s: s.rolling(5).min())                   # t-4..t
    d["low4_prev"] = g.low.transform(lambda s: s.shift(1).rolling(4).min())     # t-4..t-1
    d["is_down"] = (d.close < d.prev_close).astype(float).where(d.prev_close.notna())
    d["down4_prev"] = d.groupby("symbol", sort=False).is_down.transform(lambda s: s.shift(1).rolling(4).sum())
    d["prev_close2"] = g.close.shift(2)
    d["ema20_prev"] = g.ema20.shift(1)
    d["atr_prev"] = g.atr14.shift(1)
    d["vol20"] = g.volume.transform(lambda s: s.shift(1).rolling(20).mean())   # the 20 sessions before t
    d["vol4_prev"] = g.volume.transform(lambda s: s.shift(1).rolling(4).mean())
    d["hi55_incl"] = g.high.transform(lambda s: s.rolling(55).max())
    d["hi15_incl"] = g.high.transform(lambda s: s.rolling(15).max())
    return d


def _frame(d: pd.DataFrame, mask, arm, order_type, ref, stop, valid=1, trigger=None) -> pd.DataFrame:
    x = d[mask].copy()
    ref = ref[mask]
    out = pd.DataFrame({
        "signal_id": arm + "-" + x.symbol + "-" + x.date.dt.strftime("%Y%m%d"), "date": x.date.dt.date, "symbol": x.symbol,
        "arm": arm, "order_type": order_type, "trigger": trigger[mask] if trigger is not None else np.nan,
        "valid_sessions": valid, "stop": clamp_stop(stop[mask], ref), "reference_price": ref, "atr": x.atr14,
        "rank": x.rs20})
    return out[np.isfinite(out.stop) & np.isfinite(out.reference_price) & np.isfinite(out.atr)].reset_index(drop=True)


def e1(d: pd.DataFrame) -> pd.DataFrame:
    m = (d.eligible & (d.close >= 0.97 * d.hi55) & (d.close < d.hi55) & (d.range10_pct <= 0.30) & (d.close > d.ema50)
         & (d.rs20 > 0))
    trig = d.hi55 * 1.001
    return _frame(d, m, "E1", "BUY_STOP", trig, d.low10, valid=3, trigger=trig)


def e2(d: pd.DataFrame) -> pd.DataFrame:
    trend = (d.close > d.ema50) & (d.hi55_incl == d.hi15_incl)
    pull = ((d.down4_prev >= 3) & (d.low4_prev >= d.ema20_prev - d.atr_prev) & (d.low4_prev <= d.ema20_prev + d.atr_prev)
            & (d.vol4_prev < d.vol20))
    first_up = (d.close > d.prev_close) & (d.close > d.open) & (d.prev_close <= d.prev_close2)
    m = d.eligible & trend & pull & first_up
    return _frame(d, m, "E2", "MOO", d.close, d.low5 - 0.5 * d.atr14)


def e3(d: pd.DataFrame) -> pd.DataFrame:
    m = (d.eligible & (d.rvol >= 1.5) & (d.close_pos >= 0.75) & (d.close > d.ema20) & (d.close > d.ema50) & (d.rs20 > 0)
         & (d.close > d.hi55))
    return _frame(d, m, "E3", "MOO", d.close, d.close - 2 * d.atr14)


# ---------------- D1: results-reaction drift ----------------
def results_broadcasts(symbols: set, root: str = "/app/research/pit_audit/nse") -> pd.DataFrame:
    """Earliest ORIGINAL results broadcast per (symbol, period_end) under R-NSE-RES-1: flagged revisions (no broadcast)
    and AV-1 contradictions (public time > 15 min before submission) are excluded."""
    from archive import Archive
    rows = []
    for f in Archive(root).read("filings"):
        if f["filing_type"] != "RESULTS" or f["symbol"] not in symbols or f["revision_flag"] == "REVISED":
            continue
        if not f.get("broadcast_at"):
            continue
        b = dt.datetime.fromisoformat(f["broadcast_at"])
        s = dt.datetime.fromisoformat(f["submitted_at"]) if f.get("submitted_at") else None
        rows.append({"symbol": f["symbol"], "period_end": f["period_end"], "broadcast_at": b,
                     "contradiction": bool(s and b < s - dt.timedelta(minutes=15))})
    x = pd.DataFrame(rows)
    ok = x[~x.contradiction]
    first = ok.sort_values("broadcast_at").groupby(["symbol", "period_end"], as_index=False).first()
    first.attrs["excluded_contradictions"] = int(x.contradiction.sum())
    return first


def reaction_session(b: dt.datetime, sessions: list) -> dt.date | None:
    """The first full session after the broadcast: b's own date if b is a session day and b < 09:15 IST, else the next
    session after b's date. None beyond the calendar."""
    b = b.astimezone(IST)
    d = b.date()
    import bisect
    i = bisect.bisect_left(sessions, d)
    if i < len(sessions) and sessions[i] == d and b.time() < dt.time(9, 15):
        return d
    j = bisect.bisect_right(sessions, d)
    return sessions[j] if j < len(sessions) else None


def d1(d: pd.DataFrame, idx: pd.DataFrame, broadcasts: pd.DataFrame, rule: dict) -> tuple[pd.DataFrame, dict]:
    import pit_policy as P
    sessions = sorted(idx.date.dt.date)
    idx_ret = dict(zip(idx.date.dt.date, idx.idx_close.pct_change()))
    key = d.set_index([d.symbol, d.date.dt.date])
    validated = P.point_in_time_validated("PIT_VALIDATED_RULE", rule=rule)
    stats = {"broadcasts": int(len(broadcasts)), "excluded_contradictions": broadcasts.attrs.get("excluded_contradictions"),
             "no_session": 0, "gate_rejected": 0, "no_bar": 0, "triggered": 0}
    out = []
    for r in broadcasts.itertuples(index=False):
        rs = reaction_session(r.broadcast_at, sessions)
        if rs is None:
            stats["no_session"] += 1
            continue
        decision = dt.datetime.combine(rs, dt.time(15, 30), tzinfo=IST)
        ok, _ = P.is_feature_eligible("PIT_VALIDATED_RULE", r.broadcast_at, decision, validated, rule=rule)
        if not ok:
            stats["gate_rejected"] += 1
            continue
        if (r.symbol, rs) not in key.index:
            stats["no_bar"] += 1
            continue
        row = key.loc[(r.symbol, rs)]
        abn = row.close / row.prev_close - 1 - idx_ret.get(rs, np.nan)
        if bool(row.eligible) and abn >= 0.04 and row.volume >= 2 * row.vol20:
            stats["triggered"] += 1
            out.append({"signal_id": f"D1-{r.symbol}-{rs:%Y%m%d}", "date": rs, "symbol": r.symbol, "arm": "D1",
                        "order_type": "MOO", "trigger": np.nan, "valid_sessions": 1,
                        "stop": float(clamp_stop(row.close - 2 * row.atr14, row.close)), "reference_price": row.close,
                        "atr": row.atr14, "rank": row.rs20, "available_at": r.broadcast_at.isoformat()})
    s = pd.DataFrame(out)
    if len(s):
        s = s[np.isfinite(s.stop) & np.isfinite(s.atr)].drop_duplicates("signal_id").reset_index(drop=True)
    return s, stats


def build_all(rule: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """(panel with features, all EOD signals, D1 stats, sector map). Discovery period only (asserted by load_daily)."""
    d = add_features(C.build_panel())
    assert d.date.min() >= C.DISCOVERY_START, "sealed data in the panel"
    idx = C.load_index()
    n5 = pd.read_csv(C.N500)
    sectors = dict(zip(n5.Symbol, n5.Industry))
    sig = [e1(d), e2(d), e3(d)]
    s_d1, st = d1(d, idx, results_broadcasts(set(n5.Symbol)), rule)
    return d, pd.concat(sig + [s_d1], ignore_index=True), st, sectors
