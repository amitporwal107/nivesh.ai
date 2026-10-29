"""TrueData's live quote against Kite's for the same symbol (LK-1 … LK-5 in test_reports/truedata_live_dq_TESTCASES.md).

Kite's quotes come from the live-feed cache (services/kite_live_feed/quote_cache.read_quotes), read only. Two quotes
are compared only when their exchange times are within MAX_TIME_GAP_S of each other; otherwise prices legitimately
differ and the pair is "not comparable", never a disagreement. Previous close is compared whatever the time: both
sources publish NSE's official close of the last session.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

MAX_TIME_GAP_S = 2.0
REL_TOLERANCE = 0.0005           # 0.05%
DEFAULT_TICK = 0.05


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return None


def compare(td: Dict[str, Any], kite: Optional[Dict[str, Any]], tick: Optional[float] = None) -> Tuple[str, List[str], Dict[str, Any]]:
    """(outcome, extra finding codes, detail). outcome: agree | disagree | not_comparable | no_kite_quote."""
    if not kite or kite.get("ltp") is None:
        return "no_kite_quote", [], {}
    codes: List[str] = []
    detail: Dict[str, Any] = {"symbol": td.get("symbol"), "td_ltp": td.get("ltp"), "kite_ltp": kite.get("ltp")}
    k_prev = (kite.get("ohlc") or {}).get("close")
    t_prev = td.get("prev_close")
    if k_prev and t_prev and abs(float(k_prev) - float(t_prev)) > 0.005:
        codes.append("PREV_CLOSE_MISMATCH")
        detail.update(td_prev_close=t_prev, kite_prev_close=k_prev)
    t_ts, k_ts = _aware(td.get("ts")), _aware(kite.get("exchange_ts"))
    if t_ts is None or k_ts is None:
        return "not_comparable", codes, {**detail, "why": "a quote has no exchange time"}
    gap = abs((t_ts - k_ts).total_seconds())
    detail.update(td_ts=t_ts.isoformat(), kite_ts=k_ts.isoformat(), time_gap_s=round(gap, 3))
    if gap > MAX_TIME_GAP_S:
        return "not_comparable", codes, detail
    t_ltp, k_ltp = float(td["ltp"]), float(kite["ltp"])
    tol = max(tick or DEFAULT_TICK, REL_TOLERANCE * k_ltp) + 1e-9
    k_oi, t_oi = kite.get("oi"), td.get("oi")
    if k_oi and (t_oi or 0) != k_oi:
        codes.append("OI_MISMATCH")
        detail.update(td_oi=t_oi, kite_oi=k_oi)
    if abs(t_ltp - k_ltp) <= tol:
        return "agree", codes, detail
    codes.append("KITE_DISAGREE")
    return "disagree", codes, {**detail, "tolerance": round(tol, 4)}
