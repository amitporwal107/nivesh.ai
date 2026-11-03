"""F&O carry-forward ROLL of a strategy paper trade (owner decision, option C of the idea-persistence study,
/home/deploy/phase0-approval/study_idea_persistence.md §5).

A user-initiated roll of an open strategy paper trade whose contracts expire within ROLL_WINDOW_SESSIONS sessions (or on
the expiry day itself, after the close): the old structure is closed and the SAME structure — same family, direction
and lots, the strikes moved together by one shift so their distances are kept — is opened on the next LISTED expiry.

    Price      BOTH sides at session D's NSE F&O bhavcopy `close_price` (nidp.fno_bhavcopy through the data platform).
               Never the settle price: on an expiry date it holds the UNDERLYING's settlement price (56 of 56 legs in the
               study), and the close is the field the desk's entries use. No Kite option close exists, so D's bhavcopy
               must be in: it lands after 22:15 IST; before that the roll is refused (`roll_chain_not_ready`).
    Session D  today (IST) when today is an NSE session; otherwise the last session (a roll on a Saturday uses
               Friday's close). From the NSE holiday list (positional_engine/session_calendar); an unreadable calendar
               refuses rather than assumes.
    Strikes    strike_mode "distance" (default): every option strike moves by one shift = the listed strike on the next
               expiry nearest to (first option strike + (underlying close on D − the trade's reference price)), minus
               that first strike; "same": no shift. Every new strike must be listed with a close on the next expiry,
               else `strike_not_listed` names it. Nothing is re-centred leg by leg and no premium is invented.
    Lots       the old trade's lots, at the next expiry's exchange lot (the bhavcopy's board lot), which can differ.
    Levels     the old trade's stop / target on the underlying are carried when they still sit on the right side of
               D's close; otherwise they are dropped and the preview says so (a future without a stop is refused).

Nothing here writes or places an order: `plan_roll` is pure, `fetch_day_rows` reads. routes/desk_trading.py runs the
risk checks (the same as any entry), closes the old trade, reserves and opens the new one, and links them.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from services import desk_strategy_trades as strat
from services import desk_trading as base
from services.copilot_tools import daas_client

ROLL_RULES_VERSION = "desk-roll-v1 (2026-10-27)"
ROLL_WINDOW_SESSIONS = 3
STRIKE_MODES = ("distance", "same")
FNO_READY_TEXT = ("The NSE F&O bhavcopy for {day} is not in yet: it lands after 22:15 IST, and the roll records both "
                  "sides at that day's close. Try again once it is in.")
PAGE = 5000
MAX_PAGES = 10
SOURCE = "NSE F&O bhavcopy close_price (nidp.fno_bhavcopy via the data platform)"


class RollRefused(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(code)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# ── calendar ─────────────────────────────────────────────────────────────────
async def _holidays(years: Sequence[int]) -> Dict[date, str]:
    from services.positional_engine import session_calendar as cal

    out: Dict[date, str] = {}
    try:
        for y in sorted(set(years)):
            out.update(await cal.holidays_for_year(y))
    except cal.CalendarUnavailable as exc:
        raise RollRefused(503, "calendar_unavailable", f"The NSE holiday calendar could not be read ({exc}); "
                                                       "a session is never assumed, so nothing was rolled.") from exc
    return out


def _is_session(d: date, holidays: Dict[date, str]) -> bool:
    return d.weekday() < 5 and d not in holidays


def roll_session(today: date, holidays: Dict[date, str]) -> date:
    """Session D: today when it is an NSE session, else the last session before it."""
    d = today
    for _ in range(15):
        if _is_session(d, holidays):
            return d
        d -= timedelta(days=1)
    raise RollRefused(503, "calendar_unavailable", "No NSE session in the last 15 days on the holiday calendar.")


def sessions_to(d: date, expiry: date, holidays: Dict[date, str]) -> int:
    """Sessions after D up to and including the expiry (0 when D is the expiry day)."""
    n, x = 0, d
    while x < expiry:
        x += timedelta(days=1)
        if _is_session(x, holidays):
            n += 1
    return n


async def calendar_for(today: date, expiry: date) -> Tuple[date, int, Dict[date, str]]:
    hol = await _holidays([today.year, (today - timedelta(days=15)).year, expiry.year])
    d = roll_session(today, hol)
    return d, sessions_to(d, expiry, hol), hol


# ── data ─────────────────────────────────────────────────────────────────────
async def fetch_day_rows(underlying: str, day: date) -> List[Dict[str, Any]]:
    """Every F&O bhavcopy row of `underlying` on `day` (GET /v1/fno/{symbol}?on=day, paged). [] when that day is not
    loaded; raises RollRefused 503 when the platform cannot be read."""
    if not daas_client.is_configured():
        raise RollRefused(503, "prices_unavailable", "The data platform is not configured.")
    rows: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"on": day.isoformat(), "limit": PAGE, "offset": 0}
    for _ in range(MAX_PAGES):
        try:
            body = await daas_client._get(f"/fno/{quote(underlying, safe='')}", params=params, timeout=20.0)
        except daas_client.DaasError as exc:
            raise RollRefused(503, "prices_unavailable", f"The F&O bhavcopy could not be read ({exc}).") from exc
        data = (body or {}).get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return rows
        rows.extend(r for r in data if isinstance(r, dict) and str(r.get("as_of_date"))[:10] == day.isoformat())
        nxt = ((body or {}).get("pagination") or {}).get("next_offset")
        if nxt is None:
            return rows
        params = {**params, "offset": int(nxt)}
    raise RollRefused(503, "prices_unavailable", f"Too many F&O rows for {underlying} on {day.isoformat()}.")


# ── the roll itself (pure) ───────────────────────────────────────────────────
_OPT = {"call": "CE", "put": "PE"}


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _row_for(rows: Sequence[Dict[str, Any]], kind: str, expiry: str, strike: Optional[float], option_type: Optional[str]) -> Optional[Dict[str, Any]]:
    for r in rows:
        if str(r.get("expiry_date"))[:10] != expiry:
            continue
        ot = (r.get("option_type") or "").upper()
        if kind == "future":
            if ot in ("", "XX", "NONE") and r.get("strike_price") in (None, 0, 0.0, "0"):
                return r
            continue
        if ot == _OPT[option_type] and _num(r.get("strike_price")) is not None and abs(float(r["strike_price"]) - float(strike)) < 1e-6:
            return r
    return None


def _expiries(rows: Sequence[Dict[str, Any]], kind: str) -> List[str]:
    out = set()
    for r in rows:
        ot = (r.get("option_type") or "").upper()
        is_opt = ot in ("CE", "PE")
        if (kind == "option") == is_opt:
            out.add(str(r.get("expiry_date"))[:10])
    return sorted(out)


def _strikes(rows: Sequence[Dict[str, Any]], expiry: str, option_type: str) -> List[float]:
    return sorted({float(r["strike_price"]) for r in rows if str(r.get("expiry_date"))[:10] == expiry
                   and (r.get("option_type") or "").upper() == _OPT[option_type] and _num(r.get("close_price")) is not None
                   and _num(r.get("strike_price")) is not None})


def _close(row: Optional[Dict[str, Any]]) -> Optional[float]:
    return None if row is None else _num(row.get("close_price"))


def plan_roll(trade: Dict[str, Any], rows: Sequence[Dict[str, Any]], session: date, sessions_left: int, *,
              strike_mode: str = "distance") -> Dict[str, Any]:
    """The roll of `trade` on session D from D's bhavcopy rows: {session, sessions_to_expiry, old {...}, new {...},
    body (the new trade's request body), notes}. Raises RollRefused with the reason; never a made-up price."""
    if strike_mode not in STRIKE_MODES:
        raise RollRefused(422, "invalid_strike_mode", f"strike_mode must be one of {', '.join(STRIKE_MODES)}.")
    legs = trade["legs"]
    deriv = [l for l in legs if l["kind"] in ("future", "option")]
    expiries = {l["expiry"] for l in deriv}
    if not deriv:
        raise RollRefused(422, "nothing_to_roll", "This trade has no futures or options leg.")
    if len(expiries) > 1:
        raise RollRefused(422, "mixed_expiries_not_rollable", "The legs expire on different dates; a roll moves one expiry.")
    old_expiry = next(iter(expiries))
    if session > date.fromisoformat(old_expiry):
        raise RollRefused(409, "already_expired", f"The contracts expired on {old_expiry}; the exit rule settles the trade.")
    if sessions_left > ROLL_WINDOW_SESSIONS:
        raise RollRefused(409, "roll_not_due", f"The contracts expire in {sessions_left} sessions; a roll is offered from "
                                               f"{ROLL_WINDOW_SESSIONS} sessions before the expiry.", sessions_to_expiry=sessions_left)
    if not rows:
        raise RollRefused(409, "roll_chain_not_ready", FNO_READY_TEXT.format(day=session.isoformat()), session=session.isoformat())
    underlying_close = next((_num(r.get("underlying_price")) for r in rows if _num(r.get("underlying_price"))), None)
    if underlying_close is None:
        raise RollRefused(409, "underlying_unpriced", f"The {session.isoformat()} bhavcopy has no underlying price for {trade['underlying']}.")

    old_legs = []
    for i, l in enumerate(legs):
        if l["kind"] == "cash":
            raise RollRefused(422, "cash_leg_not_rollable", "A structure with a share leg is not rolled; close it and record a new one.")
        px = _close(_row_for(rows, l["kind"], l["expiry"], l.get("strike"), l.get("option_type")))
        if px is None:
            raise RollRefused(409, "old_leg_unpriced", f"Leg {i + 1} ({strat.leg_label(l)}) has no close in the "
                                                      f"{session.isoformat()} bhavcopy, so it cannot be closed at that close.")
        old_legs.append({"index": i, "label": strat.leg_label(l), "entry_price": l["entry_price"], "close": px,
                         "pnl_rs": round((px - float(l["entry_price"])) * l["lots"] * l["lot_size"] * (1 if l["side"] == "buy" else -1), 2)})

    nxt: Dict[str, str] = {}
    for kind in {l["kind"] for l in deriv}:
        later = [e for e in _expiries(rows, kind) if e > old_expiry]
        if not later:
            raise RollRefused(409, "no_next_expiry", f"No {kind} expiry after {old_expiry} is listed in the {session.isoformat()} bhavcopy.")
        nxt[kind] = later[0]

    options = [l for l in legs if l["kind"] == "option"]
    shift = 0.0
    if options and strike_mode == "distance":
        anchor = options[0]
        listed = _strikes(rows, nxt["option"], anchor["option_type"])
        if not listed:
            raise RollRefused(409, "strike_not_listed", f"No {anchor['option_type']} strike with a close is listed for {nxt['option']}.")
        want = float(anchor["strike"]) + (underlying_close - float(trade["reference_price"]))
        shift = min(listed, key=lambda k: (abs(k - want), k)) - float(anchor["strike"])

    new_legs: List[Dict[str, Any]] = []
    for i, l in enumerate(legs):
        exp = nxt[l["kind"]]
        strike = None if l["kind"] == "future" else float(l["strike"]) + shift
        row = _row_for(rows, l["kind"], exp, strike, l.get("option_type"))
        px = _close(row)
        if px is None:
            what = f"{l['option_type']} {strike:g}" if strike is not None else "future"
            raise RollRefused(409, "strike_not_listed", f"Leg {i + 1}: the {what} for {exp} is not listed with a close in the "
                                                        f"{session.isoformat()} bhavcopy, so the same structure cannot be opened.",
                              leg=i + 1, strike=strike, expiry=exp)
        lot = row.get("new_board_lot_qty")
        try:
            lot = int(float(lot))
        except (TypeError, ValueError):
            lot = 0
        if lot <= 0:
            raise RollRefused(409, "lot_size_unverified", f"Leg {i + 1}: the {exp} contract's exchange lot is not in the bhavcopy.")
        new_legs.append({"kind": l["kind"], "side": l["side"], "lots": l["lots"], "lot_size": lot, "entry_price": px,
                         "expiry": exp, "strike": strike, "option_type": l.get("option_type"),
                         "price_source": f"NSE F&O bhavcopy close, {session.isoformat()} (roll)"})

    notes: List[str] = []
    up = trade["direction"] == "bullish"
    carried: Dict[str, Optional[float]] = {}
    for key in ("stop_underlying", "target_underlying"):
        v = trade.get(key)
        ok = v is not None and trade["direction"] != "neutral" and (
            ((v < underlying_close) if up else (v > underlying_close)) if key == "stop_underlying"
            else ((v > underlying_close) if up else (v < underlying_close)))
        carried[key] = v if ok else None
        if v is not None and not ok:
            notes.append(f"The old {key.replace('_', ' ')} {v:g} is on the wrong side of the {session.isoformat()} close "
                         f"{underlying_close:g}, so it is not carried.")
    sig = trade.get("signal") or {}
    body = {
        "kind": "strategy", "underlying": trade["underlying"], "direction": trade["direction"], "family": trade["family"],
        "reference_price": underlying_close, **{k: v for k, v in carried.items() if v is not None},
        "legs": new_legs,
        "signal": {"signal_at": session.isoformat(), "rule_version": ROLL_RULES_VERSION[:60],
                   "source_refs": [{"kind": "rolled_from", "ref": trade["_id"], "as_of": session.isoformat()},
                                   {"kind": "option_chain", "ref": "NSE F&O bhavcopy close_price", "as_of": session.isoformat()}]
                   + [r for r in (sig.get("source_refs") or []) if r.get("kind") != "rolled_from"][:8],
                   "evidence_summary": (f"Rolled from paper trade {trade['_id']} ({strat.legs_summary(trade)}) at the "
                                        f"{session.isoformat()} NSE bhavcopy close; same family, strikes moved by {shift:g} "
                                        f"({strike_mode}). " + (sig.get("evidence_summary") or ""))[:1000]},
        "note": f"Rolled from {trade['_id']} on {session.isoformat()}",
    }
    if trade.get("max_hold_sessions"):
        body["max_hold_sessions"] = trade["max_hold_sessions"]
    return {"session": session.isoformat(), "sessions_to_expiry": sessions_left, "rules_version": ROLL_RULES_VERSION,
            "price_source": SOURCE, "underlying_close": underlying_close, "strike_mode": strike_mode, "strike_shift": shift,
            "old": {"trade_id": trade["_id"], "expiry": old_expiry, "legs": old_legs,
                    "gross_pnl_rs": round(sum(l["pnl_rs"] for l in old_legs), 2)},
            "new": {"expiry": sorted(set(nxt.values()))[0], "legs": [{**l, "label": strat.leg_label(l)} for l in new_legs],
                    "net_premium_rs": strat.net_premium(new_legs, [l["entry_price"] for l in new_legs])},
            "carried_levels": carried, "notes": notes, "body": body}


def roll_sim(sim: Dict[str, Any], preview: Dict[str, Any], session: date) -> Dict[str, Any]:
    """The simulate_strategy result the old trade closes with: its path (MFE / MAE, sessions) as simulated, every leg
    marked at D's bhavcopy close (mark basis `roll_close`) and the gross P&L at those closes."""
    out = dict(sim)
    out["legs"] = [{"mark": l["close"], "mark_date": session, "mark_basis": "roll_close", "settled": False, "exit_mark": l["close"]}
                   for l in preview["old"]["legs"]]
    out["gross_pnl_rs"] = preview["old"]["gross_pnl_rs"]
    out["flags"] = [f for f in sim.get("flags") or [] if f.get("code") not in ("exit_marked_at_session_marks",)]
    out["checked_through"] = max(sim.get("checked_through") or session, session)
    return out


def exit_before_roll(sim: Dict[str, Any], session: date) -> Optional[Dict[str, Any]]:
    """An exit the trade's own rules took on or before D that the roll must not override: a stop, a target or a time
    exit (an EXPIRY on D itself is what the roll replaces)."""
    ex = sim.get("exit")
    if ex is None:
        return None
    if ex["exit_reason"] == "expiry" and ex["exit_session"] >= session:
        return None
    return ex


def preview_costs(trade: Dict[str, Any], preview: Dict[str, Any]) -> Dict[str, Any]:
    """desk-cost-v2 on both legs: the old trade's round trip closed at D's closes, and the new trade's round trip
    estimated at its entry premiums."""
    old_bd = strat.strategy_cost_breakdown(trade, [l["close"] for l in preview["old"]["legs"]])
    new_trade = {"legs": preview["body"]["legs"], "cost_model": dict(base.COST_MODEL)}
    new_bd = strat.strategy_cost_breakdown(new_trade, [l["entry_price"] for l in preview["body"]["legs"]])
    return {"old_round_trip": old_bd, "old_net_pnl_rs": (round(preview["old"]["gross_pnl_rs"] - old_bd["total"], 2) if old_bd else None),
            "new_round_trip_estimate": new_bd, "model": (trade.get("cost_model") or {}).get("version"),
            "new_model": base.COST_MODEL.get("version")}
