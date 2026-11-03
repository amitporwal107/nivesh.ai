"""TrueData's live quote against Kite's for the same symbol (LK-1 … LK-6 in test_reports/truedata_live_dq_TESTCASES.md).

Kite's quotes come from the live-feed cache (services/kite_live_feed/quote_cache.read_quotes), read only. Prices move
between two quotes taken at different moments, so a pair is compared only when both describe the same moment:
  * same EXCHANGE second, when both carry an exchange time (F&O: Kite's "full" mode). On 30 Oct 2026 Kite's F&O
    exchange time was UTC labelled as IST (5 h 30 m behind its own receive time); that exact offset is corrected here
    and reported as `kite_ts_mislabelled`;
  * otherwise RECEIVE times within MAX_RECEIVE_GAP_S, both stamped on this server's clock (Kite's cash and index
    quotes carry no exchange time: its "quote" mode).
Anything else is "not comparable", never a disagreement. Tolerance: one tick or 0.05% (stocks, futures, indices);
for options, two ticks or 0.5%, because an at-the-money weekly option can move 1% within a second.
Previous close is compared whatever the time: both sources publish NSE's official close of the last session.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

MAX_RECEIVE_GAP_S = 1.0
REL_TOLERANCE = {"OPT": 0.005}
DEFAULT_REL = 0.0005
DEFAULT_TICK = 0.05
IST_OFFSET_S = 5.5 * 3600


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return None


def kite_exchange_time(kite: Dict[str, Any]) -> Tuple[Optional[datetime], bool]:
    """Kite's exchange time, corrected when it is the UTC time labelled as IST. (time, was_mislabelled)."""
    ex, rec = _aware(kite.get("exchange_ts")), _aware(kite.get("received_at"))
    if ex is None:
        return None, False
    if rec is not None:
        lag = (rec - ex).total_seconds()
        if abs(lag - IST_OFFSET_S) <= 120:
            return ex + timedelta(seconds=IST_OFFSET_S), True
        if abs(lag) > 120:                                       # not explainable: do not use it
            return None, False
    return ex, False


def compare(td: Dict[str, Any], kite: Optional[Dict[str, Any]], tick: Optional[float] = None,
            kind: str = "EQ") -> Tuple[str, List[str], Dict[str, Any]]:
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
    t_ex = _aware(td.get("ts"))
    k_ex, mislabelled = kite_exchange_time(kite)
    if mislabelled:
        detail["kite_ts_mislabelled"] = True
    if t_ex is not None and k_ex is not None:
        detail.update(basis="exchange_second", td_exchange_ts=t_ex.isoformat(), kite_exchange_ts=k_ex.isoformat())
        if int(t_ex.timestamp()) != int(k_ex.timestamp()):
            return "not_comparable", codes, detail
    else:
        t_rec, k_rec = _aware(td.get("received_at")), _aware(kite.get("received_at"))
        if t_rec is None or k_rec is None:
            return "not_comparable", codes, {**detail, "why": "a quote has neither exchange nor receive time"}
        gap = abs((t_rec - k_rec).total_seconds())
        detail.update(basis="receive_time", time_gap_s=round(gap, 3))
        if gap > MAX_RECEIVE_GAP_S:
            return "not_comparable", codes, detail
    t_ltp, k_ltp = float(td["ltp"]), float(kite["ltp"])
    step = tick or DEFAULT_TICK
    tol = max(step * (2 if kind == "OPT" else 1), REL_TOLERANCE.get(kind, DEFAULT_REL) * k_ltp) + 1e-9
    detail["rel_diff_pct"] = round(100 * abs(t_ltp - k_ltp) / k_ltp, 4) if k_ltp else None
    k_oi, t_oi = kite.get("oi"), td.get("oi")
    if k_oi and (t_oi or 0) != k_oi:
        codes.append("OI_MISMATCH")
        detail.update(td_oi=t_oi, kite_oi=k_oi)
    if abs(t_ltp - k_ltp) <= tol:
        return "agree", codes, detail
    codes.append("KITE_DISAGREE")
    return "disagree", codes, {**detail, "tolerance": round(tol, 4)}
