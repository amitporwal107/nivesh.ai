"""SPT slice B — the risk decision, the pipeline's modes, approvals, modifications, the kill-switch state and the event
log (TESTCASES test_reports/spt_b_TESTCASES.md, SPT-B-18..33, 37, 38).

The universal risk service, risk_book, risk_profile, risk_controls, the paper account's reservation and the cost card
run for real on the in-memory store (tests/spt_b_fakes.py); slices A and C are the DESIGN §4 fakes.
MOCK — not real data: every user, symbol, price, opportunity and order is made up."""
from __future__ import annotations

import asyncio
import copy
from datetime import timedelta

import pytest

from services import desk_trading as desk
from services import paper_account as acct
from services import risk_controls as rc
from services.risk_gate import estimate as est
from services.risk_gate import service
from services.spt import allocation, constants as C, events, pipeline, policy, proposals, risk
from tests.spt_b_fakes import NOW, U1, U2, opportunity, plan, world  # noqa: F401 (world is a fixture)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def setup(world, mode="auto", px=502.0, **extras):
    world.store.add(opportunity())
    world.quote("FIXA", px, ask=px)
    run(world.set_mode(U1, mode, **extras))


def only(world, user=U1):
    [p] = world.proposals(user)
    return p


def states(p):
    return [s["to"] for s in p["state_history"]]


def kill(world, field="kill_switch"):
    run(rc.set_control(world.db, U1, field=field, value=True, reason="MOCK test", actor=U1, now=NOW))


def peak(world, dd_pct):
    """MOCK — an equity peak that puts the account's drawdown at dd_pct (equity = the ₹10 lakh opening cash)."""
    run(acct.ensure(world.db, U1))
    world.account(U1)["equity_peak_rs"] = round(1_000_000.0 / (1 - dd_pct / 100.0), 2)


# ── SPT-B-18 risk before the order (auto) ────────────────────────────────────
def test_spt_b_18_auto_mode_reserves_then_creates_the_order_under_the_reservations_trade_id(world):
    setup(world)
    report = run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_ORDER_CREATED and report["orders"] == 1 and report["errors"] == []
    assert states(p) == [C.PROP_GENERATED, C.PROP_AWAITING_RISK, C.PROP_RISK_APPROVED, C.PROP_READY_FOR_ORDER,
                         C.PROP_ORDER_CREATED]
    rec = p["risk"]
    assert rec["decision"] == C.RISK_APPROVE and rec["reservation_id"] == rec["risk_service_decision_id"]
    [row] = world.decisions()
    assert (row["path"], row["store"], row["mode"], row["actor_id"]) == ("spt_entry", C.ORDERS, "paper", "spt_pipeline")
    assert row["trade_id"] == rec["order_id"] == p["order_id"] and row["reservation_id"] == rec["reservation_id"]
    assert row["snapshot"]["request"]["target_price"] == 580.0 and row["snapshot"]["request"]["direction"] == "long"
    [call] = world.orders.calls
    assert call["order_id"] == rec["order_id"] and call["idempotency_key"] == f"spt:{U1}:opp-FIXA:entry"
    assert (call["side"], call["order_type"], call["quantity"]) == ("BUY", "MARKET", rec["approved_qty"])
    assert call["risk_decision"]["reservation_id"] == rec["reservation_id"] and call["exit_plan"] == p["exit_plan"]
    [res] = world.account(U1)["reservations"]
    assert res["trade_id"] == rec["order_id"] and res["store"] == C.ORDERS and res["path"] == "spt_entry"
    assert world.account(U1)["blocked_rs"] == round(rec["approved_qty"] * 502.0, 2)
    assert p["order"]["order_id"] == rec["order_id"] and p["order_day"] == "2026-11-05"


# ── SPT-B-19 PRD-S2: a valid opportunity that breaches portfolio risk; the service's own veto ──
def test_spt_b_19_open_risk_at_the_cap_blocks_before_any_reservation(world):
    setup(world)
    run(acct.ensure(world.db, U1))
    world.account(U1)["open_risk_rs"] = 30_000.0                      # MOCK: the open-risk counter at the 3% cap
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_BLOCKED_BY_RISK and p["risk"]["decision"] == C.RISK_BLOCKED
    assert p["allocation"]["reasons"][0]["code"] == "open_risk_full" and p["risk"]["stage"] == "allocation"
    assert world.decisions() == [] and world.orders.calls == [] and not world.account(U1).get("reservations")


def test_spt_b_19b_the_risk_service_vetoes_what_spt_passed(world):
    """An admin-set profile minimum reward:risk of 5 (MOCK): SPT's own checks pass (R:R 3.5 ≥ 2), the service refuses."""
    setup(world)
    from services import risk_profile as rp
    limits = dict(rp.NAMED[rp.OWNER_DEFAULT], min_reward_risk=5.0)
    run(world.db["risk_profiles"].insert_one({"_id": "mock-profile", "user_id": U1, "profile": "custom", "limits": limits,
                                              "version": 1, "starting_capital_rs": 1e6}))
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_REJECTED and p["risk"]["decision"] == C.RISK_REJECT
    assert "reward_risk_too_low" in p["risk"]["reason_codes"] and p["risk"]["risk_service_outcome"] == "block"
    [row] = world.decisions()
    assert row["outcome"] == "blocked" and row["reservation_id"] is None
    assert world.orders.calls == [] and not world.account(U1).get("reservations")


# ── SPT-B-20 PRD-S7: the daily loss limit ────────────────────────────────────
def test_spt_b_20_daily_loss_breached_blocks_and_restricts(world, monkeypatch):
    setup(world)

    async def no_bars(starts):
        return {}, {}
    monkeypatch.setattr(desk, "fetch_bars_many", no_bars)
    # MOCK: a desk trade opened and closed today for a net loss of ₹25,000, already in paper cash
    run(world.db[desk.TRADES].insert_one({"_id": "mock-loss", "user_id": U1, "status": "closed", "kind": "cash",
                                          "symbol": "LOSSX", "quantity": 100, "entry_price": 1000.0,
                                          "opened_at": (NOW - timedelta(hours=1)).isoformat(),
                                          "closed_at": (NOW - timedelta(minutes=30)).isoformat(), "net_pnl_rs": -25_000.0}))
    run(world.db["paper_accounts"].insert_one({"user_id": U1, "cash_rs": 975_000.0, "blocked_rs": 0.0,
                                               "starting_capital_rs": 1_000_000.0}))
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_BLOCKED_BY_RISK and p["risk"]["decision"] == C.RISK_BLOCKED
    assert "daily_loss_halt" in p["risk"]["reason_codes"]
    assert world.orders.calls == [] and not world.account(U1).get("reservations")
    ks = run(risk.kill_switch_state(world.db, U1, now=NOW))
    assert ks["state"] == "RESTRICTED" and "daily_loss_halt" in [r["code"] for r in ks["reasons"]]


# ── SPT-B-21 PRD-S14: the kill switch ────────────────────────────────────────
def test_spt_b_21_kill_switch_halts_before_any_reservation(world):
    setup(world)
    kill(world)
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_BLOCKED_BY_RISK and p["risk"]["decision"] == C.RISK_HALT
    assert p["risk"]["reason_codes"] == ["kill_switch_on"] and p["risk"]["risk_service_decision_id"] is None
    assert world.decisions() == [] and world.orders.calls == []
    ks = run(risk.kill_switch_state(world.db, U1, now=NOW))
    assert ks["state"] == "TRIGGERED" and ks["reasons"][0]["code"] == "kill_switch_on"


def test_spt_b_21b_kill_switch_state_mapping(world):
    assert run(risk.kill_switch_state(world.db, U1, now=NOW))["state"] == "DISABLED"
    run(world.set_mode(U1, "approval"))
    assert run(risk.kill_switch_state(world.db, U1, now=NOW))["state"] == "ACTIVE"
    peak(world, 4.5)
    assert run(risk.kill_switch_state(world.db, U1, now=NOW))["state"] == "RESTRICTED"
    peak(world, 6.5)
    ks = run(risk.kill_switch_state(world.db, U1, now=NOW))
    assert ks["state"] == "TRIGGERED" and "RESET_PENDING" in ks["states"] and "not produced" in ks["reset_pending_note"]


# ── SPT-B-22 the drawdown ladder ─────────────────────────────────────────────
def test_spt_b_22_reduce_band_halves_the_risk_percentage(world):
    setup(world)
    peak(world, 2.5)
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_ORDER_CREATED
    assert p["sizing"]["risk_pct"]["factor"] == 0.5 and p["sizing"]["risk_pct"]["pct"] == 0.25
    full = desk.max_units_within_budget(5000.0, 502.0, 480.0)
    assert p["sizing"]["steps"][0]["after"] == desk.max_units_within_budget(2500.0, 502.0, 480.0) < full


@pytest.mark.parametrize("dd, decision, code", [(4.5, C.RISK_BLOCKED, "drawdown_restricted"),
                                                (6.5, C.RISK_HALT, "drawdown_halt_ladder")])
def test_spt_b_22b_restricted_and_halt_bands_refuse_new_entries(world, dd, decision, code):
    setup(world)
    peak(world, dd)
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_BLOCKED_BY_RISK and p["risk"]["decision"] == decision and code in p["risk"]["reason_codes"]
    assert world.decisions() == [] and world.orders.calls == []


# ── SPT-B-23 the service reduces; the decision record ────────────────────────
def test_spt_b_23_a_reduce_is_approve_reduced_and_the_record_is_complete(world, risk_mock_inputs):
    risk_mock_inputs["regime"] = "BEAR"                     # MOCK: the governor halves the size limit in a BEAR market
    setup(world)
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    rec = p["risk"]
    assert p["state"] == C.PROP_ORDER_CREATED and rec["decision"] == C.RISK_APPROVE_REDUCED
    assert 0 < rec["approved_qty"] < rec["requested_qty"] and "BEAR_REGIME" in rec["reason_codes"]
    assert world.orders.calls[0]["quantity"] == rec["approved_qty"]
    [row] = world.decisions()
    assert row["outcome"] == "reduced" and row["approved_qty"] == rec["approved_qty"] and row["_id"] == rec["reservation_id"]
    q = rec["approved_qty"]
    planned = round(q * 22 + desk.round_trip_cost(q, 502.0, 480.0), 2)
    assert rec["planned_risk_rs"] == planned and rec["stressed_risk_rs"] == round(planned + q * 480 * 0.01, 2)
    assert rec["portfolio_risk_before_rs"] == 0.0
    assert rec["portfolio_risk_after_rs"] == est.cash_risk(q, 502.0, 480.0)["total"]
    assert rec["exposure_before_rs"] == 0.0 and rec["exposure_after_rs"] == round(q * 502.0, 2)
    for k in ("decision_id", "risk_service_decision_id", "reservation_id", "order_id", "opportunity_id", "proposal_id",
              "account_id", "reason_codes", "explanations", "at"):
        assert rec.get(k) is not None, k
    assert set(rec["policy_versions"]) >= {"spt_risk", "risk_service", "limits_version", "config_version", "sizing",
                                           "allocation", "estimate", "cost_model"}
    assert rec["policy_versions"]["risk_service"] == service.POLICY_VERSION


# ── SPT-B-24 SPT checks before the service ───────────────────────────────────
def _prop(rr_t2=3.5):
    return {"_id": "p-x", "user_id": U1, "opportunity_id": "opp-X", "symbol": "FIXA", "horizon": "positional",
            "entry": {"type": "MARKET", "price": 502.0}, "stop_loss": 480.0, "target_2": 580.0,
            "rr": {"t2": rr_t2, "min_rr": 2.0}}


def _state(world, **over):
    s = run(allocation.account_state(world.db, U1, now=NOW))
    s.update(over)
    return s


def _px():
    return proposals.price_from_quote({"ltp": 502.0, "ask": 502.0, "received_at": (NOW - timedelta(seconds=3)).isoformat()},
                                      NOW)


@pytest.mark.parametrize("over, kw, decision, code", [
    ({}, {"rr_t2": 1.5}, C.RISK_REJECT, "rr_below_minimum"),
    ({"open_risk_rs": 29_000.0}, {}, C.RISK_BLOCKED, "stressed_risk_exceeds_room"),
    ({"positions_open": 10}, {}, C.RISK_BLOCKED, "max_positions"),
])
def test_spt_b_24_spt_checks_refuse_without_calling_the_service(world, over, kw, decision, code):
    run(world.set_mode(U1, "auto"))
    rec = run(risk.evaluate(world.db, user_id=U1, proposal=_prop(**kw), state=_state(world, **over), quantity=100,
                            stressed_risk=100 * 26.6, price=_px(), actor_id="spt_pipeline", how="reserve",
                            order_id="o-1", now=NOW))
    assert rec["decision"] == decision and code in rec["reason_codes"]
    assert rec["risk_service_decision_id"] is None and world.decisions() == []
    assert not world.account(U1).get("reservations")


def test_spt_b_24b_a_stale_price_blocks(world):
    run(world.set_mode(U1, "auto"))
    stale = {**_px(), "received_at": (NOW - timedelta(seconds=300)).isoformat()}
    rec = run(risk.evaluate(world.db, user_id=U1, proposal=_prop(), state=_state(world), quantity=100, stressed_risk=2660.0,
                            price=stale, actor_id="spt_pipeline", how="reserve", order_id="o-1", now=NOW))
    assert rec["decision"] == C.RISK_BLOCKED and rec["reason_codes"] == ["price_stale"] and world.decisions() == []


# ── SPT-B-25, 31 approval mode ───────────────────────────────────────────────
def awaiting(world, **extras):
    setup(world, mode="approval", **extras)
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_AWAITING_USER
    return p


def test_spt_b_25_an_approval_cannot_override_a_hard_limit(world):
    awaiting(world)
    kill(world)
    world.quote("FIXA", 502.0, ask=502.0, at=NOW + timedelta(minutes=1))
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.approve(world.db, user_id=U1, opportunity_id="opp-FIXA", now=NOW + timedelta(minutes=1)))
    assert e.value.code == "risk_refused" and e.value.status == 409 and e.value.extra["decision"] == C.RISK_HALT
    p = only(world)
    assert p["state"] == C.PROP_APPROVAL_EXPIRED and p["approval"]["decision"] == "expired"
    assert p["approval"]["reason_codes"] == ["kill_switch_on"] and world.orders.calls == []
    assert not world.account(U1).get("reservations")


def test_spt_b_29_31_approval_waits_then_a_fresh_risk_run_creates_the_order(world):
    p = awaiting(world)
    assert p["approval"]["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()
    [screen] = world.decisions()
    assert screen["reservation_id"] is None and not world.account(U1).get("reservations")        # DB-1
    world.quote("FIXA", 502.5, ask=502.5, at=NOW + timedelta(minutes=2))
    out = run(pipeline.approve(world.db, user_id=U1, opportunity_id="opp-FIXA", now=NOW + timedelta(minutes=2)))
    p = out["proposal"]
    assert p["state"] == C.PROP_ORDER_CREATED and out["idempotent"] is False
    assert states(p)[-3:] == [C.PROP_AWAITING_USER, C.PROP_READY_FOR_ORDER, C.PROP_ORDER_CREATED]
    assert p["approval"]["decision"] == "approved" and p["approval"]["decided_by"] == U1
    fresh = [d for d in world.decisions() if d["_id"] != screen["_id"]]
    assert len(fresh) == 1 and fresh[0]["actor_id"] == U1 and fresh[0]["reservation_id"] == fresh[0]["_id"]
    assert world.orders.calls[0]["order_id"] == fresh[0]["trade_id"] == p["order_id"]
    assert len(p["risk_history"]) == 2 and p["entry"]["price"] == 502.5                  # the fresh ask
    again = run(pipeline.approve(world.db, user_id=U1, opportunity_id="opp-FIXA", now=NOW + timedelta(minutes=3)))
    assert again["idempotent"] is True and len(world.orders.calls) == 1


def test_spt_b_31b_approve_refusals(world):
    awaiting(world)
    with pytest.raises(pipeline.PipelineError) as e:                     # another user's opportunity
        run(pipeline.approve(world.db, user_id=U2, opportunity_id="opp-FIXA", now=NOW))
    assert e.value.code == "proposal_not_found" and e.value.status == 404
    world.quote("FIXA", 506.0, ask=506.0)                               # above the chase bound ₹505
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.approve(world.db, user_id=U1, opportunity_id="opp-FIXA", now=NOW))
    assert e.value.code == "approval_expired" and e.value.extra["reason_codes"] == ["price_outside_entry_range"]
    assert only(world)["state"] == C.PROP_APPROVAL_EXPIRED and world.orders.calls == []


def test_spt_b_31c_expired_window_and_reject(world):
    awaiting(world)
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.approve(world.db, user_id=U1, opportunity_id="opp-FIXA", now=NOW + timedelta(minutes=31)))
    assert e.value.code == "approval_expired" and only(world)["state"] == C.PROP_APPROVAL_EXPIRED
    world2_opp = opportunity("FIXB")
    world.store.add(world2_opp)
    world.quote("FIXB", 501.0, ask=501.0)
    run(pipeline.run_round(world.db, NOW))
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.reject(world.db, user_id=U1, opportunity_id="opp-FIXB", reason="  ", now=NOW))
    assert e.value.code == "reason_required" and e.value.status == 422
    out = run(pipeline.reject(world.db, user_id=U1, opportunity_id="opp-FIXB", reason="too extended", now=NOW))
    assert out["proposal"]["state"] == C.PROP_USER_REJECTED and out["proposal"]["approval"]["reason"] == "too extended"


def test_spt_b_29b_approval_expiry_never_passes_the_session_close_or_the_opportunity(world):
    setup(world, mode="approval", approval_expiry_minutes=390)
    world.store.opps["opp-FIXA"]["window_until"] = (NOW + timedelta(minutes=10)).isoformat()
    run(pipeline.run_round(world.db, NOW))
    assert only(world)["approval"]["expires_at"] == (NOW + timedelta(minutes=10)).isoformat()
    p = only(world)
    p2 = {**p, "opportunity": {}}
    cfg = run(policy.read(world.db, U1))
    assert proposals.approval_expiry(NOW, cfg, p2) == proposals.session_close(NOW)


# ── SPT-B-26 the order cannot be created ─────────────────────────────────────
def test_spt_b_26_a_failed_create_releases_the_reservation_and_is_not_retried(world):
    setup(world)
    world.orders.fail = RuntimeError("MOCK slice C down")
    report = run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_READY_FOR_ORDER and p["order_error"]["error"] == "RuntimeError"
    assert p["order_error"]["reservation_released"] is True and p["order_error"]["retried"] is False
    assert world.account(U1)["reservations"] == [] and world.account(U1)["blocked_rs"] == 0.0
    assert [r["action"] for r in world.db.docs(acct.LEDGER)] == ["reserve", "cancel_reservation"]
    assert report["errors"][0]["stage"] == "create_entry_order"
    run(pipeline.run_round(world.db, NOW + timedelta(seconds=30)))
    assert len(world.orders.calls) == 1                                   # never retried
    state_doc = world.db.docs(C.STATE)[0]
    assert state_doc["_id"] == "spt_b" and state_doc["last_round_at"] == (NOW + timedelta(seconds=30)).isoformat()


def test_spt_b_26b_an_order_that_exists_after_an_error_keeps_its_reservation(world):
    setup(world)
    world.orders.fail = TimeoutError("MOCK timeout after the insert")
    world.orders.write_before_fail = True
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_ORDER_CREATED and len(world.account(U1)["reservations"]) == 1


# ── SPT-B-27, 28 modifications ───────────────────────────────────────────────
POS = {"_id": "pos-1", "symbol": "FIXA", "direction": "long", "quantity": 100, "avg_entry_price": 500.0, "stop_loss": 480.0}


@pytest.mark.parametrize("change, decision, code", [
    ({"stop_loss": 470.0}, C.RISK_APPROVE, None),
    ({"stop_loss": 400.0}, C.RISK_REJECT, "per_trade_risk_exceeded"),
    ({"remove_stop": True}, C.RISK_REJECT, "stop_required"),
    ({"add_quantity": 200, "price": 500.0}, C.RISK_REJECT, "position_exceeded"),
])
def test_spt_b_27_risk_increasing_changes_are_revalidated_and_recorded(world, change, decision, code):
    out = run(risk.check_modification(world.db, user_id=U1, position=POS, change=change, now=NOW))
    assert out["risk_increasing"] is True and out["decision"] == decision
    assert (code in out["reason_codes"]) if code else out["reason_codes"] == []
    [row] = world.decisions()
    assert row["source"] == "spt_risk" and row["path"] == "spt_modification" and row["_id"] == out["decision_id"]
    assert row["outcome"] == ("allowed" if decision == C.RISK_APPROVE else "blocked")


def test_spt_b_27b_kill_switch_blocks_increases_but_never_reductions_or_exits(world):
    kill(world)
    up = run(risk.check_modification(world.db, user_id=U1, position=POS, change={"stop_loss": 470.0}, now=NOW))
    assert up["decision"] == C.RISK_HALT and "kill_switch_on" in up["reason_codes"]
    for change in ({"stop_loss": 490.0}, {"add_quantity": -50}, {"target_2": 600.0}):
        out = run(risk.check_modification(world.db, user_id=U1, position=POS, change=change, now=NOW))
        assert out["decision"] == C.RISK_APPROVE and out["risk_increasing"] is False, change
    peak(world, 6.5)
    assert run(risk.check_modification(world.db, user_id=U1, position=POS, change={"stop_loss": 495.0},
                                       now=NOW))["decision"] == C.RISK_APPROVE


def test_spt_b_27c_an_unrecorded_increase_is_refused_a_reduction_is_not(world, monkeypatch):
    async def unrecorded(*a, **kw):
        return None
    monkeypatch.setattr(rc, "record_decision", unrecorded)
    up = run(risk.check_modification(world.db, user_id=U1, position=POS, change={"stop_loss": 470.0}, now=NOW))
    assert up["decision"] == C.RISK_REJECT and "decision_unrecorded" in up["reason_codes"]
    down = run(risk.check_modification(world.db, user_id=U1, position=POS, change={"stop_loss": 490.0}, now=NOW))
    assert down["decision"] == C.RISK_APPROVE


# ── SPT-B-29 modes; SPT-B-30 idempotent rounds, leader, session ──────────────
def test_spt_b_29_off_proposes_nothing_and_tracking_orders_nothing(world):
    world.store.add(opportunity())
    world.quote("FIXA", 502.0, ask=502.0)
    report = run(pipeline.run_round(world.db, NOW))
    assert report["users"] == 0 and world.proposals() == []
    run(world.set_mode(U1, "tracking"))
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_TRACKING_ONLY and p["risk"]["dry_run"] is True and p["risk"]["decision"] == C.RISK_APPROVE
    assert world.decisions() == [] and world.orders.calls == [] and not world.account(U1).get("reservations")


def test_spt_b_30_rounds_are_idempotent_and_only_the_leader_in_session_runs(world):
    setup(world)
    run(pipeline.run_round(world.db, NOW))
    counts = (len(world.proposals()), len(world.events()), len(world.orders.calls), len(world.decisions()))
    run(pipeline.run_round(world.db, NOW + timedelta(seconds=30)))
    assert (len(world.proposals()), len(world.events()), len(world.orders.calls), len(world.decisions())) == counts

    class Store:
        def __init__(self, ok):
            self.ok, self.calls = ok, []

        async def lead(self, key, me, ttl, now):
            self.calls.append(key)
            return self.ok
    follower = Store(False)
    assert run(pipeline.loop_once(NOW, db=world.db, store=follower)) is False and follower.calls == [pipeline.LEADER_KEY]
    closed = Store(True)
    assert run(pipeline.loop_once(NOW.replace(hour=11), db=world.db, store=closed)) is False and closed.calls == []
    assert run(pipeline.loop_once(NOW + timedelta(days=2), db=world.db, store=closed)) is False      # Saturday
    assert run(pipeline.loop_once(NOW, db=world.db, store=Store(True))) is True
    assert pipeline.enabled({"APP_ENV": "staging"}) and not pipeline.enabled({"APP_ENV": "staging", "SPT_B_ENABLED": "0"})
    assert pipeline.enabled({"SPT_B_ENABLED": "1"}) and not pipeline.enabled({})


def test_spt_b_30b_ranked_batch_shares_the_room(world):
    """Two qualified opportunities, room for one entry today: the higher opportunity_score goes first."""
    run(world.set_mode(U1, "auto", max_new_per_day=1))
    world.store.add(opportunity("FIXA", score=60.0, scanner_score=99.0), opportunity("FIXB", score=85.0, scanner_score=70.0))
    world.quote("FIXA", 502.0, ask=502.0)
    world.quote("FIXB", 502.0, ask=502.0)
    run(pipeline.run_round(world.db, NOW))
    by = {p["symbol"]: p for p in world.proposals(U1)}
    assert by["FIXB"]["state"] == C.PROP_ORDER_CREATED
    assert by["FIXA"]["state"] == C.PROP_BLOCKED_BY_RISK and by["FIXA"]["allocation"]["reasons"][0]["code"] == "max_new_per_day"


def test_spt_b_30c_no_fresh_price_writes_nothing_and_is_tried_next_round(world):
    setup(world)
    world.quote_cache_down = True
    report = run(pipeline.run_round(world.db, NOW))
    assert world.proposals() == [] and report["skipped"] == {"quote_cache_unavailable": 1}
    world.quote_cache_down = False
    run(pipeline.run_round(world.db, NOW + timedelta(seconds=30)))
    assert only(world)["state"] == C.PROP_ORDER_CREATED


# ── SPT-B-32 the expiry sweep ────────────────────────────────────────────────
def test_spt_b_32_the_sweep_expires_and_releases_a_recorded_reservation(world):
    p = awaiting(world)
    caps = {"open_risk_cap_rs": 30_000.0, "exposure_cap_rs": 800_000.0, "sector_cap_rs": 250_000.0, "max_positions": 10}
    run(acct.reserve_entry(world.db, U1, {"id": "mock-res", "trade_id": "mock-order", "store": C.ORDERS, "path": "spt_entry",
                                          "kind": "cash", "symbol": "FIXA", "sector": "MOCK Sector", "funding_rs": 5000.0,
                                          "risk_rs": 300.0, "exposure_rs": 5000.0, "positions": 1, "held": True}, caps))
    doc = next(d for d in world.db.docs(C.PROPOSALS) if d["_id"] == p["_id"])
    doc["risk"]["reservation_id"] = "mock-res"                         # MOCK: a proposal that holds a reservation
    assert run(pipeline.expire_approvals(world.db, NOW + timedelta(minutes=29))) == 0
    assert run(pipeline.expire_approvals(world.db, NOW + timedelta(minutes=30))) == 1
    p = only(world)
    assert p["state"] == C.PROP_APPROVAL_EXPIRED and p["approval"]["reason_codes"] == ["approval_window_passed"]
    assert world.account(U1)["reservations"] == [] and world.account(U1)["blocked_rs"] == 0.0


# ── SPT-B-33 the event log ───────────────────────────────────────────────────
def test_spt_b_33_events_have_stable_keys_and_a_replay_adds_none(world):
    setup(world)
    run(pipeline.run_round(world.db, NOW))
    kinds = sorted(e["event_type"] for e in world.events())
    assert kinds == sorted(["TRADE_PROPOSAL_CREATED", "POSITION_SIZE_CALCULATED", "ALLOCATION_APPROVED", "RISK_APPROVED"]
                           + ["PROPOSAL_STATE_CHANGED"] * 4)
    p = only(world)
    for e in world.events():
        assert e["correlation_id"] == p["_id"] and e["account_id"] == U1 and e["instrument_id"] == "FIXA"
        again = run(events.emit(world.db, e["event_type"], idempotency_key=e["idempotency_key"],
                                source_service="replay", payload={}))
        assert again == {"stored": False, "duplicate": True, "error": None}
    assert len(world.events()) == 8


# ── SPT-B-37 the spt_entry path ──────────────────────────────────────────────
def test_spt_b_37_spt_entry_is_a_known_path_and_decides_like_the_desk():
    from tests.test_risk_service import snap
    assert "spt_entry" in service.PATHS
    base = dict(correlation_id="c", user_id="u1", actor_id="u1", mode="paper", symbol="FIXA", quantity=50,
                entry_price=1005.0, stop_price=970.0, target_price=1110.0)
    a = service.decide(service.EntryRequest(path="spt_entry", store=C.ORDERS, **base), snap())
    b = service.decide(service.EntryRequest(path="desk_paper_trade", **base), snap())
    assert (a["outcome"], a["approved_qty"], [r["code"] for r in a["reasons"]]) == \
        (b["outcome"], b["approved_qty"], [r["code"] for r in b["reasons"]])
    assert "path_unknown" not in [r["code"] for r in a["reasons"]]


# ── SPT-B-38 the stress test (P1) ────────────────────────────────────────────
def test_spt_b_38_stress_scenarios_on_the_open_spt_book(world):
    setup(world)
    run(pipeline.run_round(world.db, NOW))
    q = only(world)["risk"]["approved_qty"]
    st = run(allocation.account_state(world.db, U1, now=NOW))
    rows = run(risk.open_spt_book(world.db, U1, st))
    assert rows[0]["quantity"] == q and rows[0]["entry"] == 502.0 and rows[0]["stop"] == 480.0
    out = risk.stress(rows, gap_pct=1.0)
    planned = round(q * 22 + desk.round_trip_cost(q, 502.0, 480.0), 2)
    gap = next(s for s in out["scenarios"] if s["name"] == "gap_through_stop")
    assert gap["planned_rs"] == planned and gap["stressed_rs"] == round(planned + q * 480 * 0.01, 2)
    mkt = next(s for s in out["scenarios"] if s["name"] == "market_shock")["results"]
    assert [(r["shock_pct"], r["beta_assumed"], r["loss_rs"]) for r in mkt] == \
        [(-3.0, True, round(q * 502 * 0.03, 2)), (-5.0, True, round(q * 502 * 0.05, 2))]
    sec = next(s for s in out["scenarios"] if s["name"] == "sector_shock")
    assert sec["worst_sector"] == "MOCK Sector" and sec["worst_loss_rs"] == round(q * 502 * 0.05, 2)
    assert risk.stress([{"order_id": "x", "quantity": None, "entry": 1.0, "stop": 0.5}], gap_pct=1.0)["unpriced"] == ["x"]
