"""One exit-evaluation step, shared by the DSL backtest and the desk paper-trade simulators (version `exit-rules-v1`).

    step(state, bar, rules) -> (state', exit | None)

Pure: no I/O, no clock, no globals; the same state and bar always give the same answer. A caller replays a trade by
folding `step` over its end-of-day bars, oldest first, from the first session it holds.

ORDER INSIDE ONE SESSION (the bar of session t: open, high, low, close)
  1. Gap rule on the OPEN, against the stop as it stood at the previous close. An open through the stop never traded at
     the stop: the fill is the open, worse than the stop (`fill: "gap_open"`, `gapped: True`).
  2. A trend exit signalled at the previous close fills at this open (`trend`, `fill: "open"`).
  3. Intrabar touch of that SAME stop (the stop is never raised by this bar's own high before its low is tested), or of
     the target. Both inside one bar → the stop: a daily bar does not show which came first, so the conservative reading
     is taken (`both_in_range: True`). A target touch fills AT THE TARGET, also when the bar opened beyond it (a target
     jump): no credit is taken for the better open (the desk FILL MODEL, services/desk_trading.py).
  4. Expiry (when the caller says the position expired this session), then the time exit: the close of the session
     `max_hold_sessions` sessions held. Time is counted in SESSIONS held (bars stepped), never calendar days.
  5. Only after the bar, for the next session:
       ATR_t   Wilder's average true range over `atr_period` bars UP TO AND INCLUDING t (seeded by the caller from bars
               before the entry, or from the first `atr_period` true ranges after it). Never a stand-in value: with no
               ATR yet, the trail does not move and the step says so (`atr_unavailable`).
       mark    the high-water mark is the highest HIGH since entry (PRD §7 "highest price since entry"; the low-water
               mark, the lowest LOW, for a short), seeded with the entry price.
       trail   stop = max(stop, mark − k·ATR_t) for a long (min(stop, mark + k·ATR_t) for a short), rounded to the
               paisa; in force from the next session. The stop NEVER loosens, and every change is a new version in
               `stop_history` [{session, stop, reason, version}].
       trend   close below EMA-N (above, for a short) → exit at the next session's open.

EXIT REASONS: `stop` (the initial stop), `trailing_stop` (a stop the trail raised), `target`, `time`, `trend`, `expiry`;
`manual` and `risk_control` are recorded by callers, never produced here.

RULES. Stop, target and time are always on. ATR trailing (`trail-atr-v1`) and the EMA trend exit (`trend-ema-v1`) are
OPT-IN, labelled, versioned RESEARCH rules (owner decision D4, docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md §7): off unless
a trade or a backtest spec turns them on, and a rule that is off changes nothing (no state it keeps is read by an exit).
Neither is a default until the corrected backtest has tested it.

Prices are whatever basis the caller trades on (raw bhavcopy for paper trades, split-adjusted for the backtest); fills are
returned before slippage, which the caller applies.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "exit-rules-v1"
TRAIL_ATR_VERSION = "trail-atr-v1"
TREND_EMA_VERSION = "trend-ema-v1"
REASONS = ("stop", "trailing_stop", "target", "time", "trend", "expiry", "manual", "risk_control")
SIDES = ("long", "short")

DEFAULT_ATR_PERIOD = 14
DEFAULT_TREND_PERIOD = 20
MAX_TRAIL_MULT = 10.0
MAX_PERIOD = 200


class IncompleteBar(ValueError):
    """A bar without a usable high and low: no exit can be judged on it. Callers stop the scan (paper) or skip it."""


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out > 0 else None


@dataclass(frozen=True)
class Rules:
    """What is evaluated. `trail_atr_mult` / `trend_ema_period` None = that research rule is OFF."""
    side: str = "long"
    target: Optional[float] = None
    max_hold_sessions: Optional[int] = None
    trail_atr_mult: Optional[float] = None
    atr_period: int = DEFAULT_ATR_PERIOD
    trend_ema_period: Optional[int] = None
    price_decimals: Optional[int] = 2

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}")
        if self.target is not None and _num(self.target) is None:
            raise ValueError("target must be a positive number")
        if self.max_hold_sessions is not None and (not isinstance(self.max_hold_sessions, int) or self.max_hold_sessions < 1):
            raise ValueError("max_hold_sessions must be a whole number of sessions, at least 1")
        if self.trail_atr_mult is not None and not (0 < float(self.trail_atr_mult) <= MAX_TRAIL_MULT):
            raise ValueError(f"trail_atr_mult must be in (0, {MAX_TRAIL_MULT}]")
        if not isinstance(self.atr_period, int) or not 2 <= self.atr_period <= MAX_PERIOD:
            raise ValueError(f"atr_period must be a whole number from 2 to {MAX_PERIOD}")
        if self.trend_ema_period is not None and (not isinstance(self.trend_ema_period, int) or not 2 <= self.trend_ema_period <= MAX_PERIOD):
            raise ValueError(f"trend_ema_period must be a whole number from 2 to {MAX_PERIOD}")

    @property
    def trailing(self) -> bool:
        return self.trail_atr_mult is not None

    @property
    def trend(self) -> bool:
        return self.trend_ema_period is not None


@dataclass(frozen=True)
class State:
    """One position's exit state as of the close of the last session stepped (`stop` is in force for the NEXT one)."""
    entry_price: float
    stop: Optional[float]
    initial_stop: Optional[float]
    sessions_held: int = 0
    extreme: Optional[float] = None                 # high-water (long) / low-water (short) since entry
    atr: Optional[float] = None                     # ATR as of the last close stepped
    atr_trs: Tuple[float, ...] = ()                 # true ranges collected while the ATR has no seed
    prev_close: Optional[float] = None
    ema: Optional[float] = None
    ema_closes: Tuple[float, ...] = ()              # closes collected while the EMA has no seed
    trend_pending: bool = False                     # a close crossed the EMA: exit at the next open
    stop_history: Tuple[Dict[str, Any], ...] = ()
    stop_version: int = 1
    events: Tuple[Dict[str, Any], ...] = ()         # what THIS step noticed (stop raised, ATR unavailable, ...)
    closed: bool = False


def validate_levels(entry: Any, stop: Any, target: Any = None, side: str = "long") -> None:
    """Raise ValueError naming the problem when the levels cannot be a trade: a missing or non-positive price, a long's
    stop at or above its entry (a short's at or below), a long's target at or below its entry (a short's at or above)."""
    e, s = _num(entry), _num(stop)
    if e is None:
        raise ValueError("invalid_entry_price")
    if s is None:
        raise ValueError("invalid_stop_price")
    if side == "long" and s >= e:
        raise ValueError("stop_not_below_entry")
    if side == "short" and s <= e:
        raise ValueError("stop_not_above_entry")
    if target is not None:
        t = _num(target)
        if t is None:
            raise ValueError("invalid_target_price")
        if side == "long" and t <= e:
            raise ValueError("target_not_above_entry")
        if side == "short" and t >= e:
            raise ValueError("target_not_below_entry")


def _round(value: float, rules: Rules) -> float:
    return round(value, rules.price_decimals) if rules.price_decimals is not None else value


def start(entry_price: float, stop: Optional[float], rules: Rules, *, session: Any = None,
          atr: Optional[float] = None, prev_close: Optional[float] = None, ema: Optional[float] = None,
          warmup: Iterable[Dict[str, Any]] = ()) -> State:
    """The state at entry. `stop` None = no stop (a neutral structure). Indicator seeds, all optional:
    `warmup` = end-of-day bars BEFORE the first session held (oldest first): the ATR and EMA are worked out from them
    exactly as `step` would; `atr` / `prev_close` / `ema` = values already known as of the entry close (the backtest's
    stored atr14) and override what the warm-up gave. A seed that is missing, zero or not a number is not used: the
    indicator then seeds itself from the bars after entry."""
    entry = _num(entry_price)
    if entry is None:
        raise ValueError("invalid_entry_price")
    s = None if stop is None else _num(stop)
    if stop is not None and s is None:
        raise ValueError("invalid_stop_price")
    history = ({"session": _session_text(session), "stop": _round(s, rules), "reason": "initial", "version": 1,
                "side": rules.side},) if s is not None else ()
    state = State(entry_price=entry, stop=_round(s, rules) if s is not None else None,
                  initial_stop=_round(s, rules) if s is not None else None, extreme=entry, stop_history=history)
    for bar in warmup:
        state = _indicators(state, bar, rules)
    seed_atr, seed_close, seed_ema = _num(atr), _num(prev_close), _num(ema)
    if seed_atr is not None:
        state = replace(state, atr=seed_atr, atr_trs=())
    if seed_close is not None:
        state = replace(state, prev_close=seed_close)
    if seed_ema is not None:
        state = replace(state, ema=seed_ema, ema_closes=())
    return replace(state, events=(), trend_pending=False)


def _session_text(session: Any) -> Optional[str]:
    if session is None:
        return None
    return session.isoformat() if hasattr(session, "isoformat") else str(session)[:10]


def _indicators(state: State, bar: Dict[str, Any], rules: Rules) -> State:
    """ATR and EMA updated with one bar (only the ones a rule that is ON needs)."""
    high, low, close = _num(bar.get("high")), _num(bar.get("low")), _num(bar.get("close"))
    out = state
    if rules.trailing and high is not None and low is not None:
        pc = state.prev_close
        tr = max(high - low, abs(high - pc), abs(low - pc)) if pc is not None else high - low
        n = rules.atr_period
        if state.atr is not None:
            out = replace(out, atr=(state.atr * (n - 1) + tr) / n)
        else:
            trs = state.atr_trs + (tr,)
            out = replace(out, atr=sum(trs) / n, atr_trs=()) if len(trs) >= n else replace(out, atr_trs=trs)
    if rules.trend and close is not None:
        n = rules.trend_ema_period
        if state.ema is not None:
            alpha = 2.0 / (n + 1)
            out = replace(out, ema=alpha * close + (1 - alpha) * state.ema)
        else:
            closes = state.ema_closes + (close,)
            out = replace(out, ema=sum(closes) / n, ema_closes=()) if len(closes) >= n else replace(out, ema_closes=closes)
    if close is not None:
        out = replace(out, prev_close=close)
    return out


def _exit(reason: str, price: float, session: Any, fill: str, state: State, *, gapped: bool = False,
          both: bool = False) -> Dict[str, Any]:
    return {"reason": reason, "price": price, "session": session, "fill": fill, "gapped": gapped,
            "both_in_range": both, "stop_in_force": state.stop, "sessions_held": state.sessions_held,
            "rules_version": VERSION}


def step(state: State, bar: Dict[str, Any], rules: Rules, *, skip_target: bool = False,
         expired: bool = False) -> Tuple[State, Optional[Dict[str, Any]]]:
    """Evaluate one session's bar (see the module docstring for the order). `skip_target`: the caller knows the target
    cannot count this session (a pull-back entry's own session, whose high may have come before the fill). `expired`:
    the position expired this session (strategy trades), checked after the stop and target and before the time exit.

    Returns (the new state, the exit or None). The exit is {reason, price, session, fill, gapped, both_in_range,
    stop_in_force, sessions_held, rules_version}; `price` is before slippage. Raises IncompleteBar when the bar has no
    usable high and low, and ValueError when stepped after a close."""
    if state.closed:
        raise ValueError("the position is already closed")
    high, low = _num(bar.get("high")), _num(bar.get("low"))
    if high is None or low is None or high < low:
        raise IncompleteBar(f"the {bar.get('date')} bar has no usable high and low")
    opn, close = _num(bar.get("open")), _num(bar.get("close"))
    session = bar.get("date")
    long = rules.side == "long"
    held = replace(state, sessions_held=state.sessions_held + 1, events=())
    stop = held.stop
    stop_reason = "trailing_stop" if _raised(held, rules) else "stop"
    target = None if skip_target else rules.target
    hit_target = target is not None and (high >= target if long else low <= target)
    events: List[Dict[str, Any]] = []

    def done(ex: Dict[str, Any]) -> Tuple[State, Dict[str, Any]]:
        return replace(held, closed=True, events=tuple(events)), ex

    # 1. gap through the stop at the open (the stop as of the previous close)
    if stop is not None and opn is not None and (opn < stop if long else opn > stop):
        return done(_exit(stop_reason, opn, session, "gap_open", held, gapped=True, both=hit_target))
    # 2. a trend exit signalled at the previous close fills at this open
    if held.trend_pending and rules.trend:
        if opn is not None:
            return done(_exit("trend", opn, session, "open", held))
        events.append({"code": "open_unknown", "session": _session_text(session),
                       "text": "The trend exit was due at this open, but the bar has no open; it is taken at the close."})
        if close is not None:
            return done(_exit("trend", close, session, "close", held))
    # 3. intrabar touch of the same stop, then the target
    hit_stop = stop is not None and (low <= stop if long else high >= stop)
    if hit_stop:
        if opn is None:
            events.append({"code": "open_unknown", "session": _session_text(session),
                           "text": "The bar has no open, so a gap through the stop cannot be seen; filled at the stop."})
        return done(_exit(stop_reason, stop, session, "level", held, both=hit_target))
    if hit_target:
        return done(_exit("target", target, session, "level", held))
    # 4. expiry, then time (closes)
    if expired:
        return done(_exit("expiry", close if close is not None else 0.0, session, "close", held))
    if rules.max_hold_sessions is not None and held.sessions_held >= rules.max_hold_sessions and close is not None:
        return done(_exit("time", close, session, "close", held))
    # 5. after the bar: indicators as of this close, then the trail and the trend check for the next session
    nxt = _indicators(held, bar, rules)
    if rules.trailing and stop is not None:
        mark = held.extreme
        mark = max(mark, high) if long else min(mark, low)
        nxt = replace(nxt, extreme=mark)
        atr = nxt.atr
        if atr is None or atr <= 0:
            events.append({"code": "atr_unavailable", "session": _session_text(session),
                           "text": (f"Not enough bars for a {rules.atr_period}-session ATR yet"
                                    if atr is None else "The ATR is zero") + "; the trailing stop did not move."})
        else:
            cand = _round(mark - rules.trail_atr_mult * atr if long else mark + rules.trail_atr_mult * atr, rules)
            if (cand > stop + 1e-9) if long else (cand < stop - 1e-9):
                version = nxt.stop_version + 1
                entry = {"session": _session_text(session), "stop": cand, "reason": "trailing_atr", "version": version,
                         "side": rules.side, "mark": _round(mark, rules), "atr": round(atr, 4), "k": rules.trail_atr_mult}
                nxt = replace(nxt, stop=cand, stop_version=version, stop_history=nxt.stop_history + (entry,))
                events.append({"code": "stop_raised" if long else "stop_lowered", "session": _session_text(session),
                               "text": f"Trailing stop moved to {cand} (mark {round(mark, 2)} − {rules.trail_atr_mult} × ATR "
                                       f"{round(atr, 2)}), in force from the next session.", "price": cand})
    if rules.trend and close is not None and nxt.ema is not None and (close < nxt.ema if long else close > nxt.ema):
        nxt = replace(nxt, trend_pending=True)
        events.append({"code": "trend_signal", "session": _session_text(session),
                       "text": f"Closed {'below' if long else 'above'} the {rules.trend_ema_period}-session EMA "
                               f"({round(nxt.ema, 2)}); the trend exit is taken at the next open."})
    return replace(nxt, events=tuple(events)), None


def _raised(state: State, rules: Rules) -> bool:
    if state.stop is None or state.initial_stop is None:
        return False
    return state.stop > state.initial_stop + 1e-9 if rules.side == "long" else state.stop < state.initial_stop - 1e-9


def replay(state: State, bars: Iterable[Dict[str, Any]], rules: Rules) -> Tuple[State, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fold `step` over bars until the first exit: (final state, exit or None, every event noticed on the way)."""
    events: List[Dict[str, Any]] = []
    for bar in bars:
        state, ex = step(state, bar, rules)
        events.extend(state.events)
        if ex is not None:
            return state, ex, events
    return state, None, events


# ── opt-in rule configuration (stored on a paper trade as `exit_rules`) ─────────
RULE_CODES = ("trailing_atr", "trend_ema")


def clean_rule_config(raw: Any) -> List[Dict[str, Any]]:
    """The opt-in research rules from a request: {"trailing_atr": {"k": 2, "atr_period": 14}, "trend_ema": {"period": 20}}
    (either key optional; null or {} = none). Returns the list stored on the trade, each {code, version, params}.
    Raises ValueError("invalid_exit_rules") on anything else."""
    if raw is None:
        return []
    if not isinstance(raw, dict) or set(raw) - set(RULE_CODES):
        raise ValueError("invalid_exit_rules")
    out: List[Dict[str, Any]] = []
    trail = raw.get("trailing_atr")
    if trail is not None:
        if not isinstance(trail, dict) or set(trail) - {"k", "atr_period"}:
            raise ValueError("invalid_exit_rules")
        k = trail.get("k")
        period = trail.get("atr_period", DEFAULT_ATR_PERIOD)
        if isinstance(k, bool) or not isinstance(k, (int, float)) or not 0 < float(k) <= MAX_TRAIL_MULT:
            raise ValueError("invalid_exit_rules")
        if isinstance(period, bool) or not isinstance(period, int) or not 2 <= period <= MAX_PERIOD:
            raise ValueError("invalid_exit_rules")
        out.append({"code": "trailing_atr", "version": TRAIL_ATR_VERSION, "params": {"k": float(k), "atr_period": period}})
    trend = raw.get("trend_ema")
    if trend is not None:
        if not isinstance(trend, dict) or set(trend) - {"period"}:
            raise ValueError("invalid_exit_rules")
        period = trend.get("period", DEFAULT_TREND_PERIOD)
        if isinstance(period, bool) or not isinstance(period, int) or not 2 <= period <= MAX_PERIOD:
            raise ValueError("invalid_exit_rules")
        out.append({"code": "trend_ema", "version": TREND_EMA_VERSION, "params": {"period": period}})
    return out


def rule_labels(stored: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The stored opt-in rules as the API shows them: {code, version, label, params}."""
    out: List[Dict[str, Any]] = []
    for r in stored or []:
        p = r.get("params") or {}
        if r.get("code") == "trailing_atr":
            label = (f"ATR trailing stop: highest high since entry − {p.get('k'):g} × ATR({p.get('atr_period')}), worked out at "
                     f"each close and in force from the next session; never loosens (research rule {r.get('version')}, opt-in)")
        elif r.get("code") == "trend_ema":
            label = (f"Trend exit: a close below the {p.get('period')}-session EMA exits at the next session's open "
                     f"(research rule {r.get('version')}, opt-in)")
        else:
            label = str(r.get("code"))
        out.append({"code": r.get("code"), "version": r.get("version"), "label": label, "params": dict(p)})
    return out


def rules_from_config(stored: Optional[List[Dict[str, Any]]], *, side: str = "long", target: Optional[float] = None,
                      max_hold_sessions: Optional[int] = None, price_decimals: Optional[int] = 2) -> Rules:
    """Rules for a trade from its stored opt-in list plus its always-on levels."""
    trail = next((r for r in stored or [] if r.get("code") == "trailing_atr"), None)
    trend = next((r for r in stored or [] if r.get("code") == "trend_ema"), None)
    return Rules(side=side, target=target, max_hold_sessions=max_hold_sessions,
                 trail_atr_mult=float(trail["params"]["k"]) if trail else None,
                 atr_period=int(trail["params"].get("atr_period", DEFAULT_ATR_PERIOD)) if trail else DEFAULT_ATR_PERIOD,
                 trend_ema_period=int(trend["params"]["period"]) if trend else None,
                 price_decimals=price_decimals)


def public_history(state: State) -> List[Dict[str, Any]]:
    """The stop history as the API shows it: {session, stop, reason, version}."""
    return [{"session": h.get("session"), "stop": h.get("stop"), "reason": h.get("reason"), "version": h.get("version")}
            for h in state.stop_history]
