"""SPT slice B — account config, proposals, sizing and allocation (TESTCASES test_reports/spt_b_TESTCASES.md,
SPT-B-01..17). MOCK — not real data: every symbol, price, user and opportunity is made up; the PRD / Workflow worked
examples use the documents' own hypothetical numbers (PRD §8.4, WF §8.4, WF §9.4)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from services import desk_trading as desk
from services import risk_profile as rp
from services.risk_gate import estimate as est
from services.spt import allocation, constants as C, policy, proposals, sizing
from tests.spt_b_fakes import NOW, U1, FakeDB, opportunity, plan, quote_row, world  # noqa: F401 (world is a fixture)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def cfg(**extras):
    c = policy.default_state(U1)
    c["extras"] = policy._merge(c["extras"], extras)
    return c


def price(px, **kw):
    return proposals.price_from_quote(quote_row("FIXA", ltp=px, ask=px, **kw), NOW)


# ── SPT-B-01..03 account config ──────────────────────────────────────────────
def test_spt_b_01_defaults_are_off_and_the_prd_26_values():
    c = run(policy.read(FakeDB(), U1))
    assert c["mode"] == C.MODE_OFF and c["stored"] is False and c["version"] == 0
    ex = c["extras"]
    assert ex["drawdown_ladder"] == {"reduce_at_pct": 2.0, "restrict_at_pct": 4.0, "halt_at_pct": 6.0, "reduce_factor": 0.5}
    assert ex["max_positions"] == 10 and ex["min_rr"] == {"positional": 2.0}
    assert ex["risk_pct"] == {"positional": 0.5, "intraday": 0.35, "fno": 0.35}
    assert ex["allocation_buckets_pct"] == {"equity_positional": 45.0, "equity_intraday": 25.0, "fno": 20.0, "reserve": 10.0}
    assert ex["stressed_gap_pct"] == est.GAP_STRESS_PCT
    assert set(c["defaults_source"]) == set(ex)


@pytest.mark.parametrize("kw, code", [
    ({"mode": "live"}, "invalid_mode"),
    ({"extras": {"max_lots": 3}}, "unknown_field"),
    ({"extras": {"max_positions": 11}}, "out_of_range"),
    ({"extras": {"max_positions": 2.5}}, "invalid_number"),
    ({"extras": {"allocation_buckets_pct": {"reserve": 20}}}, "buckets_must_sum_100"),
    ({"extras": {"drawdown_ladder": {"restrict_at_pct": 1.5}}}, "ladder_not_ascending"),
    ({"extras": {"risk_pct": {"positional": 0.75}}}, "risk_pct_above_profile"),
    ({"extras": {"max_adv_participation_pct": 6}}, "out_of_range"),
    ({"extras": {"stressed_gap_pct": 0.5}}, "out_of_range"),
    ({"mode": "auto", "reason": "x" * 501}, "reason_too_long"),
    ({}, "invalid_body"),
])
def test_spt_b_02_invalid_changes_are_422_with_a_code_and_write_nothing(kw, code):
    db = FakeDB()
    with pytest.raises(policy.ConfigError) as e:
        run(policy.update(db, U1, actor=U1, profile_limits=rp.default_state(U1)["limits"], now=NOW, **kw))
    assert e.value.code == code and e.value.status == 422
    assert db.docs(C.ACCOUNT_CONFIG) == [] and db.docs(C.ACCOUNT_CONFIG_VERSIONS) == []


def test_spt_b_03_every_change_is_versioned_with_who_when_old_new():
    db = FakeDB()
    limits = rp.default_state(U1)["limits"]
    c1 = run(policy.update(db, U1, actor="advisor-9", mode="approval", reason="opt in", profile_limits=limits, now=NOW))
    assert c1["mode"] == "approval" and c1["version"] == 1 and c1["stored"]
    c2 = run(policy.update(db, U1, actor=U1, extras={"max_chase_pct": 0.5, "risk_pct": {"positional": 0.4}},
                           expected_version=1, profile_limits=limits, now=NOW + timedelta(minutes=1)))
    assert c2["version"] == 2 and c2["extras"]["max_chase_pct"] == 0.5 and c2["extras"]["risk_pct"]["intraday"] == 0.35
    rows = sorted(db.docs(C.ACCOUNT_CONFIG_VERSIONS), key=lambda r: r["version"])
    assert [r["version"] for r in rows] == [1, 2] and all(r["status"] == "applied" for r in rows)
    assert rows[0]["actor"] == "advisor-9" and rows[0]["old"]["mode"] == "off" and rows[0]["new"]["mode"] == "approval"
    assert rows[1]["changed"] == ["max_chase_pct", "risk_pct.positional"] and rows[1]["at"] > rows[0]["at"]
    with pytest.raises(policy.ConfigError) as e:                    # a stale expected_version
        run(policy.update(db, U1, actor=U1, mode="auto", expected_version=1, profile_limits=limits, now=NOW))
    assert e.value.code == "concurrent_change" and e.value.status == 409
    with pytest.raises(policy.ConfigError) as e:
        run(policy.update(db, U1, actor=U1, mode="approval", profile_limits=limits, now=NOW))
    assert e.value.code == "no_change"
    # a mode-only change never re-judges stored extras: off always works even after the profile tightened
    tighter = dict(limits, per_trade_risk_pct=0.25)
    c3 = run(policy.update(db, U1, actor=U1, mode="off", profile_limits=tighter, now=NOW))
    assert c3["mode"] == "off" and c3["version"] == 3
    assert policy.effective_risk_pct(c3, "positional", tighter)["pct"] == 0.25          # capped where used


def test_spt_b_03b_effective_risk_is_capped_by_the_profile_and_cut_by_the_ladder():
    c = cfg()
    eff = policy.effective_risk_pct(c, "positional", {"per_trade_risk_pct": 0.5}, policy.ladder(2.5, c))
    assert eff == {"pct": 0.25, "configured_pct": 0.5, "profile_pct": 0.5, "factor": 0.5, "capped_by_profile": False}
    assert [policy.ladder(d, c)["band"] for d in (0.0, 1.99, 2.0, 4.0, 5.9, 6.0, None)] == \
        ["normal", "normal", "reduce", "restricted", "restricted", "halt", "unknown"]


# ── SPT-B-05..10 proposals ───────────────────────────────────────────────────
def test_spt_b_05_immediate_entry_at_the_ask_with_the_plan_levels_and_exit_plan():
    b = proposals.build(opportunity(), price(502.0), cfg(), NOW)
    assert b["outcome"] == "ok"
    e = b["entry"]
    assert e["type"] == "MARKET" and e["price"] == 502.0 and e["basis"] == "live ask" and e["chase_bound"] == 505.0
    assert e["time_in_force"] == "DAY" and e["expires_at"] == proposals.session_close(NOW).isoformat()
    assert (b["stop_loss"], b["target_1"], b["target_2"]) == (480.0, 540.0, 580.0)        # the plan's, never widened
    assert b["rr"]["t1"] == round(38 / 22, 4) and b["rr"]["t2"] == round(78 / 22, 4) and b["rr"]["measured_to"] == "target_2"
    assert b["exit_plan"] == {"stop_loss": 480.0, "target_1": 540.0, "target_2": 580.0, "t1_exit_fraction": 0.5,
                              "move_stop_to_breakeven_at_t1": True, "trail": {"rule": "trail-atr-v1", "k": 2},
                              "trend_exit": {"rule": "close_below_sma20"}, "max_hold_sessions": 20}
    ltp_only = proposals.price_from_quote({**quote_row("FIXA", ltp=499.0), "ask": None}, NOW)
    assert proposals.build(opportunity(), ltp_only, cfg(), NOW)["entry"]["basis"].startswith("live ltp")


def test_spt_b_06_above_the_chase_bound_is_a_limit_at_the_plan_entry_until_the_window():
    b = proposals.build(opportunity(), price(506.0), cfg(), NOW)
    e = b["entry"]
    assert b["outcome"] == "ok" and e["type"] == "LIMIT" and e["price"] == 500.0 and e["limit_price"] == 500.0
    assert e["time_in_force"] == "GTD" and e["expires_at"] == "2026-11-07T10:00:00+00:00"   # min(window, expiry)
    assert b["rr"]["t2"] == 4.0


@pytest.mark.parametrize("opp_over, px, code, outcome", [
    ({"strong": None}, 502.0, "no_valid_plan", "rejected"),
    ({"strong": {"plan": plan(plan_ok=False, plan_note="ATR unknown")}}, 502.0, "no_valid_plan", "rejected"),
    ({"strong": {"plan": plan(stop=505.0)}}, 502.0, "no_valid_plan", "rejected"),
    ({}, 480.0, "price_at_or_below_stop", "rejected"),
    ({"strong": {"plan": plan(t2=520.0, t1=510.0)}}, 504.0, "rr_below_minimum", "rejected"),
    ({"horizon": "intraday"}, 502.0, "horizon_not_enabled", "not_tradable"),
    ({"direction": "short"}, 502.0, "direction_not_enabled", "not_tradable"),
    ({"instrument": "futures"}, 502.0, "instrument_not_enabled", "not_tradable"),
])
def test_spt_b_07_08_refusals_carry_reason_codes(opp_over, px, code, outcome):
    b = proposals.build(opportunity(**opp_over), price(px), cfg(), NOW)
    assert b["outcome"] == outcome and b["reason_codes"] == [code] and b["explanations"]
    assert b["opp_invalidated"] is (code == "price_at_or_below_stop")


def test_spt_b_07b_a_price_below_the_stop_expires_the_opportunity_through_slice_a(world):
    from services.spt import pipeline
    world.store.add(opportunity())
    world.quote("FIXA", 479.0, ask=479.0)
    run(world.set_mode(U1, "auto"))
    run(pipeline.run_round(world.db, NOW))
    [p] = world.proposals(U1)
    assert p["state"] == C.PROP_REJECTED and p["reason_codes"] == ["price_at_or_below_stop"]
    assert world.store.transitions == [{"opp_id": "opp-FIXA", "to": C.OPP_EXPIRED,
                                        "reason": "plan invalidated: the live price is at or below the stop (slice B)"}]
    assert world.orders.calls == [] and world.decisions() == []


def test_spt_b_09_one_proposal_per_user_and_opportunity(world):
    c = run(world.set_mode(U1, "approval"))
    o = opportunity()
    p1, created1 = run(proposals.create(world.db, U1, o, price(502.0), c, NOW))
    p2, created2 = run(proposals.create(world.db, U1, o, price(503.0), c, NOW))
    assert created1 and not created2 and p1["_id"] == p2["_id"] and len(world.proposals(U1)) == 1
    # the unique index refuses a racing second insert too
    with pytest.raises(Exception) as e:
        run(world.db[C.PROPOSALS].insert_one({**p1, "_id": "other"}))
    assert type(e.value).__name__ == "DuplicateKeyError"


@pytest.mark.parametrize("row, code", [(None, "price_unavailable"), ("stale", "price_stale"), ("undated", "price_undated")])
def test_spt_b_10_no_fresh_price_writes_no_proposal_and_invents_no_number(world, row, code):
    c = run(world.set_mode(U1, "auto"))
    q = {"stale": quote_row("FIXA", ltp=502.0, age_s=121), "undated": {**quote_row("FIXA", ltp=502.0), "received_at": None},
         None: None}[row]
    px = proposals.price_from_quote(q, NOW)
    assert px["ok"] is False and px["reason"] == code and px["price"] is None
    with pytest.raises(proposals.PriceUnavailable) as e:
        run(proposals.create(world.db, U1, opportunity(), px, c, NOW))
    assert e.value.code == code and world.proposals() == []
    # refusals that need no price are written at once
    p, created = run(proposals.create(world.db, U1, opportunity(horizon="intraday"), px, c, NOW))
    assert created and p["state"] == C.PROP_NOT_TRADABLE


# ── SPT-B-11..14 sizing ──────────────────────────────────────────────────────
def test_spt_b_11_prd_8_4_example_243_shares():
    r = sizing.size(equity_rs=1_000_000, risk_pct=0.5, entry=500, stop=480, cost_per_share=0.50)
    assert r["allowed_risk"] == 5000.0
    assert r["quantity"] == 243 and r["capital_required"] == 121_500.0 and r["planned_risk"] == 4981.50
    assert r["stressed_risk"] == round(4981.50 + 243 * 480 * est.GAP_STRESS_PCT / 100, 2)
    assert r["steps"][0] == {"cap": "risk_budget", "before": None, "after": 243, "limit": 5000.0, "binding": True,
                             "reason": r["steps"][0]["reason"]}
    assert r["version"] == C.SIZING_VERSION and r["blocked"] == []


def test_spt_b_12_cost_card_costs_keep_the_loss_at_the_stop_within_the_allowed_risk():
    r = sizing.size(equity_rs=1_000_000, risk_pct=0.5, entry=500, stop=480)
    q = r["quantity"]
    loss = lambda n: n * 20 + desk.round_trip_cost(n, 500, 480, desk.COST_MODEL)      # noqa: E731
    assert loss(q) <= 5000 < loss(q + 1)
    assert r["planned_risk"] == round(loss(q), 2) and r["cost_per_share"] == round(desk.round_trip_cost(q, 500, 480) / q, 4)


def test_spt_b_13_caps_apply_in_order_and_each_step_is_recorded():
    base = dict(equity_rs=1_000_000, risk_pct=0.5, entry=500, stop=480, cost_per_share=0.5, min_adv_rs=1e7,
                max_adv_participation_pct=5.0, max_position_pct=10.0, available_rs=1_000_000, reserve_rs=100_000)
    r = sizing.size(**{**base, "min_adv_rs": 1e5}, adv_rs=1_000_000)   # liquidity: 5% of ₹10 lakh = ₹50,000 = 100 shares
    assert [s["cap"] for s in r["steps"]] == ["risk_budget", "risk_profile_per_trade", "liquidity", "position_exposure",
                                              "available_capital", "lot_size"]
    assert [(s["before"], s["after"]) for s in r["steps"][2:]] == [(243, 100), (100, 100), (100, 100), (100, 100)]
    r = sizing.size(**base, adv_rs=5e9)                          # position: 10% of ₹10 lakh = 200 shares
    assert r["quantity"] == 200 and next(s for s in r["steps"] if s["cap"] == "position_exposure")["binding"]
    r = sizing.size(**{**base, "available_rs": 150_000}, adv_rs=5e9)   # ₹1.5 lakh less the ₹1 lakh reserve = 100 shares
    assert r["quantity"] == 100 and r["steps"][4]["cap"] == "available_capital" and r["steps"][4]["binding"]
    r = sizing.size(**{**base, "cost_per_share": None}, adv_rs=5e9, profile_per_trade_pct=0.5)  # DB-3: the profile's measure
    fit = est.max_cash_qty(5000, 500, 480, 10 ** 6)
    assert r["quantity"] == fit and est.cash_risk(fit, 500, 480)["total"] <= 5000 < est.cash_risk(fit + 1, 500, 480)["total"]


def test_spt_b_14_unknown_or_thin_liquidity_sizes_nothing():
    base = dict(equity_rs=1_000_000, risk_pct=0.5, entry=500, stop=480, min_adv_rs=1e7, max_adv_participation_pct=5.0)
    r = sizing.size(**base, adv_rs=None)
    assert r["quantity"] == 0 and [b["code"] for b in r["blocked"]] == ["liquidity_unknown"]
    r = sizing.size(**base, adv_rs=9_999_999)
    assert r["quantity"] == 0 and [b["code"] for b in r["blocked"]] == ["liquidity_below_floor"]
    r = sizing.size(equity_rs=None, risk_pct=0.5, entry=500, stop=480)
    assert r["quantity"] == 0 and r["blocked"][0]["code"] == "equity_unknown"


# ── SPT-B-15..17 allocation ──────────────────────────────────────────────────
def state(**over):
    s = {"error": None, "equity_rs": 1_000_000.0, "available_rs": 1_000_000.0, "reserve_rs": 100_000.0,
         "profile": {"limits": rp.default_state(U1)["limits"]}, "positions_open": 0, "max_positions": 10,
         "new_today": 0, "max_new_per_day": 5, "bucket_cap_rs": {"equity_positional": 450_000.0},
         "bucket_used_rs": {"equity_positional": 0.0}, "sector_rs": {}, "unclassified_exposure_rs": 0.0,
         "open_risk_rs": 0.0, "open_risk_cap_rs": 30_000.0, "config": cfg()}
    s.update(over)
    return s


def cand(q=243, **over):
    c = {"symbol": "FIXA", "sector": "MOCK Sector", "category": "equity_positional", "entry": 500.0, "quantity": q,
         "stressed_per_share": 20.5 + 4.8}
    c.update(over)
    return c


def test_spt_b_15_wf_9_4_example_80000_available():
    s = state(available_rs=80_000.0, reserve_rs=0.0,
              config=cfg(allocation_buckets_pct={"equity_positional": 55, "equity_intraday": 25, "fno": 20, "reserve": 0}))
    a = allocation.allocate(s, cand())
    assert a["decision"] == "ALLOCATION_REDUCED" and a["quantity"] == 160 and a["capital_rs"] == 80_000.0
    assert a["capital_rs"] <= 80_000.0 and a["reasons"][0]["code"] == "capital_reduced"
    a = allocation.allocate(state(available_rs=80_000.0), cand())       # the default 10% reserve holds ₹1,00,000
    assert a["decision"] == "ALLOCATION_REJECTED" and a["reasons"][0]["code"] == "reserve_protected" and a["quantity"] == 0


def test_spt_b_16_buckets_sector_open_risk_positions_and_new_per_day():
    a = allocation.allocate(state(bucket_used_rs={"equity_positional": 400_000.0}), cand())
    assert a["decision"] == "ALLOCATION_REDUCED" and a["quantity"] == 100 and a["reasons"][0]["code"] == "bucket_reduced"
    a = allocation.allocate(state(sector_rs={"MOCK Sector": 240_000.0}), cand())
    assert a["quantity"] == 20 and a["reasons"][-1]["code"] == "sector_reduced"
    a = allocation.allocate(state(open_risk_rs=29_000.0), cand())
    assert a["quantity"] == int(1000 // 25.3) and a["reasons"][-1]["code"] == "open_risk_reduced"
    assert allocation.allocate(state(positions_open=10), cand())["reasons"][0]["code"] == "max_positions"
    assert allocation.allocate(state(new_today=5), cand())["reasons"][0]["code"] == "max_new_per_day"
    assert allocation.allocate(state(), cand(sector=None))["reasons"][0]["code"] == "sector_unknown"
    assert allocation.allocate(state(equity_rs=None), cand())["reasons"][0]["code"] == "equity_unknown"
    assert allocation.allocate(state(), cand())["decision"] == "ALLOCATION_APPROVED"


def test_spt_b_16b_reserved_capital_of_pending_entries_is_not_deployed(world):
    """A reservation on spt_orders whose order is PENDING (or not written yet) is reserved; a FILLED one is deployed."""
    db = world.db
    run(world.set_mode(U1, "auto"))
    from services import paper_account as acct
    run(acct.ensure(db, U1))
    caps = {"open_risk_cap_rs": 30_000.0, "exposure_cap_rs": 800_000.0, "sector_cap_rs": 250_000.0, "max_positions": 10}
    for i, st in ((1, C.ORD_PENDING), (2, C.ORD_FILLED), (3, None)):
        run(acct.reserve_entry(db, U1, {"id": f"r{i}", "trade_id": f"o{i}", "store": C.ORDERS, "path": "spt_entry",
                                        "kind": "cash", "symbol": f"SYM{i}", "sector": "MOCK Sector", "funding_rs": 10_000.0,
                                        "risk_rs": 500.0, "exposure_rs": 10_000.0, "positions": 1, "held": True}, caps))
        if st:
            run(db[C.ORDERS].insert_one({"_id": f"o{i}", "state": st, "quantity": 20}))
    s = run(allocation.account_state(db, U1, now=NOW))
    assert s["blocked_rs"] == 30_000.0 and s["reserved_rs"] == 20_000.0 and s["deployed_rs"] == 10_000.0
    assert {p["order_state"] for p in s["pending_entries"]} == {C.ORD_PENDING, "not_written_yet"}
    assert s["bucket_used_rs"]["equity_positional"] == 30_000.0 and s["positions_open"] == 3
    assert s["available_rs"] == 970_000.0 and s["reserve_rs"] == 100_000.0


def test_spt_b_17_ranking_uses_opportunity_score_then_rr_then_liquidity_never_the_scanner_score():
    rows = [{"symbol": "A", "opportunity_score": 60, "rr": 4.0, "adv_rs": 9e9, "scanner_score": 99},
            {"symbol": "B", "opportunity_score": 80, "rr": 2.5, "adv_rs": 1e8, "scanner_score": 70},
            {"symbol": "C", "opportunity_score": 80, "rr": 3.0, "adv_rs": 1e8, "scanner_score": 71},
            {"symbol": "D", "opportunity_score": 80, "rr": 3.0, "adv_rs": 5e8, "scanner_score": 72},
            {"symbol": "E", "opportunity_score": None, "rr": 9.0, "adv_rs": 9e9, "scanner_score": 100}]
    assert [r["symbol"] for r in allocation.rank(rows)] == ["D", "C", "B", "A", "E"]
    # a batch never exceeds the room: three candidates of ₹1,21,500 against ₹2,00,000 deployable
    s = state(available_rs=300_000.0)
    used = allocation.empty_consumed()
    got = []
    for _ in range(3):
        a = allocation.allocate(s, cand(), used)
        allocation.consume(used, cand(), a)
        got.append((a["decision"], a["quantity"]))
    assert got == [("ALLOCATION_APPROVED", 243), ("ALLOCATION_REDUCED", 157), ("ALLOCATION_REJECTED", 0)]
    assert used["capital_rs"] <= 200_000.0
