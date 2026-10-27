"""F&O idea "Paper trade" ⇄ POST /api/desk/paper-trades — the contract test of Phase 0 release gate 7 (item 0.1).

The body every F&O idea's "Paper trade" button sends (frontend-v5 strategy/top-actions.ts paperTradeBodyFor: the Top by
regime cards, the desk Top 10 F&O rows, the lab's focus panel and the AI watchlist F&O rows) is pinned in ONE shared
fixture, frontend-v5/e2e/fixtures/contract-fno-idea-paper-trade.json. The Playwright specs (copilot-app-desk-strategy-top,
copilot-app-desk-top10, copilot-app-ai-watchlist) assert the browser sends exactly those bodies; here the same bodies go
through the real route and validator (routes/desk_trading.create_paper_trade → services/desk_strategy_trades
.new_strategy_trade) with the in-memory fakes of tests/test_desk_trading.py. If the button and the validator drift apart,
one of the two sides fails. Before the fix the button sent no `signal` and every click was refused with 422
invalid_signal (B-3 keeps that body as the regression case).

B-1 … B-6 of test_reports/fno_idea_paper_trade_TESTCASES.md.

The idea is a REAL staging capture (desk-strategy-top.json, POST /api/desk/strategy/top on 2026-10-21); the levels reply
the browser specs use is asserted below to be exactly the real engine's answer. The clock is 2026-10-22 10:30 IST: after
the chain date (signal_at may not be in the future) and before the legs' expiry (2026-10-27).
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from services import ai_watchlist_build as build
from services import strategy_levels
from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401  (`world` and `api` are fixtures)

FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"
CLOCK = datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)


def load(name: str) -> Dict[str, Any]:
    path = FIXTURES / name
    # A gate, not a convenience: without the shared fixture the contract is not tested, so fail rather than skip.
    assert path.exists(), f"{path} is the shared browser/route contract fixture and must be present"
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load("contract-fno-idea-paper-trade.json")
TOP = load(CONTRACT["idea"]["fixture"])
REPLY = load(CONTRACT["levels_reply_fixture"])
IDEA = next(i for i in TOP["classes"][CONTRACT["idea"]["class"]]["ideas"] if i["underlying"] == CONTRACT["idea"]["underlying"])


@pytest.fixture(autouse=True)
def exchange_lots(monkeypatch):
    """The exchange lot the route checks every strategy leg against when the F&O risk gate is off
    (desk_strategy_trades.check_exchange_lots -> services/risk_gate/reference.lookup, from fix/desk-paper-safety).
    MOCK — not real data: the lot is the captured idea's own (the 2026-10-21 staging chain), as the reference would read it."""
    from services.risk_gate import reference
    lots = {leg["expiry"]: leg["lot_size"] for leg in IDEA["legs"]}

    async def lookup(underlying, expiries, today):
        return {e: {"listed": True, "lot_size": lots.get(e), "source": reference.BHAVCOPY_SOURCE,
                    "as_of": IDEA["data_as_of"]["chain"], "error": None} for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)


@pytest.fixture(autouse=True)
def underlying_bar(world):
    """MOCK — not real data: one BANKNIFTY end-of-day bar on 21 Oct at the idea's reference price. The universal risk
    service reads the underlying's last close on the server (Phase 1) and refuses when there is none."""
    from tests.test_desk_paper_sim import obar
    world.rows["BANKNIFTY"] = [obar("2026-10-21", 54900.0, 55120.0, 54810.0, 54976.9)]


# ── B-1, B-2: the bodies the button sends open a trade ───────────────────────
@pytest.mark.parametrize("variant", ["body_with_levels", "body_without_levels"])
def test_the_body_the_idea_button_sends_opens_a_strategy_trade_with_its_signal(api, world, variant):
    world.now = CLOCK
    body = copy.deepcopy(CONTRACT[variant])
    r = api.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 201, r.text
    t = r.json()["trade"]
    assert (t["kind"], t["underlying"], t["direction"], t["family"]) == ("strategy", "BANKNIFTY", "bearish", "bear_put_spread")
    [doc] = world.db.trades.docs
    assert doc["status"] == "open" and doc["kind"] == "strategy" and doc["user_id"] == "user_a"
    sig = doc["signal"]
    assert sig["signal_at"] == IDEA["data_as_of"]["chain"] == "2026-10-21"
    assert sig["rule_version"] == TOP["rules_version"] == "regime-fit-v1 (2026-10-22)"
    assert sig["source_refs"] == body["signal"]["source_refs"]
    assert sig["evidence_summary"] == body["signal"]["evidence_summary"] and sig["evidence_summary"].startswith("Fit 92.5")
    assert doc["stop_underlying"] == body.get("stop_underlying") and doc["target_underlying"] == body.get("target_underlying")
    assert [(leg["side"], leg["option_type"], leg["strike"], leg["lots"], leg["lot_size"], leg["entry_price"]) for leg in doc["legs"]] == [
        (leg["side"], leg["option_type"], leg["strike"], leg["quantity"], leg["lot_size"], leg["entry_price"]) for leg in IDEA["legs"]]
    assert doc["reference_price"] == IDEA["reference_price"] and doc["entry_record_hash"]
    assert [e["type"] for e in doc["events"]] == ["created", "entered"]


def test_with_levels_the_trade_carries_the_engines_underlying_stop_and_target_1(api, world):
    world.now = CLOCK
    r = api.post(TRADES_URL, json=copy.deepcopy(CONTRACT["body_with_levels"]), headers=A)
    assert r.status_code == 201, r.text
    [doc] = world.db.trades.docs
    # bearish: the stop above the reference, the target below it (the route's own rule)
    assert doc["target_underlying"] < doc["reference_price"] < doc["stop_underlying"]
    assert (doc["stop_underlying"], doc["target_underlying"]) == (REPLY["underlying"]["stop"], REPLY["underlying"]["target"])


# ── B-3: the pre-fix body is the regression case ─────────────────────────────
def test_the_pre_fix_body_without_a_signal_is_refused_and_nothing_is_stored(api, world):
    world.now = CLOCK
    body = {k: v for k, v in copy.deepcopy(CONTRACT["body_without_levels"]).items() if k != "signal"}
    r = api.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 422 and r.json()["detail"] == "invalid_signal"
    assert world.db.trades.docs == []


# ── B-4, B-5: the browser specs' levels reply is the real engine's, and the body records it ─
def test_the_levels_reply_the_browser_specs_use_is_the_real_engine_answer():
    req = copy.deepcopy(CONTRACT["levels_request"])
    assert strategy_levels.compute(req["payoff"], req["refs"], date(2026, 10, 21)) == REPLY
    assert REPLY["valid"] is True and REPLY["sent_to_broker"] is False


def test_the_body_records_the_levels_the_row_shows_and_none_without_them():
    with_levels, without = CONTRACT["body_with_levels"], CONTRACT["body_without_levels"]
    assert REPLY["underlying"]["view"] == with_levels["direction"] == "bearish"
    assert (with_levels["stop_underlying"], with_levels["target_underlying"]) == (REPLY["underlying"]["stop"], REPLY["underlying"]["target"])
    assert with_levels["signal"]["source_refs"][-1] == {"kind": "strategy_levels", "ref": REPLY["version"], "as_of": "2026-10-21"}
    assert "stop_underlying" not in without and "target_underlying" not in without
    assert all(ref["kind"] != "strategy_levels" for ref in without["signal"]["source_refs"])


# ── B-6: the nightly job asks the engine exactly what the browser asks ───────
def test_the_nightly_job_builds_the_same_levels_request_as_the_browser():
    asked = {"payoff": build.payoff_request_for(IDEA), "refs": build.levels_refs_for(TOP, IDEA["underlying"])}
    assert asked == CONTRACT["levels_request"]
