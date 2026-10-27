"""Smart trading desk — the user's own paper trades and price alerts (MongoDB). Nothing here places an order.

Every route is scoped to the signed-in user (`user_id` from deps.get_current_user): a trade or alert that is
not yours answers 404, the same as one that does not exist. Writes pass through the app's CSRF middleware like
every other /api write; nothing here is exempt.

Endpoints (all under /api/desk):
    POST   /paper-trades               — open a paper trade (long only)  → 201 {trade}
             {symbol, quantity, entry_price, stop_price, target_price|null, note?, source?: {kind, bucket?, signal_date?},
              entry_rule?: "at_once"|"break_above"|"pullback_to", entry_window_sessions?, max_hold_sessions?,
              signal_at?, strategy_version?, rationale?}       — PRD §13.4; costs, MFE / MAE and net P&L come back on reads
    GET    /paper-trades?status=open|closed|all
                                       — {as_of, checked_through, trades, summary, ...}; applies the exit rule first
    POST   /paper-trades  with kind "strategy" — a futures / option structure (services/desk_strategy_trades.py, rules
                                         desk-paper-v3): {kind, underlying, direction, family, reference_price, stop_underlying?,
                                         target_underlying?, legs[1-4], signal{signal_at, rule_version, evidence_summary, ...},
                                         strategy_plan_id?, max_hold_sessions?, note?}; the signal and legs are saved once, never edited
    GET    /paper-trades/{id}          — one trade with its lifecycle log (and, for a strategy, its signal); read-only
    POST   /paper-trades/{id}/close    — {exit_price?}: close at that price, or at the last end-of-day close ("manual");
                                         a trade whose conditional entry was not reached is "cancelled" (no P&L)
    GET    /paper-trades/{id}/roll     — preview of an F&O roll (services/fno_roll.py): both legs at session D's NSE
                                         bhavcopy close, the next listed expiry, costs; or the reason it cannot roll
    POST   /paper-trades/{id}/roll     — {strike_mode?}: close the old structure and open the same one on the next
                                         expiry at D's close, through the same risk checks as any entry; linked both ways
    GET    /trade-plans/{plan_id}      — a TradePlan with its lifecycle status derived from your trades, the versions you
                                         may open, your newest risk-service decision on it (`risk_decision`, or null), and
                                         the size the risk service would allow YOUR account (`account_size`, plan_sizing.py)
    POST   /alerts                     — {condition, ...the condition's fields, note?} → 201 {alert}
             above | below  {symbol, level}            filing    {symbol, impact?: "any"|"high"}
             category       {category, symbol?}        volume    {symbol, multiple}
             scanner        {symbol, stage?}           sector    {index, threshold_pct, direction?}
             risk           {symbol, level}            (rules and sources: services/desk_alerts.py)
    GET    /alerts?status=active|fired|all
                                       — {as_of, checked_through, alerts, conditions, check_errors, ...}; checks every
                                         active alert first. A fired alert carries `reason` and `evidence`
    DELETE /alerts/{id}                — 204
    GET    /paper-account/corrections  — your reconciliation corrections: reason, decision (exclude / void / ...), date,
                                         in force or reverted (services/paper_reconcile.corrections); read-only
    GET    /exit-job-status            — when exits were last checked and ok | running | late | missed, by the admin
                                         job-health rule (services/job_runs.trader_status); read-only, applies nothing
    GET    /idea-scorecard             — the Phase 4.3 study's committed results for the AI ideas' ranking
                                         (services/idea_scorecard.py); 503 when the committed files cannot be read

Limits: 100 open paper trades and 50 active alerts per user (409 open_trade_limit / active_alert_limit). An active
alert identical to one the user already has (same condition, stock, level and settings) is 409 duplicate_alert.

Entry fills (POST /paper-trades, cash): an `at_once` entry must lie inside the last completed session's low-high range
(422 entry_not_tradable with the range; 422 entry_unverifiable with no bar; 503 prices_unavailable when the bars cannot
be read). The whole fill model is written once, in services/desk_trading.py ("FILL MODEL").

Duplicates and retries (POST /paper-trades): a second OPEN cash trade in the same symbol is 409 duplicate_open_trade, an
identical open structure 409 duplicate_open_structure, each with `existing_trade_id` (adding to a position is not
supported yet). An `Idempotency-Key` header (8-64 characters, one per click; a retry reuses it) makes a repeated
submit answer 200 with the trade the first one made (`replayed: true`) and charge nothing; the same key with another
body is 409 idempotency_conflict. Every refusal of a create is recorded in `risk_decisions` (path desk_paper_trade).
Errors are HTTPException with a short code in `detail` (invalid_symbol, stop_not_below_entry, trade_not_found,
trade_already_closed, no_close_available, prices_unavailable, ...).

Prices are END-OF-DAY bars of raw traded prices (nidp.prices_eod through the data platform); the rules, the
series choice and the idempotent writes live in services/desk_trading.py, shared with the evening evaluator
scripts/check_desk_alerts.py. When the data platform cannot be read, the lists still answer with the stored
trades and alerts, marks null and `marks_error` set; a mark is never made up.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pymongo.errors import DuplicateKeyError

from deps import db, get_current_user
from services import desk_alerts as alerts_svc
from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import idea_scorecard as scorecard
from services import job_runs
from services import paper_account as acct
from services import paper_reconcile as reconcile
from services import risk_controls as rc
from services import risk_gate
from services.risk_gate import plan_sizing
from services.risk_gate import service as risk_service
from services import trade_lifecycle as lifecycle
from services import fno_roll as roll
from services.strategy_plan import trade_plan as tpm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desk", tags=["desk"])

#: The evening exit check's job name in services/job_runs (scripts/check_desk_alerts.py).
EXIT_JOB = "check_desk_alerts"

_ID_MAX = 64


async def _body(request: Request, *, allow_empty: bool = False) -> Any:
    raw = await request.body()
    if allow_empty and not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")


def _input_error(exc: svc.DeskInputError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.code)


def _sort_key(stamp_field: str):
    return lambda doc: str(doc.get(stamp_field) or "")


def _price_context() -> Dict[str, Any]:
    return {"source": svc.SOURCE, "price_basis": svc.PRICE_BASIS}


def _as_of(bars: Dict[str, List[Dict[str, Any]]]):
    """(newest session read, the session every symbol with prices has been read through)."""
    latest = [b["date"] for b in (svc.last_close(v) for v in bars.values()) if b]
    return svc.latest_day(latest), svc.earliest_day(latest)


# ── paper trades ─────────────────────────────────────────────────────────────
class _Refusals:
    """Every refusal of a paper-trade create is recorded before it is answered (risk_controls.record_decision, path
    "desk_paper_trade", the request's correlation id, the symbol and quantity when the body has them): the kill switch,
    a body the validator refuses, a duplicate, a replayed key with another body, funds and the open-trade cap. Before
    this only the kill switch was recorded, without a symbol or a correlation id (study A, Q6). The record is fail-open
    as record_decision documents: the refusal stands whether or not its row could be written."""

    def __init__(self, uid: str, cid: str) -> None:
        self.uid, self.cid = uid, cid
        self.symbol: Optional[str] = None
        self.quantity: Optional[int] = None
        self.plan_id: Optional[str] = None            # the TradePlan the request named, once it is known
        self.plan_state: Optional[str] = None

    def note(self, body: Any) -> None:
        if not isinstance(body, dict):
            return
        sym = body.get("symbol") if body.get("kind") != strat.KIND else body.get("underlying")
        self.symbol = sym.strip().upper()[:20] if isinstance(sym, str) and sym.strip() else None
        qty = body.get("quantity")
        self.quantity = int(qty) if isinstance(qty, (int, float)) and not isinstance(qty, bool) and float(qty).is_integer() else None

    async def refuse(self, status: int, detail: Any, *, code: Optional[str] = None,
                     text: Optional[str] = None) -> HTTPException:
        code = code or (detail if isinstance(detail, str) else detail.get("code"))
        text = text or (detail.get("message") if isinstance(detail, dict) else None) or code
        # Phase 2.2: a refused open is a REJECTED lifecycle event. There is no trade document to carry it, so it is
        # recorded on the refusal's own risk_decisions row and, when the request named a TradePlan, on the plan.
        rejected = lifecycle.rejection_record(frm=self.plan_state, reason=text, source="desk_paper_trade",
                                              at=svc.utcnow(), codes=[code], plan_id=self.plan_id)
        await rc.record_decision(db, self.uid, action="desk_paper_trade", outcome="blocked", symbol=self.symbol,
                                 requested_qty=self.quantity,
                                 reasons=[{"code": code, "text": text, "check": "request", "severity": "block"}],
                                 correlation_id=self.cid, path="desk_paper_trade",
                                 policy_version=risk_service.POLICY_VERSION, source="desk_validation",
                                 detail={"http_status": status, **(detail if isinstance(detail, dict) else {"code": detail}),
                                         "lifecycle": rejected})
        await self.plan_event(rejected)
        return HTTPException(status_code=status, detail=detail)

    def rejection(self, source: str = "desk_paper_trade") -> Dict[str, Any]:
        """The lifecycle context the risk service puts on the row of a refused open (Phase 2.2 REJECTED)."""
        return {"source": source, "plan_id": self.plan_id, "plan_state": self.plan_state}

    async def plan_event(self, rejected: Dict[str, Any]) -> None:
        if self.plan_id:
            try:
                await db[tpm.COLLECTION].update_one({"_id": self.plan_id}, {"$push": {"events": rejected}})
            except Exception as exc:  # noqa: BLE001 — fail-open like record_decision: the refusal stands, the miss is logged
                logger.error("desk: the REJECTED event for plan %s could not be written: %r", self.plan_id, exc)

    async def risk_refused(self, exc: HTTPException, source: str = "desk_paper_trade") -> None:
        """A refusal by the risk service: its row already carries the REJECTED event (rejection()); the plan gets it too,
        with the decision's id and codes."""
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if not self.plan_id or not detail.get("decision_id"):
            return
        codes = [r.get("code") for r in detail.get("reasons") or [] if r.get("severity") in risk_service.BLOCKING] \
            or [detail.get("code")]
        await self.plan_event(lifecycle.rejection_record(frm=self.plan_state, reason=str(detail.get("message")), source=source,
                                                         at=svc.utcnow(), codes=codes, plan_id=self.plan_id,
                                                         risk_decision_id=detail["decision_id"]))


async def _open_duplicate(uid: str, doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The user's OPEN trade this one would duplicate, or None: a cash trade in the same symbol (adding to a position
    is not supported yet, PRD §7), or a strategy with the same underlying and legs (strat.structure_key). Read by
    symbol, not by `open_key`, so a trade stored before that field existed (or written by the AI trader) counts too."""
    if doc.get("kind") == strat.KIND:
        same = await db[svc.TRADES].find({"user_id": uid, "status": "open", "kind": strat.KIND,
                                          "underlying": doc["underlying"]}).to_list(svc.MAX_OPEN_TRADES * 2)
        return next((d for d in same if strat.structure_key(d) == doc["open_key"]), None)
    same = await db[svc.TRADES].find({"user_id": uid, "status": "open", "symbol": doc["symbol"]}).to_list(svc.MAX_OPEN_TRADES * 2)
    return next((d for d in same if d.get("kind") != strat.KIND), None)


def _duplicate_detail(doc: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    if doc.get("kind") == strat.KIND:
        return {"code": "duplicate_open_structure", "existing_trade_id": existing["_id"], "symbol": doc["underlying"],
                "message": (f"You already have this structure open on {doc['underlying']} (paper trade {existing['_id']}, "
                            f"opened {existing.get('opened_at')}). Close it before recording it again.")}
    return {"code": "duplicate_open_trade", "existing_trade_id": existing["_id"], "symbol": doc["symbol"],
            "message": (f"You already have an open paper trade in {doc['symbol']} (paper trade {existing['_id']}, opened "
                        f"{existing.get('opened_at')}). Adding to a position is not supported yet; close it first.")}


async def _replay(ref: _Refusals, prior: Dict[str, Any], fingerprint: str, response: Response) -> Dict[str, Any]:
    """The answer to a request whose Idempotency-Key already made a trade: that trade (200, `replayed`), never a
    second one, and no second reservation. The same key with a different body is 409 idempotency_conflict."""
    if prior.get("request_fingerprint") != fingerprint:
        raise await ref.refuse(409, {"code": "idempotency_conflict", "existing_trade_id": prior["_id"],
                                     "message": "This Idempotency-Key was already used for a different paper trade; "
                                                "nothing new was recorded."})
    response.status_code = 200
    return {"trade": _public(prior), "replayed": True, **_price_context()}


def _entry_request(user: Dict[str, Any], cid: str, doc: Dict[str, Any], fno_additional: bool) -> risk_service.EntryRequest:
    """The universal risk service's request for a desk create: only what the user asked for (the instrument, the size,
    the levels); the service resolves everything else on the server."""
    common = dict(correlation_id=cid, user_id=doc["user_id"], actor_id=rc.session_actor(user), mode="paper",
                  path="desk_paper_trade", action="open", trade_id=doc["_id"], store=svc.TRADES,
                  cost_model=doc.get("cost_model"))
    if doc.get("kind") == strat.KIND:
        return risk_service.EntryRequest(**common, instrument="structure", symbol=doc["underlying"], legs=doc["legs"],
                                         direction=doc.get("direction"), reference_price=doc.get("reference_price"),
                                         stop_underlying=doc.get("stop_underlying"),
                                         target_underlying=doc.get("target_underlying"), fno_additional=fno_additional)
    return risk_service.EntryRequest(**common, instrument="cash", symbol=doc["symbol"], quantity=doc["quantity"],
                                     entry_price=doc["entry_price"], stop_price=doc["stop_price"],
                                     target_price=doc.get("target_price"))


@router.post("/paper-trades", status_code=201)
async def create_paper_trade(request: Request, response: Response) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    ref = _Refusals(uid, risk_gate.correlation_id(request))
    # The fno_risk_gate flag only rolls out ADDITIONAL F&O structure checks; every core risk check below runs for
    # everyone (services/risk_gate/service.py), so no flag can let an entry past them.
    fno_additional = await risk_gate.enabled_for(db, user)
    raw = await request.body()
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    ref.note(body)                      # read only for the refusal's record; nothing is validated or written yet
    if body is None:
        raise await ref.refuse(422, "invalid_body")
    # Idempotency (gate 2): a retried submit with the same key gets the trade its first attempt made, before any
    # check that could charge the account again.
    try:
        key = svc.clean_idempotency_key(request.headers.get(svc.IDEMPOTENCY_HEADER))
    except svc.DeskInputError as exc:
        raise await ref.refuse(422, exc.detail())
    fingerprint = svc.request_fingerprint(body)
    if key is not None:
        prior = await db[svc.TRADES].find_one({"user_id": uid, "idempotency_key": key})
        if prior is not None:
            return await _replay(ref, prior, fingerprint, response)
    plan_ref_raw = None
    if isinstance(body, dict) and "plan_ref" in body:
        body = dict(body)
        plan_ref_raw = body.pop("plan_ref")             # checked against the stored TradePlan below, never trusted as sent
    try:
        if isinstance(body, dict) and body.get("kind") == strat.KIND:
            doc = strat.new_strategy_trade(uid, body)
            # The desk's own 422 for a made-up lot size; the risk service checks the exchange lot again (core).
            await strat.check_exchange_lots(doc)
        else:
            if isinstance(body, dict) and "kind" in body:
                if body["kind"] != "cash":
                    raise svc.DeskInputError("invalid_kind")
                body = {k: v for k, v in body.items() if k != "kind"}
            doc = svc.new_trade(uid, body)
    except svc.DeskInputError as exc:
        raise await ref.refuse(422, exc.detail())
    if plan_ref_raw is not None:
        await _attach_plan(ref, uid, doc, plan_ref_raw)
    if doc.get("kind") == strat.KIND:
        _store_premium_levels(doc)
    doc["open_key"] = strat.structure_key(doc) if doc.get("kind") == strat.KIND else svc.open_key(doc)
    existing = await _open_duplicate(uid, doc)
    if existing is not None:
        raise await ref.refuse(409, _duplicate_detail(doc, existing))
    if doc.get("kind") != strat.KIND and doc["entry_rule"] == "at_once":
        # The fill model (services/desk_trading.py): an at-once entry is filled when recorded, so it must be a price the
        # last completed session traded. Without this a scanner pullback level 8-11% below the market was booked as
        # filled (FEDERALBNK 316.89 against 337.20-344.80). No bars, no fill: refused rather than assumed.
        try:
            bars = await svc.fetch_bars(doc["symbol"], svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS))
        except svc.PricesUnavailable as exc:
            logger.warning("desk: no end-of-day bars for %s to check an at-once entry: %s", doc["symbol"], exc)
            raise await ref.refuse(503, "prices_unavailable")
        try:
            doc["entry_range_checked"] = svc.check_entry_tradable(doc, bars)
        except svc.DeskInputError as exc:
            raise await ref.refuse(422, exc.detail())
    # THE risk decision (Phase 1): recorded first, then the funds and the risk budget reserved in one atomic update.
    # 409 risk_blocked / risk_reduce (nothing written, nothing reserved) or 503 risk_decision_unrecorded.
    try:
        decision = await risk_service.enforce(db, _entry_request(user, ref.cid, doc, fno_additional),
                                              rejection=ref.rejection())
    except HTTPException as exc:
        # A retry that raced its own first attempt: the first one's position now holds the symbol, so the service
        # refuses this one (already held). The client gets the trade its key already made, never a refusal of it.
        if key is not None:
            prior = await db[svc.TRADES].find_one({"user_id": uid, "idempotency_key": key})
            if prior is not None:
                return await _replay(ref, prior, fingerprint, response)
        await ref.risk_refused(exc)
        raise
    risk_service.stamp(doc, decision)
    doc["paper_reserved_rs"] = float(decision["budget"].get("funding_rs") or 0.0)
    if key is not None:
        doc["idempotency_key"] = key
        doc["request_fingerprint"] = fingerprint

    async def give_back(why: str) -> None:
        await risk_service.release_unused(db, uid, decision, reason=why)

    await svc.ensure_indexes(db)
    svc.open_lifecycle(doc)               # Phase 2.2: state + the opening events, with the risk decision id stamped above
    open_filter = {"user_id": uid, "status": "open"}
    if await db[svc.TRADES].count_documents(open_filter) >= svc.MAX_OPEN_TRADES:
        await give_back("open_trade_limit")
        raise await ref.refuse(409, "open_trade_limit")
    try:
        await db[svc.TRADES].insert_one(doc)
    except DuplicateKeyError:
        # Another request with this key, or another open trade in this symbol / structure, was written between the
        # checks above and this insert (the unique indexes, svc.ensure_indexes). Ours takes its reservation back.
        await give_back("duplicate key on insert")
        if key is not None:
            prior = await db[svc.TRADES].find_one({"user_id": uid, "idempotency_key": key})
            if prior is not None:
                return await _replay(ref, prior, fingerprint, response)
        existing = await _open_duplicate(uid, doc)
        if existing is not None:
            raise await ref.refuse(409, _duplicate_detail(doc, existing))
        raise
    except Exception:
        await give_back("insert failed")
        raise
    # Two requests that both counted 99 can both insert; the later count catches it and takes ours back.
    if await db[svc.TRADES].count_documents(open_filter) > svc.MAX_OPEN_TRADES:
        await db[svc.TRADES].delete_one({"_id": doc["_id"], "user_id": uid})
        await give_back("open_trade_limit")
        raise await ref.refuse(409, "open_trade_limit")
    logger.info("desk: user %s opened paper trade %s (%s)", uid, doc["_id"], doc["symbol"])
    return {"trade": _public(doc), "risk": risk_service.public(decision), **_price_context()}


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = strat.public_strategy_trade(doc, detail=True) if doc.get("kind") == strat.KIND else svc.public_trade(doc)
    return _with_lifecycle(out, doc)


_PLAN_REF_FIELDS = {"plan_id", "candidate_id", "rules_version"}


async def _attach_plan(ref: "_Refusals", uid: str, doc: Dict[str, Any], raw: Any) -> None:
    """Phase 2.1: a paper trade that names a TradePlan (`plan_ref {plan_id, candidate_id?, rules_version?}`) is recorded
    only at that plan's levels. The plan must exist and be readable by the user (404 plan_not_found), match the ref
    (409 plan_ref_mismatch), still pass revalidation and be tradeable (409 plan_not_eligible), and the request's levels
    must be the plan's (409 plan_levels_mismatch). The trade then stores `plan_ref`, `trade_plan_id` and the plan's
    levels as `plan_levels`."""
    if not isinstance(raw, dict) or set(raw) - _PLAN_REF_FIELDS or not isinstance(raw.get("plan_id"), str):
        raise await ref.refuse(422, {"code": "invalid_plan_ref", "message": "plan_ref must be {plan_id, candidate_id?, rules_version?}."})
    tp = await tpm.load(db, raw["plan_id"], uid)
    ref.plan_id = raw["plan_id"] if tp is not None else None
    if tp is None:
        raise await ref.refuse(404, {"code": "plan_not_found", "message": f"No trade plan {raw['plan_id'][:40]} that you can use."})
    ref.plan_state = (tp.get("eligibility") or {}).get("state")
    for k, have in (("candidate_id", (tp.get("strategy") or {}).get("candidate_id")), ("rules_version", tp.get("rules_version"))):
        if raw.get(k) is not None and raw[k] != have:
            raise await ref.refuse(409, {"code": "plan_ref_mismatch", "message": f"{k} {raw[k]} is not the plan's ({have})."})
    elig = tp.get("eligibility") or {}
    problems = tpm.validate({k: v for k, v in tp.items() if k != "_id"})
    if problems or not elig.get("paper_eligible"):
        why = [p["message"] for p in problems] or [r.get("message") or r.get("code") for r in elig.get("reasons") or []] \
            or [f"the plan's state is {elig.get('state')}"]
        raise await ref.refuse(409, {"code": "plan_not_eligible", "plan_id": tp["plan_id"], "state": elig.get("state"),
                                     "message": "This plan cannot be paper traded: " + "; ".join(str(w) for w in why[:5])})
    mism = tpm.strategy_mismatches(tp, doc) if doc.get("kind") == strat.KIND else tpm.cash_mismatches(tp, doc)
    if mism:
        raise await ref.refuse(409, {"code": "plan_levels_mismatch", "plan_id": tp["plan_id"], "mismatches": mism[:10],
                                     "message": "The request's levels are not the plan's: " + "; ".join(mism[:3])})
    doc["plan_ref"] = tpm.plan_ref_of(tp)
    doc["trade_plan_id"] = tp["plan_id"]
    doc["plan_levels"] = tpm.canonical_levels(tp)
    if doc.get("kind") == strat.KIND and (tp.get("exit_plan") or {}).get("options"):
        doc["exit_plan"] = {"options": tp["exit_plan"]["options"], "source": "trade_plan"}


def _store_premium_levels(doc: Dict[str, Any]) -> None:
    """Phase 2.6, storage only: the strategy-levels engine's premium stop and T1 / T2 (and the underlying levels they
    correspond to) are stored on the strategy trade at entry, from its own legs and the signal's data date. EVALUATING
    them is the exits branch's (feat/p2-exits-backtest): nothing here closes a trade on them."""
    if doc.get("exit_plan"):
        return
    legs = [{"kind": l["kind"], "side": l["side"], "quantity": l["lots"], "lot_size": l["lot_size"], "entry_price": l["entry_price"],
             "expiry": l.get("expiry"), "strike": l.get("strike"), "option_type": l.get("option_type"),
             "price_source": l.get("price_source")} for l in doc["legs"]]
    as_of = str((doc.get("signal") or {}).get("signal_at") or "")[:10] or None
    if not any(l["kind"] == "option" for l in legs):
        doc["exit_plan"] = {"options": {"status": "not_applicable", "reason": "no option leg",
                                        "evaluation": f"not evaluated here: {tpm.EXITS_OWNER}"}, "source": "entry"}
        return
    levels, err = tpm.compute_levels(doc["underlying"], float(doc["reference_price"]), as_of, legs,
                                     {"put_wall": None, "call_wall": None, "expected_move": None}, svc.ist_date(doc["opened_at"]))
    doc["exit_plan"] = {"options": tpm.options_exit(levels, as_of=as_of, error=err), "source": "entry"}


def _with_lifecycle(out: Dict[str, Any], doc: Dict[str, Any]) -> Dict[str, Any]:
    """The lifecycle and plan fields every trade response carries."""
    out["state"] = lifecycle.current_state(doc)
    out["transitions"] = list(doc.get("transitions") or [])
    out["plan_ref"] = doc.get("plan_ref")
    out["plan_levels"] = doc.get("plan_levels")
    out["exit_plan"] = doc.get("exit_plan")
    out["rolled_from"] = doc.get("rolled_from")
    out["rolled_to"] = doc.get("rolled_to")
    return out


PLAN_RISK_BASIS = ("The newest decision of the universal risk service (Phase 1) on a paper-trade submission that cited this "
                   "plan: the one that allowed a trade, or one that reduced or blocked a submission. The service decides "
                   "at submission (there is no preview), so a plan nobody has submitted has no decision and is provisional.")


def _public_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    """A risk_decisions row as a card reads it (the snapshot stays on the record)."""
    return {"decision_id": row["_id"], "outcome": {"allowed": "allow", "reduced": "reduce", "blocked": "block"}.get(row.get("outcome")),
            "at": row.get("at"), "symbol": row.get("symbol"), "trade_id": row.get("trade_id"),
            "requested_qty": row.get("requested_qty"), "approved_qty": row.get("approved_qty"),
            "requested_lots": row.get("requested_lots"), "approved_lots": row.get("approved_lots"),
            "reasons": [{k: r.get(k) for k in ("code", "check", "severity", "message")} for r in row.get("reasons") or []
                        if isinstance(r, dict)],
            "estimated_risk_rs": row.get("estimated_risk_rs"), "policy_version": row.get("policy_version"),
            "limits_version": row.get("limits_version")}


async def _plan_risk_decision(uid: str, plan_id: str, trades: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The user's newest risk-service decision on this plan, or None (PLAN_RISK_BASIS). A request the desk refused before
    the risk service ran (a validation refusal: source desk_validation) is not a risk decision and is not read here."""
    ids = [t["risk_decision_id"] for t in trades if t.get("risk_decision_id")]
    rows = await db[rc.DECISIONS].find({"user_id": uid, "source": risk_service.SOURCE,
                                        "$or": [{"_id": {"$in": ids}}, {"detail.lifecycle.plan_id": plan_id}]}
                                       ).sort("at", -1).to_list(200)
    # Newest first; at the same instant the decision that wrote a trade is the later one (a refusal writes nothing, so a
    # submission that succeeded followed it).
    best = max(rows, key=lambda r: (str(r.get("at") or ""), r["_id"] in ids), default=None)
    return _public_decision(best) if best else None


@router.get("/trade-plans/{plan_id}")
async def get_trade_plan(request: Request, plan_id: str) -> Dict[str, Any]:
    """One TradePlan with its DERIVED lifecycle status (proposed until one of your paper trades cites it; then the
    furthest of approved / triggered / open / closed / rejected), its versions and the trades that cite it."""
    user = await get_current_user(request)
    uid = user["user_id"]
    tp = await tpm.load(db, plan_id, uid)
    if tp is None:
        raise HTTPException(status_code=404, detail="plan_not_found")
    trades = await db[svc.TRADES].find({"user_id": uid, "trade_plan_id": plan_id}).to_list(svc.MAX_OPEN_TRADES * 2)
    # Only the versions this user may open (their own plans and those a system job built): another user's plan in the same
    # lineage is not theirs to read, and a card that switches to "the newest version" must be able to load it.
    versions = [v for v in await db[tpm.COLLECTION].find({"lineage_key": tp.get("lineage_key")}).sort("version", 1).to_list(50)
                if tpm.readable_by(v, uid)]
    states = [lifecycle.current_state(t) for t in trades]
    # YOUR refused submissions of this plan only. The plan document is shared (a system job's plan is everyone's), and its
    # `events` hold every user's refusals, so reading them made one user's refusal show the plan as rejected to all.
    # Each refusal's decision row (risk service or desk validation) carries its REJECTED event under detail.lifecycle.
    mine = await db[rc.DECISIONS].find({"user_id": uid, "detail.lifecycle.plan_id": plan_id}).sort("at", 1).to_list(200)
    rejected = [r["detail"]["lifecycle"] for r in mine if (r["detail"]["lifecycle"] or {}).get("to") == lifecycle.REJECTED]
    status = lifecycle.plan_status(states + ([lifecycle.REJECTED] if rejected and not trades else []))
    plan = {k: v for k, v in tp.items() if k not in ("_id", "owners", "events")}
    plan["lifecycle"] = {**(plan.get("lifecycle") or {}), "status": status, "derived": True}
    return {"plan": plan, "lifecycle": {"status": status, "trades": [{"id": t["_id"], "state": s, "status": t.get("status")}
                                                                     for t, s in zip(trades, states)],
                                        "rejections": rejected[-20:]},
            "risk_decision": await _plan_risk_decision(uid, plan_id, trades),
            "risk_decision_basis": PLAN_RISK_BASIS,
            # Phase 3 release blocker: the size the card shows is the risk service's own sizing for YOUR account
            # (services/risk_gate/plan_sizing.py), never a size worked out another way.
            "account_size": await plan_sizing.size_for(db, plan, uid),
            "versions": [{"plan_id": v["_id"], "version": v.get("version"), "created_at": v.get("created_at"),
                          "revalidation_ok": (v.get("revalidation") or {}).get("ok"), "supersedes": v.get("supersedes")} for v in versions],
            "sent_to_broker": False}


@router.get("/paper-account")
async def paper_account(request: Request) -> Dict[str, Any]:
    """The paper account: starting capital, cash, what is blocked against open positions, and what is
    left. `blocked_rs` is CAPITAL AT RISK, not exchange margin — this system has no margin source."""
    user = await get_current_user(request)
    return await acct.read(db, user["user_id"])


@router.get("/paper-account/corrections")
async def paper_account_corrections(request: Request) -> Dict[str, Any]:
    """Your paper account's reconciliation corrections (services/paper_reconcile.py): each additive entry with its
    reason, the owner's decision (exclude, void, ...) and its date, and whether a revert has cancelled it. Read-only."""
    user = await get_current_user(request)
    return await reconcile.corrections(db, user["user_id"])


@router.get("/paper-trades")
async def list_paper_trades(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("open", "closed", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    all_open = await db[svc.TRADES].find({"user_id": uid, "status": "open"}).sort("opened_at", -1).to_list(svc.MAX_OPEN_TRADES * 2)
    open_docs = [d for d in all_open if d.get("kind") != strat.KIND]
    strategy_open = [d for d in all_open if d.get("kind") == strat.KIND]
    starts = svc.fetch_starts(open_docs, "opened_at")
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await svc.apply_trade_exits(db, open_docs, bars)
    strategy_evaluated, strategy_sims, strategy_errors = await strat.apply_exits(db, strategy_open) if strategy_open else ([], {}, {})

    # Read closed trades after the exits are written, so a trade closed just now is listed once, as closed.
    closed_docs = await db[svc.TRADES].find({"user_id": uid, "status": "closed"}).sort("closed_at", -1).to_list(svc.MAX_CLOSED_LISTED + 1)
    partial = len(closed_docs) > svc.MAX_CLOSED_LISTED
    closed_docs = closed_docs[: svc.MAX_CLOSED_LISTED]
    closed_ids = {d["_id"] for d in closed_docs}

    trades: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "open" and d["_id"] not in closed_ids),
                      key=_sort_key("opened_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        trades.append(_with_lifecycle(svc.public_trade(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]),
                                                       sim=counts["paths"].get(doc["_id"])), doc))
    for doc in sorted((d for d in strategy_evaluated if d.get("status") == "open" and d["_id"] not in closed_ids),
                      key=_sort_key("opened_at"), reverse=True):
        trades.append(_with_lifecycle(strat.public_strategy_trade(doc, strategy_sims.get(doc["_id"]), strategy_errors.get(doc["_id"]),
                                                                  detail=True), doc))
    trades.sort(key=lambda t: str(t.get("opened_at") or ""), reverse=True)        # cash and strategy trades, newest first
    trades.extend(_public(d) for d in closed_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "exit_rule": svc.EXIT_RULE,
        "entry_rules": svc.ENTRY_RULE_TEXT,
        "rules_version": svc.RULES_VERSION,
        "cost_model": svc.COST_MODEL,
        "orders": svc.ORDERS_NOTE,
        "marks_error": svc.marks_error({**errors, **strategy_errors}, len(starts) + len(strategy_open)),
        "strategy_rules_version": strat.RULES_VERSION,
        "strategy_families": strat.FAMILIES,
        "status": status_filter,
        "trades": [t for t in trades if status_filter == "all" or t["status"] == status_filter],
        "summary": svc.summarize(trades, partial=partial),
        "limits": {"max_open": svc.MAX_OPEN_TRADES},
        "evaluated_at": svc.utcnow().isoformat(),
    }


@router.post("/paper-trades/{trade_id}/close")
async def close_paper_trade(request: Request, trade_id: str) -> Dict[str, Any]:
    """Close at `exit_price`, or at the last end-of-day close when none is given (reason "manual").
    The exit rule is checked first: a trade the bars show already stopped out or at target is closed that
    way and the request answers 409 trade_already_closed."""
    user = await get_current_user(request)
    uid = user["user_id"]
    body = await _body(request, allow_empty=True)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid_body")
    if set(body) - {"exit_price"}:
        raise HTTPException(status_code=422, detail="unknown_field")
    exit_price: Optional[float] = None
    if body.get("exit_price") is not None:
        try:
            exit_price = svc.clean_price(body["exit_price"], "invalid_exit_price")
        except svc.DeskInputError as exc:
            raise _input_error(exc)

    doc = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid}) if len(trade_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if doc.get("status") != "open":
        raise HTTPException(status_code=409, detail="trade_already_closed")
    if doc.get("kind") == strat.KIND:
        return await _close_strategy(doc, body)

    start = svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS)
    try:
        bars: Optional[List[Dict[str, Any]]] = await svc.fetch_bars(doc["symbol"], start)
    except svc.PricesUnavailable as exc:
        logger.warning("desk: no end-of-day bars for %s while closing %s: %s", doc["symbol"], trade_id, exc)
        # A conditional entry cannot be closed blind: without bars nobody knows whether it was filled.
        if exit_price is None or (doc.get("entry_rule") or "at_once") != "at_once":
            raise HTTPException(status_code=503, detail="prices_unavailable")
        bars = None             # the user gave the price; the close does not need a mark

    session = None
    note = None
    sim: Optional[Dict[str, Any]] = None
    reason = "manual"
    if bars is not None:
        sim = svc.simulate(doc, bars)
        if sim["exit"] is not None:
            await svc.close_trade(db, doc, **sim["exit"], sim=sim)
            raise HTTPException(status_code=409, detail="trade_already_closed")
        if sim["entry_status"] not in svc.ENTERED:
            # Never filled: closing it cancels the plan; there is no position, so no price and no P&L.
            sim["entry_status"] = "not_reached"
            reason, exit_price, note = "cancelled", None, svc.CANCELLED_NOTE
        elif exit_price is None:
            bar = svc.last_close(bars)
            if bar is None:
                raise HTTPException(status_code=409, detail="no_close_available")
            exit_price, session = bar["close"], bar["date"]
            note = f"Closed at the last end-of-day close ({bar['date'].isoformat()})."

    stored, mine = await svc.close_trade(db, doc, exit_reason=reason, exit_price=exit_price,
                                         exit_session=session, exit_note=note, sim=sim)
    if not mine or stored is None:
        raise HTTPException(status_code=409, detail="trade_already_closed")
    logger.info("desk: user %s closed paper trade %s at %s", uid, trade_id, exit_price)
    return {"trade": _with_lifecycle(svc.public_trade(stored), stored), **_price_context()}


async def _close_strategy(doc: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Close a strategy trade at the last end-of-day marks (reason "manual"), after the exit rules were checked: a
    trade the data shows already stopped, at target, expired or timed out is closed that way and answers 409."""
    if body:
        raise HTTPException(status_code=422, detail="unknown_field")        # a strategy closes at its marks, never at a typed price
    try:
        bars, rows = await strat.fetch_inputs(doc)
    except svc.PricesUnavailable as exc:
        logger.warning("desk: no prices for strategy trade %s while closing: %s", doc["_id"], exc)
        raise HTTPException(status_code=503, detail="prices_unavailable")
    sim = strat.simulate_strategy(doc, bars, rows)
    if sim["exit"] is not None:
        await strat.close_strategy_trade(db, doc, **sim["exit"], sim=sim)
        raise HTTPException(status_code=409, detail="trade_already_closed")
    last = sim["last_mark_session"]
    note = (f"Closed at the last end-of-day marks ({last.isoformat()})." if last
            else "Closed with no end-of-day marks on record for it yet; it has no P&L.")
    stored, mine = await strat.close_strategy_trade(db, doc, exit_reason="manual", exit_session=last, exit_note=note, sim=sim)
    if not mine or stored is None:
        raise HTTPException(status_code=409, detail="trade_already_closed")
    logger.info("desk: user %s closed strategy paper trade %s", doc["user_id"], doc["_id"])
    return {"trade": _with_lifecycle(strat.public_strategy_trade(stored, detail=True), stored), **_price_context()}


# ── F&O roll (option C) ──────────────────────────────────────────────────────
async def _roll_inputs(doc: Dict[str, Any], strike_mode: str) -> Dict[str, Any]:
    """(preview with costs) for an open strategy trade, or RollRefused. Reads the calendar and D's bhavcopy."""
    if doc.get("kind") != strat.KIND:
        raise roll.RollRefused(422, "not_a_strategy_trade", "Only a futures / options strategy paper trade can be rolled.")
    if doc.get("status") != "open":
        raise roll.RollRefused(409, "trade_already_closed", "This paper trade is closed.")
    expiries = sorted({leg["expiry"] for leg in doc["legs"] if leg.get("expiry")})
    if not expiries:
        raise roll.RollRefused(422, "nothing_to_roll", "This trade has no futures or options leg.")
    today = svc.ist_date(svc.utcnow().isoformat())
    session, left, _hol = await roll.calendar_for(today, date.fromisoformat(expiries[0]))
    rows = await roll.fetch_day_rows(doc["underlying"], session)
    preview = roll.plan_roll(doc, rows, session, left, strike_mode=strike_mode)
    preview["costs"] = roll.preview_costs(doc, preview)
    return preview


def _roll_mode(body: Any) -> str:
    if not isinstance(body, dict) or set(body) - {"strike_mode"}:
        raise HTTPException(status_code=422, detail="unknown_field")
    mode = body.get("strike_mode", "distance")
    if mode not in roll.STRIKE_MODES:
        raise HTTPException(status_code=422, detail={"code": "invalid_strike_mode", "message": "strike_mode is distance or same."})
    return mode


@router.get("/paper-trades/{trade_id}/roll")
async def preview_roll(request: Request, trade_id: str, strike_mode: str = Query("distance")) -> Dict[str, Any]:
    """What a roll would record, read only: both legs at session D's bhavcopy close, the new expiry and strikes, costs on
    both legs; `eligible: false` with the reason when it cannot roll (nothing is written either way)."""
    user = await get_current_user(request)
    doc = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": user["user_id"]}) if len(trade_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if strike_mode not in roll.STRIKE_MODES:
        raise HTTPException(status_code=422, detail={"code": "invalid_strike_mode", "message": "strike_mode is distance or same."})
    try:
        preview = await _roll_inputs(doc, strike_mode)
    except roll.RollRefused as no:
        return {"eligible": False, "refusal": no.detail(), "trade_id": trade_id, "rules_version": roll.ROLL_RULES_VERSION,
                "orders": svc.ORDERS_NOTE}
    preview.pop("body", None)
    return {"eligible": True, "preview": preview, "trade_id": trade_id, "orders": svc.ORDERS_NOTE}


async def _roll_replay(uid: str, old: Dict[str, Any], response: Response) -> Dict[str, Any]:
    new = await db[svc.TRADES].find_one({"_id": old["rolled_to"], "user_id": uid})
    response.status_code = 200
    return {"old": _public(old), "new": _public(new) if new else None, "replayed": True, **_price_context()}


def _roll_request(user: Dict[str, Any], ref: "_Refusals", new_doc: Dict[str, Any], old_id: str,
                  fno_additional: bool) -> risk_service.EntryRequest:
    return _entry_request(user, ref.cid, new_doc, fno_additional).model_copy(
        update={"path": "desk_paper_roll", "replaces_trade_id": old_id})


async def _roll_risk(user: Dict[str, Any], ref: "_Refusals", new_doc: Dict[str, Any], old_id: str) -> Tuple[Any, Dict[str, Any]]:
    """The roll's new structure passes the SAME decision as any entry (services/risk_gate/service.py, path
    desk_paper_roll): the desk's own exchange-lot check (422), then every core risk check, judged against the book
    WITHOUT the structure it replaces (`replaces_trade_id`: that one is closed first, its funds credited). Decided and
    recorded here; the reservation is taken after the old structure closes (risk_service.reserve_decided)."""
    try:
        await strat.check_exchange_lots(new_doc)
    except svc.DeskInputError as exc:
        raise await ref.refuse(422, exc.detail())
    req = _roll_request(user, ref, new_doc, old_id, await risk_gate.enabled_for(db, user))
    try:
        decision = await risk_service.enforce(db, req, reserve=False, rejection=ref.rejection("desk_paper_roll"))
    except HTTPException as exc:
        await ref.risk_refused(exc, "desk_paper_roll")
        raise
    return req, decision


@router.post("/paper-trades/{trade_id}/roll", status_code=201)
async def roll_paper_trade(request: Request, response: Response, trade_id: str) -> Dict[str, Any]:
    """Roll an open F&O strategy paper trade to the next listed expiry at session D's bhavcopy close (both sides).
    Order: checks and the preview (nothing written) → the new structure's risk checks → funds after the old trade's
    release → close the old one (`exit_reason roll`, `rolled_to`) → reserve and insert the new one (`rolled_from`,
    a TradePlan with the lineage). A second click finds the old trade rolled and answers the same pair (200,
    `replayed`). Nothing is sent to a broker."""
    user = await get_current_user(request)
    uid = user["user_id"]
    body = await _body(request, allow_empty=True)
    mode = _roll_mode(body)
    old = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid}) if len(trade_id) <= _ID_MAX else None
    if not old:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if old.get("status") == "closed" and old.get("exit_reason") == "roll" and old.get("rolled_to"):
        return await _roll_replay(uid, old, response)
    ref = _Refusals(uid, risk_gate.correlation_id(request))
    ref.symbol = old.get("underlying")
    try:
        preview = await _roll_inputs(old, mode)
    except roll.RollRefused as no:
        raise await ref.refuse(no.status, no.detail())
    session = date.fromisoformat(preview["session"])
    try:
        bars, rows = await strat.fetch_inputs(old)
    except svc.PricesUnavailable:
        raise await ref.refuse(503, "prices_unavailable")
    sim = strat.simulate_strategy(old, bars, rows)
    ruled = roll.exit_before_roll(sim, session)
    if ruled is not None:
        raise await ref.refuse(409, {"code": "exit_rule_fired", "message": f"The trade's own {ruled['exit_reason']} exit fired on "
                                     f"{ruled['exit_session'].isoformat()}; it closes by that rule, not by a roll."})
    try:
        new_doc = strat.new_strategy_trade(uid, preview["body"], now=svc.utcnow())
    except svc.DeskInputError as exc:
        raise await ref.refuse(422, exc.detail())
    risk_req, risk_decision = await _roll_risk(user, ref, new_doc, old["_id"])
    need = acct.reservation_for(new_doc, strat.exposure_rs(new_doc))
    old_net = (preview["costs"] or {}).get("old_net_pnl_rs")
    have = (await acct.read(db, uid))["available_rs"] + float(old.get("paper_reserved_rs") or 0) + float(old_net or 0)
    if need is None or need > have + 1e-6:
        raise await ref.refuse(409, {"code": "insufficient_paper_funds", "needed_rs": need, "available_after_close_rs": round(have, 2),
                                     "message": "After the old structure is closed the paper account would not fund the new one; nothing was rolled."})
    # The new structure's TradePlan, with the lineage (the old trade and its plan).
    tp = tpm.structure_plan(
        underlying=new_doc["underlying"], reference=float(new_doc["reference_price"]), direction=new_doc["direction"],
        family=new_doc["family"], label=strat.FAMILIES.get(new_doc["family"]), legs=[{**l, "quantity": l["lots"]} for l in new_doc["legs"]],
        levels=None, levels_error="computed at entry (exit_plan.options)", as_of=preview["session"],
        data_as_of={"chain": preview["session"]}, rules={"board": roll.ROLL_RULES_VERSION, "levels": None},
        candidate_id=f"roll:{old['_id']}", status="candidate", reasons=[],
        source={"kind": "roll", "rolled_from_trade_id": old["_id"]},
        lineage={"rolled_from_trade_id": old["_id"], "rolled_from_plan_id": old.get("trade_plan_id")},
        underlying_stop={"price": new_doc.get("stop_underlying"), "rationale": "carried from the rolled trade"},
        underlying_targets=[{"name": "t1", "price": new_doc.get("target_underlying"), "rule": "carried from the rolled trade"}])
    await tpm.store_many(db, [tp], uid)
    new_doc.update(plan_ref=tpm.plan_ref_of(tp), trade_plan_id=tp["plan_id"], plan_levels=tpm.canonical_levels(tp),
                   rolled_from={"trade_id": old["_id"], "session": preview["session"], "plan_id": old.get("trade_plan_id"),
                                "strike_shift": preview["strike_shift"], "strike_mode": mode},
                   idempotency_key=f"roll:{old['_id']}"[:64], request_fingerprint=svc.request_fingerprint({"roll": old["_id"], "mode": mode}))
    _store_premium_levels(new_doc)
    new_doc["open_key"] = strat.structure_key(new_doc)
    roll_note = f"Rolled to {new_doc['_id']} at the {preview['session']} NSE bhavcopy close."
    stored_old, mine = await strat.close_strategy_trade(db, old, exit_reason="roll", exit_session=session, exit_note=roll_note,
                                                        sim=roll.roll_sim(sim, preview, session),
                                                        extra={"rolled_to": new_doc["_id"], "roll": {k: preview[k] for k in (
                                                            "session", "rules_version", "price_source", "strike_mode", "strike_shift")}})
    if not mine:
        fresh = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid})
        if fresh and fresh.get("rolled_to"):
            return await _roll_replay(uid, fresh, response)
        raise HTTPException(status_code=409, detail="trade_already_closed")
    # The old structure is closed and its funds and risk released: now the new one's funds AND risk budget, in one
    # atomic reservation under the decision's id (another entry may have taken the budget in between).
    reserved = await risk_service.reserve_decided(db, risk_req.model_copy(update={"trade_id": new_doc["_id"]}),
                                                  risk_decision, rejection=ref.rejection("desk_paper_roll"))
    if not reserved.get("reservation_id"):
        codes = [r["code"] for r in reserved["reasons"] if r.get("check") == "reservation"]
        await db[svc.TRADES].update_one({"_id": trade_id, "user_id": uid},
                                        {"$set": {"rolled_to": None, "roll_failed": {"reason": ",".join(codes) or "reservation_refused",
                                                                                     "risk_decision_id": reserved["decision_id"]}}})
        logger.error("desk: roll of %s closed the old trade but could not reserve the new one (%s)", trade_id, codes)
        raise await ref.refuse(409, {"code": "roll_open_failed", "reasons": reserved["reasons"],
                                     "decision_id": reserved["decision_id"],
                                     "message": "The old structure was closed at the roll close, but the new one could "
                                                "not be reserved: " + ", ".join(codes) + "."})
    risk_service.stamp(new_doc, reserved)
    new_doc["paper_reserved_rs"] = float(reserved["budget"].get("funding_rs") or 0.0)
    await svc.ensure_indexes(db)
    svc.open_lifecycle(new_doc)
    try:
        await db[svc.TRADES].insert_one(new_doc)
    except DuplicateKeyError:
        await risk_service.release_unused(db, uid, reserved, reason="roll insert lost to a duplicate")
        prior = await db[svc.TRADES].find_one({"user_id": uid, "idempotency_key": new_doc["idempotency_key"]})
        await db[svc.TRADES].update_one({"_id": trade_id, "user_id": uid}, {"$set": {"rolled_to": prior["_id"] if prior else None}})
        if prior is not None:
            return await _roll_replay(uid, {**stored_old, "rolled_to": prior["_id"]}, response)
        raise
    await rc.record_decision(db, uid, action="desk_paper_roll", outcome="allowed", symbol=new_doc.get("underlying"),
                             requested_qty=None, reasons=[{"code": "roll", "text": roll_note}], correlation_id=ref.cid,
                             path="desk_paper_roll", detail={"old": trade_id, "new": new_doc["_id"], "session": preview["session"]})
    logger.info("desk: user %s rolled strategy paper trade %s to %s on %s", uid, trade_id, new_doc["_id"], preview["session"])
    preview.pop("body", None)
    return {"old": _public(stored_old), "new": _public(new_doc), "preview": preview, "replayed": False, **_price_context()}


@router.get("/paper-trades/{trade_id}")
async def get_paper_trade(request: Request, trade_id: str) -> Dict[str, Any]:
    """One trade with its lifecycle log. Read-only: nothing is written, even when the data shows an exit that the
    next list read will record (it is reported as `pending_exit`). A strategy trade carries its immutable `signal`."""
    user = await get_current_user(request)
    uid = user["user_id"]
    doc = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid}) if len(trade_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if doc.get("kind") == strat.KIND:
        sim, error = None, None
        if doc.get("status") == "open":
            try:
                bars, rows = await strat.fetch_inputs(doc)
                sim = strat.simulate_strategy(doc, bars, rows)
            except svc.PricesUnavailable:
                error = svc.PRICES_UNAVAILABLE
        trade = _with_lifecycle(strat.public_strategy_trade(doc, sim, error, detail=True), doc)
        pending = sim["exit"] if sim else None
        trade["pending_exit"] = ({"exit_reason": pending["exit_reason"], "exit_session": pending["exit_session"].isoformat(),
                                  "exit_note": pending["exit_note"]} if pending else None)
        return {"trade": trade, **_price_context()}
    mark = mark_error = sim = None
    pending = None
    if doc.get("status") == "open":
        try:
            bars = await svc.fetch_bars(doc["symbol"], svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS))
            sim = svc.simulate(doc, bars)
            mark, mark_error = svc.mark_for(doc["symbol"], {doc["symbol"]: bars}, {})
            pending = sim["exit"]
        except svc.PricesUnavailable:
            mark_error = svc.PRICES_UNAVAILABLE
    trade = _with_lifecycle(svc.public_trade(doc, mark, mark_error, sim=sim), doc)
    trade["kind"] = "cash"
    trade["events"] = _cash_events(trade)
    trade["pending_exit"] = ({"exit_reason": pending["exit_reason"], "exit_session": pending["exit_session"].isoformat(),
                              "exit_note": pending["exit_note"]} if pending else None)
    return {"trade": trade, **_price_context()}


def _cash_events(trade: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The lifecycle of a share trade, worked out from its stored fields (state changes only)."""
    events = [{"type": "created", "at": trade["opened_at"], "session": None, "text": "Paper trade recorded."}]
    if trade.get("entry_status") in svc.ENTERED:
        events.append({"type": "entered", "at": trade.get("entry_session") or trade["opened_at"], "session": trade.get("entry_session"),
                       "text": "Entry assumed when recorded." if trade["entry_status"] == "assumed" else "Entry level reached."})
    if trade["status"] == "closed":
        events.append({"type": "closed", "at": trade.get("closed_at"), "session": trade.get("exit_session"), "reason": trade.get("exit_reason"),
                       "text": trade.get("exit_note") or f"Closed ({trade.get('exit_reason')})."})
    return events


# ── alerts (price, filings, categories, volume, scanner, sector, risk — services/desk_alerts.py) ──────────────
@router.post("/alerts", status_code=201)
async def create_alert(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        doc = alerts_svc.new_alert(uid, await _body(request))
    except svc.DeskInputError as exc:
        raise _input_error(exc)
    await svc.ensure_indexes(db)
    active_filter = {"user_id": uid, "status": "active"}
    # Deduplicated: the same condition on the same stock with the same level and settings is one alert.
    key = alerts_svc.dedupe_key(doc)
    mine = await db[svc.ALERTS].find(active_filter).to_list(svc.MAX_ACTIVE_ALERTS * 2)
    if any(alerts_svc.dedupe_key(d) == key for d in mine):
        raise HTTPException(status_code=409, detail="duplicate_alert")
    if len(mine) >= svc.MAX_ACTIVE_ALERTS or await db[svc.ALERTS].count_documents(active_filter) >= svc.MAX_ACTIVE_ALERTS:
        raise HTTPException(status_code=409, detail="active_alert_limit")
    await db[svc.ALERTS].insert_one(doc)
    if await db[svc.ALERTS].count_documents(active_filter) > svc.MAX_ACTIVE_ALERTS:
        await db[svc.ALERTS].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail="active_alert_limit")
    logger.info("desk: user %s set alert %s (%s)", uid, doc["_id"], alerts_svc.describe(doc))
    return {"alert": alerts_svc.public_alert(doc), **_price_context()}


@router.get("/alerts")
async def list_alerts(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("active", "fired", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    active_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "active"}).sort("created_at", -1).to_list(svc.MAX_ACTIVE_ALERTS * 2)
    starts = alerts_svc.bar_starts(active_docs)
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await alerts_svc.evaluate(db, active_docs, bars)

    fired_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "fired"}).sort("fired_at", -1).to_list(svc.MAX_FIRED_LISTED)
    fired_ids = {d["_id"] for d in fired_docs}

    alerts: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "active" and d["_id"] not in fired_ids),
                      key=_sort_key("created_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors) if doc.get("symbol") in starts else (None, None)
        alerts.append(alerts_svc.public_alert(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]),
                                              counts["check_errors"].get(doc["_id"])))
    alerts.extend(alerts_svc.public_alert(d) for d in fired_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "firing_rule": svc.FIRING_RULE,
        "marks_error": svc.marks_error(errors, len(starts)),
        "check_errors": sorted(set(counts["check_errors"].values())),
        "status": status_filter,
        "alerts": [a for a in alerts if status_filter == "all" or a["status"] == status_filter],
        "counts": {
            "active": sum(1 for a in alerts if a["status"] == "active"),
            "fired": sum(1 for a in alerts if a["status"] == "fired"),
        },
        "limits": {"max_active": svc.MAX_ACTIVE_ALERTS},
        **alerts_svc.catalogue(),
        "evaluated_at": svc.utcnow().isoformat(),
    }


@router.delete("/alerts/{alert_id}", status_code=204, response_class=Response)
async def delete_alert(request: Request, alert_id: str) -> Response:
    user = await get_current_user(request)
    uid = user["user_id"]
    res = await db[svc.ALERTS].delete_one({"_id": alert_id, "user_id": uid}) if len(alert_id) <= _ID_MAX else None
    if res is None or res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="alert_not_found")
    logger.info("desk: user %s deleted alert %s", uid, alert_id)
    return Response(status_code=204)


# ── read-only status for the desk (no database write, nothing applied) ──────
@router.get("/exit-job-status")
async def exit_job_status(request: Request) -> Dict[str, Any]:
    """When exits were last checked: the evening job's last successful run and the session it covered, and
    ok | running | late | missed by the admin route's own rule (services/job_runs.trader_status). Reads the job's
    heartbeat only. It does NOT apply exits; GET /paper-trades does that."""
    await get_current_user(request)
    return await job_runs.read_trader_status(db, EXIT_JOB, job_runs.utcnow())


@router.get("/idea-scorecard")
async def idea_scorecard(request: Request) -> Dict[str, Any]:
    """The AI ideas' scorecard: the Phase 4.3 pre-registered study's committed results (services/idea_scorecard.py),
    nulls and negatives as they are. 503 with the reason when the committed results cannot be read."""
    await get_current_user(request)
    try:
        return scorecard.load()
    except scorecard.ScorecardUnavailable as e:
        logger.warning("desk: idea scorecard unavailable (%s: %s)", e.code, e.reason)
        raise HTTPException(status_code=503, detail=e.detail())
