"""Decision-card contract (BE-8, BE-11 of test_reports/p3_decision_cards_TESTCASES.md).

The Playwright specs mock the routes with frontend-v5/e2e/fixtures/contract-decision-card.json and
contract-trade-plan-paper.json. Here the same answers are rebuilt from the REAL routes (tests/contract_fixtures.py) and
compared with the files, so a mocked screen cannot pass against a shape the backend does not send:

  BE-8   ONE cash plan_id carries identical entry, stop, targets, size and risk on the ideas route (Top 10), the Strategy
         Builder, the stored AI watchlist day and GET /api/desk/trade-plans/{id}; the F&O plan is the board's.
  BE-11  GET /api/desk/trade-plans/{id} carries the user's newest risk-service decision on the plan: null before any
         submission (the card stays provisional), ALLOW once a trade was written under the loosest profile, REDUCE under the
         owner's default 0.5% a trade, BLOCK with the kill switch on. The approval badge reads only these.

Writing the files: CONTRACT_FIXTURES_OUT=<dir> python -m pytest tests/test_decision_card_contract.py -q
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.strategy_plan import trade_plan as tpm
from tests import contract_fixtures as cf
from tests.test_fno_idea_paper_trade_contract import exchange_lots  # noqa: F401  (autouse: the MOCK exchange lot of the capture)

PAPER = "contract-trade-plan-paper.json"
CARD = "contract-decision-card.json"


@pytest.fixture(scope="module")
def built():
    # Built inside a test (not at import): the autouse risk-input stubs of tests/conftest.py must be active.
    return {}


def build(built, name):
    if name not in built:
        built[name] = cf.trade_plan_paper() if name == PAPER else cf.decision_card()
    return built[name]


def fixture(name):
    path = cf.FIXTURES / name
    assert path.exists(), f"{path} is a shared browser/route contract fixture and must be present"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(not os.environ.get("CONTRACT_FIXTURES_OUT"), reason="writes the fixtures only when asked")
def test_write_the_fixtures(built):
    out = Path(os.environ["CONTRACT_FIXTURES_OUT"])
    for name in (PAPER, CARD):
        (out / name).write_text(cf.dump(build(built, name)), encoding="utf-8")


def card_fields(tp):
    """What a decision card shows from a plan: levels, size and risk, evidence and warnings (as JSON text)."""
    keep = {**tpm.canonical_levels(tp), "size": tp.get("size"), "r_per_unit": tp.get("r_per_unit"),
            "costs": tp.get("costs"), "evidence": tp.get("evidence"), "warnings": tp.get("warnings"),
            "exit_plan": tp.get("exit_plan"), "eligibility": tp.get("eligibility")}
    return json.dumps(keep, sort_keys=True)


# ── BE-8 ─────────────────────────────────────────────────────────────────────
def test_be8_one_cash_plan_id_is_identical_on_every_surface(built):
    b = build(built, CARD)
    idea = b["cash"]["ideas_response"]["ideas"][0]
    tp = idea["trade_plan"]
    builder = next(c for c in b["cash"]["builder_response"]["candidates"] if c["segment"] == "cash")["trade_plan"]
    row = next(e for e in b["ai_watchlist_day"]["cash"] if e["symbol"] == idea["symbol"])["trade_plan"]
    got = b["cash"]["trade_plan_response"]["plan"]
    assert tp["size"]["status"] == "complete" and tp["size"]["quantity"] and tp["size"]["risk_rs"], tp["size"]
    assert {tp["plan_id"], builder["plan_id"], row["plan_id"], got["plan_id"]} == {tp["plan_id"]}
    assert card_fields(builder) == card_fields(row) == card_fields(got) == card_fields(tp)


def test_be8b_the_files_are_the_plans_the_routes_build(built):
    for name in (PAPER, CARD):
        want, got = fixture(name), build(built, name)
        if name == PAPER:
            assert got["cash"]["body"] == want["cash"]["body"] and got["fno"]["body"] == want["fno"]["body"]
            pairs = [(got["cash"]["trade_plan"], want["cash"]["trade_plan"]), (got["fno"]["trade_plan"], want["fno"]["trade_plan"])]
        else:
            g, w = got["cash"]["ideas_response"]["ideas"][0]["trade_plan"], want["cash"]["ideas_response"]["ideas"][0]["trade_plan"]
            gf = got["fno"]["trade_plan_response"]["plan"]
            pairs = [(g, w), (gf, want["fno"]["trade_plan_response"]["plan"]),
                     (next(c for c in got["futures"]["builder_response"]["candidates"] if c["segment"] == "futures")["trade_plan"],
                      next(c for c in want["futures"]["builder_response"]["candidates"] if c["segment"] == "futures")["trade_plan"])]
            assert got["cash"]["body"] == want["cash"]["body"]
            for k in ("allowed", "reduced", "blocked"):
                gd, wd = got["cash"][k]["trade_plan_response"]["risk_decision"], want["cash"][k]["trade_plan_response"]["risk_decision"]
                assert (gd["outcome"], [r["code"] for r in gd["reasons"]], gd["approved_qty"], gd["estimated_risk_rs"]) == \
                       (wd["outcome"], [r["code"] for r in wd["reasons"]], wd["approved_qty"], wd["estimated_risk_rs"])
        for g, w in pairs:
            assert g["plan_id"] == w["plan_id"] and card_fields(g) == card_fields(w)


# ── BE-11 ────────────────────────────────────────────────────────────────────
def test_be11_the_plan_route_carries_only_real_risk_decisions(built):
    b = build(built, CARD)
    assert b["cash"]["trade_plan_response"]["risk_decision"] is None             # nobody submitted it: provisional
    assert "no preview" in b["cash"]["trade_plan_response"]["risk_decision_basis"]
    allowed = b["cash"]["allowed"]
    assert allowed["paper_status"] == 201, allowed
    d = allowed["trade_plan_response"]["risk_decision"]
    assert d["outcome"] == "allow" and d["approved_qty"] == b["cash"]["body"]["quantity"] and d["policy_version"] == "universal-risk-v1"
    assert d["estimated_risk_rs"]["total"] > 0 and d["limits_version"]
    assert allowed["trade_plan_response"]["lifecycle"]["status"] == "open"
    reduced = b["cash"]["reduced"]
    assert reduced["paper_status"] == 409 and reduced["paper_detail"]["code"] == "risk_reduce", reduced["paper_detail"]
    rd = reduced["trade_plan_response"]["risk_decision"]
    # the plan's own 113 is cut to exactly the size the card showed this user before submitting (plan_sizing)
    assert rd["outcome"] == "reduce" and rd["approved_qty"] == reduced["trade_plan_response_before"]["account_size"]["quantity"]
    assert rd["approved_qty"] < reduced["sent"]["quantity"] == b["cash"]["ideas_response"]["ideas"][0]["trade_plan"]["size"]["quantity"]
    assert allowed["sent"]["quantity"] == allowed["trade_plan_response_before"]["account_size"]["quantity"]
    assert rd["decision_id"] == reduced["paper_detail"]["decision_id"]
    blocked = b["cash"]["blocked"]
    assert blocked["paper_status"] == 409 and blocked["paper_detail"]["code"] == "risk_blocked"
    bd = blocked["trade_plan_response"]["risk_decision"]
    assert bd["outcome"] == "block" and "kill_switch_on" in [r["code"] for r in bd["reasons"]]
    # the profile the card reads its equity basis from
    p = b["risk_profile"]
    assert p["live"]["equity"]["equity_rs"] == 1000000.0 and p["profile"]["capital_basis"] == "paper_equity"


def test_be11b_a_validation_refusal_is_not_a_risk_decision(built):
    """A request the desk refuses before the risk service runs (here: levels that are not the plan's) records a
    desk_validation row with the plan id; the card must not read it as the plan's risk decision."""
    import copy
    from tests.test_trade_plan_contract import make_surfaces
    from tests.test_desk_trading import bar
    with pytest.MonkeyPatch.context() as mp:
        c = make_surfaces(mp)
        idea = c.post("/api/desk/strategy/ideas", json=cf.SIZED, headers=cf.A).json()["ideas"][0]
        sym = idea["symbol"]
        c.rows[sym] = [dict(bar("2026-10-19", 1215.0, 1185.0, 1200.0), symbol=sym)]
        body = cf.cash_body(idea, "2026-10-19", 10)
        body["stop_price"] = body["stop_price"] - 1
        r = c.post("/api/desk/paper-trades", json=copy.deepcopy(body), headers=cf.A)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_levels_mismatch", r.text
        got = c.get(f"/api/desk/trade-plans/{idea['trade_plan']['plan_id']}", headers=cf.A).json()
    assert got["risk_decision"] is None
