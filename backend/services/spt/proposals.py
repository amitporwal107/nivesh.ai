"""Per-account trade proposals from QUALIFIED opportunities (WF §7, PRD §7.1, DESIGN.md §4, §5).

ONE PROPOSAL PER (user, opportunity) (`spt_proposals`, unique index): a second create returns the first (PRD §18 rule 6).

TEMPLATE `cash_long_positional_v1` (the only tradable one tonight, DESIGN D5), from the opportunity's strong-signal plan
(scan-plan-v3: stop = entry − 2 ATR, T1 = entry + 2R, T2 = entry + 4R, trend exit = a daily close below the SMA20):
    entry    IMMEDIATE (a marketable order) when the live price is ≤ plan entry × (1 + max_chase_pct %) and above the
             stop: priced at the live ask (the LTP when the quote carries no ask, said so in `entry.basis`);
             otherwise a LIMIT at the plan entry (a pullback), GTD until the opportunity's window / expiry ends.
    stop     the plan's stop, never widened to fit a size (PRD §8.5)
    targets  the plan's T1 and T2
    exits    T1 exits 50 % and moves the stop to breakeven, an ATR trail (trail-atr-v1, k = 2), the trend exit (a daily
             close below the SMA20) and a 20-session time exit (DESIGN §4 `exit_plan`)
    R:R      at the ACTUAL entry, on prices: to T1 and to T2. The minimum (config min_rr.positional) is judged to T2
             (TESTCASES DB-4).
REFUSALS
    NOT_TRADABLE  horizon_not_enabled (intraday), direction_not_enabled (short), instrument_not_enabled (non-cash)
    REJECTED      no_valid_plan (no strong plan or plan_ok false), price_at_or_below_stop (the plan is invalidated:
                  the opportunity is EXPIRED market-wide through slice A's `transition`), target_already_reached,
                  rr_below_minimum
A price is never made up: without a fresh live quote no proposal is written (PriceUnavailable; the pipeline tries again
next round). Refusals that need no price (not tradable, no valid plan) are written at once.

STATE (constants PROP_*): every transition is ONE conditional update on (state, version), appended to `state_history`,
and logged as PROPOSAL_STATE_CHANGED with a stable idempotency key, so a replay adds nothing.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import data_freshness as fresh

from . import constants as C
from . import events

logger = logging.getLogger(__name__)

TEMPLATE = "cash_long_positional_v1"
SOURCE = "spt.proposals"
IST = fresh.IST
SESSION_CLOSE = (15, 30)
#: The live quote's age budget, shared with slice C's execution model (DESIGN §6): the admin's spt_settings value, else
#: env SPT_QUOTE_MAX_AGE_S, else 120 s (services/spt/settings.quote_max_age_s, read at call time).
def quote_max_age_s() -> float:
    from . import settings
    return settings.quote_max_age_s()
QUOTE_SOURCE = "Kite live quote cache (services/kite_live_feed/quote_cache.read_quotes)"
MAX_HOLD_SESSIONS = 20
T1_EXIT_FRACTION = 0.5
TRAIL = {"rule": "trail-atr-v1", "k": 2}
TREND_EXIT = {"rule": "close_below_sma20"}

TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    C.PROP_GENERATED: (C.PROP_AWAITING_RISK, C.PROP_NOT_TRADABLE, C.PROP_REJECTED),
    C.PROP_AWAITING_RISK: (C.PROP_BLOCKED_BY_RISK, C.PROP_REJECTED, C.PROP_NOT_TRADABLE, C.PROP_RISK_APPROVED),
    C.PROP_RISK_APPROVED: (C.PROP_AWAITING_USER, C.PROP_READY_FOR_ORDER, C.PROP_TRACKING_ONLY),
    C.PROP_AWAITING_USER: (C.PROP_USER_REJECTED, C.PROP_APPROVAL_EXPIRED, C.PROP_READY_FOR_ORDER),
    C.PROP_READY_FOR_ORDER: (C.PROP_ORDER_CREATED,),
}
TERMINAL = (C.PROP_BLOCKED_BY_RISK, C.PROP_REJECTED, C.PROP_NOT_TRADABLE, C.PROP_USER_REJECTED, C.PROP_APPROVAL_EXPIRED,
            C.PROP_ORDER_CREATED, C.PROP_TRACKING_ONLY)


class TransitionError(RuntimeError):
    """A transition the state machine does not allow (a programming error, not a race)."""


class PriceUnavailable(RuntimeError):
    """No fresh live price for an otherwise tradable opportunity: nothing is written (a transient data gap must not end
    the proposal), and the caller tries again later. `code` is price_unavailable / price_stale / price_undated /
    quote_cache_unavailable."""

    def __init__(self, code: str) -> None:
        super().__init__(f"no fresh live price ({code})")
        self.code = code


PRICE_CODES = ("price_unavailable", "price_stale", "price_undated", "quote_cache_unavailable")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def _dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def session_close(now: datetime) -> datetime:
    """15:30 IST of `now`'s IST date."""
    ist = now.astimezone(IST)
    return ist.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0).astimezone(timezone.utc)


# ── the live price ───────────────────────────────────────────────────────────
def price_from_quote(row: Optional[Dict[str, Any]], now: datetime, *, max_age_s: Optional[float] = None) -> Dict[str, Any]:
    """{ok, price, ltp, bid, ask, basis, received_at, age_s, source, reason} from one quote-cache row. `price` is what a
    BUY would pay now: the ask, else the LTP (basis says which). Not ok when absent, unpriced or older than max_age_s
    (default: quote_max_age_s())."""
    max_age_s = quote_max_age_s() if max_age_s is None else float(max_age_s)
    out = {"ok": False, "price": None, "ltp": None, "bid": None, "ask": None, "basis": None, "received_at": None,
           "age_s": None, "max_age_s": max_age_s, "source": QUOTE_SOURCE, "reason": None}
    if not row:
        out["reason"] = "price_unavailable"
        return out
    ltp, bid, ask = _f(row.get("ltp")), _f(row.get("bid")), _f(row.get("ask"))
    out.update(ltp=ltp, bid=bid, ask=ask, received_at=row.get("received_at"))
    got = _dt(row.get("received_at"))
    if got is None:
        out["reason"] = "price_undated"
        return out
    age = (now - got).total_seconds()
    out["age_s"] = round(age, 1)
    if age > max_age_s:
        out["reason"] = "price_stale"
        return out
    if ask is not None and ask > 0:
        out.update(price=ask, basis="ask")
    elif ltp is not None and ltp > 0:
        out.update(price=ltp, basis="ltp (the quote carries no ask)")
    else:
        out["reason"] = "price_unavailable"
        return out
    out["ok"] = True
    return out


async def read_prices(symbols: List[str], now: datetime) -> Dict[str, Dict[str, Any]]:
    """The live price of each symbol (price_from_quote). The cache unavailable → every symbol `price_unavailable`."""
    from services.kite_live_feed import quote_cache
    rows = await quote_cache.read_quotes(sorted(set(symbols)))
    if rows is None:
        return {s: price_from_quote(None, now) | {"reason": "quote_cache_unavailable"} for s in symbols}
    return {s: price_from_quote(rows.get(s), now) for s in symbols}


# ── the proposal, pure ───────────────────────────────────────────────────────
def _instrument(opp: Dict[str, Any]) -> str:
    raw = str(opp.get("instrument") or opp.get("segment") or "cash").strip().lower()
    return "cash" if raw in ("cash", "equity", "eq", "") else raw


def opportunity_summary(opp: Dict[str, Any]) -> Dict[str, Any]:
    v = opp.get("validation") or {}
    return {"opportunity_id": opp.get("_id"), "state_at_proposal": opp.get("state"), "version": opp.get("version"),
            "consolidation_key": opp.get("consolidation_key"), "category": opp.get("category"), "family": opp.get("family"),
            "opportunity_score": v.get("opportunity_score"), "validation_version": v.get("version"),
            "validated_at": v.get("at"), "liquidity": v.get("liquidity"), "signals": len(opp.get("signals") or []),
            "conflicts": len(opp.get("conflicts") or []), "first_seen_at": opp.get("first_seen_at"),
            "window_until": opp.get("window_until"), "expires_at": opp.get("expires_at"), "day": opp.get("day")}


def exit_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {"stop_loss": plan.get("stop_loss"), "target_1": plan.get("target_1"), "target_2": plan.get("target_2"),
            "t1_exit_fraction": T1_EXIT_FRACTION, "move_stop_to_breakeven_at_t1": True,
            "trail": dict(TRAIL) if _f(plan.get("atr")) else None,
            "trend_exit": dict(TREND_EXIT) if (_f(plan.get("sma20")) or plan.get("trend_exit")) else None,
            "max_hold_sessions": MAX_HOLD_SESSIONS}


def _earliest(*values: Any) -> Optional[datetime]:
    got = [d for d in (_dt(v) for v in values) if d is not None]
    return min(got) if got else None


def build(opp: Dict[str, Any], price: Dict[str, Any], config: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """The proposal body for `opp` at `price` under `config` (no ids, no state). `outcome` is "ok", "not_tradable" or
    "rejected", with reason codes and explanations. `opp_invalidated` = True when the plan is invalid market-wide."""
    extras = config["extras"]
    body: Dict[str, Any] = {"template": TEMPLATE, "symbol": str(opp.get("symbol") or "").upper(),
                            "exchange": opp.get("exchange") or "NSE", "direction": opp.get("direction"),
                            "horizon": opp.get("horizon"), "instrument": _instrument(opp),
                            "opportunity": opportunity_summary(opp), "price": price, "outcome": "ok",
                            "reason_codes": [], "explanations": [], "opp_invalidated": False}

    def refuse(outcome: str, code: str, text: str) -> Dict[str, Any]:
        body.update(outcome=outcome)
        body["reason_codes"].append(code)
        body["explanations"].append(text)
        return body

    if body["horizon"] not in C.TRADABLE_HORIZONS:
        return refuse("not_tradable", "horizon_not_enabled",
                      f"The {body['horizon'] or 'unknown'} horizon is tracked, not traded, in this release (positional only).")
    if body["direction"] not in C.TRADABLE_DIRECTIONS:
        return refuse("not_tradable", "direction_not_enabled",
                      f"{body['direction'] or 'Unknown'} opportunities are tracked, not traded, in this release (long only).")
    if body["instrument"] not in C.TRADABLE_INSTRUMENTS:
        return refuse("not_tradable", "instrument_not_enabled",
                      f"The {body['instrument']} instrument is tracked, not traded, in this release (cash shares only).")
    # Slice A keeps a QUALIFIED opportunity QUALIFIED when an opposite-direction signal arrives later (DESIGN §5 has no
    # move for it) and flags it instead; a proposal is not made against conflicting evidence (Workflow §5.4).
    if opp.get("conflict_after_qualified"):
        return refuse("rejected", "conflicting_signals",
                      "An opposite-direction signal for this stock arrived after the opportunity qualified.")
    plan = ((opp.get("strong") or {}).get("plan") or {})
    p_entry, p_stop = _f(plan.get("entry")), _f(plan.get("stop_loss"))
    t1, t2 = _f(plan.get("target_1")), _f(plan.get("target_2"))
    body["plan"] = dict(plan) if plan else None
    if not plan or not plan.get("plan_ok") or None in (p_entry, p_stop, t1, t2) or not (0 < p_stop < p_entry < t1 < t2):
        return refuse("rejected", "no_valid_plan", "There is no valid strategy plan (entry, stop loss, target 1 and "
                                                   "target 2 in order) for this opportunity" +
                      (f": {plan.get('plan_note')}" if plan and plan.get("plan_note") else "."))
    body.update(stop_loss=p_stop, target_1=t1, target_2=t2, exit_plan=exit_plan(plan))
    if not price.get("ok"):
        return refuse("rejected", price.get("reason") or "price_unavailable",
                      "No fresh live price, so no entry can be priced.")
    px = float(price["price"])
    if px <= p_stop:
        body["opp_invalidated"] = True
        return refuse("rejected", "price_at_or_below_stop",
                      f"The live price ₹{px:,.2f} is at or below the plan's stop loss ₹{p_stop:,.2f}: the plan is invalidated.")
    chase = float(extras["max_chase_pct"])
    bound = round(p_entry * (1 + chase / 100.0), 4)
    opp_end = _earliest(opp.get("window_until"), opp.get("expires_at"))
    if px <= bound:
        entry = {"type": "MARKET", "price": px, "basis": f"live {price.get('basis')}", "chase_bound": bound,
                 "plan_entry": p_entry, "limit_price": None, "time_in_force": "DAY",
                 "expires_at": _iso(min(session_close(now), opp_end) if opp_end else session_close(now)),
                 "rule": f"immediate: live price ≤ plan entry × (1 + {chase:g}%) and above the stop"}
    else:
        entry = {"type": "LIMIT", "price": p_entry, "basis": "plan entry (a pullback limit)", "chase_bound": bound,
                 "plan_entry": p_entry, "limit_price": p_entry, "time_in_force": "GTD",
                 "expires_at": _iso(opp_end) if opp_end else _iso(session_close(now)),
                 "rule": f"pullback: live price ₹{px:,.2f} is above plan entry × (1 + {chase:g}%) = ₹{bound:,.2f}"}
    body["entry"] = entry
    e = float(entry["price"])
    risk_ps = e - p_stop
    rr1, rr2 = (t1 - e) / risk_ps, (t2 - e) / risk_ps
    min_rr = float(extras["min_rr"]["positional"])
    body["rr"] = {"t1": round(rr1, 4), "t2": round(rr2, 4), "min_rr": min_rr, "measured_to": "target_2",
                  "basis": "prices at the actual entry, no costs (the risk service judges reward:risk after costs)"}
    body["risk_per_share"] = round(risk_ps, 4)
    body["expires_at"] = _iso(opp_end) if opp_end else None
    if rr1 <= 0:
        return refuse("rejected", "target_already_reached",
                      f"The entry ₹{e:,.2f} is at or above target 1 ₹{t1:,.2f}.")
    if rr2 < min_rr - 1e-9:
        return refuse("rejected", "rr_below_minimum",
                      f"Reward:risk to target 2 at the entry ₹{e:,.2f} is {rr2:.2f}; the minimum is {min_rr:g}.")
    return body


# ── the store ────────────────────────────────────────────────────────────────
_indexed = False


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    await db[C.PROPOSALS].create_index([("user_id", 1), ("opportunity_id", 1)], unique=True)
    await db[C.PROPOSALS].create_index([("user_id", 1), ("state", 1)])
    await db[C.PROPOSALS].create_index([("state", 1), ("approval.expires_at", 1)])
    await db[C.PROPOSALS].create_index([("order_id", 1)])
    _indexed = True


async def get(db, proposal_id: str, *, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    q: Dict[str, Any] = {"_id": proposal_id}
    if user_id is not None:
        q["user_id"] = user_id
    return await db[C.PROPOSALS].find_one(q)


async def for_opportunity(db, user_id: str, opportunity_id: str) -> Optional[Dict[str, Any]]:
    return await db[C.PROPOSALS].find_one({"user_id": user_id, "opportunity_id": opportunity_id})


async def list_for_user(db, user_id: str, *, states: Optional[List[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"user_id": user_id}
    if states:
        q["state"] = {"$in": list(states)}
    n = max(1, min(int(limit), 500))
    return await db[C.PROPOSALS].find(q).sort("created_at", -1).limit(n).to_list(n)


async def _emit(db, event_type: str, doc: Dict[str, Any], key: str, payload: Dict[str, Any]) -> None:
    await events.emit(db, event_type, idempotency_key=key, source_service=SOURCE, payload=payload,
                      correlation_id=doc["_id"], account_id=doc["user_id"], instrument_id=doc.get("symbol"))


async def create(db, user_id: str, opp: Dict[str, Any], price: Dict[str, Any], config: Dict[str, Any], now: datetime,
                 ) -> Tuple[Dict[str, Any], bool]:
    """(the proposal, created?). Idempotent per (user, opportunity): the unique index refuses a second insert and the
    first proposal is returned. A not-tradable or rejected body is created and moved to its terminal state at once, so
    the refusal is on record (and not proposed again)."""
    await ensure_indexes(db)
    existing = await for_opportunity(db, user_id, opp["_id"])
    if existing:
        return existing, False
    body = build(opp, price, config, now)
    if body["outcome"] == "rejected" and body["reason_codes"] and body["reason_codes"][0] in PRICE_CODES:
        raise PriceUnavailable(body["reason_codes"][0])
    pid = str(uuid.uuid4())
    at = _iso(now)
    doc = {k: v for k, v in body.items() if k not in ("outcome",)}
    doc.update({"_id": pid, "proposal_id": pid, "user_id": user_id, "account_id": user_id, "opportunity_id": opp["_id"],
                "state": C.PROP_GENERATED, "version": 1, "created_at": at, "updated_at": at,
                "day": fresh.ist_today(now).isoformat(),
                "state_history": [{"from": None, "to": C.PROP_GENERATED, "at": at, "reason": "proposal generated"}],
                "mode_at_creation": config["mode"], "config_version": config["version"],
                "sizing": None, "allocation": None, "risk": None, "risk_history": [], "order_id": None, "order": None,
                "approval": None, "versions": {"proposal": C.PROPOSAL_VERSION, "config": config.get("policy_version")}})
    try:
        await db[C.PROPOSALS].insert_one(doc)
    except Exception as e:  # noqa: BLE001 — a concurrent create won (unique (user, opportunity)): return that one
        if type(e).__name__ != "DuplicateKeyError" and "duplicate key" not in str(e).lower():
            raise
        existing = await for_opportunity(db, user_id, opp["_id"])
        if existing:
            return existing, False
        raise
    await _emit(db, "TRADE_PROPOSAL_CREATED", doc, f"proposal:{pid}:created",
                {"proposal_id": pid, "opportunity_id": opp["_id"], "template": TEMPLATE, "outcome": body["outcome"],
                 "entry": doc.get("entry"), "stop_loss": doc.get("stop_loss"), "target_1": doc.get("target_1"),
                 "target_2": doc.get("target_2"), "rr": doc.get("rr"), "reason_codes": body["reason_codes"],
                 "version": C.PROPOSAL_VERSION})
    if body["outcome"] == "not_tradable":
        doc = await transition(db, doc, C.PROP_NOT_TRADABLE, reason=";".join(body["reason_codes"]), now=now) or doc
    elif body["outcome"] == "rejected":
        doc = await transition(db, doc, C.PROP_REJECTED, reason=";".join(body["reason_codes"]), now=now) or doc
    return doc, True


async def transition(db, doc: Dict[str, Any], to_state: str, *, reason: str, now: datetime,
                     extra: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Move `doc` from its state to `to_state` if nobody moved it first: ONE update filtered on (state, version).
    Returns the stored document after the move, or None when the filter did not match (another worker moved it).
    Raises TransitionError for a move the state machine does not allow."""
    frm = doc["state"]
    if to_state not in TRANSITIONS.get(frm, ()):
        raise TransitionError(f"proposal {doc['_id']}: {frm} -> {to_state} is not allowed")
    at = _iso(now)
    version = int(doc.get("version") or 1)
    step = {"from": frm, "to": to_state, "at": at, "reason": reason, "actor": actor}
    sets = {"state": to_state, "version": version + 1, "updated_at": at, **(extra or {})}
    res = await db[C.PROPOSALS].update_one({"_id": doc["_id"], "state": frm, "version": version},
                                           {"$set": sets, "$push": {"state_history": step}})
    if not res.matched_count:
        logger.warning("spt proposals: %s %s -> %s lost a race (state or version changed)", doc["_id"], frm, to_state)
        return None
    await _emit(db, "PROPOSAL_STATE_CHANGED", doc, f"proposal:{doc['_id']}:state:{version + 1}:{to_state}",
                {"proposal_id": doc["_id"], "opportunity_id": doc.get("opportunity_id"), "from": frm, "to": to_state,
                 "reason": reason, "actor": actor, "version": version + 1})
    return await db[C.PROPOSALS].find_one({"_id": doc["_id"]})


async def annotate(db, doc: Dict[str, Any], fields: Dict[str, Any], *, now: datetime,
                   push: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Record a calculation (sizing, allocation, risk) on the proposal without changing its state: conditional on the
    version, which it increments. None when another writer moved the proposal first."""
    version = int(doc.get("version") or 1)
    update: Dict[str, Any] = {"$set": {**fields, "version": version + 1, "updated_at": _iso(now)}}
    if push:
        update["$push"] = push
    res = await db[C.PROPOSALS].update_one({"_id": doc["_id"], "state": doc["state"], "version": version}, update)
    if not res.matched_count:
        return None
    return await db[C.PROPOSALS].find_one({"_id": doc["_id"]})


def public(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What a client sees: the proposal without the internal state version counter's noise kept intact (it is useful
    for audit), `_id` named proposal_id."""
    if doc is None:
        return None
    out = dict(doc)
    out["proposal_id"] = out.pop("_id", out.get("proposal_id"))
    return out


def approval_expiry(now: datetime, config: Dict[str, Any], doc: Dict[str, Any]) -> datetime:
    """When an approval request lapses: now + approval_expiry_minutes, never past the session close nor the
    opportunity's window/expiry (WF §11.2)."""
    cands = [now + timedelta(minutes=int(config["extras"]["approval_expiry_minutes"])), session_close(now)]
    opp = doc.get("opportunity") or {}
    end = _earliest(opp.get("window_until"), opp.get("expires_at"))
    if end is not None:
        cands.append(end)
    return min(cands)
