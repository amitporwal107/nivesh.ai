"""Plan version + actual fills -> exit-rules-v1 Rules and State, and the decisions of one clock moment (PHASE3_DESIGN §4).

PURE: no I/O, no clock. The rule engine is services/exit_rules.py; this module only adapts a plan to it:
  setup()     which row the levels are judged on, the levels in that row's terms, objectives, holding period, trail, trend
  at_open()   the OPEN moment: exit-rules-v1 stepped on an OPEN-ONLY row (high = low = open, no close). Its state is kept only
              when it decided something, so an open never moves the ATR or the high-water mark.
  at_close()  the CLOSE moment: exit-rules-v1 stepped on the whole row.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional

from services import exit_rules as XR

from .. import contracts as C

R = C.CloseReason
H = C.PriceHow
_TRAIL = re.compile(r"trail-atr-v1\s*\(\s*([0-9.]+)\s*[x×*]\s*ATR\s*([0-9]+)\s*\)", re.IGNORECASE)
_TREND = re.compile(r"trend-ema-v1(?:\s*\(\s*(?:EMA\s*)?([0-9]+)\s*\))?", re.IGNORECASE)
DERIVED = ("CE", "PE")


@dataclass(frozen=True)
class Setup:
    trigger_key: Optional[str]          # the leg key of the row levels are judged on; None = no level rules
    trigger_basis: str                  # OWN_ROW | FUTURE_ROW_TRANSLATED | UNDERLYING_ROW | NONE
    side: str                           # long | short (of the trigger series)
    ratio: Decimal                      # level multiplier (futures: future ÷ underlying previous closes)
    level: Optional[Decimal]            # invalidation level in the trigger's terms
    objectives: list[dict]              # [{"level": str, "fraction": str}] in the trigger's terms
    max_hold: Optional[int]
    trail: Optional[tuple[float, int]]  # (k, ATR period)
    trend: Optional[int]
    pre_expiry_sessions: Optional[int]
    entry_trigger_price: Decimal
    structure: bool                     # True: an option structure judged on the underlying (priced at its legs' rows)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = asdict(self)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


def parse_trail(text: Any) -> Optional[tuple[float, int]]:
    m = _TRAIL.search(str(text or ""))
    return (float(m.group(1)), int(m.group(2))) if m else None


def parse_trend(text: Any) -> Optional[int]:
    m = _TREND.search(str(text or ""))
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else XR.DEFAULT_TREND_PERIOD


def _dec(v: Any) -> Optional[Decimal]:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except Exception:  # noqa: BLE001 — a malformed plan field is reported in the notes, never guessed
        return None
    return d if d > 0 else None


def setup(body: dict, legs: list[dict], *, fut_prev_close: Optional[Decimal] = None,
          und_prev_close: Optional[Decimal] = None, und_open: Optional[Decimal] = None) -> Setup:
    """`legs`: position legs {kind, underlying, side LONG/SHORT, avg_price, expiry}. Prices are the entry session's (known at
    its open): the future's and the underlying's previous closes (for the futures ratio) and the underlying's open."""
    notes: list[str] = []
    kinds = {lg["kind"] for lg in legs}
    und = legs[0]["underlying"]
    inval = _dec((body.get("invalidation") or {}).get("underlying_level"))
    direction = str((body.get("market_context") or {}).get("direction") or "BULLISH").upper()
    holding = body.get("holding") or {}
    rules_text = body.get("exit_rules") or {}
    trail = parse_trail(rules_text.get("trailing"))
    trend = parse_trend(rules_text.get("trend"))
    if rules_text.get("trailing") and trail is None:
        notes.append(f"the plan's trailing text {rules_text.get('trailing')!r} names no trail-atr-v1 (k × ATRn): no trail")
    max_hold = holding.get("max_holding_days")
    max_hold = int(max_hold) if isinstance(max_hold, (int, float)) and int(max_hold) >= 1 else None
    pre = holding.get("close_days_before_expiry")
    pre = int(pre) if isinstance(pre, (int, float)) and int(pre) >= 0 and any(lg.get("expiry") for lg in legs) else None
    ratio = Decimal("1")
    if kinds == {"EQ"}:
        key, basis, side, entry, structure = f"EQ:{und}", "OWN_ROW", "long", Decimal(str(legs[0]["avg_price"])), False
    elif kinds == {"FUT"} and len(legs) == 1:
        lg = legs[0]
        key = f"FUT:{und}:{lg['expiry']}"
        basis, side, structure = "FUTURE_ROW_TRANSLATED", ("long" if lg["side"] == "LONG" else "short"), False
        entry = Decimal(str(lg["avg_price"]))
        if fut_prev_close and und_prev_close:
            ratio = (fut_prev_close / und_prev_close).quantize(Decimal("0.00000001"))
        else:
            basis = "FUTURE_ROW"
            notes.append("the entry session's previous closes of the future and the share were not both known: the plan's "
                         "levels are used on the future's row as given (no basis translation)")
    else:
        structure = True
        if direction == "NEUTRAL":
            key, basis, side = None, "NONE", "long"
            notes.append("neutral structure: no level or objective rule; the holding period, the sessions-before-expiry rule "
                         "and settlement apply")
        else:
            key, basis, side = f"EQ:{und}", "UNDERLYING_ROW", ("short" if direction == "BEARISH" else "long")
        ref = _dec((body.get("entry") or {}).get("reference_price"))
        entry = und_open or ref or inval or Decimal("1")
        if und_open is None:
            notes.append("the underlying's open of the entry session was not read: the plan's reference price stands in as "
                          "the trail's starting mark")
    level = (inval * ratio).quantize(Decimal("0.01")) if inval is not None and key else None
    objectives = []
    for t in body.get("targets") or []:
        lvl = _dec(t.get("level"))
        if lvl is None or not key:
            continue
        if (t.get("basis") or "UNDERLYING") != "UNDERLYING":
            notes.append(f"an objective on basis {t.get('basis')} is not judged in 3A (only underlying levels)")
            continue
        frac = Decimal(str(t.get("exit_fraction") or "1"))
        objectives.append({"level": str((lvl * ratio).quantize(Decimal("0.01"))), "fraction": str(min(max(frac, Decimal("0")), Decimal("1")))})
    return Setup(trigger_key=key, trigger_basis=basis, side=side, ratio=ratio, level=level, objectives=objectives,
                 max_hold=max_hold, trail=trail, trend=trend, pre_expiry_sessions=pre, entry_trigger_price=entry,
                 structure=structure, notes=notes)


def make_rules(s: Setup, next_objective: int) -> XR.Rules:
    obj = s.objectives[next_objective]["level"] if next_objective < len(s.objectives) else None
    return XR.Rules(side=s.side, target=float(obj) if obj else None, max_hold_sessions=s.max_hold,
                    trail_atr_mult=s.trail[0] if s.trail else None,
                    atr_period=s.trail[1] if s.trail else XR.DEFAULT_ATR_PERIOD, trend_ema_period=s.trend, price_decimals=2)


def start_state(s: Setup, rules: XR.Rules, *, session: date, warmup: list[dict]) -> XR.State:
    scaled = [{k: (float(v) * float(s.ratio) if k in ("open", "high", "low", "close") and v is not None else v)
               for k, v in b.items()} for b in warmup]
    return XR.start(float(s.entry_trigger_price), float(s.level) if s.level is not None else None, rules, session=session,
                    warmup=scaled)


# ── state <-> JSON ────────────────────────────────────────────────────────────────────────────────────────────────────

def state_to_json(st: XR.State) -> dict:
    return asdict(st)


def state_from_json(d: dict) -> XR.State:
    d = dict(d)
    for k in ("atr_trs", "ema_closes"):
        d[k] = tuple(d.get(k) or ())
    for k in ("stop_history", "events"):
        d[k] = tuple(dict(x) for x in (d.get(k) or ()))
    return XR.State(**d)


# ── decisions ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Decision:
    reason: C.CloseReason
    how: C.PriceHow
    fraction: Decimal                  # of the remaining quantity
    level: Optional[Decimal] = None    # the level or objective, in the trigger's terms
    trigger_price: Optional[Decimal] = None
    gapped: bool = False
    both_in_range: bool = False
    objective_index: Optional[int] = None
    detail: str = ""


def _bar(b: Any, session: date) -> dict:
    return {"date": session, "open": _f(b.open), "high": _f(b.high), "low": _f(b.low), "close": _f(b.close)}


def _f(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


def _reason(ex: dict) -> C.CloseReason:
    return C.CloseReason(ex["reason"])


def _fraction(s: Setup, idx: int) -> Decimal:
    return Decimal(s.objectives[idx]["fraction"]) if idx < len(s.objectives) else Decimal("1")


def at_open(s: Setup, state: XR.State, next_objective: int, open_px: Decimal, session: date) -> Optional[Decision]:
    """Only the open is seen. Open through the level: closing at the real open. An objective already passed at the open: a
    resting limit fills at the objective (shares, futures) or the structure closes at its legs' opens. Trend due: the open."""
    if s.trigger_key is None or state.closed:
        return None
    rules = make_rules(s, next_objective)
    o = float(open_px)
    _st, ex = XR.step(state, {"date": session, "open": o, "high": o, "low": o, "close": None}, rules)
    if ex is None:
        return None
    r = _reason(ex)
    if r in (R.STOP, R.TRAILING_STOP, R.TREND):
        return Decision(reason=r, how=H.OPEN, fraction=Decimal("1"), level=_lvl(ex.get("stop_in_force")),
                        trigger_price=open_px, gapped=bool(ex.get("gapped")), detail=f"open {open_px}")
    if r == R.TARGET:
        lvl = Decimal(s.objectives[next_objective]["level"])
        through = open_px > lvl if s.side == "long" else open_px < lvl
        if not through:
            return None
        return Decision(reason=r, how=H.OPEN if s.structure else H.OBJECTIVE, fraction=_fraction(s, next_objective),
                        level=lvl, trigger_price=open_px, objective_index=next_objective,
                        detail=f"open {open_px} beyond the objective {lvl}")
    return None


def _lvl(v: Any) -> Optional[Decimal]:
    return Decimal(str(v)).quantize(Decimal("0.01")) if v is not None else None


@dataclass
class CloseStep:
    state: XR.State                            # the state for the next session (closed when everything closes)
    decision: Optional[Decision] = None
    then: Optional[Decision] = None            # a second closing the same moment (the rest after a partial objective)
    events: list[dict] = field(default_factory=list)


def at_close(s: Setup, state: XR.State, next_objective: int, bar: Any, session: date, *, expired: bool = False,
             freeze_trail: bool = False) -> CloseStep:
    """The whole row is known. Raises exit_rules.IncompleteBar for a row with no usable high and low."""
    if s.trigger_key is None:
        rules = make_rules(s, next_objective)
        held = replace(state, sessions_held=state.sessions_held + 1, events=())
        if expired:
            return CloseStep(state=replace(held, closed=True),
                             decision=Decision(reason=R.EXPIRY, how=H.SETTLEMENT, fraction=Decimal("1")))
        if rules.max_hold_sessions is not None and held.sessions_held >= rules.max_hold_sessions:
            return CloseStep(state=replace(held, closed=True),
                             decision=Decision(reason=R.TIME, how=H.CLOSE, fraction=Decimal("1"),
                                               detail=f"{held.sessions_held} sessions held"))
        return CloseStep(state=held)
    rules = make_rules(s, next_objective)
    if freeze_trail and rules.trailing:
        rules = replace(rules, trail_atr_mult=None)
    b = _bar(bar, session)
    st, ex = XR.step(state, b, rules, expired=expired)
    if ex is None:
        return CloseStep(state=st, events=list(st.events))
    r = _reason(ex)
    px = Decimal(str(ex["price"])).quantize(Decimal("0.0001")) if ex.get("price") is not None else None
    if r in (R.STOP, R.TRAILING_STOP):
        how = H.CLOSE if (s.structure or ex.get("fill") == "gap_open") else H.LEVEL
        return CloseStep(state=st, events=list(st.events), decision=Decision(
            reason=r, how=how, fraction=Decimal("1"), level=_lvl(ex.get("stop_in_force")), trigger_price=px,
            gapped=bool(ex.get("gapped")), both_in_range=bool(ex.get("both_in_range")),
            detail=f"row {b['low']}–{b['high']}"))
    if r == R.TARGET:
        lvl = Decimal(s.objectives[next_objective]["level"])
        hi, lo = Decimal(str(b["high"])), Decimal(str(b["low"]))
        through = hi > lvl if s.side == "long" else lo < lvl
        if not s.structure and not through:
            # a touch is not a fill (PRD §8.6): the session goes on as if the objective were not there
            st2, ex2 = XR.step(state, b, rules, skip_target=True, expired=expired)
            out = CloseStep(state=st2, events=list(st2.events) + [{"code": "objective_touched", "session": str(session),
                            "text": f"the row reached {lvl} without trading through it; a resting order there does not fill"}])
            if ex2 is not None:
                out.decision = _from_ex(s, ex2, b)
            return out
        frac = _fraction(s, next_objective)
        d = Decision(reason=r, how=H.CLOSE if s.structure else H.OBJECTIVE, fraction=frac, level=lvl, trigger_price=px,
                     objective_index=next_objective, detail=f"row high {b['high']}, low {b['low']}")
        if frac >= 1:
            return CloseStep(state=st, decision=d, events=list(st.events))
        # a partial objective: the rest of the position goes on with this session's row stepped without the objective
        nxt = make_rules(s, next_objective + 1)
        if freeze_trail and nxt.trailing:
            nxt = replace(nxt, trail_atr_mult=None)
        st2, ex2 = XR.step(state, b, replace(nxt, target=None), skip_target=True, expired=expired)
        out = CloseStep(state=st2, decision=d, events=list(st2.events))
        if ex2 is not None:
            out.then = _from_ex(s, ex2, b)
        return out
    return CloseStep(state=st, decision=_from_ex(s, ex, b), events=list(st.events))


def _from_ex(s: Setup, ex: dict, b: dict) -> Decision:
    r = _reason(ex)
    if r == R.EXPIRY:
        return Decision(reason=r, how=H.SETTLEMENT, fraction=Decimal("1"))
    if r in (R.STOP, R.TRAILING_STOP):
        how = H.CLOSE if (s.structure or ex.get("fill") == "gap_open") else H.LEVEL
        return Decision(reason=r, how=how, fraction=Decimal("1"), level=_lvl(ex.get("stop_in_force")),
                        gapped=bool(ex.get("gapped")), both_in_range=bool(ex.get("both_in_range")))
    return Decision(reason=r, how=H.CLOSE, fraction=Decimal("1"),
                    detail=f"{ex.get('sessions_held')} sessions held" if r == R.TIME else "")


def lots_to_close(quantity: int, lot: int, fraction: Decimal) -> int:
    """Whole lots of `fraction` of what is left; a fraction that rounds to no lot closes everything (PHASE3_DESIGN §13-7)."""
    if fraction >= 1:
        return quantity
    lots = (Decimal(quantity // lot) * fraction).to_integral_value(rounding=ROUND_DOWN)
    return int(lots) * lot if lots >= 1 else quantity
