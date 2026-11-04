"""The SPT slice-B pipeline: QUALIFIED opportunity → proposal → sizing → allocation → risk → by the account's mode
(WF §7-§11, §18; DESIGN.md §2, §4, §5). Nothing here talks to a broker: an order is a simulated paper order (slice C).

THE LOOP (start()/stop(), wired by the integrator): every LOOP_S seconds in the NSE session (09:15-15:30 IST, weekdays),
on the worker holding the leader lock `nivesh:spt:b:leader` (scan_builder.signals.get_store().lead, the scan dashboard's
own lock store), one round (`run_round`):
    1. the users whose SPT config mode is tracking / approval / auto (mode `off`, the default, is never touched: D4)
    2. the QUALIFIED opportunities (slice A, `services.spt.opportunities.store.list_by_state`)
    3. per user, the opportunities with no proposal for that user, RANKED (allocation.rank: opportunity_score, then
       R:R, then liquidity), each: live price → proposal (proposals.create, idempotent per (user, opportunity)) →
       AWAITING_RISK → sizing → allocation (with what this round already took) → risk (risk.evaluate) → by mode:
         auto      reserve (service.enter, reserve=True) → RISK_APPROVED → READY_FOR_ORDER → slice C
                   create_entry_order(order_id = the reservation's trade_id, idempotency_key "spt:<user>:<opp>:entry")
                   → ORDER_CREATED. A failed create releases the reservation (service.release_unused) unless the order
                   turns out to exist, records why on the proposal and in spt_state, and is NOT retried (a retry could
                   duplicate an order whose create landed after a timeout).
         approval  a recorded decision WITHOUT a reservation (TESTCASES DB-1) → RISK_APPROVED → AWAITING_USER_APPROVAL
                   with approval.expires_at = min(now + approval_expiry_minutes, the session close, the opportunity's
                   window / expiry). POST /api/v1/opportunities/{id}/approve re-validates and re-runs the risk service
                   with a reservation (`approve`).
         tracking  a dry-run decision (TESTCASES DB-2) → RISK_APPROVED → TRACKING_ONLY. Nothing is reserved or ordered.
    4. the approval expiry sweep (`expire_approvals`)
    5. spt_state {_id: "spt_b"}: the last round, its counts and its errors (the morning check reads it)
A refused proposal ends REJECTED (the trade: no plan, R:R, liquidity) or BLOCKED_BY_RISK (the account / portfolio);
a proposal is never re-proposed for the same (user, opportunity). No fresh live price → nothing is written for that
opportunity this round (tried again next round). A price at or below the plan's stop expires the opportunity
market-wide through slice A's `transition` (the only write B makes to spt_opportunities).

ENABLED where APP_ENV=staging or SPT_B_ENABLED=1; SPT_B_ENABLED=0 turns it off everywhere.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import desk_trading as desk
from services.risk_gate import inputs
from services.risk_gate import service

from . import allocation, constants as C, events, policy, proposals, risk, sizing

logger = logging.getLogger(__name__)

SOURCE = "spt.pipeline"
STATE_ID = "spt_b"
LEADER_KEY = "nivesh:spt:b:leader"
LEADER_TTL_S = 90
LOOP_S = 30.0
IDLE_S = 60.0
MAX_ERRORS_KEPT = 20
ACTIVE_MODES = (C.MODE_TRACKING, C.MODE_APPROVAL, C.MODE_AUTO)
HOW_BY_MODE = {C.MODE_AUTO: "reserve", C.MODE_APPROVAL: "record", C.MODE_TRACKING: "dry"}

_ME = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
_task: Optional[asyncio.Task] = None


class PipelineError(RuntimeError):
    """A refused request (approve / reject): the route answers `status` with {code, message, ...detail}."""

    def __init__(self, code: str, message: str, *, status: int = 409, **detail: Any) -> None:
        super().__init__(message)
        self.code, self.status, self.extra = code, status, detail

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.extra}


# ── the other slices' interfaces (DESIGN §4), imported when used so tests replace them ──
def opportunity_store():
    from services.spt.opportunities import store            # slice A
    return store


def paper_orders():
    from services.spt.paper import orders                   # slice C
    return orders


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("SPT_B_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def in_session(now: datetime) -> bool:
    ist = now.astimezone(proposals.IST)
    return ist.weekday() < 5 and (9, 15) <= (ist.hour, ist.minute) < proposals.SESSION_CLOSE


async def _emit(db, event_type: str, prop: Dict[str, Any], key: str, payload: Dict[str, Any]) -> None:
    await events.emit(db, event_type, idempotency_key=key, source_service=SOURCE, payload=payload,
                      correlation_id=prop["_id"], account_id=prop["user_id"], instrument_id=prop.get("symbol"))


# ── one proposal's calculations ──────────────────────────────────────────────
async def adv_of(opp: Optional[Dict[str, Any]], symbol: str, now: datetime) -> Dict[str, Any]:
    """The 20-session average daily traded value: slice A's validation figure when it has one, else the risk service's
    own input (risk_gate.inputs.instrument). {adv_rs, source}."""
    liq = (((opp or {}).get("validation") or {}).get("liquidity") or {})
    if isinstance(liq.get("adv_rs"), (int, float)) and not isinstance(liq.get("adv_rs"), bool):
        return {"adv_rs": float(liq["adv_rs"]), "source": "opportunity validation (slice A)"}
    from services import data_freshness as fresh
    inst = await inputs.instrument(symbol, fresh.ist_today(now))
    return {"adv_rs": inst.get("adv_rs"), "source": inst.get("source") or inputs.BARS_SOURCE, "error": inst.get("error")}


def size_proposal(prop: Dict[str, Any], state: Dict[str, Any], config: Dict[str, Any], adv: Dict[str, Any]) -> Dict[str, Any]:
    """The sizing (sizing.size) of a proposal against the account state."""
    limits = ((state.get("profile") or {}).get("limits")) or {}
    if state.get("error") or not limits:
        return sizing.size(equity_rs=None, risk_pct=None, entry=prop["entry"]["price"], stop=prop["stop_loss"])
    eff = policy.effective_risk_pct(config, prop.get("horizon") or "positional", limits, state.get("ladder"))
    ex = config["extras"]
    out = sizing.size(equity_rs=state.get("equity_rs"), risk_pct=eff["pct"], entry=prop["entry"]["price"],
                      stop=prop["stop_loss"], adv_rs=adv.get("adv_rs"), min_adv_rs=ex["min_adv_rs"],
                      max_adv_participation_pct=ex["max_adv_participation_pct"],
                      max_position_pct=limits["max_position_pct"], available_rs=state.get("available_rs"),
                      reserve_rs=state.get("reserve_rs") or 0.0, profile_per_trade_pct=limits["per_trade_risk_pct"],
                      stressed_gap_pct=ex["stressed_gap_pct"], model=desk.COST_MODEL)
    out["risk_pct"] = eff
    out["adv_source"] = adv.get("source")
    return out


async def candidate_of(prop: Dict[str, Any], sz: Dict[str, Any], adv: Dict[str, Any]) -> Dict[str, Any]:
    q = int(sz.get("quantity") or 0)
    sec = await inputs.sector_of(prop["symbol"])
    gap = float(sz["inputs"].get("stressed_gap_pct") or 0.0)
    per = (sz["stressed_risk"] / q) if q else sizing.stressed_per_share(prop["entry"]["price"], prop["stop_loss"],
                                                                        sz.get("cost_per_share") or 0.0, gap)
    return {"proposal_id": prop.get("_id"), "symbol": prop["symbol"], "sector": sec.get("sector"),
            "sector_error": sec.get("error"), "category": allocation.category_of(prop.get("horizon"), prop.get("instrument")),
            "entry": float(prop["entry"]["price"]), "quantity": q, "stressed_per_share": per,
            "opportunity_score": (prop.get("opportunity") or {}).get("opportunity_score"),
            "rr": (prop.get("rr") or {}).get("t2"), "adv_rs": adv.get("adv_rs")}


def _allocation_record(al: Dict[str, Any], cand: Dict[str, Any]) -> Dict[str, Any]:
    return {**al, "candidate": {k: cand.get(k) for k in ("symbol", "sector", "category", "entry", "quantity",
                                                        "stressed_per_share", "opportunity_score", "rr", "adv_rs")}}


def _spt_refusal(prop: Dict[str, Any], state: Dict[str, Any], decision: str, reasons: List[Dict[str, Any]],
                 now: datetime, stage: str) -> Dict[str, Any]:
    """A decision record for a proposal refused before the risk service (sizing or allocation)."""
    return {"decision_id": str(uuid.uuid4()), "at": _iso(now), "decision": decision, "stage": stage,
            "account_id": prop["user_id"], "proposal_id": prop["_id"], "opportunity_id": prop.get("opportunity_id"),
            "symbol": prop.get("symbol"), "requested_qty": 0, "approved_qty": 0, "reservation_id": None,
            "risk_service_decision_id": None, "dry_run": False,
            "reason_codes": [r.get("code") for r in reasons], "explanations": [r.get("message") for r in reasons],
            "reasons": reasons, "portfolio_risk_before_rs": state.get("open_risk_rs"),
            "exposure_before_rs": state.get("exposure_rs"),
            "policy_versions": {"spt_risk": C.SPT_RISK_VERSION, "sizing": C.SIZING_VERSION,
                                "allocation": C.ALLOCATION_VERSION,
                                "config_version": (state.get("config") or {}).get("version"),
                                "limits_version": (state.get("profile") or {}).get("limits_version")}}


async def evaluate_proposal(db, prop: Dict[str, Any], *, state: Dict[str, Any], config: Dict[str, Any],
                            price: Dict[str, Any], opp: Optional[Dict[str, Any]], how: str, actor_id: str,
                            now: datetime, consumed: Optional[Dict[str, Any]] = None, emit: bool = True,
                            ) -> Dict[str, Any]:
    """Sizing → allocation → risk for a proposal (no state change). {sizing, allocation, risk, candidate, order_id}."""
    adv = await adv_of(opp, prop["symbol"], now)
    sz = size_proposal(prop, state, config, adv)
    if emit:
        await _emit(db, "POSITION_SIZE_CALCULATED", prop, f"proposal:{prop['_id']}:size:{sz['inputs_hash'][:24]}",
                    {"proposal_id": prop["_id"], "quantity": sz["quantity"], "capital_required": sz["capital_required"],
                     "planned_risk": sz["planned_risk"], "stressed_risk": sz["stressed_risk"], "steps": sz["steps"],
                     "blocked": sz["blocked"], "version": C.SIZING_VERSION})
    if sz["quantity"] < 1:
        codes = {b["code"] for b in sz["blocked"]}
        decision = C.RISK_BLOCKED if codes & {"equity_unknown"} or state.get("error") else C.RISK_REJECT
        return {"sizing": sz, "allocation": None, "candidate": None, "order_id": None,
                "risk": _spt_refusal(prop, state, decision, sz["blocked"] or [{"code": "sized_to_zero",
                                                                              "message": "No whole share fits."}],
                                     now, "sizing")}
    cand = await candidate_of(prop, sz, adv)
    al = allocation.allocate(state, cand, consumed)
    rec_al = _allocation_record(al, cand)
    if emit:
        await _emit(db, al["decision"], prop, f"proposal:{prop['_id']}:allocation:{sz['inputs_hash'][:16]}:"
                                               f"{al['decision']}:{al['quantity']}",
                    {"proposal_id": prop["_id"], "decision": al["decision"], "requested_qty": al["requested_qty"],
                     "quantity": al["quantity"], "reasons": al["reasons"], "room": al["room"],
                     "version": C.ALLOCATION_VERSION})
    if al["decision"] == "ALLOCATION_REJECTED":
        return {"sizing": sz, "allocation": rec_al, "candidate": cand, "order_id": None,
                "risk": _spt_refusal(prop, state, C.RISK_BLOCKED, al["reasons"], now, "allocation")}
    order_id = str(uuid.uuid4()) if how == "reserve" else None
    rec = await risk.evaluate(db, user_id=prop["user_id"], proposal=prop, state=state, quantity=al["quantity"],
                              stressed_risk=al.get("stressed_risk_rs"), price=price, actor_id=actor_id, how=how,
                              order_id=order_id, now=now, emit=emit)
    return {"sizing": sz, "allocation": rec_al, "candidate": cand, "risk": rec, "order_id": order_id}


def _state_after_risk(decision: str) -> str:
    if decision in risk.APPROVED:
        return C.PROP_RISK_APPROVED
    if decision == C.RISK_REJECT:
        return C.PROP_REJECTED
    return C.PROP_BLOCKED_BY_RISK


async def _record_and_move(db, prop: Dict[str, Any], ev: Dict[str, Any], now: datetime, *, actor: str) -> Dict[str, Any]:
    """Store sizing / allocation / risk on the proposal and move it to the state the risk decision gives."""
    rec = ev["risk"]
    fields = {"sizing": ev["sizing"], "allocation": ev["allocation"], "risk": rec}
    if ev.get("order_id") and rec["decision"] in risk.APPROVED:
        fields["order_id"] = ev["order_id"]
    to = _state_after_risk(rec["decision"])
    moved = await proposals.transition(db, prop, to, reason=f"{rec['decision']}: " + (", ".join(rec["reason_codes"][:4])
                                                                                       or "all checks passed"),
                                       now=now, extra=fields, actor=actor)
    if moved is not None:
        await db[C.PROPOSALS].update_one({"_id": prop["_id"]}, {"$push": {"risk_history": rec}})
        moved["risk_history"] = (moved.get("risk_history") or []) + [rec]
    return moved or prop


# ── order creation (slice C) ─────────────────────────────────────────────────
def _order_args(prop: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    e = prop["entry"]
    return {"user_id": prop["user_id"], "proposal_id": prop["_id"], "opportunity_id": prop["opportunity_id"],
            "risk_decision": rec.get("risk_service_decision") or {}, "symbol": prop["symbol"], "side": "BUY",
            "order_type": e["type"], "quantity": int(rec["approved_qty"]),
            "limit_price": e.get("limit_price") if e["type"] == "LIMIT" else None, "trigger_price": None,
            "time_in_force": e.get("time_in_force") or "DAY", "expires_at": e.get("expires_at"),
            "exit_plan": prop.get("exit_plan"),
            "idempotency_key": f"spt:{prop['user_id']}:{prop['opportunity_id']}:entry", "order_id": rec["order_id"]}


async def create_order(db, prop: Dict[str, Any], now: datetime, report: Optional[Dict[str, Any]] = None
                       ) -> Dict[str, Any]:
    """READY_FOR_ORDER → slice C's create_entry_order → ORDER_CREATED. On a failure the reservation is released unless
    the order exists after all; the error stays on the proposal (state READY_FOR_ORDER, `order_error`), not retried."""
    rec = prop["risk"]
    order_id = rec["order_id"]
    args = _order_args(prop, rec)
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        order = await paper_orders().create_entry_order(db, **args)
    except Exception as e:  # noqa: BLE001 — judged below: the order may still exist (a timeout after the insert)
        error = type(e).__name__
        logger.warning("spt pipeline: create_entry_order failed for proposal %s (%s)", prop["_id"], error)
        order = await db[C.ORDERS].find_one({"_id": order_id})
    if order is not None and order.get("_id", order.get("order_id")) not in (order_id, None):
        # An earlier order holds this idempotency key: the reservation taken for `order_id` backs nothing.
        await service.release_unused(db, prop["user_id"], {"reservation_id": rec.get("reservation_id")},
                                     reason="spt: the entry order already existed under another id")
        logger.warning("spt pipeline: proposal %s matched an existing order %s", prop["_id"], order.get("_id"))
    if order is None:
        released = await service.release_unused(db, prop["user_id"], {"reservation_id": rec.get("reservation_id")},
                                                 reason=f"spt: create_entry_order failed ({error or 'no order'})")
        info = {"at": _iso(now), "error": error or "no order returned", "reservation_released": bool(released),
                "retried": False}
        if report is not None:
            report["errors"].append({"proposal_id": prop["_id"], "stage": "create_entry_order", **info})
        return await proposals.annotate(db, prop, {"order_error": info}, now=now) or prop
    oid = order.get("_id", order.get("order_id"))
    summary = {"order_id": oid, "state": order.get("state"), "order_type": order.get("order_type"),
               "quantity": order.get("quantity"), "created_at": order.get("created_at")}
    moved = await proposals.transition(db, prop, C.PROP_ORDER_CREATED, reason=f"paper order {oid} created", now=now,
                                       extra={"order": summary, "order_id": oid, "order_created_at": _iso(now)})
    return moved or prop


# ── the round ────────────────────────────────────────────────────────────────
async def _expire_opportunity(db, opp_id: str, reason: str) -> None:
    try:
        await opportunity_store().transition(db, opp_id, expect_states=[C.OPP_QUALIFIED], to_state=C.OPP_EXPIRED,
                                             reason=reason)
    except Exception as e:  # noqa: BLE001 — the proposal's refusal stands; slice A's revalidation also expires it
        logger.warning("spt pipeline: opportunity %s not expired (%s)", opp_id, type(e).__name__)


async def process_one(db, *, user_id: str, config: Dict[str, Any], state: Dict[str, Any], opp: Dict[str, Any],
                      price: Dict[str, Any], now: datetime, consumed: Dict[str, Any], report: Dict[str, Any],
                      ) -> Optional[Dict[str, Any]]:
    try:
        prop, created = await proposals.create(db, user_id, opp, price, config, now)
    except proposals.PriceUnavailable as e:
        report["skipped"][e.code] = report["skipped"].get(e.code, 0) + 1
        return None
    if not created:
        return prop
    report["proposals"] += 1
    if prop["state"] in proposals.TERMINAL:
        report["refused"] += 1
        if prop.get("opp_invalidated"):
            await _expire_opportunity(db, opp["_id"], "plan invalidated: the live price is at or below the stop (slice B)")
        return prop
    moved = await proposals.transition(db, prop, C.PROP_AWAITING_RISK, reason="sizing, allocation and risk", now=now)
    if moved is None:
        return prop
    prop = moved
    mode = config["mode"]
    how = HOW_BY_MODE[mode]
    ev = await evaluate_proposal(db, prop, state=state, config=config, price=price, opp=opp, how=how,
                                 actor_id=risk.PIPELINE_ACTOR, now=now, consumed=consumed)
    prop = await _record_and_move(db, prop, ev, now, actor=risk.PIPELINE_ACTOR)
    rec = ev["risk"]
    if rec["decision"] not in risk.APPROVED:
        report["refused"] += 1
        return prop
    allocation.consume(consumed, ev["candidate"], {"quantity": rec["approved_qty"]})
    if mode == C.MODE_TRACKING:
        return await proposals.transition(db, prop, C.PROP_TRACKING_ONLY, reason="tracking mode: no order",
                                          now=now, actor=risk.PIPELINE_ACTOR) or prop
    if mode == C.MODE_APPROVAL:
        exp = proposals.approval_expiry(now, config, prop)
        report["awaiting_approval"] += 1
        return await proposals.transition(
            db, prop, C.PROP_AWAITING_USER, reason="approval mode: waiting for the user", now=now, actor=risk.PIPELINE_ACTOR,
            extra={"approval": {"requested_at": _iso(now), "expires_at": _iso(exp), "decided_at": None,
                                "decided_by": None, "decision": None}}) or prop
    ready = await proposals.transition(db, prop, C.PROP_READY_FOR_ORDER, reason="auto mode", now=now,
                                       actor=risk.PIPELINE_ACTOR, extra={"order_day": state["day"]})
    if ready is None:
        await service.release_unused(db, user_id, {"reservation_id": rec.get("reservation_id")},
                                     reason="spt: the proposal moved before its order was created")
        return prop
    out = await create_order(db, ready, now, report)
    if out.get("state") == C.PROP_ORDER_CREATED:
        report["orders"] += 1
    return out


async def process_user(db, config: Dict[str, Any], qualified: List[Dict[str, Any]], prices: Dict[str, Dict[str, Any]],
                       now: datetime, report: Dict[str, Any]) -> None:
    user_id = config["user_id"]
    ids = [o["_id"] for o in qualified]
    have = {p["opportunity_id"] for p in await db[C.PROPOSALS].find(
        {"user_id": user_id, "opportunity_id": {"$in": ids}}).to_list(len(ids) + 1)} if ids else set()
    new = [o for o in qualified if o["_id"] not in have]
    if not new:
        return
    state = await allocation.account_state(db, user_id, now=now, config=config)
    pre = []
    for o in new:
        px = prices.get(str(o.get("symbol") or "").upper()) or proposals.price_from_quote(None, now)
        b = proposals.build(o, px, config, now)
        pre.append({"opp": o, "price": px, "symbol": o.get("symbol"),
                    "opportunity_score": ((o.get("validation") or {}).get("opportunity_score")),
                    "rr": (b.get("rr") or {}).get("t2"),
                    "adv_rs": (((o.get("validation") or {}).get("liquidity") or {}).get("adv_rs"))})
    consumed = allocation.empty_consumed()
    for c in allocation.rank(pre):
        await process_one(db, user_id=user_id, config=config, state=state, opp=c["opp"], price=c["price"], now=now,
                          consumed=consumed, report=report)


def new_report(now: datetime) -> Dict[str, Any]:
    return {"at": _iso(now), "users": 0, "qualified": 0, "proposals": 0, "refused": 0, "orders": 0,
            "awaiting_approval": 0, "expired_approvals": 0, "skipped": {}, "errors": []}


async def run_round(db, now: datetime) -> Dict[str, Any]:
    """One round (module docstring). Returns the round's report (also written to spt_state)."""
    report = new_report(now)
    configs = await policy.users_in_modes(db, ACTIVE_MODES)
    report["users"] = len(configs)
    if configs:
        qualified = await opportunity_store().list_by_state(db, [C.OPP_QUALIFIED])
        report["qualified"] = len(qualified)
        symbols = sorted({str(o.get("symbol") or "").upper() for o in qualified if o.get("symbol")})
        prices = await proposals.read_prices(symbols, now) if symbols else {}
        for cfg in configs:
            try:
                await process_user(db, cfg, qualified, prices, now, report)
            except Exception as e:  # noqa: BLE001 — one user's failure never stops the others; logged and reported
                logger.warning("spt pipeline: user %s failed (%s)", cfg.get("user_id"), type(e).__name__)
                report["errors"].append({"user_id": cfg.get("user_id"), "stage": "process_user", "error": type(e).__name__})
    try:
        report["expired_approvals"] = await expire_approvals(db, now)
    except Exception as e:  # noqa: BLE001 — retried next round
        logger.warning("spt pipeline: the approval expiry sweep failed (%s)", type(e).__name__)
        report["errors"].append({"stage": "expire_approvals", "error": type(e).__name__})
    await write_state(db, report)
    return report


async def write_state(db, report: Dict[str, Any], *, leader: str = _ME) -> None:
    try:
        await db[C.STATE].update_one(
            {"_id": STATE_ID},
            {"$set": {"last_round": report, "last_round_at": report["at"], "leader": leader,
                      "errors": report["errors"][-MAX_ERRORS_KEPT:], "updated_at": report["at"]}}, upsert=True)
    except Exception as e:  # noqa: BLE001 — the state row is a record for the morning check, not a gate
        logger.warning("spt pipeline: spt_state not written (%s)", type(e).__name__)


async def loop_once(now: datetime, *, db=None, store: Any = None, me: str = _ME) -> bool:
    """One round when in the session and holding the leader lock. True if it ran."""
    if not in_session(now):
        return False
    if store is None:
        from services.scan_builder import signals as sb
        store = sb.get_store()
    if not await store.lead(LEADER_KEY, me, LEADER_TTL_S, time.time()):
        return False
    if db is None:
        from deps import db as app_db
        db = app_db
    await run_round(db, now)
    return True


async def _loop() -> None:
    while True:
        try:
            ran = await loop_once(datetime.now(timezone.utc))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one failed round never stops the loop; logged with its trace
            logger.exception("spt pipeline: a round failed")
            ran = False
        await asyncio.sleep(LOOP_S if ran or in_session(datetime.now(timezone.utc)) else IDLE_S)


def start() -> bool:
    """Start the loop on this worker when enabled (server startup). True if started."""
    global _task
    if not enabled() or (_task is not None and not _task.done()):
        return False
    _task = asyncio.get_running_loop().create_task(_loop())
    logger.info("spt pipeline: loop started (every %.0f s in the session, one leader across workers)", LOOP_S)
    return True


def stop() -> None:
    if _task is not None and not _task.done():
        _task.cancel()


# ── approval mode ────────────────────────────────────────────────────────────
async def _expire(db, prop: Dict[str, Any], now: datetime, codes: List[str], text: str, *, actor: str,
                  risk_rec: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rid = (prop.get("risk") or {}).get("reservation_id")
    if rid:                                  # none in this release (DB-1); released if a future change ever holds one
        await service.release_unused(db, prop["user_id"], {"reservation_id": rid}, reason="spt: approval expired")
    approval = {**(prop.get("approval") or {}), "decided_at": _iso(now), "decided_by": actor, "decision": "expired",
                "reason_codes": codes, "text": text}
    extra: Dict[str, Any] = {"approval": approval}
    if risk_rec is not None:
        extra["risk"] = risk_rec
    moved = await proposals.transition(db, prop, C.PROP_APPROVAL_EXPIRED, reason=f"{', '.join(codes)}: {text}", now=now,
                                       actor=actor, extra=extra)
    if moved is not None and risk_rec is not None:
        await db[C.PROPOSALS].update_one({"_id": prop["_id"]}, {"$push": {"risk_history": risk_rec}})
    return moved


async def expire_approvals(db, now: datetime, *, user_id: Optional[str] = None) -> int:
    """AWAITING_USER_APPROVAL past approval.expires_at → APPROVAL_EXPIRED (a recorded reservation is released)."""
    q: Dict[str, Any] = {"state": C.PROP_AWAITING_USER, "approval.expires_at": {"$lte": _iso(now)}}
    if user_id:
        q["user_id"] = user_id
    n = 0
    for prop in await db[C.PROPOSALS].find(q).to_list(500):
        if await _expire(db, prop, now, ["approval_window_passed"], "The approval window passed.", actor="spt_expiry"):
            n += 1
    return n


async def approve(db, *, user_id: str, opportunity_id: str, now: datetime) -> Dict[str, Any]:
    """The user approves their AWAITING proposal for `opportunity_id`. Re-validates (not expired, the opportunity still
    QUALIFIED, a fresh price inside the entry range) and ALWAYS re-runs sizing, allocation and the risk service with a
    reservation (WF §11.2; TESTCASES DB-1), then creates the paper order. A failed re-validation expires the proposal
    (APPROVAL_EXPIRED) and raises PipelineError 409; no approval can override a hard limit (WF §10.4)."""
    prop = await proposals.for_opportunity(db, user_id, opportunity_id)
    if prop is None:
        raise PipelineError("proposal_not_found", "You have no proposal for this opportunity.", status=404)
    if prop["state"] in (C.PROP_ORDER_CREATED, C.PROP_READY_FOR_ORDER) and (prop.get("approval") or {}).get("decision") == "approved":
        return {"proposal": prop, "idempotent": True}
    if prop["state"] != C.PROP_AWAITING_USER:
        raise PipelineError("invalid_state", f"The proposal is {prop['state']}, not awaiting your approval.",
                            state=prop["state"])
    config = await policy.read(db, user_id)
    if config["mode"] not in (C.MODE_APPROVAL, C.MODE_AUTO):
        raise PipelineError("spt_mode_not_trading", f"The account's SPT mode is {config['mode']}; set approval or auto "
                                                     f"to place paper orders.", mode=config["mode"])

    async def lapse(codes: List[str], text: str, risk_rec: Optional[Dict[str, Any]] = None, *, code: str) -> None:
        await _expire(db, prop, now, codes, text, actor=user_id, risk_rec=risk_rec)
        raise PipelineError(code, text, reason_codes=codes, decision=(risk_rec or {}).get("decision"))

    exp = proposals._dt((prop.get("approval") or {}).get("expires_at"))
    if exp is None or now >= exp:
        await lapse(["approval_window_passed"], "The approval window has passed; the proposal expired.",
                    code="approval_expired")
    opp = await opportunity_store().get(db, opportunity_id)
    if opp is None or opp.get("state") != C.OPP_QUALIFIED:
        await lapse(["opportunity_not_qualified"], f"The opportunity is {(opp or {}).get('state') or 'gone'}, no longer "
                                                   f"QUALIFIED.", code="approval_expired")
    sym = prop["symbol"]
    price = (await proposals.read_prices([sym], now)).get(sym) or proposals.price_from_quote(None, now)
    if not price.get("ok"):
        await lapse([price.get("reason") or "price_unavailable"], "Market data is not fresh, so the entry cannot be "
                                                                  "re-validated; the proposal expired.",
                    code="approval_expired")
    fresh_body = proposals.build(opp, price, config, now)
    if fresh_body["outcome"] != "ok":
        await lapse(fresh_body["reason_codes"], "; ".join(fresh_body["explanations"]), code="approval_expired")
    if prop["entry"]["type"] == "MARKET" and fresh_body["entry"]["type"] != "MARKET":
        await lapse(["price_outside_entry_range"],
                    f"The live price ₹{float(price['price']):,.2f} is above the entry range (≤ ₹"
                    f"{prop['entry']['chase_bound']:,.2f}); the approved immediate entry no longer holds.",
                    code="approval_expired")
    updated = dict(prop)
    if prop["entry"]["type"] == "MARKET":
        updated.update(entry=fresh_body["entry"], rr=fresh_body["rr"], price=price,
                       risk_per_share=fresh_body.get("risk_per_share"))
    else:
        updated.update(price=price)
    state = await allocation.account_state(db, user_id, now=now, config=config)
    ev = await evaluate_proposal(db, updated, state=state, config=config, price=price, opp=opp, how="reserve",
                                 actor_id=user_id, now=now)
    rec = ev["risk"]
    if rec["decision"] not in risk.APPROVED:
        await lapse(rec["reason_codes"] or ["risk_refused"],
                    "The risk engine refused the entry at approval: " + ("; ".join(rec["explanations"][:3]) or rec["decision"]),
                    rec, code="risk_refused")
    approval = {**(prop.get("approval") or {}), "decided_at": _iso(now), "decided_by": user_id, "decision": "approved"}
    ready = await proposals.transition(
        db, prop, C.PROP_READY_FOR_ORDER, reason="approved by the user; fresh risk " + rec["decision"], now=now,
        actor=user_id, extra={"approval": approval, "entry": updated["entry"], "rr": updated.get("rr"),
                              "price": price, "sizing": ev["sizing"], "allocation": ev["allocation"], "risk": rec,
                              "order_id": ev["order_id"], "order_day": state["day"]})
    if ready is None:
        await service.release_unused(db, user_id, {"reservation_id": rec.get("reservation_id")},
                                     reason="spt: the proposal moved while it was being approved")
        raise PipelineError("concurrent_change", "The proposal changed while it was being approved; reload it.")
    await db[C.PROPOSALS].update_one({"_id": prop["_id"]}, {"$push": {"risk_history": rec}})
    out = await create_order(db, ready, now)
    if out.get("state") != C.PROP_ORDER_CREATED:
        raise PipelineError("order_not_created", "The risk engine approved, but the paper order could not be created; "
                                                 "the reservation was released.", status=503,
                            order_error=out.get("order_error"))
    return {"proposal": out, "idempotent": False}


async def reject(db, *, user_id: str, opportunity_id: str, reason: Any, now: datetime) -> Dict[str, Any]:
    text = "" if reason is None else str(reason).strip()
    if not text:
        raise PipelineError("reason_required", "Say why the proposal is rejected (the reason is recorded).", status=422)
    if len(text) > policy.MAX_REASON:
        raise PipelineError("reason_too_long", f"The reason must be at most {policy.MAX_REASON} characters.", status=422)
    prop = await proposals.for_opportunity(db, user_id, opportunity_id)
    if prop is None:
        raise PipelineError("proposal_not_found", "You have no proposal for this opportunity.", status=404)
    if prop["state"] == C.PROP_USER_REJECTED:
        return {"proposal": prop, "idempotent": True}
    if prop["state"] != C.PROP_AWAITING_USER:
        raise PipelineError("invalid_state", f"The proposal is {prop['state']}, not awaiting your approval.",
                            state=prop["state"])
    rid = (prop.get("risk") or {}).get("reservation_id")
    if rid:
        await service.release_unused(db, user_id, {"reservation_id": rid}, reason="spt: rejected by the user")
    approval = {**(prop.get("approval") or {}), "decided_at": _iso(now), "decided_by": user_id, "decision": "rejected",
                "reason": text}
    moved = await proposals.transition(db, prop, C.PROP_USER_REJECTED, reason=f"rejected by the user: {text}", now=now,
                                       actor=user_id, extra={"approval": approval})
    if moved is None:
        raise PipelineError("concurrent_change", "The proposal changed meanwhile; reload it.")
    return {"proposal": moved, "idempotent": False}


# ── reads for the routes (no writes, except risk_book raising the equity peak as it always does) ──
async def recommendations(db, user_id: str, now: datetime) -> Dict[str, Any]:
    """The QUALIFIED opportunities ranked for this account with the size and risk they would get now. Writes nothing."""
    config = await policy.read(db, user_id)
    qualified = await opportunity_store().list_by_state(db, [C.OPP_QUALIFIED])
    symbols = sorted({str(o.get("symbol") or "").upper() for o in qualified if o.get("symbol")})
    prices = await proposals.read_prices(symbols, now) if symbols else {}
    state = await allocation.account_state(db, user_id, now=now, config=config)
    rows = []
    for o in qualified:
        px = prices.get(str(o.get("symbol") or "").upper()) or proposals.price_from_quote(None, now)
        b = proposals.build(o, px, config, now)
        existing = await proposals.for_opportunity(db, user_id, o["_id"])
        rows.append({"opp": o, "body": b, "price": px, "symbol": b["symbol"], "existing": existing,
                     "opportunity_score": (o.get("validation") or {}).get("opportunity_score"),
                     "rr": (b.get("rr") or {}).get("t2"),
                     "adv_rs": (((o.get("validation") or {}).get("liquidity") or {}).get("adv_rs"))})
    consumed = allocation.empty_consumed()
    out = []
    for r in allocation.rank(rows):
        b = r["body"]
        item = {"rank": r["rank"], "opportunity_id": r["opp"]["_id"], "symbol": r["symbol"],
                "opportunity_score": r["opportunity_score"], "rr": b.get("rr"), "entry": b.get("entry"),
                "stop_loss": b.get("stop_loss"), "target_1": b.get("target_1"), "target_2": b.get("target_2"),
                "price": r["price"], "outcome": b["outcome"], "reason_codes": b["reason_codes"],
                "explanations": b["explanations"],
                "proposal": ({"proposal_id": r["existing"]["_id"], "state": r["existing"]["state"]}
                             if r["existing"] else None), "sizing": None, "allocation": None}
        if b["outcome"] == "ok":
            pseudo = {**b, "_id": f"preview-{r['opp']['_id']}", "user_id": user_id, "opportunity_id": r["opp"]["_id"]}
            adv = await adv_of(r["opp"], b["symbol"], now)
            sz = size_proposal(pseudo, state, config, adv)
            item["sizing"] = {k: sz.get(k) for k in ("quantity", "capital_required", "planned_risk", "stressed_risk",
                                                      "cost_per_share", "steps", "blocked", "version", "risk_pct")}
            if sz["quantity"] > 0:
                cand = await candidate_of(pseudo, sz, adv)
                al = allocation.allocate(state, cand, consumed)
                allocation.consume(consumed, cand, al)
                item["allocation"] = {k: al.get(k) for k in ("decision", "requested_qty", "quantity", "reasons", "room",
                                                              "capital_rs", "stressed_risk_rs", "version")}
        out.append(item)
    return {"account_id": user_id, "as_of": _iso(now), "mode": config["mode"], "items": out,
            "rank_basis": "opportunity_score, then reward:risk at the entry, then average daily traded value",
            "writes": "none", "price_source": proposals.QUOTE_SOURCE}


async def recalculate(db, user_id: str, now: datetime) -> Dict[str, Any]:
    """Re-run sizing and allocation for the caller's AWAITING_USER_APPROVAL proposals (ranked, sharing the room), and
    record the new figures on each (state unchanged; risk is re-run at approval)."""
    config = await policy.read(db, user_id)
    awaiting = await proposals.list_for_user(db, user_id, states=[C.PROP_AWAITING_USER], limit=200)
    state = await allocation.account_state(db, user_id, now=now, config=config)
    consumed = allocation.empty_consumed()
    rows = [{"prop": p, "symbol": p["symbol"], "opportunity_score": (p.get("opportunity") or {}).get("opportunity_score"),
             "rr": (p.get("rr") or {}).get("t2"), "adv_rs": ((p.get("sizing") or {}).get("inputs") or {}).get("adv_rs")}
            for p in awaiting]
    out = []
    for r in allocation.rank(rows):
        p = r["prop"]
        adv = await adv_of(None, p["symbol"], now) if r["adv_rs"] is None else {"adv_rs": r["adv_rs"],
                                                                                 "source": "the proposal's sizing"}
        sz = size_proposal(p, state, config, adv)
        al: Optional[Dict[str, Any]] = None
        if sz["quantity"] > 0:
            cand = await candidate_of(p, sz, adv)
            al = _allocation_record(allocation.allocate(state, cand, consumed), cand)
            allocation.consume(consumed, cand, al)
        saved = await proposals.annotate(db, p, {"sizing": sz, "allocation": al, "recalculated_at": _iso(now)}, now=now)
        out.append({"proposal_id": p["_id"], "symbol": p["symbol"], "rank": r["rank"], "quantity": sz["quantity"],
                    "allocation": (al or {}).get("decision"), "allocated_qty": (al or {}).get("quantity"),
                    "recorded": saved is not None})
    return {"account_id": user_id, "as_of": _iso(now), "recalculated": out}


async def validate_trade(db, user_id: str, body: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """POST /risk/validate-trade: sizing, allocation and the risk checks as a DRY RUN — nothing recorded, nothing
    reserved, no proposal. `body`: {opportunity_id} (its plan at the live price), or {symbol, entry, stop_loss,
    target, quantity?} (a manual long cash entry, judged at the live price's freshness)."""
    config = await policy.read(db, user_id)
    opp = None
    if body.get("opportunity_id"):
        opp = await opportunity_store().get(db, str(body["opportunity_id"]))
        if opp is None:
            raise PipelineError("opportunity_not_found", "No such opportunity.", status=404)
        sym = str(opp.get("symbol") or "").upper()
        price = (await proposals.read_prices([sym], now)).get(sym) or proposals.price_from_quote(None, now)
        b = proposals.build(opp, price, config, now)
        if b["outcome"] != "ok":
            return {"dry_run": True, "outcome": b["outcome"], "reason_codes": b["reason_codes"],
                    "explanations": b["explanations"], "proposal": b}
        pseudo = {**b, "_id": f"dry-{uuid.uuid4()}", "user_id": user_id, "opportunity_id": opp["_id"]}
    else:
        sym = str(body.get("symbol") or "").strip().upper()
        e, s, t = (sizing._f(body.get(k)) for k in ("entry", "stop_loss", "target"))
        if not sym or e is None or s is None or t is None or not (0 < s < e < t):
            raise PipelineError("invalid_input", "Send opportunity_id, or symbol, entry, stop_loss and target with "
                                                 "stop_loss < entry < target.", status=422)
        price = (await proposals.read_prices([sym], now)).get(sym) or proposals.price_from_quote(None, now)
        pseudo = {"_id": f"dry-{uuid.uuid4()}", "user_id": user_id, "opportunity_id": None, "symbol": sym,
                  "horizon": "positional", "instrument": "cash",
                  "entry": {"type": "MARKET", "price": e, "basis": "as sent", "time_in_force": "DAY"},
                  "stop_loss": s, "target_1": None, "target_2": t,
                  "rr": {"t2": round((t - e) / (e - s), 4), "min_rr": float(config["extras"]["min_rr"]["positional"]),
                         "measured_to": "target_2"}, "opportunity": {}}
    state = await allocation.account_state(db, user_id, now=now, config=config)
    qty = body.get("quantity")
    if qty is not None:
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise PipelineError("invalid_input", "quantity must be a positive whole number.", status=422)
        adv = await adv_of(opp, sym, now)
        sz = size_proposal(pseudo, state, config, adv)
        cand = await candidate_of(pseudo, {**sz, "quantity": qty,
                                           "stressed_risk": sizing.stressed_per_share(
                                               pseudo["entry"]["price"], pseudo["stop_loss"], sz.get("cost_per_share") or 0.0,
                                               float(config["extras"]["stressed_gap_pct"])) * qty}, adv)
        al = allocation.allocate(state, cand)
        rec = await risk.evaluate(db, user_id=user_id, proposal=pseudo, state=state, quantity=qty,
                                  stressed_risk=cand["stressed_per_share"] * qty, price=price, actor_id=user_id,
                                  how="dry", order_id=None, now=now, emit=False)
        ev = {"sizing": sz, "allocation": _allocation_record(al, cand), "risk": rec}
    else:
        ev = await evaluate_proposal(db, pseudo, state=state, config=config, price=price, opp=opp, how="dry",
                                     actor_id=user_id, now=now, emit=False)
    return {"dry_run": True, "writes": "none: no risk_decisions row, no reservation, no proposal",
            "symbol": sym, "entry": pseudo["entry"], "stop_loss": pseudo["stop_loss"], "target": pseudo["target_2"],
            "rr": pseudo.get("rr"), "price": price, "sizing": ev["sizing"], "allocation": ev["allocation"],
            "risk": ev["risk"], "decision": ev["risk"]["decision"]}

