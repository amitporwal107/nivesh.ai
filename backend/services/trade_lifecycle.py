"""The unified trade lifecycle (Phase 2.2, docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md; design B §10 Q8b).

One state machine for every paper trade (`desk_paper_trades`, cash and strategy) and every AI Trader ticket
(`ai_trader_tickets`):

    NO_SETUP → WAIT_FOR_CONFIRMATION → TRADE_ELIGIBLE → ENTRY_TRIGGERED → POSITION_OPEN → EXIT_PENDING → CLOSED
    REJECTED is terminal: a candidate, plan or ticket that failed eligibility or risk validation.

Stored on the document itself:
    state          the current state (one of STATES)
    transitions    APPEND-ONLY list of events {event_id, seq, from, to, at, session, reason, source, actor,
                   rule_version, signal_at, data_as_of, levels, quantity, est_costs_rs, risk_decision_id,
                   rejection_reasons, fill_price, slippage, exit_reason, derived, lifecycle_version}

Writes. Every event is written in the SAME conditional update that changes the document's status: the update's
filter names the expected prior `state` (and the status the caller already filtered on), its `$set` carries the new
state and its `$push` the events (`update_for`). A repeated event finds the state already moved and matches
nothing, so it cannot be written twice; a retry after a restart re-reads the document and continues from its stored
state (`current_state`). Nothing here talks to the database; the callers own the writes.

Documents stored before this module existed have no `state`. `derive_history` rebuilds their events from the stored
fields (each flagged `derived: true`): scripts/backfill_trade_lifecycle.py writes them once, and a close of such a
document writes them in its own update first, so a closed trade always has a complete chain.

Nothing here places an order.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LIFECYCLE_VERSION = "trade-lifecycle-v1 (2026-10-27)"

NO_SETUP = "NO_SETUP"
WAIT = "WAIT_FOR_CONFIRMATION"
ELIGIBLE = "TRADE_ELIGIBLE"
TRIGGERED = "ENTRY_TRIGGERED"
OPEN = "POSITION_OPEN"
EXIT_PENDING = "EXIT_PENDING"
CLOSED = "CLOSED"
REJECTED = "REJECTED"
STATES = (NO_SETUP, WAIT, ELIGIBLE, TRIGGERED, OPEN, EXIT_PENDING, CLOSED, REJECTED)
TERMINAL = frozenset({CLOSED, REJECTED})

# from → the states it may move to. `None` is "no state yet" (the first event of a document).
ALLOWED: Dict[Optional[str], frozenset] = {
    None: frozenset({NO_SETUP, WAIT, ELIGIBLE, REJECTED}),
    NO_SETUP: frozenset({WAIT, ELIGIBLE, REJECTED}),
    WAIT: frozenset({ELIGIBLE, REJECTED}),
    # a conditional entry that is never reached, or is cancelled before its fill, closes from here with no position
    ELIGIBLE: frozenset({TRIGGERED, REJECTED, CLOSED}),
    # an AI Trader ticket's claim is released back to eligible when its paper trade could not be written
    TRIGGERED: frozenset({OPEN, ELIGIBLE, REJECTED}),
    OPEN: frozenset({EXIT_PENDING}),
    # an exit that could not complete goes back to open, to be retried by the next evaluation
    EXIT_PENDING: frozenset({CLOSED, OPEN}),
    CLOSED: frozenset(),
    REJECTED: frozenset(),
}

EVENT_FIELDS = ("event_id", "seq", "from", "to", "at", "session", "reason", "source", "actor", "rule_version",
                "signal_at", "data_as_of", "levels", "quantity", "est_costs_rs", "risk_decision_id",
                "rejection_reasons", "fill_price", "slippage", "exit_reason", "derived", "lifecycle_version")

IST = timezone(timedelta(hours=5, minutes=30))

# The plan's derived status (TradePlan.lifecycle.status), from the states of its linked trades: the furthest one wins.
PLAN_STATUS_BY_STATE = {ELIGIBLE: "approved", TRIGGERED: "triggered", OPEN: "open", EXIT_PENDING: "open",
                        CLOSED: "closed", REJECTED: "rejected"}
_PLAN_STATUS_ORDER = ("proposed", "rejected", "approved", "triggered", "closed", "open")


class InvalidTransition(ValueError):
    """A transition the state machine does not allow."""

    def __init__(self, frm: Optional[str], to: str):
        super().__init__(f"invalid lifecycle transition {frm} -> {to}")
        self.frm, self.to = frm, to


def allowed(frm: Optional[str], to: str) -> bool:
    return to in STATES and to in ALLOWED.get(frm, frozenset())


def ist_session(at: Any) -> Optional[str]:
    """The IST calendar day of a timestamp (ISO text or datetime), as YYYY-MM-DD; None when it cannot be read."""
    if at is None:
        return None
    if isinstance(at, date) and not isinstance(at, datetime):
        return at.isoformat()
    try:
        moment = at if isinstance(at, datetime) else datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).date().isoformat()


def _iso(at: Any) -> Optional[str]:
    if at is None:
        return None
    if isinstance(at, datetime):
        return at.astimezone(timezone.utc).isoformat()
    return str(at)


def make_event(doc_id: str, seq: int, frm: Optional[str], to: str, *, at: Any, reason: str, source: str,
               actor: Optional[str] = None, rule_version: Optional[str] = None, signal_at: Any = None,
               data_as_of: Any = None, levels: Optional[Dict[str, Any]] = None, quantity: Any = None,
               est_costs_rs: Optional[float] = None, risk_decision_id: Optional[str] = None,
               rejection_reasons: Optional[List[Any]] = None, fill_price: Optional[float] = None,
               slippage: Optional[float] = None, exit_reason: Optional[str] = None, session: Optional[str] = None,
               derived: bool = False) -> Dict[str, Any]:
    """One transition event. Raises InvalidTransition when the state machine does not allow it. The event id is
    `<doc id>:<seq>`: the same transition replayed has the same id, so a replay is recognisable."""
    if not allowed(frm, to):
        raise InvalidTransition(frm, to)
    return {
        "event_id": f"{doc_id}:{seq}", "seq": seq, "from": frm, "to": to,
        "at": _iso(at), "session": session or ist_session(at), "reason": reason, "source": source, "actor": actor,
        "rule_version": rule_version, "signal_at": _iso(signal_at) if isinstance(signal_at, datetime) else signal_at,
        "data_as_of": data_as_of, "levels": levels, "quantity": quantity, "est_costs_rs": est_costs_rs,
        "risk_decision_id": risk_decision_id, "rejection_reasons": rejection_reasons, "fill_price": fill_price,
        "slippage": slippage, "exit_reason": exit_reason, "derived": derived, "lifecycle_version": LIFECYCLE_VERSION,
    }


def chain(doc_id: str, frm: Optional[str], seq0: int, steps: Sequence[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Events for consecutive steps [(to, fields)] starting at state `frm` after event number `seq0`."""
    out: List[Dict[str, Any]] = []
    cur, seq = frm, seq0
    for to, fields in steps:
        seq += 1
        out.append(make_event(doc_id, seq, cur, to, **fields))
        cur = to
    return out


def last_seq(doc: Dict[str, Any]) -> int:
    return max((int(e.get("seq") or 0) for e in doc.get("transitions") or []), default=0)


def update_for(events: Sequence[Dict[str, Any]], extra_set: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The `$set` / `$push` parts that write `events` and move `state` to the last event's state, merged with the
    caller's own `$set` (the status change). Use with a filter that names the expected prior state."""
    upd: Dict[str, Any] = {"$set": dict(extra_set or {})}
    if events:
        upd["$set"]["state"] = events[-1]["to"]
        upd["$push"] = {"transitions": {"$each": list(events)}}
    return upd


def state_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The filter part that pins the state a write expects: the stored one (None matches a legacy document with no
    state field)."""
    return {"state": doc.get("state")}


def replay(transitions: Iterable[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
    """(the state the events lead to, problems). Every event must follow the previous one (its `from` is the previous
    `to`, its `seq` the next number) and be an allowed transition. A broken chain is reported, never repaired."""
    state: Optional[str] = None
    problems: List[str] = []
    expect = 1
    for e in transitions:
        seq = e.get("seq")
        if seq != expect:
            problems.append(f"event {e.get('event_id')}: seq {seq}, expected {expect}")
        if e.get("from") != state:
            problems.append(f"event {e.get('event_id')}: from {e.get('from')}, but the state was {state}")
        if not allowed(e.get("from"), e.get("to")):
            problems.append(f"event {e.get('event_id')}: {e.get('from')} -> {e.get('to')} is not an allowed transition")
        state = e.get("to")
        expect = (seq or expect) + 1
    return state, problems


def consistent(doc: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Whether a stored document's `state` is what its transitions replay to (restart / replay check)."""
    state, problems = replay(doc.get("transitions") or [])
    if doc.get("state") != state:
        problems.append(f"stored state {doc.get('state')} but the transitions replay to {state}")
    return not problems, problems


# ── paper trades (desk_paper_trades) ─────────────────────────────────────────
def _levels_cash(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"entry": doc.get("entry_price"), "stop": doc.get("stop_price"), "target": doc.get("target_price"),
            "entry_rule": doc.get("entry_rule") or "at_once"}


def _levels_strategy(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"reference": doc.get("reference_price"), "stop_underlying": doc.get("stop_underlying"),
            "target_underlying": doc.get("target_underlying"),
            "legs": [{"index": i, "entry_price": leg.get("entry_price"), "strike": leg.get("strike"),
                      "expiry": leg.get("expiry"), "side": leg.get("side")} for i, leg in enumerate(doc.get("legs") or [])]}


def _is_strategy(doc: Dict[str, Any]) -> bool:
    return doc.get("kind") == "strategy"


def _common(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Fields every event of a paper trade carries."""
    strat = _is_strategy(doc)
    sig = doc.get("signal") or {}
    return {
        "rule_version": doc.get("rules_version"),
        "signal_at": sig.get("signal_at") if strat else doc.get("signal_at") or (doc.get("source") or {}).get("signal_date"),
        "data_as_of": (doc.get("plan_ref") or {}).get("data_as_of"),
        "levels": _levels_strategy(doc) if strat else _levels_cash(doc),
        "quantity": ([{"lots": leg.get("lots"), "lot_size": leg.get("lot_size")} for leg in doc.get("legs") or []]
                     if strat else doc.get("quantity")),
        "risk_decision_id": doc.get("risk_decision_id"),
    }


def _source(doc: Dict[str, Any]) -> str:
    if doc.get("rolled_from"):
        return "roll"
    if (doc.get("source") or {}).get("kind") == "ai_trader":
        return "ai_trader"
    if doc.get("plan_ref"):
        return "trade_plan"
    return "desk_paper_trade"


def opening_events(doc: Dict[str, Any], *, est_costs_rs: Optional[float] = None,
                   actor: Optional[str] = None) -> List[Dict[str, Any]]:
    """The events a NEW paper trade is inserted with. An at-once entry (every strategy trade, and a cash trade
    recorded `at_once`) is eligible, triggered and open at the moment it is recorded, filled at the recorded price;
    a conditional cash entry (`break_above` / `pullback_to`) is eligible and waits for its level."""
    at = doc.get("opened_at")
    base = {**_common(doc), "at": at, "source": _source(doc), "actor": actor or doc.get("user_id")}
    plan = doc.get("plan_ref") or {}
    eligible_reason = (f"Plan {plan.get('plan_id')} ({plan.get('candidate_id')}) accepted for a paper trade."
                       if plan.get("plan_id") else "Paper trade accepted by the desk's checks.")
    if doc.get("rolled_from"):
        eligible_reason = f"Roll of paper trade {(doc['rolled_from'] or {}).get('trade_id')} accepted by the desk's checks."
    steps: List[Tuple[str, Dict[str, Any]]] = [(ELIGIBLE, {**base, "reason": eligible_reason, "est_costs_rs": est_costs_rs})]
    rule = "at_once" if _is_strategy(doc) else (doc.get("entry_rule") or "at_once")
    if rule == "at_once":
        fill = None if _is_strategy(doc) else doc.get("entry_price")
        steps.append((TRIGGERED, {**base, "reason": "At-once entry: triggered when recorded."}))
        steps.append((OPEN, {**base, "reason": "Filled at the recorded price" + (" (every leg)." if _is_strategy(doc) else "."),
                             "fill_price": fill, "slippage": 0.0 if fill is not None else None}))
    return chain(doc["_id"], None, 0, steps)


def derive_history(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The events a paper trade stored before this module would have had, rebuilt from its stored fields, each
    flagged `derived`. Up to its CURRENT state: for a closed trade that includes the close."""
    base = {**_common(doc), "source": "derived_from_stored_fields", "actor": None, "derived": True}
    opened = doc.get("opened_at")
    steps: List[Tuple[str, Dict[str, Any]]] = [(ELIGIBLE, {**base, "at": opened, "reason": "Recorded before the lifecycle "
                                                                                             "existed; rebuilt from the stored trade."})]
    strat = _is_strategy(doc)
    rule = "at_once" if strat else (doc.get("entry_rule") or "at_once")
    status = doc.get("status")
    reason = doc.get("exit_reason")
    entered: bool
    if rule == "at_once":
        entered = True
        steps.append((TRIGGERED, {**base, "at": opened, "reason": "At-once entry: triggered when recorded."}))
        steps.append((OPEN, {**base, "at": opened, "reason": "Filled at the recorded price.",
                             "fill_price": None if strat else doc.get("sim_entry_price") or doc.get("entry_price")}))
    else:
        entered = doc.get("entry_status") in ("assumed", "reached") or (status == "closed" and reason not in ("entry_not_reached", "cancelled", None))
        if entered:
            sess = doc.get("entry_session")
            fill = doc.get("sim_entry_price")
            steps.append((TRIGGERED, {**base, "at": sess or opened, "session": sess, "reason": f"Entry level reached ({rule})."}))
            steps.append((OPEN, {**base, "at": sess or opened, "session": sess, "reason": "Filled.", "fill_price": fill,
                                 "slippage": None if fill is None else round(float(fill) - float(doc.get("entry_price")), 4)}))
    if status == "closed":
        closed_at = doc.get("closed_at") or doc.get("updated_at")
        close = {**base, "at": closed_at, "session": doc.get("exit_session"), "exit_reason": reason,
                 "fill_price": doc.get("exit_price")}
        if not entered:
            steps.append((CLOSED, {**close, "reason": f"Closed without a position ({reason})."}))
        else:
            steps.append((EXIT_PENDING, {**close, "reason": f"Exit ({reason}) decided."}))
            steps.append((CLOSED, {**close, "reason": f"Closed ({reason})."}))
    return chain(doc["_id"], None, 0, steps)


def current_state(doc: Dict[str, Any]) -> Optional[str]:
    """The stored state, or the state its stored fields imply for a document stored before this module."""
    if doc.get("state"):
        return doc["state"]
    events = derive_history(doc)
    return events[-1]["to"] if events else None


def _history_and_state(doc: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    """(derived events to write first, the state to continue from, the last seq) for a write on `doc`."""
    if doc.get("state"):
        return [], doc["state"], last_seq(doc)
    derived = derive_history(doc)
    return derived, (derived[-1]["to"] if derived else None), len(derived)


def entry_fill_events(doc: Dict[str, Any], *, session: Any, fill_price: Optional[float],
                      at: Any = None) -> List[Dict[str, Any]]:
    """The events for a conditional cash entry that the bars show reached: TRADE_ELIGIBLE → ENTRY_TRIGGERED →
    POSITION_OPEN, with the fill and its slippage against the entry level. [] when the trade is not waiting."""
    history, state, seq = _history_and_state(doc)
    if state != ELIGIBLE:
        return []
    sess = session.isoformat() if isinstance(session, date) else session
    base = {**_common(doc), "source": "end_of_day_bars", "actor": "desk_paper_simulator", "at": at or sess, "session": sess}
    entry = doc.get("entry_price")
    slip = None if fill_price is None or entry is None else round(float(fill_price) - float(entry), 4)
    steps = [(TRIGGERED, {**base, "reason": f"Entry level reached on the {sess} session ({doc.get('entry_rule')})."}),
             (OPEN, {**base, "reason": "Filled" + (" at the open, beyond the level (gap)." if slip else " at the entry level."),
                     "fill_price": fill_price, "slippage": slip})]
    return history + chain(doc["_id"], state, seq, steps)


def close_events(doc: Dict[str, Any], *, exit_reason: str, at: Any, session: Any = None,
                 fill_price: Optional[float] = None, est_costs_rs: Optional[float] = None,
                 entry_session: Any = None, entry_fill: Optional[float] = None, entered: Optional[bool] = None,
                 source: str = "desk_paper_simulator", actor: Optional[str] = None,
                 note: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every event a close writes, from the document's current state to CLOSED:
        TRADE_ELIGIBLE, never entered      → CLOSED                        (entry_not_reached, cancelled)
        TRADE_ELIGIBLE, entered on the bars → ENTRY_TRIGGERED → POSITION_OPEN → EXIT_PENDING → CLOSED
        POSITION_OPEN                       → EXIT_PENDING → CLOSED
        EXIT_PENDING                        → CLOSED
    A legacy document's derived history comes first. Raises InvalidTransition from a terminal state."""
    history, state, seq = _history_and_state(doc)
    sess = session.isoformat() if isinstance(session, date) else session
    base = {**_common(doc), "source": source, "actor": actor, "at": at, "session": sess}
    steps: List[Tuple[str, Dict[str, Any]]] = []
    if state == ELIGIBLE:
        if entered is None:
            entered = exit_reason not in ("entry_not_reached", "cancelled")
        if not entered:
            steps.append((CLOSED, {**base, "reason": note or f"Closed without a position ({exit_reason}).",
                                   "exit_reason": exit_reason}))
            return history + chain(doc["_id"], state, seq, steps)
        es = entry_session.isoformat() if isinstance(entry_session, date) else entry_session
        entry = doc.get("entry_price")
        steps.append((TRIGGERED, {**base, "at": es or at, "session": es, "reason": "Entry level reached."}))
        steps.append((OPEN, {**base, "at": es or at, "session": es, "reason": "Filled.", "fill_price": entry_fill,
                             "slippage": None if entry_fill is None or entry is None else round(float(entry_fill) - float(entry), 4)}))
    elif state not in (OPEN, EXIT_PENDING):
        raise InvalidTransition(state, CLOSED)
    if state != EXIT_PENDING:
        steps.append((EXIT_PENDING, {**base, "reason": f"Exit ({exit_reason}) decided.", "exit_reason": exit_reason}))
    steps.append((CLOSED, {**base, "reason": note or f"Closed ({exit_reason}).", "exit_reason": exit_reason,
                           "fill_price": fill_price, "est_costs_rs": est_costs_rs}))
    return history + chain(doc["_id"], state, seq, steps)


def rejection_record(*, frm: Optional[str], reason: str, source: str, at: Any, codes: Sequence[str],
                     plan_id: Optional[str] = None, risk_decision_id: Optional[str] = None) -> Dict[str, Any]:
    """The REJECTED event of a refused open, for a record that has no trade document (the refusal's
    `risk_decisions` row, and the plan's own events when the request named a plan)."""
    if not allowed(frm, REJECTED):
        frm = None
    return {"from": frm, "to": REJECTED, "at": _iso(at), "session": ist_session(at), "reason": reason,
            "source": source, "rejection_reasons": list(codes), "plan_id": plan_id,
            "risk_decision_id": risk_decision_id, "lifecycle_version": LIFECYCLE_VERSION}


# ── AI Trader tickets (ai_trader_tickets) ────────────────────────────────────
def _ticket_common(ticket: Dict[str, Any]) -> Dict[str, Any]:
    decision = ticket.get("decision") or {}
    return {"rule_version": decision.get("limits_version") or ticket.get("strategy_version"),
            "signal_at": ticket.get("signal_date"), "data_as_of": ticket.get("signal_date"),
            "levels": {"entry": ticket.get("entry_price"), "stop": ticket.get("stop_price"), "target": ticket.get("target_price")},
            "quantity": ticket.get("quantity"), "risk_decision_id": ticket.get("risk_decision_id")}


def ticket_opening_events(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The events a NEW ticket is inserted with, from its status: rejected by the governor → REJECTED;
    awaiting_confirmation → TRADE_ELIGIBLE; confirmed (paper, cleared) → TRADE_ELIGIBLE → ENTRY_TRIGGERED."""
    base = {**_ticket_common(ticket), "at": ticket.get("created_at"), "source": "ai_trader", "actor": "risk_governor"}
    status = ticket.get("status")
    if status == "rejected":
        return chain(ticket["_id"], None, 0, [(REJECTED, {**base, "reason": "Refused by the risk governor.",
                                                          "rejection_reasons": list(ticket.get("reason_codes") or [])})])
    steps: List[Tuple[str, Dict[str, Any]]] = [(ELIGIBLE, {**base, "reason": "Cleared by the risk governor."})]
    if status == "confirmed":
        steps.append((TRIGGERED, {**base, "reason": "Paper mode: acted on at once."}))
    return chain(ticket["_id"], None, 0, steps)


def ticket_step(ticket: Dict[str, Any], to: str, *, at: Any, reason: str, actor: Optional[str] = None,
                **fields: Any) -> List[Dict[str, Any]]:
    """The event(s) that move a ticket to `to` from its current state (a legacy ticket's derived history first)."""
    history, state, seq = _ticket_history_and_state(ticket)
    if state == to:
        return []
    base = {**_ticket_common(ticket), "at": at, "source": "ai_trader", "actor": actor, **fields}
    return history + chain(ticket["_id"], state, seq, [(to, {**base, "reason": reason})])


def derive_ticket_history(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A legacy ticket's events rebuilt from its status (flagged `derived`)."""
    base = {**_ticket_common(ticket), "source": "derived_from_stored_fields", "actor": None, "derived": True,
            "at": ticket.get("created_at")}
    status = ticket.get("status")
    if status == "rejected" and ticket.get("rejected_by") in (None, "risk_governor"):
        return chain(ticket["_id"], None, 0, [(REJECTED, {**base, "reason": "Refused by the risk governor.",
                                                          "rejection_reasons": list(ticket.get("reason_codes") or [])})])
    steps: List[Tuple[str, Dict[str, Any]]] = [(ELIGIBLE, {**base, "reason": "Cleared by the risk governor."})]
    if status in ("confirmed", "executed_paper") or ticket.get("rejected_by") == "desk":
        steps.append((TRIGGERED, {**base, "reason": "Acted on."}))
    if status == "executed_paper":
        steps.append((OPEN, {**base, "at": ticket.get("confirmed_at") or ticket.get("updated_at"),
                             "reason": f"Paper trade {ticket.get('trade_id')} recorded."}))
    elif status == "rejected":
        steps.append((REJECTED, {**base, "at": ticket.get("rejected_at") or ticket.get("updated_at"),
                                 "reason": f"Rejected by the {ticket.get('rejected_by')}.",
                                 "rejection_reasons": [c for c in [ticket.get("reject_reason")] if c]}))
    elif status == "expired":
        steps.append((REJECTED, {**base, "at": ticket.get("updated_at"), "reason": "Expired: not confirmed in its session.",
                                 "rejection_reasons": ["expired"]}))
    return chain(ticket["_id"], None, 0, steps)


def _ticket_history_and_state(ticket: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    if ticket.get("state"):
        return [], ticket["state"], last_seq(ticket)
    derived = derive_ticket_history(ticket)
    return derived, (derived[-1]["to"] if derived else None), len(derived)


# ── the plan's derived status ────────────────────────────────────────────────
def plan_status(states: Iterable[Optional[str]]) -> str:
    """A TradePlan's lifecycle status from its linked trades' states: `proposed` with none; otherwise the furthest
    of approved / triggered / open / closed / rejected (an open position outranks a closed one)."""
    best = "proposed"
    for s in states:
        st = PLAN_STATUS_BY_STATE.get(s or "")
        if st and _PLAN_STATUS_ORDER.index(st) > _PLAN_STATUS_ORDER.index(best):
            best = st
    return best
