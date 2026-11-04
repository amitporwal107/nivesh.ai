"""Exit watch rules, rule `exit-atr-trail-v1` (docs/paper_pnl_dashboard/EXIT_WATCH.md). Pure functions: no I/O, no clock.

Bars are NSE end-of-day bars of the underlying, oldest first: {date: date, open, high, low, close, volume?}
(services/desk_trading.fetch_bars). They are exchange data only. A Kite close never sets or moves a stop
(owner rule 29 Oct).

    series break  nidp.prices_eod is NOT adjusted for bonuses or splits. A close-to-close ratio below 0.65 or above 1.5
                  in the last 60 sessions is a break; only the bars after the latest break are used, and a stop
                  stored before it is worked out again.
                  Example: HDFCAMC 1:1 bonus, ex-date 2025-11-26: 5,336.5 → 2,679.0.
    ATR14         Wilder: TR = max(high − low, |high − previous close|, |low − previous close|); the first ATR is
                  the mean of the first 14 TRs, then ATR = (ATR × 13 + TR) / 14. Needs at least 15 bars after any
                  break. A bar without a high or low uses its close for that side.
    candidate     long: close − 2 × ATR14 · short: close + 2 × ATR14 (2 decimals)
    trail         each session after the stored day, in date order: long stop = max(stop, candidate), short stop =
                  min(stop, candidate). It never loosens.
    status        HIT (the price is through the stop) · FLOOR (a hedged position at or through its option strike;
                  the loss is capped) · NEAR (within EXIT_NEAR_ATR × ATR, default 0.5) · OK · NO_STOP
    signals       on the evening's bar (the caller checks it is today's):
                  CLOSE_THROUGH_STOP, SUPPORT_BREAK (against the previous 20 sessions' lowest low / highest high),
                  TREND_TURN (close < EMA20 < EMA50 for a long, the reverse for a short, true today and not the
                  session before; needs 51 bars), STOP_RAISED (comes from `advance_level`)
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

RULE_ID = "exit-atr-trail-v1"
ATR_N = 14
ATR_MULT = 2.0
MIN_BARS = ATR_N + 1
BREAK_LOOKBACK = 60
BREAK_LOW, BREAK_HIGH = 0.65, 1.5
SUPPORT_N = 20
TREND_FAST, TREND_SLOW = 20, 50
HISTORY_MAX = 30
NEAR_ATR_DEFAULT = 0.5

HIT, FLOOR, NEAR, OK, NO_STOP = "HIT", "FLOOR", "NEAR", "OK", "NO_STOP"
ATR_TRAIL, YOURS, PUT_FLOOR, CALL_CAP, NONE = "atr_trail", "yours", "put_floor", "call_cap", "none"
HEDGE_METHODS = (PUT_FLOOR, CALL_CAP)
METHOD_TEXT = {ATR_TRAIL: "2 × ATR trail", YOURS: "your stop", PUT_FLOOR: "put floor", CALL_CAP: "call cap", NONE: "no stop"}
BREAK_REASON = "price series break (bonus or split)"

RULE_TEXT = ("Stop loss = the last NSE close − 2 × ATR14 (Wilder's 14-session average true range) for a long, + for a short. "
             "After each NSE end-of-day file it moves only in the position's favour; it never loosens. Your own stop for the "
             "stock replaces it. A hedged position's stop is its option strike. Levels are on the share price. Alerts are "
             "in the app only; nothing places or changes an order.")


def near_atr(env: Optional[Dict[str, str]] = None) -> float:
    raw = (os.environ if env is None else env).get("EXIT_NEAR_ATR")
    try:
        v = float(raw) if raw not in (None, "") else NEAR_ATR_DEFAULT
    except ValueError:
        return NEAR_ATR_DEFAULT
    return v if v >= 0 else NEAR_ATR_DEFAULT


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def r2(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v + 0.0, 2)


def _day(b: Dict[str, Any]) -> str:
    d = b.get("date")
    return d.isoformat() if isinstance(d, date) else str(d)[:10]


# ── bars ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def clean_bars(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bars with a positive close, oldest first, one per day."""
    by: Dict[str, Dict[str, Any]] = {}
    for b in bars or []:
        c = _num(b.get("close"))
        if c is None or c <= 0:
            continue
        by[_day(b)] = b
    return [by[d] for d in sorted(by)]


def series_break(bars: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """(the bars after the latest break in the last BREAK_LOOKBACK sessions, that break's day or None)."""
    start = max(1, len(bars) - BREAK_LOOKBACK)
    cut, day = 0, None
    for i in range(start, len(bars)):
        prev, cur = float(bars[i - 1]["close"]), float(bars[i]["close"])
        ratio = cur / prev
        if ratio < BREAK_LOW or ratio > BREAK_HIGH:
            cut, day = i, _day(bars[i])
    return bars[cut:], day


def true_ranges(bars: List[Dict[str, Any]]) -> List[Optional[float]]:
    """TR per bar (None for the first, which has no previous close)."""
    out: List[Optional[float]] = [None]
    for prev, b in zip(bars, bars[1:]):
        pc, c = float(prev["close"]), float(b["close"])
        h = _num(b.get("high")) or c
        lo = _num(b.get("low")) or c
        out.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return out


def atr_series(bars: List[Dict[str, Any]], n: int = ATR_N) -> List[Optional[float]]:
    """Wilder ATR aligned with `bars` (None until n TRs exist)."""
    trs = true_ranges(bars)
    out: List[Optional[float]] = [None] * len(bars)
    if len(bars) < n + 1:
        return out
    a = sum(t for t in trs[1:n + 1] if t is not None) / n
    out[n] = a
    for i in range(n + 1, len(bars)):
        a = (a * (n - 1) + (trs[i] or 0.0)) / n
        out[i] = a
    return out


def atr(bars: List[Dict[str, Any]], n: int = ATR_N) -> Optional[float]:
    s = atr_series(bars, n)
    return s[-1] if s else None


def ema_series(values: List[float], n: int) -> List[Optional[float]]:
    """EMA with an SMA seed (alpha 2 / (n + 1)), aligned with `values`."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < n:
        return out
    e = sum(values[:n]) / n
    out[n - 1] = e
    k = 2.0 / (n + 1)
    for i in range(n, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def candidate(close: float, atr_value: float, side: str) -> float:
    return round(close - ATR_MULT * atr_value if side == "long" else close + ATR_MULT * atr_value, 2)


def support_level(bars: List[Dict[str, Any]], side: str, n: int = SUPPORT_N) -> Optional[float]:
    """The previous n sessions' lowest low (long) / highest high (short), the last bar excluded."""
    window = bars[-n - 1:-1]
    if len(window) < n:
        return None
    if side == "long":
        return r2(min(_num(b.get("low")) or float(b["close"]) for b in window))
    return r2(max(_num(b.get("high")) or float(b["close"]) for b in window))


# ── the level ────────────────────────────────────────────────────────────────────────────────────────────────────────

def evaluate(bars: List[Dict[str, Any]], side: str) -> Dict[str, Any]:
    """The stateless rule on the latest bar: {available, why, bars (post-break), break_day, day, close, atr, atr_pct,
    candidate, support}."""
    clean = clean_bars(bars)
    kept, brk = series_break(clean)
    out: Dict[str, Any] = {"available": False, "why": None, "bars": kept, "break_day": brk, "day": None, "close": None,
                           "atr": None, "atr_pct": None, "candidate": None, "support": None}
    if not clean:
        out["why"] = "no NSE end-of-day prices for this stock"
        return out
    if len(kept) < MIN_BARS:
        out["why"] = (f"ATR14 needs {MIN_BARS} sessions after the {BREAK_REASON} on {brk}; {len(kept)} available"
                      if brk else f"ATR14 needs {MIN_BARS} sessions of NSE end-of-day prices; {len(kept)} available")
        return out
    a = atr(kept)
    last = kept[-1]
    close = float(last["close"])
    out.update(available=True, day=_day(last), close=r2(close), atr=r2(a), atr_pct=r2(a / close * 100.0),
               candidate=candidate(close, a, side), support=support_level(kept, side))
    return out


def _entry(day: str, close: float, atr_value: float, cand: float, stop: float, moved: bool, reason: str) -> Dict[str, Any]:
    return {"day": day, "close": r2(close), "atr": r2(atr_value), "candidate": cand, "stop": stop, "moved": moved,
            "reason": reason}


def advance_level(stored: Optional[Dict[str, Any]], bars: List[Dict[str, Any]], side: str) -> Dict[str, Any]:
    """The trailing stop after the bars: {available, why, stop, day, atr, atr_pct, close, support, history, moved,
    reset, first, previous_stop}. `stored` is the level doc ({stop, day, history}) or None.

    first   no stored stop: the candidate of the latest bar, one history entry "first stop"
    reset   a series break after the stored day (or the stored day older than every bar kept): worked out again from the
            post-break bars, reason "price series break (bonus or split)"
    trail   every bar after the stored day, oldest first: the stop moves only in the position's favour
    same    no bar after the stored day: unchanged (moved false, no entry)"""
    ev = evaluate(bars, side)
    hist = list((stored or {}).get("history") or [])
    prev_stop = _num((stored or {}).get("stop"))
    prev_day = (stored or {}).get("day")
    base = {"available": ev["available"], "why": ev["why"], "atr": ev["atr"], "atr_pct": ev["atr_pct"], "close": ev["close"],
            "support": ev["support"], "break_day": ev["break_day"], "moved": False, "reset": False, "first": False,
            "previous_stop": prev_stop}
    if not ev["available"]:
        broken = bool(stored and ev["break_day"] and (not prev_day or ev["break_day"] > str(prev_day)))
        return {**base, "stop": None if broken or not stored else prev_stop, "day": None if broken else prev_day,
                "history": hist, "reset": broken}
    kept = ev["bars"]
    atrs = atr_series(kept)
    last_i = len(kept) - 1
    last_atr = atrs[last_i]
    if stored is None or prev_stop is None:
        cand = ev["candidate"]
        hist.append(_entry(ev["day"], ev["close"], last_atr, cand, cand, False, "first stop"))
        return {**base, "stop": cand, "day": ev["day"], "history": hist[-HISTORY_MAX:], "first": True}
    oldest = _day(kept[0])
    if (ev["break_day"] and ev["break_day"] > str(prev_day)) or str(prev_day) < oldest:
        cand = ev["candidate"]
        hist.append(_entry(ev["day"], ev["close"], last_atr, cand, cand, True, BREAK_REASON))
        return {**base, "stop": cand, "day": ev["day"], "history": hist[-HISTORY_MAX:], "reset": True}
    stop, moved_any = prev_stop, False
    for i in range(len(kept)):
        d = _day(kept[i])
        if d <= str(prev_day) or atrs[i] is None:
            continue
        close = float(kept[i]["close"])
        cand = candidate(close, atrs[i], side)
        new = max(stop, cand) if side == "long" else min(stop, cand)
        moved = round(new, 2) != round(stop, 2)
        stop = round(new, 2)
        moved_any = moved_any or moved
        hist.append(_entry(d, close, atrs[i], cand, stop, moved, "trail moved" if moved else "trail held"))
    if not any(_day(b) > str(prev_day) for b in kept):
        return {**base, "stop": prev_stop, "day": prev_day, "history": hist}
    return {**base, "stop": stop, "day": ev["day"], "history": hist[-HISTORY_MAX:], "moved": moved_any}


# ── status and money ─────────────────────────────────────────────────────────────────────────────────────────────────

def status_of(side: str, price: Optional[float], stop: Optional[float], atr_value: Optional[float], method: str,
              near: Optional[float] = None) -> Tuple[str, Optional[float], Optional[float]]:
    """(status, distance_pct, distance_atr). Distance is positive while the price is on the safe side of the stop."""
    if stop is None or price is None or price <= 0:
        return NO_STOP, None, None
    diff = price - stop if side == "long" else stop - price
    pct = r2(diff / price * 100.0)
    in_atr = r2(diff / atr_value) if atr_value else None
    if diff <= 0:
        return (FLOOR if method in HEDGE_METHODS else HIT), pct, in_atr
    near = near_atr() if near is None else near
    if atr_value and diff <= near * atr_value:
        return NEAR, pct, in_atr
    return OK, pct, in_atr


def loss_at_stop(kind: str, side: str, legs: List[Dict[str, Any]], stop: Optional[float], *, spot: Optional[float] = None,
                 hedge: Optional[Dict[str, Any]] = None) -> Tuple[Optional[float], str]:
    """(₹ gross loss from the average cost if the stop is where the position ends, the basis text). Negative = a gain
    locked in. `legs`: the delta-one legs {type EQ|FUT, quantity (signed), avg, price?}."""
    if kind == "hedged" and hedge:
        k = _num(hedge.get("strike"))
        if k is None:
            return None, "the hedge strike is unknown"
        total = 0.0
        for leg in legs:
            avg = _num(leg.get("avg"))
            if avg is None:
                return None, "the broker sent no average price for a leg"
            total += (avg - k) * float(leg["quantity"])
        put = hedge.get("type") == "PE"
        opts = hedge.get("legs") or [{"strike": k, "quantity": hedge.get("quantity"), "avg": hedge.get("avg")}]
        for o in opts:
            prem, q, ki = _num(o.get("avg")), abs(_num(o.get("quantity")) or 0.0), _num(o.get("strike")) or k
            if prem is None:
                return None, "the broker sent no average price for the hedge"
            # Each option's cost, less what it is worth with the share at the binding strike at expiry.
            total += (prem - (max(ki - k, 0.0) if put else max(k - ki, 0.0))) * q
        what = "put" if put else "call"
        return r2(total), (f"Floor loss at expiry: the {_strike(k)} {what} caps the loss — (average − strike) × quantity "
                           f"+ the {what}'s cost, before charges.")
    if stop is None:
        return None, "no stop loss"
    total, basis_note = 0.0, None
    for leg in legs:
        avg = _num(leg.get("avg"))
        if avg is None:
            return None, "the broker sent no average price for a leg"
        exit_px = stop
        if leg.get("type") == "FUT":
            px = _num(leg.get("price"))
            if px is not None and spot:
                exit_px = stop + (px - spot)
                basis_note = "the future is assumed to keep today's basis to the share price"
            else:
                basis_note = "the future's basis to the share price is unknown here, so it is taken as 0"
        total += (avg - exit_px) * float(leg["quantity"])
    text = "(average − stop loss) × quantity, before charges" + (f"; {basis_note}" if basis_note else "")
    return r2(total), text[0].upper() + text[1:] + "."


def _strike(k: float) -> str:
    return f"{k:g}" if float(k).is_integer() else f"{k:.2f}"


# ── evening signals ──────────────────────────────────────────────────────────────────────────────────────────────────

def evening_signals(bars: List[Dict[str, Any]], side: str, stop_in_force: Optional[float], method: str) -> List[Dict[str, Any]]:
    """The evening's signals on the LAST bar (the caller checks it is today's NSE bar). Each {kind, close, level, ...}.

    CLOSE_THROUGH_STOP   the close is through the stop in force that day (not for a hedged position: FLOOR_REACHED)
    FLOOR_REACHED        a hedged position's close is at or through its option strike
    SUPPORT_BREAK        long: close < the previous 20 sessions' lowest low · short: close > their highest high
    TREND_TURN           long: close < EMA20 < EMA50 today and not the session before · short: the reverse"""
    kept, _ = series_break(clean_bars(bars))
    if not kept:
        return []
    last = kept[-1]
    close = float(last["close"])
    out: List[Dict[str, Any]] = []
    if stop_in_force is not None:
        through = close <= stop_in_force if side == "long" else close >= stop_in_force
        if through:
            out.append({"kind": "FLOOR_REACHED" if method in HEDGE_METHODS else "CLOSE_THROUGH_STOP", "close": r2(close),
                        "level": r2(stop_in_force)})
    sup = support_level(kept, side)
    if sup is not None and ((side == "long" and close < sup) or (side == "short" and close > sup)):
        out.append({"kind": "SUPPORT_BREAK", "close": r2(close), "level": sup})
    if len(kept) >= TREND_SLOW + 1:
        closes = [float(b["close"]) for b in kept]
        f, s = ema_series(closes, TREND_FAST), ema_series(closes, TREND_SLOW)

        def turned(i: int) -> bool:
            if f[i] is None or s[i] is None:
                return False
            return closes[i] < f[i] < s[i] if side == "long" else closes[i] > f[i] > s[i]
        if turned(-1) and not turned(-2):
            out.append({"kind": "TREND_TURN", "close": r2(close), "level": r2(f[-1]), "ema20": r2(f[-1]), "ema50": r2(s[-1])})
    return out
