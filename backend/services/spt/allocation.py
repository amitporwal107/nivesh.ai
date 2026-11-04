"""Capital allocation for SPT proposals (PRD §8.1, §8.6-§8.7; WF §9, §18).

ACCOUNT STATE (`account_state`, read once per user per pipeline round; reads only, except risk_book raising the
equity peak as it always does):
    equity            risk_book equity (sizing.EQUITY_BASIS); None → nothing is allocated (equity_unknown)
    cash, available   the paper account (services/paper_account): available = cash − blocked
    reserved          capital blocked for ENTRY orders not yet filled: reservations whose `store` is spt_orders and
                      whose order is CREATED / VALIDATED / PENDING or not yet written (in flight); a partly filled order
                      counts its unfilled share (`filled_qty` / `quantity` on slice C's order)
    deployed          blocked − reserved (open positions: desk, journal and filled SPT entries)
    open risk         risk_book open.risk_rs: the risk service's estimate (stop loss + costs + 1 % gap stress) of
                      every reserved and legacy position — the measure the profile's open-risk limit is judged on
    buckets           SPT reservations' exposure by category (equity_positional, equity_intraday, fno) against
                      equity × allocation_buckets_pct; `reserve` is never allocated
    sector            risk_book open.sector_rs (+ unclassified exposure, counted against every sector)
    positions         the account's reserved positions + legacy positions vs config max_positions
    new today         this user's SPT proposals that reached READY_FOR_ORDER / ORDER_CREATED today (IST)

ALLOCATE ONE (`allocate`): the sized quantity is cut, in order, to: max positions and max new per day (else REJECTED),
available capital less the reserve bucket (never silently exceeded, WF §9.4), the category bucket, the sector limit
(profile max_sector_pct), and the open-risk room for its STRESSED risk per share (profile max_open_risk_pct). Cut to 0 →
ALLOCATION_REJECTED with the binding constraint's code; cut → ALLOCATION_REDUCED; else ALLOCATION_APPROVED. `consumed`
carries what earlier candidates in the same batch took, so a batch can never exceed the room (no reservation is taken
here: the risk service reserves atomically later).

SPT POSITIONS' P&L (`spt_pnl`): risk_book reads desk trades and the journal only, so B adds slice C's `spt_positions`
(services/spt/paper/positions.py) itself, reading only:
    equity      + the P&L of SPT positions not yet in paper cash: open positions (realized_net_rs + the live mark's
                unrealized_net_rs) and closed ones whose release to cash is not `done`. An open position without a mark,
                or with one older than MARK_BUDGET_SESSIONS sessions, makes equity unknown (fail closed: the ladder is
                `unknown` and new entries are blocked), never zero — except one filled under MARK_GRACE_S (300 s) ago,
                valued at its fill (minus the entry costs paid), so slice C does not cancel the rest of a partly
                filled entry before its monitor's first mark.
    day / week  + SPT P&L in the period: a position opened in the period counts its whole P&L (exact: it started at 0);
                one opened BEFORE the period counts its loss since entry when it is a loss, and nothing when it is a gain
                (CONSERVATIVE: no start-of-period mark is stored for SPT positions, so a gain is never used to offset a
                loss; listed in `conservative`).
    drawdown    (peak − adjusted equity) / peak with risk_book's stored peak (B never writes the peak).
The universal risk service still measures its own limits on risk_book's equity (desk + journal); B's checks on the
adjusted figures can only add refusals.

RANKING (`rank`, PRD §8.7): opportunity_score (slice A's validation score), then R:R at the entry, then liquidity
(ADV) — never the scanner score, which is not a success probability (PRD §27 decision 1).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import data_freshness as fresh
from services import paper_account as acct
from services import risk_book
from services.risk_gate import inputs

from . import constants as C
from . import policy

logger = logging.getLogger(__name__)

PENDING_ORDER_STATES = (C.ORD_CREATED, C.ORD_VALIDATED, C.ORD_PENDING)
SPT_PNL_VERSION = "spt-pnl-v1"
MARK_BUDGET_SESSIONS = 2
MARK_GRACE_S = 300
MAX_SPT_POSITIONS_READ = 2000
CATEGORIES = ("equity_positional", "equity_intraday", "fno")


def category_of(horizon: Optional[str], instrument: Optional[str]) -> str:
    if (instrument or "cash") != "cash":
        return "fno"
    return "equity_intraday" if horizon == "intraday" else "equity_positional"


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def _unfilled_fraction(order: Dict[str, Any]) -> float:
    qty = _f(order.get("quantity")) or 0.0
    filled = _f(order.get("filled_qty"))
    if filled is None:
        filled = _f(order.get("filled_quantity")) or 0.0
    if qty <= 0:
        return 1.0
    return max(0.0, min(1.0, (qty - filled) / qty))


def proposals_dt(stamp: Any) -> Optional[datetime]:
    from .proposals import _dt
    return _dt(stamp)


def _ist_day(stamp: Any):
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=fresh.IST)                    # a naive stamp is IST, as slice C reads them
    return d.astimezone(fresh.IST).date()


async def spt_pnl(db, user_id: str, *, now: datetime) -> Dict[str, Any]:
    """The P&L of the user's SPT positions that risk_book does not see (module docstring). Reads only."""
    today = fresh.ist_today(now)
    starts = {"day": today, "week": risk_book.week_start(today)}
    docs = await db[C.POSITIONS].find({"user_id": user_id}).to_list(MAX_SPT_POSITIONS_READ)
    unknown: List[str] = []
    conservative: List[str] = []
    not_in_cash = 0.0
    period = {"day": 0.0, "week": 0.0}
    n_open = 0
    for d in docs:
        sym = d.get("symbol") or d.get("_id")
        is_open = d.get("state") in C.POS_OPEN_STATES
        realized = float(d.get("realized_net_rs") or 0.0)
        closed_day = None if is_open else _ist_day(d.get("closed_at"))
        if not is_open and closed_day is not None and closed_day < starts["week"] \
                and (d.get("release") or {}).get("state") == "done":
            continue                                       # closed and paid out before this week: nothing to add
        if is_open:
            n_open += 1
            m = d.get("mark") or {}
            un = _f(m.get("unrealized_net_rs"))
            if int(d.get("quantity") or 0) > 0 and un is None:
                opened_at = proposals_dt(d.get("opened_at"))
                if opened_at is not None and 0 <= (now - opened_at).total_seconds() <= MARK_GRACE_S:
                    # Filled moments ago, not yet marked by slice C's monitor: at its fill the P&L is minus the entry
                    # costs paid. Treating it as unknown would block entries and make slice C cancel the rest of a
                    # partly filled entry order before its first mark.
                    value = realized - float(d.get("entry_costs_rs") or 0.0)
                    conservative.append(f"{sym} (valued at its fill: no mark yet)")
                    not_in_cash += value
                    opened = _ist_day(d.get("opened_at")) or today
                    for key, start in starts.items():
                        if opened >= start or value < 0:
                            period[key] += value
                    continue
                unknown.append(f"{sym}: SPT position has no live mark")
                continue
            if un is not None and not fresh.assess("SPT position mark (slice C)", _ist_day(m.get("at")),
                                                   budget_sessions=MARK_BUDGET_SESSIONS, now=now)["ok"]:
                unknown.append(f"{sym}: SPT position mark as of {m.get('at')} is stale")
                continue
            value = realized + (un or 0.0)
        else:
            value = realized
        if is_open or (d.get("release") or {}).get("state") != "done":
            not_in_cash += value
        opened = _ist_day(d.get("opened_at")) or today
        for key, start in starts.items():
            if not is_open and (closed_day is None or closed_day < start):
                continue
            if opened >= start:
                period[key] += value
            elif value < 0:
                period[key] += value
                conservative.append(f"{sym} ({key})")
    ok = not unknown
    return {"version": SPT_PNL_VERSION, "source": "spt_positions (slice C): realized_net_rs, mark.unrealized_net_rs",
            "open_positions": n_open, "equity_adjustment_rs": round(not_in_cash, 2) if ok else None,
            "day_pnl_rs": round(period["day"], 2) if ok else None, "week_pnl_rs": round(period["week"], 2) if ok else None,
            "unknown_reasons": unknown, "conservative": conservative,
            "conservative_text": "positions opened before the period count their loss since entry (no start-of-period "
                                 "mark is stored), and a gain is never counted" if conservative else None}


async def account_state(db, user_id: str, *, now: datetime, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The account as allocation, sizing and the SPT risk checks see it (module docstring). Never raises for a store it
    cannot read: `error` says which, and every decision that needs it blocks."""
    cfg = config or await policy.read(db, user_id)
    out: Dict[str, Any] = {"user_id": user_id, "as_of": now.astimezone(timezone.utc).isoformat(),
                           "day": fresh.ist_today(now).isoformat(), "config": cfg, "error": None, "book": None}
    try:
        book = await risk_book.read(db, user_id, now=now, sector_of=inputs.sector_of)
    except Exception as e:  # noqa: BLE001 — fail closed: allocation and risk block on a missing book
        logger.error("spt allocation: the book of %s could not be read (%s)", user_id, type(e).__name__)
        out["error"] = f"the account and positions could not be read ({type(e).__name__})"
        out["controls"] = await risk_book.controls(db, user_id)
        out["ladder"] = policy.ladder(None, cfg)
        return out
    out["book"] = book
    out["controls"] = await risk_book.controls(db, user_id)
    profile = book["profile"]
    limits = profile["limits"]
    try:
        spt = await spt_pnl(db, user_id, now=now)
    except Exception as e:  # noqa: BLE001 — fail closed: equity and the period P&L are unknown
        logger.error("spt allocation: the SPT positions of %s could not be read (%s)", user_id, type(e).__name__)
        spt = {"version": SPT_PNL_VERSION, "equity_adjustment_rs": None, "day_pnl_rs": None, "week_pnl_rs": None,
               "unknown_reasons": [f"the SPT positions could not be read ({type(e).__name__})"], "conservative": []}
    book_equity = _f(book["equity"]["equity_rs"])
    equity = None if book_equity is None or spt["equity_adjustment_rs"] is None \
        else round(book_equity + float(spt["equity_adjustment_rs"]), 2)

    def _period(key: str):
        pnl = _f(book[key]["pnl_rs"])
        if pnl is None or spt[f"{key}_pnl_rs"] is None or equity is None:
            return None, None
        total = round(pnl + float(spt[f"{key}_pnl_rs"]), 2)
        return total, round(equity - total, 2)

    day_pnl, day_start = _period("day")
    week_pnl, week_start = _period("week")
    peak = float(book["peak"]["peak_rs"])
    drawdown = None if equity is None or peak <= 0 else round(max(0.0, (peak - equity) / peak * 100.0), 4)
    account = book["account"]
    account_doc = await db[acct.ACCOUNTS].find_one({"user_id": user_id}) or {}
    entries = list(account_doc.get("reservations") or [])
    spt_ids = [e.get("trade_id") for e in entries if e.get("store") == C.ORDERS and e.get("trade_id")]
    orders: Dict[str, Dict[str, Any]] = {}
    proposals: Dict[str, Dict[str, Any]] = {}
    if spt_ids:
        for o in await db[C.ORDERS].find({"_id": {"$in": spt_ids}}).to_list(len(spt_ids)):
            orders[o["_id"]] = o
        for p in await db[C.PROPOSALS].find({"user_id": user_id, "order_id": {"$in": spt_ids}}).to_list(len(spt_ids)):
            proposals[p["order_id"]] = p
    reserved = 0.0
    bucket_used = {c: 0.0 for c in CATEGORIES}
    pending: List[Dict[str, Any]] = []
    for e in entries:
        funding = float(e.get("funding_rs") or 0.0)
        if e.get("store") != C.ORDERS:
            continue
        order = orders.get(e.get("trade_id"))
        if order is None or order.get("state") in PENDING_ORDER_STATES:
            frac = 1.0
        elif order.get("state") == C.ORD_PARTIAL:
            frac = _unfilled_fraction(order)
        else:
            frac = 0.0
        if frac > 0:
            reserved += funding * frac
            pending.append({"order_id": e.get("trade_id"), "symbol": e.get("symbol"), "reserved_rs": round(funding * frac, 2),
                            "order_state": (order or {}).get("state") or "not_written_yet"})
        p = proposals.get(e.get("trade_id")) or {}
        cat = category_of(p.get("horizon") or "positional", p.get("instrument") or e.get("kind") or "cash")
        bucket_used[cat] = bucket_used.get(cat, 0.0) + float(e.get("exposure_rs") or 0.0)
    blocked = float(account["blocked_rs"])
    buckets_pct = cfg["extras"]["allocation_buckets_pct"]
    new_today = await db[C.PROPOSALS].count_documents(
        {"user_id": user_id, "order_day": out["day"], "state": {"$in": [C.PROP_READY_FOR_ORDER, C.PROP_ORDER_CREATED]}})
    positions = int(account_doc.get("open_positions") or 0) + int(book["open"].get("legacy_positions") or 0)
    out.update({
        "profile": {"limits": limits, "limits_version": profile.get("limits_version"), "profile": profile.get("profile")},
        "equity_rs": equity, "book_equity_rs": book_equity, "spt_pnl": spt,
        "equity_unknown_reasons": (book["equity"].get("unknown_reasons") or []) + list(spt.get("unknown_reasons") or []),
        "cash_rs": account["cash_rs"], "blocked_rs": blocked, "available_rs": account["available_rs"],
        "reserved_rs": round(reserved, 2), "deployed_rs": round(max(0.0, blocked - reserved), 2),
        "pending_entries": pending,
        "reserve_rs": round(equity * float(buckets_pct["reserve"]) / 100.0, 2) if equity is not None else None,
        "open_risk_rs": float(book["open"]["risk_rs"]),
        "open_risk_basis": "risk service estimate: stop loss + round-trip costs + 1% gap stress (est-risk-v1)",
        "open_risk_cap_rs": round(equity * limits["max_open_risk_pct"] / 100.0, 2) if equity is not None else None,
        "exposure_rs": float(book["open"]["exposure_rs"]),
        "sector_rs": dict(book["open"]["sector_rs"]), "unclassified_exposure_rs": float(book["open"]["unclassified_exposure_rs"]),
        "bucket_used_rs": {k: round(v, 2) for k, v in bucket_used.items()},
        "bucket_cap_rs": {k: (round(equity * float(buckets_pct[k]) / 100.0, 2) if equity is not None else None)
                          for k in CATEGORIES},
        "positions_open": positions, "max_positions": int(cfg["extras"]["max_positions"]),
        "new_today": int(new_today), "max_new_per_day": int(cfg["extras"]["max_new_per_day"]),
        "drawdown_pct": drawdown, "book_drawdown_pct": book.get("drawdown_pct"), "peak_rs": peak,
        "day_pnl_rs": day_pnl, "day_start_equity_rs": day_start,
        "week_pnl_rs": week_pnl, "week_start_equity_rs": week_start,
        "ladder": policy.ladder(drawdown, cfg),
    })
    return out


def empty_consumed() -> Dict[str, Any]:
    return {"capital_rs": 0.0, "risk_rs": 0.0, "positions": 0, "new": 0, "bucket_rs": {}, "sector_rs": {}}


def consume(consumed: Dict[str, Any], cand: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Add an allocated candidate to the batch's running totals."""
    q = int(result.get("quantity") or 0)
    if q <= 0:
        return
    entry = float(cand["entry"])
    consumed["capital_rs"] += q * entry
    consumed["risk_rs"] += q * float(cand["stressed_per_share"])
    consumed["positions"] += 1
    consumed["new"] += 1
    cat = cand.get("category") or "equity_positional"
    consumed["bucket_rs"][cat] = consumed["bucket_rs"].get(cat, 0.0) + q * entry
    if cand.get("sector"):
        consumed["sector_rs"][cand["sector"]] = consumed["sector_rs"].get(cand["sector"], 0.0) + q * entry


def allocate(state: Dict[str, Any], cand: Dict[str, Any], consumed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One candidate {symbol, sector, category, entry, quantity (sized), stressed_per_share} against the account state
    and what the batch already took. Pure. Returns {decision, requested_qty, quantity, reasons[], steps[], room, version}."""
    used = consumed or empty_consumed()
    requested = int(cand.get("quantity") or 0)
    out: Dict[str, Any] = {"decision": None, "requested_qty": requested, "quantity": 0, "reasons": [], "steps": [],
                           "room": {}, "version": C.ALLOCATION_VERSION, "category": cand.get("category")}

    def reject(code: str, message: str) -> Dict[str, Any]:
        out["reasons"].insert(0, {"code": code, "message": message})       # the refusal first, the cuts behind it
        out.update(decision="ALLOCATION_REJECTED", quantity=0)
        return out

    if state.get("error") or state.get("equity_rs") is None:
        return reject("equity_unknown", state.get("error") or "Paper equity is unknown: " +
                      ("; ".join(state.get("equity_unknown_reasons") or []) or "unknown") + ".")
    if requested < 1:
        return reject("sized_to_zero", "The sizing left no whole share.")
    entry = float(cand["entry"])
    if state["positions_open"] + used["positions"] >= state["max_positions"]:
        return reject("max_positions", f"Open positions ({state['positions_open'] + used['positions']}) are at the limit "
                                       f"of {state['max_positions']}.")
    if state["new_today"] + used["new"] >= state["max_new_per_day"]:
        return reject("max_new_per_day", f"{state['new_today'] + used['new']} new SPT entries today; the limit is "
                                         f"{state['max_new_per_day']}.")
    q = requested
    equity = float(state["equity_rs"])
    limits = state["profile"]["limits"]

    def cut(name: str, code: str, room_rs: float, per_unit: float, text: str) -> None:
        nonlocal q
        fit = int(math.floor(max(room_rs, 0.0) / per_unit + 1e-9)) if per_unit > 0 else q
        out["room"][name] = round(room_rs, 2)
        after = min(q, fit)
        out["steps"].append({"cap": name, "before": q, "after": after, "room_rs": round(room_rs, 2), "binding": after < q,
                             "reason": text})
        if after < q:
            out["reasons"].append({"code": code, "message": f"{text}: at most {after} shares fit."})
        q = after

    reserve = float(state.get("reserve_rs") or 0.0)
    avail_room = float(state["available_rs"]) - reserve - used["capital_rs"]
    if float(state["available_rs"]) - used["capital_rs"] > 0 and avail_room <= 0 and reserve > 0:
        out["steps"].append({"cap": "available_capital", "before": q, "after": 0, "room_rs": round(avail_room, 2),
                             "binding": True, "reason": "all the available capital is inside the reserve bucket"})
        return reject("reserve_protected", f"Available capital ₹{float(state['available_rs']) - used['capital_rs']:,.2f} is "
                                           f"within the {state['config']['extras']['allocation_buckets_pct']['reserve']:g}% "
                                           f"reserve (₹{reserve:,.2f}), which is never allocated.")
    cut("available_capital", "capital_reduced", avail_room, entry,
        f"available ₹{float(state['available_rs']):,.2f} less the reserve ₹{reserve:,.2f} and this batch ₹{used['capital_rs']:,.2f}")
    cat = cand.get("category") or "equity_positional"
    cap_b = (state.get("bucket_cap_rs") or {}).get(cat)
    if cap_b is not None:
        cut("bucket", "bucket_reduced", cap_b - float(state["bucket_used_rs"].get(cat, 0.0)) - used["bucket_rs"].get(cat, 0.0),
            entry, f"the {cat} bucket ₹{cap_b:,.2f} ({state['config']['extras']['allocation_buckets_pct'][cat]:g}% of equity)")
    sector = cand.get("sector")
    if not sector:
        return reject("sector_unknown", "The sector is unknown, so the sector limit cannot be checked.")
    sector_cap = equity * float(limits["max_sector_pct"]) / 100.0
    sector_used = float(state["sector_rs"].get(sector, 0.0)) + float(state.get("unclassified_exposure_rs") or 0.0)
    cut("sector", "sector_reduced", sector_cap - sector_used - used["sector_rs"].get(sector, 0.0), entry,
        f"the {sector} sector limit {limits['max_sector_pct']:g}% (₹{sector_cap:,.2f})")
    risk_cap = float(state["open_risk_cap_rs"])
    cut("open_risk", "open_risk_reduced", risk_cap - float(state["open_risk_rs"]) - used["risk_rs"],
        float(cand["stressed_per_share"]),
        f"the open-risk limit {limits['max_open_risk_pct']:g}% (₹{risk_cap:,.2f}) for its stressed risk")
    out["quantity"] = q
    if q < 1:
        binding = next((s for s in reversed(out["steps"]) if s["binding"]), None)
        code = {"available_capital": "insufficient_capital", "bucket": "bucket_full", "sector": "sector_full",
                "open_risk": "open_risk_full"}.get((binding or {}).get("cap"), "no_room")
        return reject(code, f"No whole share fits: {(binding or {}).get('reason', 'no room')}.")
    out["decision"] = "ALLOCATION_REDUCED" if q < requested else "ALLOCATION_APPROVED"
    out["capital_rs"] = round(q * entry, 2)
    out["stressed_risk_rs"] = round(q * float(cand["stressed_per_share"]), 2)
    return out


def rank_key(cand: Dict[str, Any]):
    score = _f(cand.get("opportunity_score"))
    rr = _f(cand.get("rr"))
    adv = _f(cand.get("adv_rs"))
    return (-(score if score is not None else -math.inf), -(rr if rr is not None else -math.inf),
            -(adv if adv is not None else 0.0), str(cand.get("symbol") or ""))


def rank(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PRD §8.7 order: opportunity_score, then R:R, then liquidity. The scanner score is never a key."""
    ranked = sorted(cands, key=rank_key)
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
        c["rank_basis"] = "opportunity_score, then reward:risk at the entry, then average daily traded value"
    return ranked
