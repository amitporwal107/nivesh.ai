"""The Copilot's trade idea for a stock (services/copilot_trade_idea.py and its use in routes/chat.py stream_chat).

Covers TI-1 … TI-12 of test_reports/copilot_trade_idea_20261029.md.

What is replaced, and by what (MOCK — not real data; every symbol, level and id is invented):
  * the desk's plan builder's I/O: `collect_snapshots` (live sources), `build_plan` (returns a canned StrategyPlan in the
    real shape), `attach_symbol_suggestions` / `finish_plan` (identity), `routes.strategy_plan.store_trade_plans`
    (records what it would store), and the risk service's sizing (`copilot_trade_idea._size`);
  * for the stream route: the harness of tests/test_broker_contract_chart.py (fake chat DB, a fake engine that records
    its input, fake user) — the route itself runs for real.
The input normalisation (normalise_inputs), the card, the facts text and the route's wiring run for real.
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from routes import chat
from routes import strategy_plan as plan_route
from services import copilot_trade_idea as ti
from services import strategy_plan as sp
from services.strategy_plan import sources
from tests.test_broker_contract_chart import ENGINE_INPUTS, POSITION, chat_db, sib, stream  # noqa: F401  (fixtures)


# ── TI-1 … TI-3: reading the question ───────────────────────────────────────
@pytest.mark.parametrize("message, persona, desk, expected", [
    ("Tell me about TVSMOTOR", "trader", None, True),
    ("Tell me about TVSMOTOR", None, "trader", True),
    ("Is Reliance a good long-term holding?", "investor", None, False),
    ("What is my SIP plan for HDFC?", "investor", None, False),
    ("How should I trade TVSMOTOR?", "investor", None, True),
    ("entry and stop loss for TCS", None, None, True),
    ("Create a trading plan for INFY", None, None, True),
    ("Is this breakout in TATASTEEL genuine?", None, None, True),
])
def test_ti1_which_questions_are_trading_questions(message, persona, desk, expected):
    assert ti.is_trade_question(message, persona, desk) is expected


@pytest.mark.parametrize("message, expected", [
    ("I expect an upside move in TVSMOTOR next week", ("bullish", True)),
    ("Plan a long trade on TCS", ("bullish", True)),
    ("Is the breakout real? where would I sell at the target", ("bullish", True)),
    ("I think TATASTEEL will fall", ("bearish", True)),
    ("Short INFY", ("bearish", True)),
    ("Buy a put on NIFTY", ("bearish", True)),
    ("Build a bull put spread on NIFTY", ("bullish", True)),
    ("Bear call spread on BANKNIFTY", ("bearish", True)),
    ("RELIANCE looks range-bound", ("neutral", True)),
    ("A short-term trade in HDFCBANK", ("bullish", False)),
    ("Trade plan for TVSMOTOR", ("bullish", False)),
])
def test_ti2_direction_from_the_words(message, expected):
    assert ti.direction_of(message) == expected


def test_ti3_horizon_from_the_words():
    assert ti.horizon_of("An intraday trade on TCS") == "intraday"
    assert ti.horizon_of("A positional trade on TCS for a week") == "positional"
    assert ti.horizon_of("Trade TCS") == "positional"


# ── a canned StrategyPlan in the builder's real shape (MOCK) ─────────────────
def tradeplan(pid, entry=1840.0, stop=1790.0, target=1940.0, state="WAIT_FOR_CONFIRMATION"):
    return {"plan_id": pid, "strategy": {"segment": "cash"},
            "entry": {"price": entry, "order_type": "stop_trigger", "desk_entry_rule": "break_above", "valid_for_sessions": 3,
                      "logic": "MOCK: a close above the 20-session high"},
            "stop": {"price": stop, "method": "structural", "invalidation": "MOCK: a close back below the breakout base"},
            "r_per_unit": entry - stop,
            "targets": [{"name": "t1", "price": target, "r_multiple": 2.0, "primary": True, "rule": "2R"}],
            "eligibility": {"state": state, "reasons": []},
            "evidence": {"items": [{"key": "trend", "label": "Trend", "status": "ok", "direction": "supports",
                                    "text": "MOCK: above a rising 50-day average"},
                                   {"key": "volume", "label": "Volume", "status": "unavailable", "text": None}]},
            "warnings": [{"key": "event", "label": "Event", "status": "flagged", "text": "MOCK: results in 4 sessions"}]}


def strategy_plan(status, n=3):
    cands = [{"id": f"c{i}", "segment": "cash" if i == 1 else "options", "family": "cash_long" if i == 1 else "bull_call_spread",
              "label": "Cash long" if i == 1 else f"Bull call spread {i}", "status": "candidate", "legs": [], "reasons": [],
              "targets": [{"name": "t1", "price": 1940.0, "rule": "2R"}], "trade_plan": tradeplan(f"tp_mock_{i}")}
             for i in range(1, n + 1)]
    cands.append({"id": "c_nolevels", "segment": "futures", "family": "long_future", "label": "Long future",
                  "status": "blocked", "legs": [], "reasons": [{"code": "liquidity", "message": "MOCK thin"}], "targets": [],
                  "trade_plan": None})
    reasons = [] if status == "plan" else [{"code": "needs_confirmation" if status == "wait" else "conflicting_evidence",
                                            "message": f"MOCK reason for {status}"}]
    return {"plan_id": "plan_mock", "status": status, "preferred": "c2" if status == "plan" else None,
            "status_reasons": reasons, "would_change_if": [] if status == "plan" else [f"MOCK: what would change {status}"],
            "summary": {"underlying": "TVSMOTOR", "direction": "bullish", "horizon": "positional", "horizon_days": 10, "segment": "all"},
            "inputs": {"underlying": "TVSMOTOR", "direction": "bullish", "horizon": "positional", "horizon_days": 10,
                       "defaults_applied": ["horizon", "instrument"]},
            "data_as_of": {"price": "2026-10-28", "fno": "2026-10-28"}, "generated_at": "2026-10-29T04:30:00+00:00",
            "candidates": cands}


class Builder:
    def __init__(self):
        self.plan = strategy_plan("plan")
        self.raise_with = None
        self.snapshot_calls = []
        self.stored = []
        self.sized = {"status": "sized", "quantity": 12, "unit": "shares", "estimated_risk_rs": {"total": 640.5},
                      "risk_pct_of_equity": 0.64, "equity_rs": 100000}


@pytest.fixture
def builder(monkeypatch):
    b = Builder()

    async def collect(request, user_id, inputs, today, shared=None):
        if b.raise_with:
            raise b.raise_with
        b.snapshot_calls.append((request, user_id, dict(inputs)))
        return {}

    def build(inputs, snaps, now, today):
        return copy.deepcopy(b.plan)

    async def same(plan, *_a):
        return plan

    async def store(plans, owner):
        b.stored.append(([p["plan_id"] for p in plans if p], owner))

    async def size(tp, user_id):
        return b.sized

    monkeypatch.setattr(sources, "collect_snapshots", collect)
    monkeypatch.setattr(sp, "build_plan", build)
    monkeypatch.setattr(sources, "attach_symbol_suggestions", same)
    monkeypatch.setattr(sources, "finish_plan", same)
    monkeypatch.setattr(plan_route, "store_trade_plans", store)
    monkeypatch.setattr(ti, "_size", size)
    return b


def run(coro):
    return asyncio.run(coro)


# ── TI-4 … TI-8: the builder's answer becomes a card and the facts ──────────
def test_ti4_a_plan_gives_the_card_the_stored_plans_and_the_facts(builder):
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "Trade plan for TVSMOTOR"))
    assert builder.snapshot_calls == [("REQ", "u1", builder.snapshot_calls[0][2])]
    inputs = builder.snapshot_calls[0][2]
    assert (inputs["underlying"], inputs["direction"], inputs["horizon"]) == ("TVSMOTOR", "bullish", "positional")
    assert builder.stored == [(["tp_mock_1", "tp_mock_2", "tp_mock_3"], "u1")]       # as the desk route stores them
    w = idea.widget
    assert w["widget_type"] == "trade_plan" and w["title"] == "Trade idea · TVSMOTOR"
    d = w["data"]
    assert [p["plan_id"] for p in d["plans"]] == ["tp_mock_2", "tp_mock_1", "tp_mock_3"]   # preferred first, at most 3
    assert d["preferred_plan_id"] == "tp_mock_2" and d["plans"][0]["preferred"] is True
    assert (d["symbol"], d["status"], d["direction"], d["direction_stated"], d["horizon"]) == \
        ("TVSMOTOR", "plan", "bullish", False, "positional")
    assert d["data_as_of"] == {"price": "2026-10-28", "fno": "2026-10-28"} and d["defaults_applied"] == ["horizon", "instrument"]
    assert d["sizing"] == "risk_profile" and d["strategy_plan_id"] == "plan_mock"
    c = idea.context
    assert c.startswith("TRADE_PLAN:") and "ASSUMED" in c and "A card with this plan is shown above the answer." in c
    assert "STRATEGY PLAN plan_mock" in c and "Status: plan" in c                        # the desk's own facts text
    assert "entry: 1840 (stop_trigger; desk entry rule break_above; valid for 3 sessions)" in c
    assert "stop: 1790 (method structural) — invalidation: MOCK: a close back below the breakout base" in c
    assert "target t1: 1940 (2R) — primary — 2R" in c
    assert "evidence Trend (supports): MOCK: above a rising 50-day average" in c and "evidence Volume" not in c
    assert "warning Event: MOCK: results in 4 sessions" in c
    assert "Account sizing (risk service, saved risk profile): 12 shares; estimated risk ₹640.5 = 0.64% of paper equity ₹100000." in c


def test_ti4_a_stated_direction_is_not_called_assumed(builder):
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "I expect an upside move, plan a trade"))
    assert idea.widget["data"]["direction_stated"] is True and "ASSUMED" not in idea.context


def test_ti5_a_setup_waiting_for_confirmation_shows_the_card_with_its_reasons(builder):
    builder.plan = strategy_plan("wait")
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR"))
    d = idea.widget["data"]
    assert d["status"] == "wait" and d["preferred_plan_id"] == "tp_mock_1"
    assert d["status_reasons"] == [{"code": "needs_confirmation", "message": "MOCK reason for wait"}]
    assert d["would_change_if"] == ["MOCK: what would change wait"]


@pytest.mark.parametrize("status", ["no_trade", "insufficient_data"])
def test_ti6_no_setup_gives_no_card_and_says_why(builder, status):
    builder.plan = strategy_plan(status)
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR"))
    assert idea.widget is None and idea.status == status
    assert "No card is shown" in idea.context and f"MOCK reason for {status}" in idea.context
    assert f"Would change if: MOCK: what would change {status}" in idea.context
    assert "Account sizing" not in idea.context                                          # nothing to size


def test_ti6_a_plan_without_levels_gives_no_card(builder):
    builder.plan = strategy_plan("plan", n=0)
    builder.plan["preferred"] = None
    assert run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR")).widget is None


def test_ti7_a_failed_or_slow_build_never_raises_and_says_no_plan(builder, monkeypatch):
    builder.raise_with = RuntimeError("MOCK source down")
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR"))
    assert idea.widget is None and "could not be built just now" in idea.context
    builder.raise_with = None
    monkeypatch.setattr(ti, "BUILD_TIMEOUT_S", 0.01)

    async def slow(request, user_id, inputs, today, shared=None):
        await asyncio.sleep(1)
    monkeypatch.setattr(sources, "collect_snapshots", slow)
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR"))
    assert idea.widget is None and "could not be built just now" in idea.context


def test_ti7_sizing_unavailable_is_said_without_a_figure(builder):
    builder.sized = {"status": "unavailable", "reason": "MOCK no profile"}
    idea = run(ti.build("REQ", "u1", "TVSMOTOR", "trade TVSMOTOR"))
    assert "Account sizing: unavailable (MOCK no profile); do not state a quantity or rupee risk." in idea.context


def test_ti8_inputs_the_builder_refuses_give_nothing(builder):
    assert run(ti.build("REQ", "u1", "NOT A SYMBOL!", "trade it")) is None
    assert builder.snapshot_calls == []


# ── TI-9 … TI-11: the stream route ───────────────────────────────────────────
CARD = {"widget_type": "trade_plan", "title": "Trade idea · FIXCO",
        "data": {"symbol": "FIXCO", "status": "plan", "plans": [{"plan_id": "tp_mock_1"}], "preferred_plan_id": "tp_mock_1"},
        "freshness": {"state": "end_of_day"}, "agent": {"id": "stock_analyst"}}


@pytest.fixture
def ideas(monkeypatch):
    calls = []

    async def build(request, user_id, symbol, message):
        calls.append((user_id, symbol, message))
        return ti.TradeIdea(widget=calls_widget[0], context="TRADE_PLAN: MOCK facts for FIXCO", status="plan")
    calls_widget = [CARD]
    monkeypatch.setattr(chat._trade_idea, "build", build)
    monkeypatch.setattr(chat._trade_idea, "symbol_for", lambda message: "FIXCO")
    return calls, calls_widget


def test_ti9_a_trading_question_gets_the_plan_card_first_and_the_engine_gets_the_facts(stream, ideas):
    calls, _ = ideas
    frames, saved = stream(message="Plan a breakout trade for FIXCO", persona="investor")
    assert calls == [("u1", "FIXCO", "Plan a breakout trade for FIXCO")]
    widgets = [f for f in frames if f["type"] == "widget"]
    assert [w["widget_type"] for w in widgets] == ["trade_plan"]                    # the engine's own card is dropped
    kinds = [f["type"] for f in frames]
    assert kinds.index("widget") < kinds.index("token")
    assert saved["widget"]["widget_type"] == "trade_plan"
    engine_input = ENGINE_INPUTS[-1]
    told = engine_input["messages"][-1].content
    assert told.startswith("Plan a breakout trade for FIXCO\n\n") and "TRADE_PLAN: MOCK facts for FIXCO" in told
    from services.llm_safety import wrap_external_data
    assert told == "Plan a breakout trade for FIXCO\n\n" + wrap_external_data("TRADE_PLAN: MOCK facts for FIXCO", source="trade_plan")
    pin = engine_input["pinned_agent"]
    assert getattr(pin, "value", pin) == "stock_analyst"


def test_ti9_no_setup_keeps_the_engines_card_but_still_tells_the_engine(stream, ideas):
    _, widget = ideas
    widget[0] = None
    frames, saved = stream(message="Plan a breakout trade for FIXCO", persona="investor")
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["instrument_detail"]
    assert "TRADE_PLAN: MOCK facts for FIXCO" in ENGINE_INPUTS[-1]["messages"][-1].content


def test_ti10_a_question_that_is_not_about_trading_is_unchanged(stream, ideas):
    calls, _ = ideas
    frames, saved = stream(persona="investor")                                      # "Show the FIXCO chart"
    assert calls == []
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["instrument_detail"]
    assert ENGINE_INPUTS[-1]["messages"][-1].content == "Show the FIXCO chart"


def test_ti10_the_trader_persona_makes_any_stock_question_a_trading_question(stream, ideas):
    calls, _ = ideas
    frames, _ = stream(persona="trader")
    assert calls == [("u1", "FIXCO", "Show the FIXCO chart")]
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["trade_plan"]


def test_ti11_a_question_from_a_position_keeps_the_position_card(stream, ideas):
    calls, _ = ideas
    frames, _ = stream(message="Plan a trade on this", position=POSITION)
    assert calls == []
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["broker_contract_chart"]


# ── TI-12: what the stock analyst is told to do with the plan ────────────────
def test_ti12_the_stock_analyst_has_the_trade_plan_rules():
    from nidp.services.copilot_agent.nodes import stock
    s = stock._SYSTEM
    for phrase in ("**How to trade it (an idea, not a recommendation)**", "Quote ONLY figures that appear in TRADE_PLAN",
                   "entry waits until it is confirmed", "the invalidation (stop) level", "the capital at risk",
                   "If TRADE_PLAN says no card is shown", "never say \"buy now\"", "Do not use \"recommend\""):
        assert phrase in s, phrase
