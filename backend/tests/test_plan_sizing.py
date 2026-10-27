"""The card's size is the risk service's size (Phase 3 release blocker; SZ-1 … SZ-6 of
test_reports/p3_decision_cards_TESTCASES.md, addendum 2).

Every case runs the REAL routes (POST /api/desk/strategy/ideas, GET /api/desk/trade-plans/{id}, POST
/api/desk/paper-trades) on one in-memory Mongo in the MOCK world of tests/test_strategy_plan.py, with the conftest's MOCK
sector and market state (tests/conftest.py risk_mock_inputs). The cash idea is the one of the earlier finding: sized by
its own inputs (capital 10,00,000, risk 0.5%) at 113 shares, which the service cut to 83 under the owner's default
profile.

  SZ-1  for the same plan and user, `account_size.quantity` is exactly what the paper-trade route approves when no
        portfolio limit binds: submitting it is ALLOWED, submitting the plan's own 113 is REDUCED to it (default profile
        and the loosest profile).
  SZ-2  the estimate the card shows is the decision's estimate (loss at the stop + costs + gap stress).
  SZ-3  open positions do not change the account size; they show as "may be reduced at submission" with the size
        allowed today and the budgets left.
  SZ-4  BEAR regime: the size carries the governor's 0.5 factor once, and that size is confirmed and allowed as is
        (the Phase 1 re-halving was fixed in #365; until then the card said "not_confirmed").
  SZ-5  an F&O board plan is sized at the lots its row records: allowed within the budget, refused (not_sizable,
        min_lot_exceeds_budget) when one lot is over it.
  SZ-6  a plan sized with capital and the same setup unsized are separate lineages: neither is a version of the other.
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from services.risk_gate import plan_sizing
from services.strategy_plan import trade_plan as tpm
from tests import contract_fixtures as cf
from tests.risk_helpers import loose_profile_doc
from tests.test_desk_trading import bar
from tests.test_trade_plan_contract import make_surfaces
from tests.test_fno_idea_paper_trade_contract import exchange_lots  # noqa: F401  (autouse: the MOCK exchange lot of the capture)

SIZED = cf.SIZED


@pytest.fixture
def world(monkeypatch):
    c = make_surfaces(monkeypatch)
    return c


def H(user):
    return {"X-Test-User": user}


def idea_for(c, user):
    r = c.post("/api/desk/strategy/ideas", json=SIZED, headers=H(user))
    assert r.status_code == 200, r.text
    idea = r.json()["ideas"][0]
    c.rows[idea["symbol"]] = [dict(bar("2026-10-19", 1215.0, 1185.0, 1200.0), symbol=idea["symbol"])]   # MOCK: the session
    return idea


def account_size(c, user, plan_id):
    r = c.get(f"/api/desk/trade-plans/{plan_id}", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()["account_size"]


def submit(c, user, idea, quantity):
    return c.post("/api/desk/paper-trades", json=cf.cash_body(idea, "2026-10-19", quantity), headers=H(user))


@pytest.mark.parametrize("user,loose", [("user_c", False), ("user_a", True)])
def test_sz1_sz2_the_cards_size_is_exactly_what_the_route_approves(world, user, loose):
    idea = idea_for(world, user)
    tp = idea["trade_plan"]
    assert tp["size"]["quantity"] == 113                       # the plan's own sizing (its inputs), the earlier finding
    size = account_size(world, user, tp["plan_id"])
    assert size["status"] == "sized", size
    q = size["quantity"]
    if not loose:
        assert q < 113                                         # the default profile cuts the plan's own 113
        over = submit(world, user, idea, 113)
        assert over.status_code == 409 and over.json()["detail"]["code"] == "risk_reduce", over.text
        assert over.json()["detail"]["approved_qty"] == q      # the route's own reduce lands on the card's size
    ok = submit(world, user, idea, q)
    assert ok.status_code == 201, ok.text
    trade = ok.json()["trade"]
    assert trade["quantity"] == q
    decision = world.get(f"/api/desk/trade-plans/{tp['plan_id']}", headers=H(user)).json()["risk_decision"]
    assert (decision["outcome"], decision["approved_qty"]) == ("allow", q)
    assert decision["estimated_risk_rs"]["total"] == size["estimated_risk_rs"]["total"]
    assert size["risk_pct_of_equity"] == round(size["estimated_risk_rs"]["total"] / size["equity_rs"] * 100, 3)


def test_sz3_open_positions_leave_the_size_and_show_what_would_be_cut_today(world):
    idea = idea_for(world, "user_a")
    pid = idea["trade_plan"]["plan_id"]
    before = account_size(world, "user_a", pid)
    assert submit(world, "user_a", idea, before["quantity"]).status_code == 201
    after = account_size(world, "user_a", pid)
    # The open position does not cut the account size (the neutral book has none); only the equity it moved does: paper
    # equity is marked net of the position's estimated round-trip costs, so the per-trade budget is a little smaller.
    assert after["status"] == "sized" and after["equity_rs"] < before["equity_rs"]
    assert before["quantity"] * 0.99 < after["quantity"] <= before["quantity"]
    assert after["portfolio_note"].startswith("May be reduced by portfolio limits at submission")
    now = after["portfolio"]
    assert now["size_now"] == 0 and "ALREADY_HELD" in [r["code"] for r in now["reasons"]]
    rem = now["remaining"]
    assert rem["open_risk_rs"] is not None and rem["open_risk_rs"] < before["portfolio"]["remaining"]["open_risk_rs"]
    assert rem["positions"] == before["portfolio"]["remaining"]["positions"] - 1


def test_sz4_bear_regime_sizes_with_the_factor_once_and_that_size_is_confirmed(world, risk_mock_inputs):
    """Until #365 the service halved any submitted size again in a BEAR market, so this card said "not_confirmed"
    and the submit was reduced. The factor now cuts the limit, not the ask: the card's size is confirmed as is."""
    idea = idea_for(world, "user_c")
    pid = idea["trade_plan"]["plan_id"]
    bull = account_size(world, "user_c", pid)["quantity"]
    risk_mock_inputs["regime"] = "BEAR"                          # MOCK: the desk regime's trend is down
    size = account_size(world, "user_c", pid)
    assert size["quantity"] == bull // 2                         # the governor's bear_regime_size_factor 0.5, once
    assert [f["code"] for f in size["factors"]] == ["BEAR_REGIME"]
    assert size["status"] == "sized" and "confirm_outcome" not in size, size


def test_sz4b_in_a_bear_regime_the_cards_size_is_allowed_as_is(world, risk_mock_inputs):
    risk_mock_inputs["regime"] = "BEAR"
    idea = idea_for(world, "user_c")
    size = account_size(world, "user_c", idea["trade_plan"]["plan_id"])
    assert submit(world, "user_c", idea, size["quantity"]).status_code == 201


def test_sz5_an_fno_board_plan_is_sized_at_the_lots_its_row_records(world):
    top = cf._fno_top()
    tp = cf._fno_idea(top)["trade_plan"]
    asyncio.run(tpm.store(world.db, copy.deepcopy(tp), "system:ai-watchlist"))
    world.db.cols["risk_profiles"].docs.append(loose_profile_doc("user_c_loose"))
    tight = account_size(world, "user_c", tp["plan_id"])           # the owner's default: 0.5% of 10,00,000
    assert tight["status"] == "not_sizable" and tight["lots"] is None
    assert "min_lot_exceeds_budget" in [r["code"] for r in tight["blocking"]], tight
    loose = account_size(world, "user_c_loose", tp["plan_id"])
    assert loose["status"] == "sized" and loose["lots"] == 1 and loose["lot_size"] == 30, loose
    assert loose["estimated_risk_rs"]["total"] > 0 and loose["unit"] == "lots per leg"


def test_sz6_a_plan_sized_with_capital_and_the_same_setup_unsized_are_separate_lineages(world):
    sized = idea_for(world, "user_a")["trade_plan"]
    unsized = world.post("/api/desk/strategy/ideas", json={"limit": 1}, headers=H("user_a")).json()["ideas"][0]["trade_plan"]
    assert sized["plan_id"] != unsized["plan_id"] and sized["lineage_key"] != unsized["lineage_key"]
    assert sized["sizing_inputs"] == {"capital": 1000000, "risk_pct": 0.5, "max_allocation_pct": 25.0}
    assert unsized["sizing_inputs"] is None
    assert (sized["version"], sized["supersedes"], unsized["version"], unsized["supersedes"]) == (1, None, 1, None)
    for tp in (sized, unsized):
        got = world.get(f"/api/desk/trade-plans/{tp['plan_id']}", headers=H("user_a")).json()
        assert [v["plan_id"] for v in got["versions"]] == [tp["plan_id"]]
        # either way the card shows the ACCOUNT's size, not the plan's own
        assert got["account_size"]["status"] == "sized"


def test_be12_one_users_refused_submission_does_not_mark_the_shared_plan_rejected_for_others(world):
    """The plan document is shared; its status for a reader comes from THAT reader's trades and refusals only."""
    from services import risk_controls as rc
    idea = idea_for(world, "user_a")
    pid = idea["trade_plan"]["plan_id"]
    world.db.cols["risk_profiles"].docs.append(loose_profile_doc("user_d"))
    asyncio.run(rc.set_control(world.db, "user_d", field="kill_switch", value=True, reason="MOCK: test", actor="user_d"))
    assert world.post("/api/desk/strategy/ideas", json=SIZED, headers=H("user_d")).status_code == 200
    r = submit(world, "user_d", idea, 10)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_blocked", r.text
    mine = world.get(f"/api/desk/trade-plans/{pid}", headers=H("user_d")).json()
    other = world.get(f"/api/desk/trade-plans/{pid}", headers=H("user_a")).json()
    assert mine["lifecycle"]["status"] == "rejected" and len(mine["lifecycle"]["rejections"]) == 1
    assert other["lifecycle"]["status"] == "proposed" and other["lifecycle"]["rejections"] == []
    assert "events" not in other["plan"]
