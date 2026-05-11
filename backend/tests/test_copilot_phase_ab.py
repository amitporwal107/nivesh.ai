"""Phase A/B regression tests for Copilot Intelligence Layer.

Covers:
  - Agent intent routing determinism (10 canonical phrases).
  - Model picker default + lookup.
  - Widget envelope shape contracts (Pydantic round-trip).

These tests are pure-Python — no DB, no LLM. They lock the contracts the
frontend depends on so a future agent can't quietly break them.
"""
import pytest
from services.copilot_agents import (
    route_intent, agent_metadata, get_agent,
    model_metadata, resolve_model,
)
from models_copilot_widgets import (
    WidgetEnvelope, FreshnessChip, AgentInfo,
    FundCardData, MarketBriefData, MarketBriefIndex,
    CompareTableData, CompareRow, SipPlanData, SipPlanAllocation,
)


# ── 1. Agent router ─────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("How is my portfolio doing?",                       "portfolio_analyzer"),
    ("Tell me about Parag Parikh Flexi Cap",              "mf_research"),
    ("Compare Parag Parikh and Quant Flexi Cap",          "mf_research"),
    ("What happened in the markets today?",               "market_strategist"),
    ("Which sectors are leading?",                        "market_strategist"),
    ("What can I harvest before year-end?",               "tax_agent"),
    ("How much LTCG do I have this FY?",                  "tax_agent"),
    ("Am I taking too much risk?",                        "compliance_agent"),
    ("Generate my Q4 portfolio summary",                  "report_generator"),
    ("Show me a rebalance plan",                          "portfolio_analyzer"),
])
def test_route_intent_canonical(message, expected):
    assert route_intent(message) == expected


def test_route_intent_empty_falls_back():
    assert route_intent("") == "portfolio_analyzer"


def test_route_intent_unknown_falls_back_to_mf_research():
    # No portfolio cue, no agent trigger
    assert route_intent("Hello there friend") == "mf_research"


# ── 2. Agent catalog ───────────────────────────────────────────

def test_agent_metadata_includes_seven_agents():
    agents = agent_metadata()
    ids = {a["id"] for a in agents}
    assert ids == {
        "auto", "portfolio_analyzer", "mf_research", "market_strategist",
        "tax_agent", "compliance_agent", "report_generator",
    }
    # Every agent has the required keys
    for a in agents:
        assert {"id", "label", "icon", "one_liner", "triggers", "default_suggestions"} <= set(a.keys())


def test_get_agent_returns_spec():
    spec = get_agent("mf_research")
    assert spec is not None
    assert spec.label == "Mutual Fund Research"
    assert get_agent("does_not_exist") is None


# ── 3. Model picker ────────────────────────────────────────────

def test_model_default_is_gpt_4o():
    default = resolve_model(None)
    assert default.id == "gpt-4o"
    assert default.is_default is True


def test_model_lookup_known():
    spec = resolve_model("claude-sonnet-4-5")
    assert spec.provider == "anthropic"
    assert spec.underlying == "claude-sonnet-4-5-20250929"


def test_model_lookup_unknown_falls_back_to_default():
    spec = resolve_model("totally-made-up-llm")
    assert spec.id == "gpt-4o"


def test_model_metadata_includes_three():
    models = model_metadata()
    assert len(models) == 3
    ids = {m["id"] for m in models}
    assert ids == {"gpt-4o", "claude-sonnet-4-5", "gemini-2.5-flash"}


# ── 4. Widget envelope contracts ───────────────────────────────

def _base_envelope_kwargs(kind):
    return dict(
        kind=kind, title="Test",
        freshness=FreshnessChip(state="cached", source=["test"]),
        agent=AgentInfo(id="mf_research", label="Mutual Fund Research", version="v1"),
    )


def test_fund_card_envelope_roundtrip():
    env = WidgetEnvelope(
        **_base_envelope_kwargs("fund_card"),
        data=FundCardData(
            scheme_name="Parag Parikh Flexi Cap",
            verdict="Strong Buy",
            verdict_score=88,
            returns={"1Y": 28.2, "3Y": 19.4, "5Y": 17.4},
        ).model_dump(),
    )
    d = env.model_dump()
    assert d["kind"] == "fund_card"
    assert d["data"]["scheme_name"] == "Parag Parikh Flexi Cap"
    # Re-validate
    env2 = WidgetEnvelope(**d)
    assert env2.kind == "fund_card"


def test_market_brief_envelope_roundtrip():
    env = WidgetEnvelope(
        **_base_envelope_kwargs("market_brief"),
        data=MarketBriefData(
            indices=[MarketBriefIndex(name="Nifty 50", value=24180.5, change_pct=0.42)],
            summary_bullets=["IT pack heavy on weak guidance"],
        ).model_dump(),
    )
    d = env.model_dump()
    assert d["data"]["indices"][0]["name"] == "Nifty 50"
    assert d["data"]["summary_bullets"][0].startswith("IT pack")


def test_compare_table_envelope_roundtrip():
    env = WidgetEnvelope(
        **_base_envelope_kwargs("compare_table"),
        data=CompareTableData(
            funds=["A", "B"],
            rows=[
                CompareRow(metric="1Y return %", values=[28.2, 24.1], best_index=0, worst_index=1),
            ],
            verdict="A leads",
        ).model_dump(),
    )
    d = env.model_dump()
    assert len(d["data"]["funds"]) == 2
    assert d["data"]["rows"][0]["best_index"] == 0


def test_sip_plan_envelope_roundtrip():
    env = WidgetEnvelope(
        **_base_envelope_kwargs("sip_plan"),
        data=SipPlanData(
            monthly_budget=50000,
            allocations=[
                SipPlanAllocation(scheme_name="Parag Parikh", monthly_amount=25000, rationale="50%"),
            ],
        ).model_dump(),
    )
    d = env.model_dump()
    assert d["data"]["monthly_budget"] == 50000


def test_envelope_partial_flag_defaults_false():
    env = WidgetEnvelope(
        **_base_envelope_kwargs("fund_card"),
        data={"scheme_name": "x"},
    )
    assert env.partial is False
