"""The compliance node's answer is the answer the user gets and the one that is saved (routes/chat.py stream_chat).

The defect (audit of 30 Oct): the stream saved and sent the raw LLM tokens; the compliance node's edits (advice scrub,
grounding caveat, 400-word cap) were used only when nothing streamed. Here the engine streams a raw draft that says
"bullish" and "you should buy", and its final response is what the REAL compliance_node makes of that draft.

MOCK — not real data: the draft text, the symbol and the session are invented; the harness is the one of
tests/test_broker_contract_chart.py (fake chat DB, fake user, a fake engine); compliance_node runs for real.
"""
from __future__ import annotations

import asyncio

import pytest

from nidp.services.copilot_agent.nodes.compliance import compliance_node
from nidp.services.copilot_agent.schemas import AgentName, AgentResponse, CopilotState
from routes import chat
from tests.test_broker_contract_chart import _Chunk, chat_db, sib, stream  # noqa: F401  (fixtures)

DRAFT_TOKENS = ["FIXCO looks bullish on the daily chart. ", "You should buy it before results."]
DRAFT = "".join(DRAFT_TOKENS)


def _complied(text: str) -> AgentResponse:
    state = CopilotState(messages=[], user_id="u1", session_id="s1",
                         response=AgentResponse(agent=AgentName.STOCK, text=text))
    return asyncio.run(compliance_node(state))["response"]


class _DraftGraph:
    """Streams the draft token by token, then ends with the compliance node's response."""

    def __init__(self, final):
        self.final = final

    async def astream_events(self, _input, config=None, version=None):
        for tok in DRAFT_TOKENS:
            yield {"event": "on_chat_model_stream", "tags": [], "data": {"chunk": _Chunk(tok)}}
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"response": self.final}}}


@pytest.fixture
def engine(monkeypatch):
    final = _complied(DRAFT)
    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: _DraftGraph(final))
    return final


def test_cc1_the_scrub_changes_the_draft():
    final = _complied(DRAFT)
    assert "bullish" not in final.text.lower() and "you should buy" not in final.text.lower()
    assert "[factual data only — no recommendation]" in final.text
    assert final.text != DRAFT


def test_cc2_done_and_saved_text_are_the_compliance_output(stream, engine):
    frames, saved = stream(message="How is FIXCO doing?")
    streamed = "".join(f["content"] for f in frames if f["type"] == "token")
    assert streamed == DRAFT                                   # tokens still stream live
    done = frames[-1]
    assert done["type"] == "done"
    assert done["content"] == engine.text                      # the final text replaces the draft
    assert saved["content"] == engine.text                     # and is what is saved
    assert "bullish" not in saved["content"].lower()
    assert "Nivesh Copilot does not give buy/sell/hold advice" in saved["content"]


def test_cc3_the_400_word_cap_reaches_the_saved_answer(stream, monkeypatch):
    long_draft = "word " * 450
    final = _complied(long_draft)
    assert final.text.endswith("*(Response truncated for brevity.)*")

    class _Long(_DraftGraph):
        async def astream_events(self, _input, config=None, version=None):
            yield {"event": "on_chat_model_stream", "tags": [], "data": {"chunk": _Chunk(long_draft)}}
            yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"response": self.final}}}

    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: _Long(final))
    frames, saved = stream(message="Tell me everything about FIXCO")
    assert saved["content"] == final.text == frames[-1]["content"]
    assert len(saved["content"].split()) < 410


def test_cc4_an_unchanged_answer_is_sent_once_and_saved_as_streamed(stream):
    # The harness's own engine: "Levels for FIXCO." streams and is also the final text.
    frames, saved = stream(message="Show the FIXCO chart")
    assert [f["content"] for f in frames if f["type"] == "token"] == ["Levels for FIXCO."]   # not doubled
    assert frames[-1]["content"] == saved["content"] == "Levels for FIXCO."


def test_cc5_an_empty_final_text_keeps_the_streamed_answer(stream, monkeypatch):
    class _Empty:
        text = ""
        widget_type = None
        widget_data = None
        agent = "stock_analyst"
        follow_ups = []
    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: _DraftGraph(_Empty()))
    frames, saved = stream(message="How is FIXCO doing?")
    assert saved["content"] == DRAFT == frames[-1]["content"]


def test_cc6_the_prompts_no_longer_ask_for_words_the_scrub_removes():
    from nidp.services.copilot_agent import persona_framing
    from nidp.services.copilot_agent.nodes import compliance, market, stock
    for name, prompt in (("stock", stock._SYSTEM), ("market", market._SYSTEM),
                         ("desk", persona_framing.DESK_ANSWER_STRUCTURE)):
        demands = [line for line in prompt.splitlines() if compliance._ADVICE_RE.search(line)
                   and "never write" not in line.lower() and "never use" not in line.lower()]
        assert demands == [], (name, demands)
    assert "**Trend** — up / down / sideways" in stock._SYSTEM
    assert "4) Upside factors and downside factors." in persona_framing.DESK_ANSWER_STRUCTURE
