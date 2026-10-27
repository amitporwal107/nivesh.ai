"""AI Trader Phases 4 and 5: paper execution and assisted tickets (docs/prd/AI_TRADER_PHASES_2_5.prd.md F4.1-F5.4).

What this module does. It turns the candidates a strategy's DSL screened into order intents (entry at the candidate's
close, the stop from `exit.stoploss_pct`, the target from `exit.target_rr`, the size from the risk budget), and it turns
an intent plus the Risk Governor's decision into a ticket document. A ticket is the record of one signal: what was
wanted, what the governor allowed, why, and what happened next. `ticket_text` writes the copy-ready order the user
places themselves, and `outcome_pairs` maps closed paper trades back to their tickets so calibration can be scored.

What it refuses to do. It imports no broker module and no order client, and it has no "live" mode: the only modes are
"paper" and "assisted" (`MODES`), so nothing here can reach a market. It never invents a price: the entry is the
candidate's close and nothing else, and a candidate without a usable close raises instead of being priced. It never
raises a limit: the size comes from `risk_governor.DEFAULT_LIMITS` (or the limits a person passes), and the governor
still vetoes afterwards. Sizing uses the risk budget only; every other limit is the governor's to apply.

Statuses (`TICKET_STATUSES`, the frozen set):
    awaiting_confirmation  assisted, cleared by the governor, waiting for the user. Expires at the end of the next
                           trading session (`expires_at`); an expired ticket can never be confirmed.
    confirmed              cleared and acted on, with no paper trade recorded yet (a transient state).
    executed_paper         a paper trade exists for it (`trade_id`); in assisted mode that trade is a shadow of the
                           order the user places at their own broker.
    rejected               not going ahead. `rejected_by` says who: "risk_governor" (any decision worse than hedge,
                           or a size under one share), "desk" (the paper-trade validator refused the order, so no
                           trade could be recorded for it) or "user".
    expired                an assisted ticket the user did not answer in time.

A decision worse than hedge never becomes actionable, in either mode: the ticket is stored with `governor_cleared`
false and the reason codes, and the user is not asked to confirm an order the risk layer refuses. A hedge decision is
actionable: it carries the full approved size and the governor's own precedence puts it above reduce, so the hedge
suggestion travels with the ticket instead of being recorded as a refusal nobody made.

Known limits, so they are not mistaken for facts: the session calendar here is weekdays only (no exchange holiday
list), so an expiry that lands on a holiday is one session early; `avg_daily_value` is read from a candidate row but
the market-data provider does not send it today, so the governor's liquidity limit is skipped with an info reason; and
the stated confidence of a ticket comes from the strategy's own win rate when it has one, else it is None and the
ticket is left out of the calibration report rather than scored against a made-up number.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .strategy import PAPER_STATS_FIELDS

from .risk_governor import DEFAULT_LIMITS, Decision, Intent, Limits

TICKET_STATUSES = ("awaiting_confirmation", "confirmed", "rejected", "expired", "executed_paper")
MODES = ("paper", "assisted")                 # there is no "live" mode, here or anywhere else in this feature
# hedge sits above reduce in the governor's precedence (PRD F3.2) and always carries the full approved size, so it is
# an order the risk layer allowed with a suggestion attached. Every other decision stops the ticket.
ACTIONABLE = ("approve", "reduce", "hedge")
TICKETS = "ai_trader_tickets"
STRATEGIES = "ai_trader_strategies"

SELF_PLACE_LINE = "Place this order yourself at your broker; Nivesh sends nothing."
TRADE_SOURCE_KIND = "ai_trader"

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_IST = time(15, 30)               # end of the regular NSE session


class ExecutionError(ValueError):
    """An input that cannot be turned into an intent or a ticket."""


# ── small helpers ────────────────────────────────────────────────────────────
def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _floor(x: float) -> int:
    return max(0, int(math.floor(x + 1e-9)))


def _text(value: Any) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ExecutionError(f"{value!r} is not a date") from None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _rupees(value: float) -> str:
    return f"₹{value:,.2f}"


# ── Phase 4: candidates -> intents ───────────────────────────────────────────
def intents_from_candidates(spec: Dict[str, Any], config: Dict[str, Any], candidates: Iterable[Dict[str, Any]], *,
                            as_of: Any, limits: Limits = DEFAULT_LIMITS) -> List[Intent]:
    """One Intent per screened candidate (PRD F4.1).

    `candidates` are the market-data provider's `screen()` rows: at least {symbol, close}, and `sector` and
    `avg_daily_value` are used when the row carries them so the governor can check its sector and liquidity limits.

    entry  = the candidate's close, rounded to paise. There is no other price source: a row without a usable close
             raises, so a signal is never priced off something made up.
    stop   = entry * (1 - exit.stoploss_pct / 100)
    target = entry + (entry - stop) * exit.target_rr
    size   = floor(initial_capital * the governor's risk-per-trade limit / the stop distance). A risk budget that does
             not buy one whole share gives quantity 0, which the governor then rejects, so the candidate is recorded
             with a reason instead of being dropped in silence.

    `as_of` is the signal date the intents belong to; it is validated here so a caller cannot ask for intents for a
    date the ticket will not agree with. The sizing itself does not depend on it."""
    _day(as_of)
    exit_ = spec.get("exit") if isinstance(spec, dict) else None
    if not isinstance(exit_, dict):
        raise ExecutionError("the strategy spec has no exit block")
    stoploss_pct = _num(exit_.get("stoploss_pct"))
    target_rr = _num(exit_.get("target_rr"))
    if stoploss_pct is None or not 0 < stoploss_pct < 100:
        raise ExecutionError("exit.stoploss_pct must be a number in (0, 100)")
    if target_rr is None or target_rr <= 0:
        raise ExecutionError("exit.target_rr must be a number above 0")
    capital = _num((config or {}).get("initial_capital"))
    if capital is None or capital <= 0:
        raise ExecutionError("config.initial_capital must be a positive number")
    budget = capital * limits.max_risk_per_trade_pct / 100.0

    intents: List[Intent] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise ExecutionError("every candidate must be an object")
        symbol = (_text(row.get("symbol")) or "").upper()
        if not symbol:
            raise ExecutionError("a candidate has no symbol")
        close = _num(row.get("close"))
        if close is None or close <= 0:
            raise ExecutionError(f"candidate {symbol} has no usable close")
        entry = round(close, 2)
        stop = round(entry * (1 - stoploss_pct / 100.0), 2)
        if not 0 < stop < entry:
            raise ExecutionError(f"candidate {symbol}: a {stoploss_pct}% stop does not sit below an entry of {entry}")
        target = round(entry + (entry - stop) * target_rr, 2)
        intents.append(Intent(symbol=symbol, quantity=_floor(budget / (entry - stop)), entry_price=entry,
                              stop_price=stop, target_price=target, sector=_text(row.get("sector")),
                              avg_daily_value=_num(row.get("avg_daily_value"))))
    return intents


# ── tickets ──────────────────────────────────────────────────────────────────
def next_session_end(as_of: Any) -> str:
    """End of the next trading session after `as_of`, as a UTC timestamp (PRD F5.1). Weekdays only: there is no
    exchange holiday list in this repo, so a session that is a holiday makes this one session early."""
    day = _day(as_of) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return _iso(datetime.combine(day, MARKET_CLOSE_IST, tzinfo=IST))


def is_expired(ticket: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True when an assisted ticket's confirmation window has passed. A ticket with no window never expires."""
    when = ticket.get("expires_at")
    if not when:
        return False
    moment = datetime.fromisoformat(str(when))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now or utcnow()) > moment


def stated_confidence(strategy_doc: Dict[str, Any]) -> Optional[float]:
    """The strategy's own stated chance of a win, as a fraction, for the calibration journal: the win rate of its
    paper record, else of its latest ordinary backtest. None when the strategy has neither, so nothing is scored
    against a number nobody stated. `win_rate` is in percentage points everywhere in this repo (see
    `strategy_engine.backtest._compute_metrics` and `paper_stats` below), so it is divided by 100 here.

    The one-shot holdout run is never read here. Its win rate is measured on the sealed 2023-01-01..2024-07-31 block,
    so using it would stamp every ticket with a confidence derived from the sealed block and then feed that back into
    the calibration report. A strategy whose only run is the holdout therefore states no confidence, and its tickets
    are left out of the report rather than scored against a number the sealed block supplied."""
    runs = [r for r in (strategy_doc.get("runs") or []) if isinstance(r, dict) and not r.get("holdout")]
    last_metrics = runs[-1].get("metrics") if runs else None
    for holder in (strategy_doc.get("paper_stats"), strategy_doc.get("metrics"), last_metrics):
        if not isinstance(holder, dict):
            continue
        points = _num(holder.get("win_rate"))
        if points is None or not 0.0 <= points <= 100.0:
            continue
        return points / 100.0
    return None


def new_ticket(user_id: str, strategy_doc: Dict[str, Any], intent: Intent, decision: Decision, *,
               as_of: Any, mode: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The ticket document for one intent and the governor's decision on it (PRD F4.2, F5.1).

    Every intent is stored, approved or not. A decision worse than hedge, or an approved size under one
    whole share, is stored as "rejected" by the risk governor with its reason codes; the user is never asked to
    confirm an order the risk layer has refused. An actionable paper ticket is "confirmed" until the caller records
    the paper trade with `mark_executed`; an actionable assisted ticket is "awaiting_confirmation" and carries the
    session it expires at."""
    if mode not in MODES:
        raise ExecutionError(f"mode must be one of {MODES}")
    signal_date = _day(as_of).isoformat()
    stamp = _iso(now or utcnow())
    cleared = decision.action in ACTIONABLE and decision.approved_qty >= 1
    reasons = [r.code for r in decision.reasons]
    if not cleared:
        status: str = "rejected"
    elif mode == "paper":
        status = "confirmed"
    else:
        status = "awaiting_confirmation"
    return {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "strategy_id": strategy_doc.get("_id"),
        "strategy_name": strategy_doc.get("name"),
        "strategy_version": strategy_doc.get("version"),
        "mode": mode,
        "signal_date": signal_date,
        "symbol": intent.symbol,
        "requested_quantity": intent.quantity,
        "quantity": decision.approved_qty,
        "entry_price": intent.entry_price,
        "stop_price": intent.stop_price,
        "target_price": intent.target_price,
        "sector": intent.sector,
        # Kept so the governor can re-apply its liquidity limit on confirm, the same reason the sector is kept. A
        # ticket whose signal carried no average traded value stores None, which the governor reports as unknown.
        "avg_daily_value": intent.avg_daily_value,
        "status": status,
        "governor_cleared": cleared,
        "decision": decision.to_dict(),
        "reason_codes": reasons,
        "confidence": stated_confidence(strategy_doc),
        "expires_at": next_session_end(signal_date) if status == "awaiting_confirmation" else None,
        "trade_id": None,
        "confirmed_at": None,
        "rejected_at": stamp if status == "rejected" else None,
        "rejected_by": "risk_governor" if status == "rejected" else None,
        "reject_reason": ", ".join(reasons) if status == "rejected" else None,
        "orders": "Nothing is sent to a broker; a paper trade is a record only.",
        "created_at": stamp,
        "updated_at": stamp,
    }


def mark_executed(ticket: Dict[str, Any], trade: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The fields that record the paper trade a cleared ticket opened. Returned as a change set so the caller can use
    it both on a document it is about to insert and in a Mongo `$set`."""
    stamp = _iso(now or utcnow())
    return {"status": "executed_paper", "trade_id": trade["_id"], "confirmed_at": stamp, "updated_at": stamp}


#: The desk's longest time exit (services/desk_trading.MAX_HOLD_SESSIONS); a strategy holding longer is capped to it.
DESK_MAX_HOLD_SESSIONS = 250


def trade_body(ticket: Dict[str, Any], *, rationale: str, exit_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The `desk_trading.new_trade` body for a ticket's paper trade: the governor's approved quantity, the ticket's
    own stop and target, and the provenance the PRD asks for (source kind, strategy version, rationale).

    `exit_spec` is the strategy's `spec.exit`, so the paper trade exits the way the backtest that promoted the strategy
    did (finding N15): `max_hold_days` (sessions held, as the backtest counts them) becomes the trade's
    `max_hold_sessions`, capped at the desk's 250, and `trailing_atr_mult` the trade's opt-in ATR trail (k, ATR 14)."""
    body = {
        "symbol": ticket["symbol"],
        "quantity": ticket["quantity"],
        "entry_price": ticket["entry_price"],
        "stop_price": ticket["stop_price"],
        "target_price": ticket["target_price"],
        "source": {"kind": TRADE_SOURCE_KIND, "signal_date": ticket["signal_date"]},
        "signal_at": ticket["signal_date"],
        "strategy_version": ticket.get("strategy_version"),
        "rationale": rationale,
    }
    exit_spec = exit_spec if isinstance(exit_spec, dict) else {}
    hold = exit_spec.get("max_hold_days")
    if isinstance(hold, int) and not isinstance(hold, bool) and hold >= 1:
        body["max_hold_sessions"] = min(hold, DESK_MAX_HOLD_SESSIONS)
    rules: Dict[str, Any] = {}
    k = exit_spec.get("trailing_atr_mult")
    if isinstance(k, (int, float)) and not isinstance(k, bool) and k > 0:
        rules["trailing_atr"] = {"k": float(k)}
    period = exit_spec.get("trend_ema_period")
    if isinstance(period, int) and not isinstance(period, bool) and period >= 2:
        rules["trend_ema"] = {"period": period}
    if rules:
        body["exit_rules"] = rules
    return body


def ticket_text(ticket: Dict[str, Any]) -> str:
    """The copy-ready order for the user to place themselves (PRD F5.2). It names the stock, the quantity, the entry,
    the stop and the target, says the governor's decision, and ends with the line that says nothing was sent."""
    decision = ticket.get("decision") or {}
    requested = ticket.get("requested_quantity")
    size_note = ""
    if decision.get("action") == "reduce" and requested:
        size_note = f" (cut from {requested} by the risk governor)"
    lines = [
        f"BUY {ticket['symbol']} — {ticket['quantity']} share(s){size_note}",
        f"Entry (limit): {_rupees(float(ticket['entry_price']))}",
        f"Stop loss: {_rupees(float(ticket['stop_price']))}",
        f"Target: {_rupees(float(ticket['target_price']))}" if ticket.get("target_price") is not None
        else "Target: none",
        f"Signal date: {ticket['signal_date']}  ·  Strategy version: {ticket.get('strategy_version') or 'unknown'}",
        f"Risk governor: {decision.get('action') or 'unknown'}"
        + (f" ({', '.join(ticket.get('reason_codes') or [])})" if ticket.get("reason_codes") else ""),
        SELF_PLACE_LINE,
    ]
    return "\n".join(lines)


# ── Phase 5: the outcome journal ─────────────────────────────────────────────
def _pnl(trade: Dict[str, Any]) -> Optional[float]:
    """Realised P&L of a closed paper trade: net of the desk's cost model when that was stored, else gross."""
    net = _num(trade.get("net_pnl_rs"))
    return net if net is not None else _num(trade.get("realized_pnl_rs"))


def outcome_pairs(tickets: Sequence[Dict[str, Any]],
                  closed_trades: Sequence[Dict[str, Any]]) -> List[Tuple[float, bool]]:
    """(stated confidence, whether it won) for every ticket whose paper trade has closed (PRD F5.4), ready for
    `calibration.calibration_report`. A win is a positive realised P&L. Tickets with no closed trade, no P&L or no
    stated confidence are left out, never counted as a loss or scored against a guessed confidence. Input order is
    kept, so the caller decides the order."""
    closed = {t.get("_id"): t for t in closed_trades if t.get("status") == "closed"}
    pairs: List[Tuple[float, bool]] = []
    for ticket in tickets:
        trade = closed.get(ticket.get("trade_id"))
        confidence = _num(ticket.get("confidence"))
        if trade is None or confidence is None:
            continue
        pnl = _pnl(trade)
        if pnl is None:
            continue
        pairs.append((confidence, pnl > 0))
    return pairs


def paper_stats(closed_trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The paper record of one strategy, under the key names the paper-to-assisted gate reads (PRD F5.4,
    `strategy._assisted_rows`): closed_trades, expectancy, profit_factor, win_rate.

    Units follow the backtest metrics so the gate can compare like with like: `win_rate` is percentage points and
    `expectancy` is rupees per closed trade, both on realised P&L net of the desk cost model where the trade stored
    it. Everything is None with no closed trades, and the profit factor is None when nothing lost, because a ratio
    with no denominator is unknown, not a large number."""
    pnls = [p for p in (_pnl(t) for t in closed_trades if t.get("status") == "closed") if p is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    lost = abs(sum(losses))
    out = {
        "closed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2) if n else None,
        "expectancy": round(sum(pnls) / n, 2) if n else None,
        "profit_factor": round(sum(wins) / lost, 4) if lost else None,
        "net_pnl_rs": round(sum(pnls), 2) if n else None,
        "avg_win_rs": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_rs": round(sum(losses) / len(losses), 2) if losses else None,
        "pnl_basis": "realised P&L net of the desk cost model where the trade stored it, else gross",
    }
    # The assisted gate reads four of these by name. Fail here rather than let the gate read None and refuse a
    # promotion for the wrong reason.
    missing = [k for k in PAPER_STATS_FIELDS if k not in out]
    if missing:
        raise ExecutionError(f"paper_stats is missing the gate field(s) {missing}")
    return out
