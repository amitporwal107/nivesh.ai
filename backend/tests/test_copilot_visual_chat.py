"""The visual answer in the chat stream (routes/chat.py stream_chat, the pre-step; services/copilot_visual.prepare).

Covers CH-1 … CH-5 of test_reports/dtc_visual_backend_20261030.md. The route runs for real on the harness of
tests/test_broker_contract_chart.py (fake chat DB, a fake engine that records its input, fake user). MOCK — not real
data: the visual readers (tests/test_copilot_visual.Src) and the desk plan builder are replaced.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from routes import chat
from services import copilot_trade_idea as ti
from services import copilot_visual as visual
from tests.test_broker_contract_chart import ENGINE_INPUTS, POSITION, chat_db, sib, stream  # noqa: F401  (fixtures)
from tests.test_copilot_visual import Src, splan


@pytest.fixture
def world(monkeypatch):
    s = Src(monkeypatch)
    s.plans = []

    async def build_plan(request, user_id, symbol, message):
        s.plans.append((user_id, symbol, message))
        return SimpleNamespace(plan=splan("plan"), widget={"widget_type": "trade_plan", "data": {"symbol": symbol}},
                               context=f"TRADE_PLAN: MOCK facts for {symbol}", status="plan", sized=None)
    monkeypatch.setattr(ti, "build", build_plan)
    monkeypatch.setattr(ti, "symbol_for", lambda message: "FIXCO")
    return s


def widgets(frames):
    return [f for f in frames if f["type"] == "widget"]


def pin(n=-1):
    p = ENGINE_INPUTS[n]["pinned_agent"]
    return getattr(p, "value", p)


def test_ch1_a_market_question_gets_the_dashboard_first_and_the_market_analyst(stream, world):
    frames, saved = stream(message="What is the market view today?", persona="trader")
    w = widgets(frames)
    assert [x["widget_type"] for x in w] == ["visual_answer"]                     # the engine's own card is not sent
    assert w[0]["data"]["intent"] == "market_view" and w[0]["data"]["schema"] == "visual-answer-v1"
    assert w[0]["title"] == "Market view · Nifty and Bank Nifty" and w[0]["agent"]["id"] == "market_analyst"
    kinds = [f["type"] for f in frames]
    assert kinds.index("widget") < kinds.index("token")
    assert saved["widget"]["widget_type"] == "visual_answer" and saved["widget"]["data"]["intent"] == "market_view"
    told = ENGINE_INPUTS[-1]["messages"][-1].content
    assert told.startswith("What is the market view today?\n\n") and 'source="visual_answer">VISUAL_ANSWER (market_view)' in told
    assert "TRADE_PLAN" not in told and world.plans == []                          # the trader persona did not build a plan
    assert pin() == "market_analyst"


@pytest.mark.parametrize("message, agent", [("Where is smart money moving?", "market_analyst"),
                                            ("Which breakouts are confirmed?", "market_analyst"),
                                            ("Today's top 5 opportunities", "market_analyst"),
                                            ("Which stocks have unusual volume?", "market_analyst"),
                                            ("What is the expected move in NIFTY?", "market_analyst")])
def test_ch1_each_list_and_market_intent_is_pinned(stream, world, message, agent):
    frames, _ = stream(message=message, persona="trader")
    assert [x["widget_type"] for x in widgets(frames)] == ["visual_answer"]
    assert pin() == agent and world.plans == []                                     # NIFTY is never a stock to plan


def test_ch2_a_stock_decision_builds_the_plan_once_and_sends_one_card(stream, world):
    frames, saved = stream(message="Is RELIANCE a buy now?", persona="trader")
    assert world.plans == [("u1", "RELIANCE", "Is RELIANCE a buy now?")]
    w = widgets(frames)
    assert [x["widget_type"] for x in w] == ["visual_answer"]                     # no separate trade_plan card
    data = w[0]["data"]
    assert data["intent"] == "stock_decision" and data["decision"]["status"] == "setup_ready"
    assert [b["plan_id"] for b in data["blocks"] if b["type"] == "trade_plan"] == ["tp_mock_1"]
    told = ENGINE_INPUTS[-1]["messages"][-1].content
    assert 'source="visual_answer">VISUAL_ANSWER for RELIANCE (stock_decision)' in told
    assert "TRADE_PLAN: MOCK facts for RELIANCE" in told
    assert pin() == "stock_analyst" and w[0]["agent"]["id"] == "stock_analyst"


def test_ch2_this_stock_takes_the_threads_stock(stream, world, chat_db):
    chat_db.chat_messages.docs.append({"user_id": "u1", "session_id": "s1", "role": "assistant", "content": "…",
                                       "created_at": "2026-10-30T04:00:00+00:00",
                                       "widget": {"widget_type": "trade_plan", "data": {"symbol": "TVSMOTOR"}}})
    frames, _ = stream(message="Is this stock a buy now?", persona="trader")
    assert world.plans == [("u1", "TVSMOTOR", "Is this stock a buy now?")]
    assert widgets(frames)[0]["data"]["decision"]["plan_id"] == "tp_mock_1"
    assert pin() == "stock_analyst"


def test_ch3_a_question_with_no_intent_takes_todays_path(stream, world):
    frames, saved = stream(persona="investor")                                     # "Show the FIXCO chart"
    assert [x["widget_type"] for x in widgets(frames)] == ["instrument_detail"]
    assert ENGINE_INPUTS[-1]["messages"][-1].content == "Show the FIXCO chart" and pin() is None
    assert world.calls == [] and world.plans == []


def test_ch4_a_builder_that_raises_takes_todays_path(stream, world, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("MOCK builder fault")
    monkeypatch.setattr(visual, "build", boom)
    frames, _ = stream(message="What is the market view today?", persona="investor")
    assert [x["widget_type"] for x in widgets(frames)] == ["instrument_detail"]
    assert "VISUAL_ANSWER" not in ENGINE_INPUTS[-1]["messages"][-1].content and pin() is None


def test_ch4_a_stock_answer_that_fails_keeps_the_plan_card_built_once(stream, world, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("MOCK builder fault")
    monkeypatch.setattr(visual, "build", boom)
    frames, _ = stream(message="Is RELIANCE a buy now?", persona="trader")
    assert len(world.plans) == 1 and [x["widget_type"] for x in widgets(frames)] == ["trade_plan"]
    assert pin() == "stock_analyst"


def test_ch5_a_position_question_and_a_client_pin_skip_the_visual_step(stream, world):
    frames, _ = stream(message="What is the market view today?", position=POSITION, persona="trader")
    assert [x["widget_type"] for x in widgets(frames)] == ["broker_contract_chart"] and world.calls == []
    frames, _ = stream(message="What is the market view today?", agent="stocks_insights", persona="trader")
    assert "visual_answer" not in [x["widget_type"] for x in widgets(frames)] and world.calls == []


# ── CE-1 … CE-4: what the chat says when an answer could not be finished (owner, 31 Oct 2026) ──────────────────────
# The staging Copilot's model runs through a gateway under one Claude login whose 5-hour usage limit the development sessions
# share, so the limit is the commonest reason a chat "did not finish". MOCK exception texts follow the gateway's real one.
from services import chat_errors as ce                                                  # noqa: E402

REAL = ("Error code: 502 - {'error': {'message': \"Claude Code failed: You've hit your 5-hour limit · resets 10:50am "
        "(Asia/Kolkata)\", 'type': 'api_error', 'code': 502}}")


def test_ce1_the_usage_limit_names_itself_and_the_reset_time():
    msg = ce.friendly_error(Exception(REAL))
    assert "usage limit" in msg and "10:50 AM IST" in msg
    assert "figures and charts" in msg and "not affected" in msg
    assert "trouble connecting" not in msg


@pytest.mark.parametrize("text, when", [
    ("You've hit your 5-hour limit · resets 9pm (Asia/Kolkata)", "9:00 PM IST"),
    ("You've hit your 5-hour limit · resets 12:05pm (Asia/Kolkata)", "12:05 PM IST"),
    ("You've hit your 5-hour limit · resets 3am (UTC)", None),            # another zone: no time is claimed
    ("usage limit reached", None),                                              # no time in the text
])
def test_ce2_the_reset_time_is_read_only_when_it_is_in_ist(text, when):
    msg = ce.friendly_error(RuntimeError(text))
    assert "usage limit" in msg
    assert (f"around {when}" in msg) if when else ("around" not in msg)


@pytest.mark.parametrize("e", [RuntimeError("boom"), TimeoutError("read timed out"), ValueError("Error code: 502 - bad gateway")])
def test_ce3_any_other_error_keeps_the_generic_text(e):
    assert ce.friendly_error(e) == ce.GENERIC


def test_ce4_the_text_never_carries_the_raw_error():
    msg = ce.friendly_error(Exception(REAL))
    assert "502" not in msg and "api_error" not in msg and "Claude Code" not in msg


def test_ce5_a_usage_limit_error_reaches_the_user_with_its_reset_time_and_the_dashboard_stays(stream, world, monkeypatch):
    """The owner's screenshot: 'DID NOT FINISH · trouble connecting'. The dashboard is sent before the model runs, so it is kept;
    the message says why and when, and the raw gateway error is not shown."""
    from routes import chat

    class LimitGraph:
        async def astream_events(self, _input, config=None, version=None):
            raise Exception(REAL)
            yield                                                                      # a generator, so `async for` reaches the raise
    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: LimitGraph())
    frames, saved = stream(message="What is the market view today?", persona="trader")
    assert [x["widget_type"] for x in widgets(frames)] == ["visual_answer"]
    err = [f for f in frames if f["type"] == "error"]
    assert len(err) == 1 and "usage limit" in err[0]["content"] and "10:50 AM IST" in err[0]["content"]
    assert "502" not in err[0]["content"] and "Claude Code" not in err[0]["content"]
    assert saved["content"] == err[0]["content"]                                      # what is saved is what was shown


def test_ce6_any_other_engine_error_keeps_the_generic_text(stream, world, monkeypatch):
    from routes import chat

    class Broken:
        async def astream_events(self, _input, config=None, version=None):
            raise RuntimeError("MOCK engine fault")
            yield
    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: Broken())
    frames, _ = stream(message="What is the market view today?", persona="trader")
    assert [f["content"] for f in frames if f["type"] == "error"] == [ce.GENERIC]
