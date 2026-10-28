"""Trade Desk › Chart Analysis › Live chart: the readings the chart draws and the signal conditions, worked out ONCE here on
the bars the chart shows (GET /api/desk/live-chart/{symbol}, routes/desk_live_chart.py). Pure: no I/O.

    ema_series     EMA 20 of the closes, the indicator engine's own formula (nidp technical_indicator_engine
                   calculator._ema_series: seeded with the first close, k = 2 / (n + 1)); null for the first n − 1 bars,
                   where the engine gives no value either
    rvol_series    volume ÷ the mean volume of the PREVIOUS 20 bars (null until 20 bars exist or when that mean is 0).
                   On 15m bars this compares a bar with the 20 bars before it, not with the same time of day
    conditions     each one evaluated on the last COMPLETED bar (an in-progress candle is never judged), with its rule in
                   words, its status and its value:
                     ema20        close above the 20 EMA                                      met | not_met
                     volume       a bar in the last 20 with volume ≥ VOLUME_MIN × its average  met | not_met
                     pullback     after that bar, price eased (lows under its close) on volume below the average
                                                                                                  met | not_met | waiting | not_applicable
                     trigger      the plan's own entry rule: break_above → a close above the entry; pullback_to → a low
                                  at or below the entry; at_once → none                          met | waiting | not_applicable
                     validity     the plan's valid_for_sessions counted in sessions after the signal day  met | not_met | unavailable
                     invalidation a close below the stop since the signal day                     hit | not_hit
    stage_markers  WATCH / READY / CONFIRMED where the scanner's stage for the symbol became ACCUMULATION / EARLY_BREAKOUT
                   / BREAKOUT, at the last bar of that signal's session (the scanner runs on the day's close). A signal day
                   outside the bars draws nothing. Signal days more than RUN_GAP_DAYS calendar days apart are separate runs
                   (the symbol left the scanner's list in between), so a new run marks its stage again.

A condition is a reading of the chart, not a fill: the desk's paper engine fills on END-OF-DAY bars (services/desk_trading.py
FILL MODEL). Long setups only (paper cash trades are long only).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

EMA_PERIOD = 20
RVOL_BARS = 20
VOLUME_MIN = 1.3                 # the design's "Volume ≥ 1.3× 20-bar avg"
VOLUME_LOOKBACK = 20             # bars searched for that volume bar
STAGE_KIND = {"ACCUMULATION": "WATCH", "EARLY_BREAKOUT": "READY", "BREAKOUT": "CONFIRMED"}
RUN_GAP_DAYS = 4                 # signal days further apart than this (a weekend and a holiday) are separate runs
STATUS = ("met", "not_met", "waiting", "hit", "not_hit", "not_applicable", "unavailable")


def ema_series(closes: Sequence[float], period: int = EMA_PERIOD) -> List[Optional[float]]:
    if not closes:
        return []
    k = 2.0 / (period + 1)
    out: List[Optional[float]] = []
    prev = float(closes[0])
    for i, c in enumerate(closes):
        prev = float(c) if i == 0 else float(c) * k + prev * (1.0 - k)
        out.append(round(prev, 2) if i >= period - 1 else None)
    return out


def rvol_series(volumes: Sequence[float], n: int = RVOL_BARS) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(volumes)):
        if i < n:
            out.append(None)
            continue
        avg = sum(float(v or 0) for v in volumes[i - n:i]) / n
        out.append(round(float(volumes[i] or 0) / avg, 2) if avg > 0 else None)
    return out


def last_completed(bars: Sequence[Sequence[Any]], minutes: Optional[int], now: datetime) -> int:
    """Index of the newest bar whose period has ended (daily bars: every bar but one dated today while the session is open
    is complete; the caller passes minutes=None and a daily bar is complete once its day is before today or now is past
    15:30). −1 when none."""
    for i in range(len(bars) - 1, -1, -1):
        t = bars[i][0]
        if minutes is None:
            day = date.fromisoformat(t[:10])
            close = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(hours=15, minutes=30)
            if now >= close:
                return i
            continue
        if datetime.fromisoformat(t) + timedelta(minutes=minutes) <= now:
            return i
    return -1


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}" if v < 1000 else f"{v:,.1f}" if v < 10000 else f"{v:,.0f}"


def _cond(key: str, label: str, status: str, value: str, rule: str, at: Optional[str] = None) -> Dict[str, Any]:
    assert status in STATUS
    return {"key": key, "label": label, "status": status, "value": value, "rule": rule, "at": at}


def sessions_after(signal_day: date, today: date, holidays: Optional[set]) -> int:
    """Trading sessions strictly after the signal day up to and including today (weekdays, less the holidays given)."""
    n, d = 0, signal_day + timedelta(days=1)
    while d <= today:
        if d.weekday() < 5 and not (holidays and d in holidays):
            n += 1
        d += timedelta(days=1)
    return n


def nth_session_after(signal_day: date, n: int, holidays: Optional[set]) -> date:
    d, k = signal_day, 0
    while k < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and not (holidays and d in holidays):
            k += 1
    return d


def conditions(bars: Sequence[Sequence[Any]], ema: Sequence[Optional[float]], rvol: Sequence[Optional[float]],
               levels: Dict[str, Any], *, minutes: Optional[int], now: datetime, tf: str,
               signal_day: Optional[date], holidays: Optional[set], holidays_checked: bool) -> Dict[str, Any]:
    """The signal conditions (see the module docstring). `levels`: entry, stop, rule (break_above | pullback_to | at_once),
    valid_for_sessions. Returns {evaluated_at_bar, conditions, volume_bar, valid_until, sessions_left}."""
    li = last_completed(bars, minutes, now)
    out: List[Dict[str, Any]] = []
    entry, stop, rule = levels.get("entry"), levels.get("stop"), levels.get("rule")
    if li < 0:
        return {"evaluated_at_bar": None, "conditions": [], "volume_bar": None, "valid_until": None, "sessions_left": None,
                "reason": "No completed bar yet."}
    bar = bars[li]
    close = float(bar[4])
    e = ema[li] if li < len(ema) else None
    if e is None:
        out.append(_cond("ema20", f"{tf} close above 20 EMA", "unavailable", "fewer than 20 bars", f"the last completed {tf} close vs the 20-bar EMA"))
    else:
        out.append(_cond("ema20", f"{tf} close above 20 EMA", "met" if close > e else "not_met",
                         f"{_fmt(close)} {'>' if close > e else '≤'} {_fmt(e)}", f"the last completed {tf} close vs the 20-bar EMA", bar[0]))

    lo = max(0, li - VOLUME_LOOKBACK + 1)
    cand = [(i, rvol[i]) for i in range(lo, li + 1) if i < len(rvol) and rvol[i] is not None]
    vol_bar = None
    if not cand:
        out.append(_cond("volume", f"Volume ≥ {VOLUME_MIN}× 20-bar avg", "unavailable", "fewer than 21 bars",
                         f"a bar in the last {VOLUME_LOOKBACK} with volume ≥ {VOLUME_MIN}× the mean of the 20 bars before it"))
    else:
        i_max, r_max = max(cand, key=lambda t: (t[1], t[0]))
        ok = r_max >= VOLUME_MIN
        if ok:
            # the most recent qualifying bar is the move's bar
            i_max, r_max = max(((i, r) for i, r in cand if r >= VOLUME_MIN), key=lambda t: t[0])
            vol_bar = {"index": i_max, "at": bars[i_max][0], "rvol": r_max}
        out.append(_cond("volume", f"Volume ≥ {VOLUME_MIN}× 20-bar avg", "met" if ok else "not_met",
                         f"{r_max:.1f}×" if ok else f"max {r_max:.1f}×", f"a bar in the last {VOLUME_LOOKBACK} with volume ≥ {VOLUME_MIN}× the mean of the 20 bars before it",
                         bars[i_max][0]))

    if vol_bar is None:
        out.append(_cond("pullback", "Pullback on lower volume", "not_applicable", "no volume bar to pull back from",
                         "after the volume bar: lows under its close on volume below the 20-bar average"))
    else:
        after = list(range(vol_bar["index"] + 1, li + 1))
        if not after:
            out.append(_cond("pullback", "Pullback on lower volume", "waiting", "no completed bar since the volume bar",
                             "after the volume bar: lows under its close on volume below the 20-bar average"))
        else:
            ref = float(bars[vol_bar["index"]][4])
            eased = min(float(bars[i][3]) for i in after) < ref
            rv = [rvol[i] for i in after if rvol[i] is not None]
            mean_rv = round(sum(rv) / len(rv), 2) if rv else None
            ok = eased and mean_rv is not None and mean_rv < 1.0
            value = (f"{mean_rv:.1f}×" if mean_rv is not None else "volume unknown") + ("" if eased else ", no pullback yet")
            out.append(_cond("pullback", "Pullback on lower volume", "met" if ok else "not_met", value,
                             "after the volume bar: lows under its close on volume below the 20-bar average"))

    since = [i for i in range(0, li + 1) if signal_day is None or bars[i][0][:10] > signal_day.isoformat()]
    if entry is None or rule not in ("break_above", "pullback_to"):
        out.append(_cond("trigger", "Entry trigger", "not_applicable",
                         "the plan enters at once (end of day)" if rule == "at_once" else "no entry level",
                         "the plan's entry rule"))
    elif rule == "break_above":
        ok = close > entry
        out.append(_cond("trigger", f"{tf} close above {_fmt(entry)}", "met" if ok else "waiting",
                         f"{_fmt(close)}" if ok else "waiting", f"break_above: a completed {tf} close above the entry", bar[0]))
    else:
        touched = [i for i in since if float(bars[i][3]) <= entry]
        out.append(_cond("trigger", f"{tf} low at or below {_fmt(entry)}", "met" if touched else "waiting",
                         f"touched at {bars[touched[0]][0][11:16] or bars[touched[0]][0][:10]}" if touched else "waiting",
                         f"pullback_to: a completed {tf} bar whose low reaches the entry", bars[touched[0]][0] if touched else None))

    vfs = levels.get("valid_for_sessions")
    valid_until, left = None, None
    if signal_day is None or not vfs:
        out.append(_cond("validity", "Inside validity window", "unavailable", "no signal day or validity on the plan", "the plan's valid_for_sessions after the signal day"))
    else:
        today = now.date()
        used = sessions_after(signal_day, today, holidays)
        left = int(vfs) - used
        last_day = nth_session_after(signal_day, int(vfs), holidays)
        valid_until = datetime.combine(last_day, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(hours=15, minutes=30)
        inside = now <= valid_until
        note = "" if holidays_checked else " (exchange holidays not checked)"
        out.append(_cond("validity", "Inside validity window", "met" if inside else "not_met",
                         (f"{max(left, 0)} of {int(vfs)} sessions left" if inside else "expired") + note,
                         f"valid for {int(vfs)} sessions after the signal day {signal_day.isoformat()}"))

    if stop is None:
        out.append(_cond("invalidation", "Invalidation", "unavailable", "no stop", "a close below the stop"))
    else:
        hit = [i for i in since if float(bars[i][4]) < stop]
        out.append(_cond("invalidation", f"Invalidation: close below {_fmt(stop)}", "hit" if hit else "not_hit",
                         f"hit at {bars[hit[0]][0][:16].replace('T', ' ')}" if hit else "not hit", f"a completed {tf} close below the stop since the signal day",
                         bars[hit[0]][0] if hit else None))
    return {"evaluated_at_bar": bar[0], "conditions": out, "volume_bar": vol_bar,
            "valid_until": valid_until.isoformat() if valid_until else None, "sessions_left": left, "reason": None}


def stage_markers(signals: Sequence[Dict[str, Any]], bars: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """`signals`: [{signal_date (YYYY-MM-DD), stage, revision?}] for the symbol, any order. One marker where the mapped kind
    CHANGES from the previous signal day's (a run of READY days is one READY), at the last bar of that day."""
    last_bar_of: Dict[str, str] = {}
    for b in bars:
        last_bar_of[b[0][:10]] = b[0]
    out: List[Dict[str, Any]] = []
    prev, prev_day = None, None
    for s in sorted(signals, key=lambda r: (r["signal_date"], r.get("revision") or 0)):
        kind = STAGE_KIND.get(str(s.get("stage") or "").upper())
        day = date.fromisoformat(s["signal_date"])
        if prev_day is not None and (day - prev_day).days > RUN_GAP_DAYS:
            prev = None                                # the symbol left the scanner's list in between: a new run
        prev_day = day
        if kind is None or kind == prev:
            prev = kind
            continue
        prev = kind
        at = last_bar_of.get(s["signal_date"])
        if at is None:
            continue
        out.append({"kind": kind, "at": at, "signal_date": s["signal_date"], "stage": s.get("stage"),
                    "text": f"{kind}: the scanner's stage {s.get('stage')} on {s['signal_date']} (end of day)"})
    return out
