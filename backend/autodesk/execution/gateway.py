"""Unified execution gateway, paper only (PRD §11, ARCH §9; docs/autodesk/PHASE2_DESIGN.md §5).

APPROVED plan → execution intent (persisted first, own commit) → controls + reservation + orders (one transaction:
VALIDATED or REFUSED) → mode router (server side, from the account row) → adapter.submit → paper fills (settle.py).

Nothing here can reach a broker. Verbs are submit / amend / withdraw. Every control is stored on the intent with its outcome.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .. import contracts as C
from .. import store
from ..market.view import IST
from . import adapters as ad
from . import capital, journal, orders
from .capital import ReservationRefused, ReserveRequest, rs
from .fill_model import DEFAULT_PARAMS, FillParams

log = logging.getLogger(__name__)

PRODUCER = "EXECUTION_GATEWAY"
SESSION_OPEN_IST = (9, 15)
WORKING = ("VALIDATED", "SUBMITTED", "ACKNOWLEDGED", "OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING")


class ExecutionRefused(Exception):
    """The intent was refused; the row stays with its codes. Raised only where a caller needs the reason."""

    def __init__(self, codes: list[str], detail: str):
        super().__init__(f"{', '.join(codes)}: {detail}")
        self.codes, self.detail = codes, detail


@dataclass
class Control:
    name: str
    ok: bool
    code: Optional[str] = None
    detail: str = ""

    def to_json(self) -> dict:
        return {"name": self.name, "outcome": "PASS" if self.ok else "FAIL", "code": self.code, "detail": self.detail}


def _utc(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(timezone.utc)


def session_open_utc(d: date) -> datetime:
    return _utc(d, *SESSION_OPEN_IST)


def session_close_utc(d: date) -> datetime:
    return _utc(d, 15, 30)


class ExecutionGateway:
    """Paper execution. `sim` prices simulations from the session's daily row, `live` prices the live desk from live
    quotes. Either may be None (the account kind that needs it is then refused with MODE_NOT_ALLOWED)."""

    def __init__(self, pool, *, sim: Optional[ad.SimulationPaperAdapter] = None,
                 live: Optional[ad.LivePaperAdapter] = None, params: FillParams = DEFAULT_PARAMS):
        self.pool, self.sim, self.live, self.params = pool, sim, live, params
        self.shadow = ad.ShadowAdapter()

    # ── routing ───────────────────────────────────────────────────────────────────────────────────

    def adapter_for(self, account: dict):
        """Mode router (ARCH §9.1): the account row decides, never client input."""
        name = ad.route_name(account)
        return {"PAPER_SIM": self.sim, "PAPER_LIVE": self.live, "SHADOW": self.shadow}[name]

    # ── 1. the intent ─────────────────────────────────────────────────────────────────────────────

    async def create_intent(self, *, tenant_id: str, trade_id: str, plan_version: int, as_of: datetime,
                            approval_id: Optional[str] = None, caller_plan_hash: Optional[str] = None,
                            action: str = "ENTER") -> dict:
        """Persist the intent (CREATED), then run the controls, reserve and write the orders in one transaction. Returns
        the intent row: VALIDATED, or REFUSED with its codes. The same key returns the same intent."""
        key = f"{trade_id}:v{plan_version}:{action}"
        async with self.pool.acquire() as c:
            async with c.transaction():
                plan = await store.get_plan(c, tenant_id, trade_id)
                account = await store.get_account(c, tenant_id, plan["account_id"])
                wf = await store.get_workflow(c, tenant_id, plan["workflow_id"]) if plan.get("workflow_id") else None
                session = (wf or {}).get("session_date") or as_of.astimezone(IST).date()
                sim_id = account["simulation_id"]
                adapter_name = ad.route_name(account)
                intent = await c.fetchrow(
                    """INSERT INTO autodesk.execution_intents (intent_id, tenant_id, account_id, simulation_id, trade_id,
                           plan_version, execution_mode, adapter, action, session_date, status, idempotency_key, sim_time)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'CREATED',$11,$12)
                       ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING *""",
                    C.new_id("INT"), tenant_id, account["account_id"], sim_id, trade_id, plan_version,
                    ad.EXECUTION_MODE_OF_KIND[account["kind"]], adapter_name, action, session, key,
                    as_of if sim_id else None)
                if intent is not None:
                    await store.emit(c, C.EventType.EXECUTION_INTENT_CREATED, tenant_id=tenant_id, producer=PRODUCER,
                                     account_id=account["account_id"], simulation_id=sim_id, correlation_id=trade_id,
                                     sim_time=as_of if sim_id else None,
                                     payload={"intent_id": intent["intent_id"], "trade_id": trade_id,
                                              "plan_version": plan_version, "adapter": adapter_name, "action": action})
        if intent is None:                       # same key: the same intent, nothing new
            async with self.pool.acquire() as c:
                return dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE tenant_id=$1 AND "
                                             "idempotency_key=$2", tenant_id, key))
        return await self._validate(dict(intent), as_of=as_of, approval_id=approval_id, caller_plan_hash=caller_plan_hash)

    async def _validate(self, intent: dict, *, as_of: datetime, approval_id: Optional[str],
                        caller_plan_hash: Optional[str]) -> dict:
        tenant_id, trade_id = intent["tenant_id"], intent["trade_id"]
        sim_id = intent["simulation_id"]
        sim_time = as_of if sim_id else None
        async with self.pool.acquire() as c:
            async with c.transaction():
                row = await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE",
                                       intent["intent_id"])
                if row["status"] != "CREATED":
                    return dict(row)
                plan = await store.get_plan(c, tenant_id, trade_id, intent["plan_version"])
                head = await store.get_plan(c, tenant_id, trade_id)
                account = await store.get_account(c, tenant_id, plan["account_id"])
                body = C.TradePlanBody.model_validate(plan["body"])
                pol_row = await store.get_policy(c, tenant_id, account["policy_id"])
                policy = C.PolicyBody.model_validate(pol_row["body"])
                controls, approval, assessment = await self._controls(
                    c, intent=intent, plan=plan, head=head, account=account, body=body, policy=policy,
                    policy_version=int(pol_row["version"]), approval_id=approval_id, caller_plan_hash=caller_plan_hash,
                    as_of=as_of)
                spec: Optional[dict] = None
                if all(k.ok for k in controls):
                    spec = orders.build_spec(body, policy, self.params)
                    for code, why in orders.spec_problems(spec, self.params):
                        controls.append(Control("order_spec", False, code, why))
                refusal = [k for k in controls if not k.ok]
                reservation: Optional[dict] = None
                if not refusal:
                    try:
                        reservation = await capital.reserve(c, self._reserve_request(intent, plan, body, policy, spec, as_of))
                        controls.append(Control("funds_and_limits", True, None, f"reserved {reservation['amount_rs']}"))
                    except ReservationRefused as e:
                        controls.append(Control("funds_and_limits", False, e.code, e.detail))
                        refusal = [controls[-1]]
                if refusal:
                    return await self._refuse(c, intent, plan, controls, spec, sim_time, as_of)
                await c.execute("UPDATE autodesk.execution_intents SET status='VALIDATED', plan_hash=$2, approval_id=$3, "
                                "reservation_id=$4, controls=$5, order_spec=$6, updated_at=now() WHERE intent_id=$1",
                                intent["intent_id"], C.plan_hash(body), approval["approval_id"],
                                reservation["reservation_id"], [k.to_json() for k in controls], spec)
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1",
                                               intent["intent_id"]))
                made = await orders.insert_orders(c, intent=intent, spec=spec, sim_time=sim_time)
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.EXECUTING)
                await store.emit(c, C.EventType.EXECUTION_INTENT_VALIDATED, tenant_id=tenant_id, producer=PRODUCER,
                                 account_id=account["account_id"], simulation_id=sim_id, correlation_id=trade_id,
                                 sim_time=sim_time, payload={"intent_id": intent["intent_id"], "trade_id": trade_id,
                                                             "reservation_id": reservation["reservation_id"],
                                                             "orders": [o["order_id"] for o in made]})
                base = dict(tenant_id=tenant_id, account_id=account["account_id"], simulation_id=sim_id, trade_id=trade_id,
                            sim_time=sim_time)
                await journal.record_chain(c, tenant_id=tenant_id, plan={**dict(head), "signal_id": head.get("signal_id")},
                                           sim_time=sim_time)
                await journal.record(c, **base, kind="EXECUTION_INTENT", ref_id=intent["intent_id"],
                                     summary=f"intent for version {intent['plan_version']} passed {len(controls)} controls "
                                             f"on the {ad.route_name(account)} adapter",
                                     data={"controls": [k.name for k in controls]})
                await journal.record(c, **base, kind="RESERVATION", ref_id=reservation["reservation_id"],
                                     summary=f"{reservation['amount_rs']} set aside for {len(made)} order(s), "
                                             f"maximum loss {reservation['risk_rs']}",
                                     data={"amount_rs": str(reservation["amount_rs"]), "risk_rs": str(reservation["risk_rs"])})
                for o in made:
                    await journal.record(c, **base, kind="ORDER", ref_id=o["order_id"],
                                         summary=f"{'long' if o['side'] == 'BUY' else 'short'} order for {o['quantity']} {o['underlying']} "
                                                 f"{o['kind']} ({o['order_type'].lower().replace('_', ' ')}) validated",
                                         data={"leg_id": o["leg_id"], "limit_price": str(o["limit_price"] or "")})
                return intent

    def _reserve_request(self, intent: dict, plan: dict, body: C.TradePlanBody, policy: C.PolicyBody, spec: dict,
                         as_of: datetime) -> ReserveRequest:
        margin = body.margin_estimate or {}
        capital_rs = Decimal(str(margin.get("amount_rs") or body.capital_required_rs))
        return ReserveRequest(
            tenant_id=intent["tenant_id"], account_id=intent["account_id"], simulation_id=intent["simulation_id"],
            trade_id=intent["trade_id"], plan_version=intent["plan_version"], idempotency_key=f"{intent['idempotency_key']}:res",
            amount_rs=Decimal(spec["funds"]["needed_rs"]), risk_rs=body.max_loss_rs,
            commitment_rs=Decimal(spec["commitment_rs"]), capital_rs=capital_rs, instrument=body.instrument,
            sector=(body.market_context or {}).get("sector") or "UNCLASSIFIED",
            fno=bool(margin.get("fno", body.segment != C.Segment.CASH)), expires_at=min(body.plan_expires_at,
                                                                                      session_close_utc(intent["session_date"])),
            as_of=as_of, policy=policy)

    async def _refuse(self, c, intent: dict, plan: dict, controls: list[Control], spec: Optional[dict],
                      sim_time: Optional[datetime], as_of: datetime) -> dict:
        codes = [k.code for k in controls if not k.ok and k.code]
        row = await c.fetchrow(
            """UPDATE autodesk.execution_intents SET status='REFUSED', refusal_codes=$2, controls=$3, order_spec=$4,
                   updated_at=now() WHERE intent_id=$1 RETURNING *""",
            intent["intent_id"], codes, [k.to_json() for k in controls], spec)
        await store.set_plan_status(c, tenant_id=intent["tenant_id"], trade_id=intent["trade_id"],
                                    status=C.PlanStatus.EXECUTION_REFUSED)
        if "ENTRIES_STOPPED" in codes:
            await store.emit(c, C.EventType.ENTRIES_STOPPED, tenant_id=intent["tenant_id"], producer=PRODUCER,
                             account_id=intent["account_id"], simulation_id=intent["simulation_id"],
                             correlation_id=intent["trade_id"], sim_time=sim_time,
                             payload={"stage": "execution", "trade_id": intent["trade_id"], "intent_id": intent["intent_id"]})
        await store.emit(c, C.EventType.EXECUTION_INTENT_REFUSED, tenant_id=intent["tenant_id"], producer=PRODUCER,
                         account_id=intent["account_id"], simulation_id=intent["simulation_id"],
                         correlation_id=intent["trade_id"], sim_time=sim_time,
                         payload={"intent_id": intent["intent_id"], "trade_id": intent["trade_id"], "codes": codes,
                                  "reasons": [k.detail for k in controls if not k.ok]})
        await journal.record(c, tenant_id=intent["tenant_id"], account_id=intent["account_id"],
                             simulation_id=intent["simulation_id"], trade_id=intent["trade_id"], kind="EXECUTION_INTENT",
                             ref_id=intent["intent_id"], sim_time=sim_time,
                             summary=f"intent refused: {', '.join(codes)}", data={"codes": codes})
        return dict(row)

    # ── controls (PRD §11.4 adapted to paper; PHASE2_DESIGN §5.2) ─────────────────────────────────

    async def _controls(self, c, *, intent: dict, plan: dict, head: dict, account: dict, body: C.TradePlanBody,
                        policy: C.PolicyBody, policy_version: int, approval_id: Optional[str],
                        caller_plan_hash: Optional[str], as_of: datetime, at_submission: bool = False):
        out: list[Control] = []

        def chk(name: str, ok: bool, code: str, detail: str) -> bool:
            out.append(Control(name, ok, None if ok else code, detail if not ok else "ok"))
            return ok

        tenant_id, trade_id, version = intent["tenant_id"], intent["trade_id"], intent["plan_version"]
        chk("account_active", account["status"] == "ACTIVE", "ACCOUNT_NOT_ACTIVE", f"account is {account['status']}")
        adapter = self.adapter_for(account)
        routed = ad.route_name(account)
        chk("mode", account["operating_mode"] != C.OperatingMode.RESEARCH.value and routed in ("PAPER_LIVE", "PAPER_SIM")
            and adapter is not None and not isinstance(adapter, ad.ShadowAdapter), "MODE_NOT_ALLOWED",
            f"{account['operating_mode']} account on the {routed} adapter takes no orders")
        wf = await store.get_workflow(c, tenant_id, plan["workflow_id"]) if plan.get("workflow_id") else None
        began = ((wf or {}).get("input") or {}).get("operating_mode")
        chk("account_mode_unchanged", began in (None, account["operating_mode"]), "ACCOUNT_MODE_CHANGED",
            f"the account was {began} when the plan began and is {account['operating_mode']} now")
        approval = None
        if approval_id:
            approval = await c.fetchrow("SELECT * FROM autodesk.approvals WHERE approval_id=$1 AND tenant_id=$2",
                                        approval_id, tenant_id)
            if approval is not None and (approval["trade_id"] != trade_id or approval["plan_version"] != version):
                approval = None
        else:
            approval = await c.fetchrow(
                """SELECT * FROM autodesk.approvals WHERE tenant_id=$1 AND trade_id=$2 AND plan_version=$3
                   AND status='APPROVED' ORDER BY created_at DESC LIMIT 1""", tenant_id, trade_id, version)
        has = approval is not None and approval["status"] == "APPROVED"
        chk("approval_exists", has, "NO_APPROVAL", f"no APPROVED approval of {trade_id} version {version}")
        if has:
            chk("approval_unexpired", approval["expires_at"] is None or approval["expires_at"] > as_of, "APPROVAL_EXPIRED",
                f"the approval expired at {approval['expires_at']}")
        assessment = await store.latest_risk_assessment(c, tenant_id, trade_id, version)
        passed = assessment is not None and assessment["verdict"] == C.RiskVerdict.PASS.value
        chk("assessment_pass", passed, "NO_PASS_ASSESSMENT", f"no PASS risk assessment of version {version}")
        chk("policy_unchanged", assessment is None or assessment["policy_version"] == policy_version, "POLICY_CHANGED",
            f"policy is version {policy_version}; the assessment used {assessment['policy_version'] if assessment else None}")
        chk("plan_version_current", head["current_version"] == version, "PLAN_VERSION_STALE",
            f"version {head['current_version']} is current, not {version}")
        stored = C.plan_hash(plan["body"])
        scope_hash = None
        scope = None
        if has:
            raw = (approval["body"] or {}).get("scope")
            scope = C.ApprovalScope.model_validate(raw) if raw else None
            scope_hash = scope.plan_hash if scope else None
        chk("plan_hash", (scope_hash is None or scope_hash == stored)
            and (caller_plan_hash is None or caller_plan_hash == stored), "PLAN_HASH_MISMATCH",
            "the approved plan hash, the stored version and the caller's hash must be the same")
        if scope is not None:
            notional = sum((lg.ref_price * lg.quantity for lg in body.legs), Decimal("0"))
            bad = []
            if scope.account_id != account["account_id"] or scope.tenant_id != tenant_id:
                bad.append("account")
            if scope.instrument != body.instrument:
                bad.append("instrument")
            if scope.strategy_type != body.strategy_type:
                bad.append("strategy")
            if max(lg.lots for lg in body.legs) > scope.max_lots:
                bad.append("lots")
            if notional > scope.max_notional_rs + Decimal("0.01"):
                bad.append("notional")
            if body.max_loss_rs > scope.max_risk_rs:
                bad.append("risk")
            if intent["action"] not in scope.allowed_actions:
                bad.append("action")
            if scope.execution_mode != ad.EXECUTION_MODE_OF_KIND[account["kind"]]:
                bad.append("execution mode")
            chk("scope", not bad, "SCOPE_EXCEEDED", f"outside the approved scope: {', '.join(bad)}")
        chk("plan_state", plan["status"] in ("APPROVED", "EXECUTING") if at_submission else plan["status"] == "APPROVED",
            "PLAN_STATE", f"plan is {plan['status']}, not APPROVED")
        stop = await store.entries_stopped(c, tenant_id, intent["simulation_id"])
        chk("entries_not_stopped", stop is None, "ENTRIES_STOPPED",
            f"STOP_NEW_ENTRIES is active ({(stop or {}).get('reason')})")
        chk("strategy_allowed", body.strategy_type in policy.allowed_strategies, "STRATEGY_NOT_ALLOWED",
            f"{body.strategy_type.value} is not allowed by the policy")
        chk("segment_allowed", body.segment in policy.allowed_segments, "SEGMENT_NOT_ALLOWED",
            f"{body.segment.value} is not allowed by the policy")
        short_fut = [lg.leg_id for lg in body.legs if lg.kind == C.InstrumentKind.FUT and lg.side == C.LegSide.SHORT]
        chk("no_short_futures", not short_fut, "STRATEGY_NOT_ALLOWED", f"short futures are not supported ({short_fut})")
        expired = [lg.leg_id for lg in body.legs if lg.expiry is not None and lg.expiry < intent["session_date"]]
        chk("contracts_live", not expired, "CONTRACT_EXPIRED", f"legs {expired} expired before the session")
        if intent["simulation_id"] and not at_submission:
            chk("session_phase", as_of < session_open_utc(intent["session_date"]), "SESSION_PHASE_PASSED",
                "the simulated session's open has passed; entries are placed before the open")
        dup = await c.fetchval(
            """SELECT intent_id FROM autodesk.execution_intents WHERE tenant_id=$1 AND trade_id=$2 AND plan_version=$3
               AND action=$4 AND intent_id<>$5 AND status<>'REFUSED' LIMIT 1""",
            tenant_id, trade_id, version, intent["action"], intent["intent_id"])
        chk("not_duplicate", dup is None, "DUPLICATE_INTENT", f"intent {dup} already covers this plan version")
        return out, approval, assessment

    # ── 2. submission ────────────────────────────────────────────────────────────────────────────

    async def submit(self, *, tenant_id: str, intent_id: str, as_of: datetime) -> dict:
        """VALIDATED → SUBMITTED: the binding, stop and account controls run again, then every order goes to the adapter.
        An adapter that raises leaves the order UNKNOWN (never retried blindly); the reservation is kept until it expires."""
        async with self.pool.acquire() as c:
            async with c.transaction():
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 AND tenant_id=$2 "
                                               "FOR UPDATE", intent_id, tenant_id))
                if intent["status"] != "VALIDATED":
                    return intent
                sim_time = as_of if intent["simulation_id"] else None
                plan = await store.get_plan(c, tenant_id, intent["trade_id"], intent["plan_version"])
                head = await store.get_plan(c, tenant_id, intent["trade_id"])
                account = await store.get_account(c, tenant_id, intent["account_id"])
                body = C.TradePlanBody.model_validate(plan["body"])
                pol_row = await store.get_policy(c, tenant_id, account["policy_id"])
                controls, _a, _r = await self._controls(
                    c, intent=intent, plan=plan, head=head, account=account, body=body,
                    policy=C.PolicyBody.model_validate(pol_row["body"]), policy_version=int(pol_row["version"]),
                    approval_id=intent["approval_id"], caller_plan_hash=intent["plan_hash"], as_of=as_of,
                    at_submission=True)
                bad = [k for k in controls if not k.ok and k.name != "not_duplicate"]
                working = await orders.of_intent(c, intent_id)
                if bad:
                    codes = [k.code for k in bad]
                    for o in working:
                        if o["state"] == "VALIDATED":
                            await orders.move(c, o, C.OrderState.REJECTED, reason="; ".join(k.detail for k in bad),
                                              sim_time=sim_time, reject_code=bad[0].code, reject_reason=bad[0].detail)
                    if intent["reservation_id"]:
                        res = await capital.get_reservation(c, tenant_id, intent["reservation_id"], for_update=True)
                        await capital.close_reservation(c, res, status=C.ReservationStatus.RELEASED,
                                                        reason=f"refused at submission: {', '.join(codes)}", sim_time=sim_time)
                    row = await c.fetchrow(
                        """UPDATE autodesk.execution_intents SET status='REFUSED', refusal_codes=$2, controls=controls || $3,
                               updated_at=now() WHERE intent_id=$1 RETURNING *""", intent_id, codes,
                        [k.to_json() for k in bad])
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=intent["trade_id"],
                                                status=C.PlanStatus.EXECUTION_REFUSED)
                    await store.emit(c, C.EventType.EXECUTION_INTENT_REFUSED, tenant_id=tenant_id, producer=PRODUCER,
                                     account_id=intent["account_id"], simulation_id=intent["simulation_id"],
                                     correlation_id=intent["trade_id"], sim_time=sim_time,
                                     payload={"intent_id": intent_id, "stage": "submission", "codes": codes})
                    return dict(row)
                adapter = self.adapter_for(account)
                for o in working:
                    if o["state"] != "VALIDATED":
                        continue
                    o = await orders.move(c, o, C.OrderState.SUBMITTED, reason=f"sent to the {adapter.name} adapter",
                                          sim_time=sim_time)
                    try:
                        await adapter.submit(o, o["idempotency_key"])
                    except Exception as e:  # noqa: BLE001 — an adapter failure must not lose the intent (AD-P2-34)
                        log.warning("adapter %s failed on %s: %s", adapter.name, o["order_id"], e)
                        await orders.move(c, o, C.OrderState.UNKNOWN, reason=f"adapter failure: {type(e).__name__}: {e}",
                                          sim_time=sim_time)
                        continue
                    o = await orders.move(c, o, C.OrderState.ACKNOWLEDGED, reason="the paper adapter accepted it",
                                          sim_time=sim_time)
                    await orders.move(c, o, C.OrderState.OPEN, reason="working at the paper venue", sim_time=sim_time)
                row = await c.fetchrow("UPDATE autodesk.execution_intents SET status='SUBMITTED', updated_at=now() "
                                       "WHERE intent_id=$1 RETURNING *", intent_id)
                return dict(row)

    # ── 3. withdraw / amend ───────────────────────────────────────────────────────────────────────

    async def withdraw(self, *, tenant_id: str, order_id: str, as_of: Optional[datetime] = None) -> dict:
        """Withdraw a working paper order (PRD §17.4). A several-leg plan is all-or-none, so its whole intent is withdrawn.
        Raises store.Conflict for a terminal order."""
        as_of = as_of or datetime.now(timezone.utc)
        async with self.pool.acquire() as c:
            async with c.transaction():
                o = await orders.get_order(c, tenant_id, order_id, for_update=True)
                if C.OrderState(o["state"]) in C.ORDER_TERMINAL or o["state"] == "CANCEL_PENDING":
                    raise store.Conflict(f"order {order_id} is {o['state']}")
                sim_time = as_of if o["simulation_id"] else None
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE",
                                               o["intent_id"]))
                account = await store.get_account(c, tenant_id, o["account_id"])
                adapter = self.adapter_for(account)
                for x in await orders.of_intent(c, o["intent_id"]):
                    st = C.OrderState(x["state"])
                    if st in C.ORDER_TERMINAL:
                        continue
                    if st == C.OrderState.VALIDATED:
                        await orders.move(c, x, C.OrderState.CANCELLED, reason="withdrawn before submission", sim_time=sim_time)
                        continue
                    if st in (C.OrderState.OPEN, C.OrderState.PARTIALLY_FILLED):
                        x = await orders.move(c, x, C.OrderState.CANCEL_PENDING, reason="withdrawal requested", sim_time=sim_time)
                        await adapter.withdraw(x, f"{x['idempotency_key']}:withdraw")
                        await orders.move(c, x, C.OrderState.CANCELLED, reason="the paper venue confirmed the withdrawal",
                                          sim_time=sim_time)
                from .settle import finish_intent    # late import: settle uses this module's constants
                return await finish_intent(c, intent, as_of=as_of, sim_time=sim_time, why="withdrawn")

    async def amend(self, *, tenant_id: str, order_id: str, changes: dict) -> dict:
        raise ad.AdapterRefused("changing a working paper order is not available in Phase 2; withdraw it instead")
