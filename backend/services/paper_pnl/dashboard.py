"""The P&L dashboard payload from a book, prices and the account. Pure: no I/O, so every figure is unit-tested.

Wording: the owner approved the standard trading words for THIS screen (4 Nov 2026): Stop loss, Target, Long / Short,
"Near stop loss", "Target reached". Never "recommend", "pick" or "suggested" (25 Oct rule).

SOURCES (5 Nov 2026): every paper row says where it came from — `source` "desk" (the desk's own paper trades), "scanner"
(a Scanner-to-Paper Trading position, services/spt/paper; with its opportunity_id / proposal_id / order_id / spt_state) or
"broker" (a live broker position). A scanner row is a cash share row in every figure; its charges are its fills' recorded
costs plus the estimate for selling what is open (scanner_charges), its levels are read-only here (it is modified through
/api/v1/paper/positions), and its exits are simulated live by the paper monitor, not at the evening check.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services.kite_live_feed import config as cfg

from . import ledger
from . import live as live_mod
from .book import SCANNER, Book, Leg, TradeItem
from .prices import CLOSE, DELAYED, EOD, LIVE, MISSING, Quote

MODE = "PAPER"
ACCOUNT_NAME = "Paper account"
PAPER_ACCOUNT_ID = "paper"
SEGMENTS = ("ALL", "EQUITY", "FUTURES", "OPTIONS")
PERIODS = ("TODAY", "1W", "1M", "ALL", "CUSTOM")
MODES = ("ALL", "PAPER", "LIVE")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
RECON_TOLERANCE_RS = 0.01
CLOSED_LISTED = 200
EXPIRY_SOON_DAYS = 2


def near_stop_pct() -> float:
    try:
        return max(0.0, float(os.environ.get("PNL_NEAR_STOP_PCT", "1.0")))
    except ValueError:
        return 1.0


def capital_warn_pct() -> float:
    try:
        return max(0.0, float(os.environ.get("PNL_CAPITAL_WARN_PCT", "80")))
    except ValueError:
        return 80.0


@dataclass
class Filters:
    segment: str = "ALL"
    period: str = "TODAY"
    start: Optional[date] = None
    end: Optional[date] = None
    mode: str = "ALL"                  # ALL | PAPER | LIVE (v2)
    account: str = "ALL"               # ALL | paper | a broker account id of the user (checked by the route)

    def public(self) -> Dict[str, Any]:
        return {"segment": self.segment, "period": self.period,
                "from": self.start.isoformat() if self.start else None, "to": self.end.isoformat() if self.end else None,
                "mode": self.mode, "account": self.account}

    @property
    def paper_on(self) -> bool:
        return self.mode in ("ALL", "PAPER") and self.account in ("ALL", PAPER_ACCOUNT_ID)

    @property
    def live_on(self) -> bool:
        return self.mode in ("ALL", "LIVE") and self.account != PAPER_ACCOUNT_ID


def clean_account(account: Optional[str]) -> str:
    """ALL / paper / a broker account id (its shape only; the route checks it is one of the user's). ValueError otherwise."""
    raw = (account or "ALL").strip()
    if raw.upper() == "ALL":
        return "ALL"
    if raw.lower() == PAPER_ACCOUNT_ID:
        return PAPER_ACCOUNT_ID
    if not _ACCOUNT_RE.match(raw):
        raise ValueError("invalid_account")
    return raw


def make_filters(segment: str, period: str, start: Optional[str], end: Optional[str], today: date,
                 mode: Optional[str] = "ALL", account: Optional[str] = "ALL") -> Filters:
    """Validated filters; ValueError with a short code on a bad value (the route answers 422)."""
    seg, per = (segment or "ALL").upper(), (period or "TODAY").upper()
    md = (mode or "ALL").upper()
    if seg not in SEGMENTS:
        raise ValueError("invalid_segment")
    if per not in PERIODS:
        raise ValueError("invalid_period")
    if md not in MODES:
        raise ValueError("invalid_mode")
    acc = clean_account(account)
    if per == "TODAY":
        return Filters(seg, per, today, today, md, acc)
    if per == "1W":
        return Filters(seg, per, today - timedelta(days=6), today, md, acc)
    if per == "1M":
        return Filters(seg, per, today - timedelta(days=29), today, md, acc)
    if per == "ALL":
        return Filters(seg, per, None, None, md, acc)
    try:
        a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except (TypeError, ValueError):
        raise ValueError("invalid_dates")
    if a > b or (b - a).days > 3660:
        raise ValueError("invalid_dates")
    return Filters(seg, per, a, b, md, acc)


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 2)


def _sum(values: List[Optional[float]]) -> Tuple[float, int]:
    """(sum of the known values, how many were unknown)."""
    known = [v for v in values if v is not None]
    return round(sum(known), 2), len(values) - len(known)


def _ist_day(stamp: Any) -> Optional[str]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:10] if len(str(stamp)) >= 10 else None
    if d.tzinfo is None:
        return d.date().isoformat()
    return d.astimezone(cfg.IST).date().isoformat()


def trade_segment(item: TradeItem) -> str:
    """A share trade is EQUITY; a structure is FUTURES when it holds a future, else OPTIONS (EQUITY when cash only)."""
    if item.kind == "cash":
        return "EQUITY"
    kinds = {l.kind for l in item.legs}
    if "future" in kinds:
        return "FUTURES"
    if "option" in kinds:
        return "OPTIONS"
    return "EQUITY"


def _in_segment(item: TradeItem, f: Filters) -> bool:
    return f.segment == "ALL" or trade_segment(item) == f.segment


def _in_period(day: Optional[str], f: Filters) -> bool:
    if f.start is None and f.end is None:
        return True
    if not day:
        return False
    return (f.start is None or day >= f.start.isoformat()) and (f.end is None or day <= f.end.isoformat())


def _leg_doc(item: TradeItem, leg: Leg) -> Optional[Dict[str, Any]]:
    if leg.leg_index is None:
        return None
    return next((x for x in item.public.get("legs") or [] if int(x.get("index", -1)) == leg.leg_index), None)


def scanner_charges(item: TradeItem, price: float) -> float:
    """A scanner (SPT) position's charges: what its fills recorded (every entry fill and every exit fill so far, slice C's
    `entry_costs_rs` + `exit_costs_rs`) plus the estimated charges of selling the open quantity at `price` as one order
    (slice C's own estimate, services/spt/paper/execution.exit_costs_per_share). Its gross P&L includes any partial exit's
    realised part, so all of its charges belong against it."""
    from services.spt.paper import execution as spt_exec
    pub = item.public
    qty = int(pub.get("quantity") or 0) if pub.get("status") == "open" else 0
    est = spt_exec.exit_costs_per_share(float(price), qty, pub.get("cost_model")) * qty if qty > 0 else 0.0
    return round(float(pub.get("entry_costs_rs") or 0.0) + float(pub.get("exit_costs_rs") or 0.0) + est, 2)


def leg_charges(item: TradeItem, leg: Leg, price: Optional[float]) -> Optional[float]:
    """Round-trip charges of one position under the trade's own cost model, the closing side at `price`; None without a price."""
    if price is None:
        return None
    pub = item.public
    if item.kind == "cash" and item.source == SCANNER:
        return scanner_charges(item, price)
    if item.kind == "cash":
        fill = pub.get("sim_entry_price") or pub.get("entry_price")
        if not fill:
            return None
        return svc.trade_cost_breakdown(pub, float(fill), float(price))["total"]
    doc = _leg_doc(item, leg)
    if doc is None:
        return None
    one = strat.strategy_cost_breakdown({"legs": [doc], "cost_model": pub.get("cost_model")}, [float(price)])
    return one["total"] if one else None


def _status(item: TradeItem, ltp: Optional[float], stop: Optional[float], target: Optional[float], side: Optional[str],
            settled: bool) -> str:
    if item.pending_exit:
        return "EXIT_DUE"
    if settled:
        return "SETTLED"
    if ltp is None or side is None:
        return "ACTIVE"
    long = side == "LONG"
    if stop is not None and (ltp <= stop if long else ltp >= stop):
        return "STOP_LOSS_HIT"
    if target is not None and (ltp >= target if long else ltp <= target):
        return "TARGET_REACHED"
    if stop is not None and ltp > 0 and abs(ltp - stop) / ltp * 100 <= near_stop_pct():
        return "NEAR_STOP_LOSS"
    return "ACTIVE"


def _strategy_status(item: TradeItem, und: Optional[float]) -> str:
    if item.pending_exit:
        return "EXIT_DUE"
    pub = item.public
    direction, stop, target = pub.get("direction"), pub.get("stop_underlying"), pub.get("target_underlying")
    if und is None or direction not in ("bullish", "bearish"):
        return "ACTIVE"
    side = "LONG" if direction == "bullish" else "SHORT"
    fake = TradeItem(item.trade_id, item.kind, item.status, pub, [], [], True)
    return _status(fake, und, stop, target, side, False)


def _position_row(item: TradeItem, leg: Leg, pos: ledger.Position, q: Quote, today: str) -> Dict[str, Any]:
    pub = item.public
    ltp = q.ltp
    unreal = pos.unrealized(ltp)
    realized = round(pos.realized_pnl, 2)
    gross = None if unreal is None else round(unreal + realized, 2)
    charges = leg_charges(item, leg, ltp) if pos.is_open else None
    net = None if gross is None or charges is None else round(gross - charges, 2)
    qty = pos.net_quantity
    avg = pos.average_price
    day_pnl = None
    if ltp is not None and pos.is_open and avg is not None and not (q.status == DELAYED and (q.day or today) < today):
        # (a contract whose last trade is from the previous session has not moved today: no day figure)
        held_before = (item.entry_session or "") < (q.day or today)
        if held_before and q.prev_close is not None:
            day_pnl = round((ltp - q.prev_close) * qty * pos.multiplier, 2)
        elif not held_before:
            day_pnl = round((ltp - avg) * qty * pos.multiplier, 2)
    stop = target = None
    if item.kind == "cash":
        # The levels in force: a Modify-risk change is a dated version, in force from the session after it (v2); the
        # ledger's public trade sends current_stop / current_target for that, the stored levels otherwise.
        stop = pub.get("current_stop") if pub.get("current_stop") is not None else pub.get("stop_price")
        target = pub.get("current_target") if pub.get("current_target") is not None else pub.get("target_price")
    side = pos.side
    dist = None
    if stop is not None and ltp:
        dist = round(((ltp - float(stop)) / ltp * 100) * (1 if side == "LONG" else -1), 2)
    risk_used = None
    if item.kind == "cash" and avg is not None and pub.get("stop_price") is not None and unreal is not None:
        budget = abs(avg - float(pub["stop_price"])) * abs(qty)
        risk_used = round(max(0.0, -unreal) / budget * 100, 1) if budget > 0 else None
    invested = round(abs(qty) * avg * pos.multiplier, 2) if avg is not None else None
    settled = leg.eod_basis in ("expiry_intrinsic", "final_settle")
    status = _status(item, ltp, stop, target, side, settled) if item.kind == "cash" else ("SETTLED" if settled else
                                                                                         ("EXIT_DUE" if item.pending_exit else "ACTIVE"))
    return {
        "position_id": leg.position_key, "trade_id": item.trade_id, "leg_index": leg.leg_index,
        "strategy_id": item.trade_id if item.kind == "strategy" else None,
        "strategy_name": pub.get("family_name") if item.kind == "strategy" else None,
        "mode": MODE, "account": ACCOUNT_NAME, "instrument": leg.instrument, "symbol": leg.symbol, "underlying": leg.symbol,
        "segment": leg.segment, "side": side, "net_quantity": qty, "lots": leg.lots, "lot_size": leg.lot_size,
        "avg_price": _r(avg), "ltp": ltp, "prev_close": q.prev_close, "price_status": q.status, "price_source": q.source,
        "price_at": q.at, "price_age_seconds": q.age_seconds, "price_day": q.day,
        "invested_value": invested, "unrealized_pnl": unreal, "realized_pnl": realized, "gross_pnl": gross,
        "charges_estimated": charges, "net_pnl": net, "day_pnl": day_pnl,
        "return_pct": round(net / invested * 100, 2) if net is not None and invested else None,
        "stop_loss": stop, "target": target, "distance_to_stop_pct": dist, "risk_used_pct": risk_used,
        "status": status, "opened_at": pub.get("opened_at"), "expiry": leg.expiry,
        "executions": [{"execution_id": e.execution_id, "side": "BUY" if e.side > 0 else "SELL", "quantity": e.quantity,
                        "price": e.price, "at": e.at, "kind": e.kind} for e in pos.executions],
        "account_id": PAPER_ACCOUNT_ID, "broker_pnl": None, "broker_read_at": None, "product": None,
        "exposure_rs": round(abs(qty * ltp * pos.multiplier), 2) if ltp is not None else None,
        "editable_levels": item.kind == "cash" and item.source != SCANNER and item.status == "open" and pos.is_open,
        "pending_levels": _pending_levels(pub) if item.kind == "cash" and item.source != SCANNER else None,
        "executions_note": SCANNER_EXEC_NOTE if item.source == SCANNER else None,
        **source_fields(item),
    }


SCANNER_EXEC_NOTE = ("Scanner paper fills: simulated on live bid/ask with the displayed depth (slice C, spt-exec-v1); "
                     "each at its traded value ÷ quantity.")


def source_fields(item: TradeItem) -> Dict[str, Any]:
    """Where a paper row came from: the desk, or a scanner (SPT) position with its ids."""
    pub = item.public
    if item.source == SCANNER:
        return {"source": SCANNER, "opportunity_id": pub.get("opportunity_id"), "proposal_id": pub.get("proposal_id"),
                "order_id": pub.get("order_id"), "spt_state": pub.get("spt_state")}
    return {"source": "desk", "opportunity_id": None, "proposal_id": None, "order_id": None, "spt_state": None}


def _exit_rule_text(item: TradeItem) -> str:
    if item.source == SCANNER:
        return ("This scanner paper position's stop and targets are watched live by the paper monitor, which exits at the "
                "next usable quote; nothing on this screen closes it.")
    return "The paper exit is decided at the evening check on today's end-of-day bar; nothing has been closed."


def _pending_levels(pub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The waiting Modify-risk change from the public trade ({stop_loss, target, from_session, version}), or None. Read
    defensively: an older ledger sends nothing, and a field the ledger names differently is passed through when it is a dict."""
    p = pub.get("pending_levels")
    if not isinstance(p, dict):
        return None
    return {"stop_loss": p.get("stop_loss", p.get("stop_price")), "target": p.get("target", p.get("target_price")),
            "from_session": p.get("from_session"), "version": p.get("version")}


def _alert(severity: str, kind: str, message: str, *, position_id: Optional[str] = None, symbol: Optional[str] = None,
           observed: Optional[float] = None, threshold: Optional[float] = None) -> Dict[str, Any]:
    return {"severity": severity, "type": kind, "position_id": position_id, "symbol": symbol, "message": message,
            "observed": observed, "threshold": threshold}


def _money(v: Optional[float]) -> str:
    return "—" if v is None else f"₹{v:,.2f}"


def build(book: Book, quotes: Dict[str, Quote], market: Dict[str, Any], account: Dict[str, Any],
          limits: Optional[Dict[str, Any]], filters: Filters, *, now: datetime,
          underlying_ltp: Optional[Dict[str, float]] = None, live: Optional[Any] = None) -> Dict[str, Any]:
    """The dashboard body. `live` is the broker side (services/paper_pnl/live.LiveView: priced rows, accounts) or None (no
    broker read: v1 behaviour, Live unavailable). `filters.mode` / `filters.account` select what the positions, summary,
    by-segment, alerts and lists hold; `modes` and `accounts` always cover both modes (the segment filter applies)."""
    today = now.astimezone(cfg.IST).date().isoformat()
    underlying_ltp = underlying_ltp or {}
    capital = float(account.get("starting_capital_rs") or 0.0)
    alerts: List[Dict[str, Any]] = []

    positions: List[Dict[str, Any]] = []
    strategies: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    trade_nets: List[Optional[float]] = []
    open_risk: List[float] = []
    strat_risk: List[Optional[float]] = []
    by_seg: Dict[str, Dict[str, Any]] = {}

    def seg_row(seg: str) -> Dict[str, Any]:
        return by_seg.setdefault(seg, {"segment": seg, "open_positions": 0, "closed_trades": 0, "realized_pnl": 0.0,
                                       "unrealized_pnl": 0.0, "charges": 0.0, "net_pnl": 0.0, "complete": True})

    for item in book.open:
        if not _in_segment(item, filters):
            continue
        if not item.entered:
            leg = item.legs[0]
            q = quotes.get(leg.position_key)
            pending.append({"trade_id": item.trade_id, "symbol": leg.symbol, "entry_rule": item.public.get("entry_rule"),
                            "level": item.public.get("entry_price"), "quantity": item.public.get("quantity"),
                            "ltp": q.ltp if q else None, "price_status": q.status if q else MISSING,
                            "opened_at": item.public.get("opened_at"),
                            "note": "Not a position yet: the entry level has not traded on an end-of-day bar."})
            continue
        pos_map = ledger.build(item.executions)
        rows = []
        for leg in item.legs:
            pos = pos_map.get(leg.position_key)
            if pos is None:
                continue
            q = quotes.get(leg.position_key) or Quote(None, None, MISSING, None, None, None, None)
            rows.append(_position_row(item, leg, pos, q, today))
        if not rows:
            if item.source == SCANNER and item.public.get("fills_missing"):
                alerts.append(_alert("WARNING", "SCANNER_FILLS_MISSING",
                                     f"{item.legs[0].symbol}: the scanner paper position's fills could not be read, so it is "
                                     "left out of the totals.", position_id=item.trade_id, symbol=item.legs[0].symbol))
            continue
        positions.extend(rows)
        unreal, unknown = _sum([r["unrealized_pnl"] for r in rows])
        charges, c_unknown = _sum([r["charges_estimated"] for r in rows])
        complete = unknown == 0 and c_unknown == 0
        net = round(unreal - charges, 2) if complete else None
        trade_nets.append(net)
        s = seg_row(trade_segment(item))
        s["open_positions"] += 1
        s["unrealized_pnl"] = round(s["unrealized_pnl"] + unreal, 2)
        s["charges"] = round(s["charges"] + charges, 2)
        s["complete"] = s["complete"] and complete
        pub = item.public
        if item.kind == "cash":
            r = rows[0]
            if r["ltp"] is not None and r["stop_loss"] is not None:
                open_risk.append(min(0.0, (float(r["stop_loss"]) - r["ltp"]) * r["net_quantity"]))
            sym = r["symbol"]
            if r["status"] == "STOP_LOSS_HIT":
                alerts.append(_alert("CRITICAL", "STOP_LOSS_HIT",
                                     f"{sym} is at {_money(r['ltp'])}, at or below its stop loss {_money(r['stop_loss'])}. "
                                     + _exit_rule_text(item),
                                     position_id=r["position_id"], symbol=sym, observed=r["ltp"], threshold=r["stop_loss"]))
            elif r["status"] == "NEAR_STOP_LOSS":
                alerts.append(_alert("WARNING", "NEAR_STOP_LOSS",
                                     f"{sym} is {r['distance_to_stop_pct']}% above its stop loss {_money(r['stop_loss'])}.",
                                     position_id=r["position_id"], symbol=sym, observed=r["ltp"], threshold=r["stop_loss"]))
            elif r["status"] == "TARGET_REACHED":
                alerts.append(_alert("INFO", "TARGET_REACHED",
                                     f"{sym} is at {_money(r['ltp'])}, at or above its target {_money(r['target'])}. "
                                     + ("The paper exit is decided at the evening check." if item.source != SCANNER
                                        else _exit_rule_text(item)), position_id=r["position_id"], symbol=sym,
                                     observed=r["ltp"], threshold=r["target"]))
        else:
            und = underlying_ltp.get(str(pub.get("underlying") or "").upper())
            status = _strategy_status(item, und)
            legs_value = strat.net_premium(pub.get("legs") or [], [r["ltp"] for r in rows]) if len(rows) == len(pub.get("legs") or []) else None
            risk = strat.exposure_rs(pub)
            strat_risk.append(risk)
            strategies.append({
                "strategy_id": item.trade_id, "name": pub.get("family_name") or pub.get("family"), "summary": pub.get("summary_text"),
                "underlying": pub.get("underlying"), "direction": pub.get("direction"), "status": status,
                "legs": [r["position_id"] for r in rows], "underlying_ltp": und,
                "stop_underlying": pub.get("stop_underlying"), "target_underlying": pub.get("target_underlying"),
                "entry_net_premium": pub.get("net_premium_rs"), "current_value": legs_value,
                "unrealized_pnl": unreal if unknown == 0 else None, "charges_estimated": charges if c_unknown == 0 else None,
                "net_pnl": net, "capital_at_risk": risk, "complete": complete, "opened_at": pub.get("opened_at"),
                "risk_note": pub.get("risk_note"),
            })
            label = f"{pub.get('family_name') or 'Structure'} {pub.get('underlying')}"
            if status == "STOP_LOSS_HIT":
                alerts.append(_alert("CRITICAL", "STOP_LOSS_HIT",
                                     f"{label}: the underlying is at {_money(und)}, through its stop loss {_money(pub.get('stop_underlying'))}. "
                                     "The paper exit is decided at the evening check.", position_id=item.trade_id,
                                     symbol=pub.get("underlying"), observed=und, threshold=pub.get("stop_underlying")))
            elif status == "TARGET_REACHED":
                alerts.append(_alert("INFO", "TARGET_REACHED",
                                     f"{label}: the underlying is at {_money(und)}, through its target {_money(pub.get('target_underlying'))}.",
                                     position_id=item.trade_id, symbol=pub.get("underlying"), observed=und,
                                     threshold=pub.get("target_underlying")))
            elif status == "NEAR_STOP_LOSS":
                alerts.append(_alert("WARNING", "NEAR_STOP_LOSS",
                                     f"{label}: the underlying is within {near_stop_pct():g}% of its stop loss {_money(pub.get('stop_underlying'))}.",
                                     position_id=item.trade_id, symbol=pub.get("underlying"), observed=und,
                                     threshold=pub.get("stop_underlying")))
            for r in rows:
                if r["expiry"] and r["status"] != "SETTLED":
                    days = (date.fromisoformat(r["expiry"]) - date.fromisoformat(today)).days
                    if 0 <= days <= EXPIRY_SOON_DAYS:
                        alerts.append(_alert("WARNING" if days == 0 else "INFO", "EXPIRY",
                                             f"{r['instrument']} expires {'today' if days == 0 else f'in {days} day' + ('s' if days > 1 else '')}.",
                                             position_id=r["position_id"], symbol=r["symbol"]))
        if item.pending_exit:
            ex = item.pending_exit
            alerts.append(_alert("WARNING", "EXIT_DUE",
                                 f"{rows[0]['instrument'] if item.kind == 'cash' else item.public.get('summary_text')}: the "
                                 f"{str(ex.get('exit_reason') or 'exit').replace('_', ' ')} rule fired on "
                                 f"{ex.get('exit_session')}; "
                                 + ("the paper monitor exits it at the next session's first live quote." if item.source == SCANNER
                                    else "the ledger records the close at its next check."),
                                 position_id=item.trade_id, symbol=rows[0]["symbol"]))

    # Closed trades: the period's list, the booked figures, and the reconciliation against the stored ledger.
    closed_rows: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    checked = 0
    for item in book.closed:
        pub = item.public
        stored = pub.get("realized_pnl_rs")
        if not item.executions:
            continue                                       # never entered (entry not reached / cancelled): no position
        pos_map = ledger.build(item.executions)
        engine = round(sum(p.realized_pnl for p in pos_map.values()), 2)
        # A scanner position can close over several exit fills (T1, T2, a stop); the engine rounds each closing fill's
        # realised P&L to the paisa, so it is allowed one paisa of rounding per closing fill against C's exact total.
        closing = sum(1 for e in item.executions if e.side < 0)
        tol = RECON_TOLERANCE_RS * max(1, closing) if item.source == SCANNER else RECON_TOLERANCE_RS
        if stored is not None:
            checked += 1
            if abs(engine - float(stored)) > tol + 1e-9:
                mismatches.append({"trade_id": item.trade_id, "instrument": item.legs[0].instrument if item.kind == "cash" else pub.get("summary_text"),
                                   "ledger_realized_pnl": stored, "engine_realized_pnl": engine, "difference": round(engine - float(stored), 2),
                                   "source": item.source})
        day = pub.get("exit_session") or _ist_day(pub.get("closed_at"))
        if not _in_segment(item, filters) or not _in_period(day, filters):
            continue
        realized = float(stored) if stored is not None else engine
        charges = pub.get("costs_rs")
        net = pub.get("net_pnl_rs") if pub.get("net_pnl_rs") is not None else (round(realized - charges, 2) if charges is not None else None)
        closed_rows.append({"trade_id": item.trade_id, "kind": item.kind,
                            "instrument": item.legs[0].instrument if item.kind == "cash" else (pub.get("summary_text") or pub.get("underlying")),
                            "segment": trade_segment(item), "opened_at": pub.get("opened_at"), "closed_at": pub.get("closed_at"),
                            "exit_session": day, "exit_reason": pub.get("exit_reason"), "realized_pnl": round(realized, 2),
                            "charges": charges, "net_pnl": net, "held_sessions": pub.get("held_sessions"),
                            **source_fields(item)})
        s = seg_row(trade_segment(item))
        s["closed_trades"] += 1
        s["realized_pnl"] = round(s["realized_pnl"] + realized, 2)
        s["charges"] = round(s["charges"] + (charges or 0.0), 2)
    for m in mismatches:
        alerts.append(_alert("WARNING", "RECONCILIATION_MISMATCH",
                             f"{m['instrument']}: the ledger booked {_money(m['ledger_realized_pnl'])} realized, the P&L engine "
                             f"computes {_money(m['engine_realized_pnl'])} from its fills.", position_id=m["trade_id"]))

    # ── v2: the selection. Paper and the broker positions are built in full (for `modes` and `accounts`); the mode and account
    # filters then choose what the positions, summary, by-segment, alerts and lists hold. Closed trades and waiting entries are
    # paper only.
    paper_positions = positions
    paper_day_total, _ = _sum([p["day_pnl"] for p in paper_positions])
    live_all = [r for r in (live.positions if live is not None else [])
                if filters.segment == "ALL" or r.get("segment") == filters.segment]
    for r in live_all:
        r.setdefault("source", "broker")
    paper_on, live_on = filters.paper_on, filters.live_on
    sel_live = [r for r in live_all if live_on and (filters.account == "ALL" or r.get("account_id") == filters.account)]
    modes = {"PAPER": _mode_block(paper_positions, closed_rows, capital or None, True, None, realized_known=True),
             "LIVE": _mode_block(live_all, [], None, live is not None and live.note is None,
                                 (live.note if live is not None else "Broker positions were not read for this answer."),
                                 realized_known=False)}
    closed_sel = closed_rows if paper_on else []
    if not paper_on:
        positions, strategies, pending, trade_nets, open_risk, strat_risk, alerts = [], [], [], [], [], [], []
        by_seg = {}
    positions = positions + sel_live
    for r in sel_live:
        s = seg_row(r["segment"])
        s["open_positions"] += 1
        s["unrealized_pnl"] = round(s["unrealized_pnl"] + (r["unrealized_pnl"] or 0.0), 2)
        s["charges"] = round(s["charges"] + (r["charges_estimated"] or 0.0), 2)
        s["complete"] = s["complete"] and r["unrealized_pnl"] is not None and r["charges_estimated"] is not None
        trade_nets.append(r["net_pnl"])
        if r["expiry"]:
            days = (date.fromisoformat(r["expiry"]) - date.fromisoformat(today)).days
            if 0 <= days <= EXPIRY_SOON_DAYS:
                alerts.append(_alert("WARNING" if days == 0 else "INFO", "EXPIRY",
                                     f"{r['instrument']} ({r['account']}) expires {'today' if days == 0 else f'in {days} day' + ('s' if days > 1 else '')}.",
                                     position_id=r["position_id"], symbol=r["symbol"]))
    if live is not None and live_on:
        for a in live.accounts:
            if filters.account not in ("ALL", a["account_id"]) or a["state"] == "OK":
                continue
            sev = "INFO" if a["state"] in ("STALE", "OFF") else "WARNING"
            alerts.append(_alert(sev, "BROKER", f"{a['name']}: {a['state_note'] or a['state'].replace('_', ' ').lower()}"))
    for s in by_seg.values():
        s["net_pnl"] = round(s["realized_pnl"] + s["unrealized_pnl"] - s["charges"], 2)

    # Prices that are not live while the market is open, and positions with no price at all.
    session_open = market.get("session") == "open"
    unpriced = [p for p in positions if p["price_status"] == MISSING]
    stale = [p for p in positions if session_open and p["price_status"] in (DELAYED, EOD, CLOSE)]
    if session_open and market.get("feed") not in ("live",):
        alerts.append(_alert("CRITICAL", "FEED", f"Live prices are {str(market.get('feed')).replace('_', ' ')}: open P&L is at the "
                                                 "last available price, not live. Each row shows its price time."))
    if stale:
        alerts.append(_alert("WARNING", "STALE_PRICE", f"{len(stale)} position(s) are not priced live: "
                                                      + ", ".join(sorted({p['instrument'] for p in stale})[:6])))
    if unpriced:
        alerts.append(_alert("CRITICAL", "MISSING_PRICE", f"{len(unpriced)} position(s) have no price at all, so the totals leave "
                                                          "them out: " + ", ".join(sorted({p['instrument'] for p in unpriced})[:6])))

    realized_total, _ = _sum([c["realized_pnl"] for c in closed_sel])
    booked, _ = _sum([c["charges"] for c in closed_sel])
    unreal_total, unreal_unknown = _sum([p["unrealized_pnl"] for p in positions])
    est_total, est_unknown = _sum([p["charges_estimated"] for p in positions])
    day_total, _ = _sum([p["day_pnl"] for p in positions])
    exposure_total, _ = _sum([p.get("exposure_rs") for p in positions])
    gross = round(realized_total + unreal_total, 2)
    net = round(gross - booked - est_total, 2)
    complete = unreal_unknown == 0 and est_unknown == 0
    sel_capital = capital if (paper_on and capital) else None
    if sel_live:
        ret = None
        capital_basis = ("Paper: the paper account's starting capital. " if paper_on else "") + live_mod.CAPITAL_BASIS
    else:
        ret = round(net / sel_capital * 100, 4) if sel_capital else None
        capital_basis = "The paper account's starting capital." if paper_on else live_mod.CAPITAL_BASIS

    # Risk: capital (what the paper account blocks is capital at risk, not exchange margin) and the profile's limits.
    cash = float(account.get("cash_rs") or 0.0)
    blocked = float(account.get("blocked_rs") or 0.0)
    spt_reserved = account.get("spt_reserved_rs")             # the route reads it from the account's reservations
    blocked_by_source = None
    if spt_reserved is not None:
        blocked_by_source = {"scanner": round(float(spt_reserved), 2), "desk": round(blocked - float(spt_reserved), 2),
                             "basis": "scanner = the funding of the account's reservations for scanner (SPT) orders and "
                                      "positions (store spt_orders); desk = the rest of what the account blocks"}
    if book.spt_error:
        alerts.append(_alert("WARNING", "SCANNER_BOOK", f"Scanner paper positions are not shown: {book.spt_error}. The capital "
                                                        "they block is still in the blocked figure."))
    util = round(blocked / cash * 100, 2) if cash > 0 else None
    if paper_on and util is not None and util >= capital_warn_pct():
        alerts.append(_alert("WARNING", "CAPITAL", f"{util}% of the paper account's cash is blocked by open positions.",
                             observed=util, threshold=capital_warn_pct()))
    lim = limits or {}
    open_risk_limit = round(capital * float(lim["max_open_risk_pct"]) / 100, 2) if lim.get("max_open_risk_pct") is not None and capital else None
    daily_limit = round(capital * float(lim["daily_loss_pct"]) / 100, 2) if lim.get("daily_loss_pct") is not None and capital else None
    realized_today = sum(c["net_pnl"] or 0.0 for c in closed_rows if c["exit_session"] == today)
    day_loss = max(0.0, -(paper_day_total + realized_today))
    daily_used = round(day_loss / daily_limit * 100, 1) + 0.0 if daily_limit and paper_on else None
    if daily_used is not None and daily_used >= 100:
        alerts.append(_alert("CRITICAL", "DAILY_LOSS_LIMIT", f"Today's loss {_money(-day_loss)} has reached the daily loss limit "
                                                             f"{_money(daily_limit)}.", observed=-day_loss, threshold=daily_limit))
    elif daily_used is not None and daily_used >= 75:
        alerts.append(_alert("WARNING", "DAILY_LOSS_LIMIT", f"Today's loss is {daily_used}% of the daily loss limit "
                                                            f"{_money(daily_limit)}.", observed=-day_loss, threshold=daily_limit))
    if paper_on and sel_live:
        margin = {"used_pct": util, "basis": "Paper account only: capital blocked by open trades, not exchange margin. "
                                             "Broker margin is not read."}
    elif paper_on:
        margin = {"used_pct": util, "basis": "Paper: capital blocked by open trades, not exchange margin."}
    else:
        margin = {"used_pct": None, "basis": "Not read from brokers."}

    # Analytics over the period's closed trades (net of charges), in closing order.
    nets = [c for c in sorted(closed_sel, key=lambda c: str(c["closed_at"] or c["exit_session"] or "")) if c["net_pnl"] is not None]
    wins = [c["net_pnl"] for c in nets if c["net_pnl"] > 0]
    losses = [c["net_pnl"] for c in nets if c["net_pnl"] < 0]
    equity, peak, dd = 0.0, 0.0, 0.0
    for c in nets:
        equity += c["net_pnl"]
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    daily: Dict[str, float] = {}
    for c in nets:
        daily[c["exit_session"]] = round(daily.get(c["exit_session"], 0.0) + c["net_pnl"], 2)

    # Accounts: the paper account and every broker account (whatever the filters; the segment filter applies to the counts).
    accts: List[Dict[str, Any]] = [{
        "account_id": PAPER_ACCOUNT_ID, "name": ACCOUNT_NAME, "mode": MODE, "broker": None, "state": "OK", "state_note": None,
        "read_at": now.astimezone(cfg.IST).isoformat(), "capital": capital or None,
        "capital_basis": "The paper account's starting capital.", "open_positions": modes["PAPER"]["open_positions"],
        "net_pnl": modes["PAPER"]["net_pnl"]}]
    for a in (live.accounts if live is not None else []):
        mine = [r for r in live_all if r.get("account_id") == a["account_id"]]
        known = [r["net_pnl"] for r in mine if r["net_pnl"] is not None]
        accts.append({**a, "open_positions": len(mine),
                      "net_pnl": round(sum(known), 2) if mine and len(known) == len(mine) else (0.0 if not mine and a["state"] in ("OK", "STALE") else None)})

    severity = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: severity.get(a["severity"], 3))
    closed_sel.sort(key=lambda c: str(c["closed_at"] or ""), reverse=True)
    notes = {
        "display_only": "Live prices here are for display. Paper fills and exits use end-of-day prices at the evening check; "
                        "nothing on this screen places, changes or closes a trade.",
        "charges": "Booked = the desk cost card at the fills of closed trades. Estimated = the same card with the closing side at "
                   "the current price. Both are modelled; paper trades have no contract note.",
        "unrealized": "Open P&L = (price now − average price) × quantity, per position; a structure is the sum of its legs.",
        "capital": "Return % = net P&L ÷ the paper account's starting capital.",
        "scanner": "Scanner rows (source \"scanner\") are Scanner-to-Paper Trading positions: filled and exited in the session on "
                   "live bid/ask by the paper monitor, not at the evening check; charges are their fills' recorded costs; "
                   "their levels are changed through /api/v1/paper/positions, not here.",
    }
    if live is not None:
        notes["live"] = live_mod.REALIZED_NOTE + " Broker positions are read-only here: Nivesh places no live order."
    return {
        "mode": filters.mode, "currency": "INR", "account": ACCOUNT_NAME,
        "filters": filters.public(), "market": market,
        "accounts": accts, "modes": modes,
        "summary": {
            "realized_pnl": realized_total, "unrealized_pnl": unreal_total, "gross_pnl": gross,
            "charges_booked": booked, "charges_estimated": est_total, "net_pnl": net, "day_pnl": day_total,
            "allocated_capital": sel_capital or None, "return_pct": ret, "capital_basis": capital_basis,
            "exposure_rs": exposure_total,
            "open_positions": len({p["trade_id"] for p in positions}), "open_legs": len(positions),
            "open_positions_by_source": {s: len({p["trade_id"] for p in positions if p.get("source") == s})
                                         for s in ("desk", SCANNER, "broker")},
            "winning_positions": sum(1 for n in trade_nets if n is not None and n > 0),
            "losing_positions": sum(1 for n in trade_nets if n is not None and n < 0),
            "closed_trades": len(closed_sel), "pending_entries": len(pending),
            "unpriced_positions": len(unpriced), "stale_positions": len(stale), "complete": complete,
        },
        "by_segment": sorted(by_seg.values(), key=lambda s: SEGMENTS.index(s["segment"])),
        "positions": positions, "strategies": strategies, "pending_entries": pending,
        "closed": closed_sel[:CLOSED_LISTED], "closed_total": len(closed_sel), "closed_partial": book.partial,
        "risk": {
            "capital": {"starting": capital or None, "cash": cash, "blocked": round(blocked, 2), "available": round(cash - blocked, 2),
                        "utilisation_pct": util, "basis": "Capital at risk blocked by open positions, not exchange margin.",
                        "blocked_by_source": blocked_by_source},
            "open_risk_rs": round(sum(open_risk), 2) if paper_on else None, "open_risk_limit_rs": open_risk_limit,
            "strategies_capital_at_risk_rs": (_sum(strat_risk)[0] if strat_risk else 0.0) if paper_on else None,
            "daily_loss_limit_rs": daily_limit, "daily_loss_used_pct": daily_used,
            "near_stop_pct": near_stop_pct(), "alerts": alerts, "margin": margin, "exposure_rs": exposure_total,
        },
        "analytics": {
            "trades": len(nets), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(nets) * 100, 1) if nets else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and wins else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "max_drawdown_rs": round(dd, 2), "max_drawdown_pct": round(dd / capital * 100, 4) if capital else None,
            "daily": [{"date": d, "net_pnl": v} for d, v in sorted(daily.items())],
        },
        "reconciliation": {"checked": checked, "mismatches": mismatches,
                           "basis": "Each closed trade's realized P&L recomputed from its fills, compared with the ledger's booked "
                                    "figure (a scanner position: its fills against slice C's realized_gross_rs, one paisa of "
                                    "rounding allowed per closing fill).",
                           "scanner_reserved_rs": round(float(spt_reserved), 2) if spt_reserved is not None else None,
                           "scanner_reservations": account.get("spt_reservations")},
        "marks_error": book.marks_error, "scanner_error": book.spt_error,
        "notes": notes,
    }


def _mode_block(rows: List[Dict[str, Any]], closed: List[Dict[str, Any]], capital: Optional[float], available: bool,
                note: Optional[str], *, realized_known: bool) -> Dict[str, Any]:
    """One mode card: realized (closed in the period; null for Live: brokers do not split it), unrealized, charges (booked +
    estimated), net, return on the mode's capital, open positions (a structure counts once)."""
    realized = _sum([c["realized_pnl"] for c in closed])[0] if realized_known else None
    booked = _sum([c["charges"] for c in closed])[0]
    unreal, u_unknown = _sum([r["unrealized_pnl"] for r in rows])
    est, e_unknown = _sum([r["charges_estimated"] for r in rows])
    gross = round((realized or 0.0) + unreal, 2)
    charges = round(booked + est, 2)
    net = round(gross - charges, 2)
    return {"realized_pnl": realized, "unrealized_pnl": unreal, "gross_pnl": gross, "charges": charges, "net_pnl": net,
            "capital": capital, "return_pct": round(net / capital * 100, 4) if capital else None,
            "open_positions": len({r["trade_id"] for r in rows}), "complete": u_unknown == 0 and e_unknown == 0,
            "available": available, "note": note}
