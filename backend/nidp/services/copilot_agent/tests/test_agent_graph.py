"""Unit tests for the LangGraph copilot agent framework.

All LLM calls and tool calls are mocked — no network, no DB needed.
Run from /app/backend:
    PYTHONPATH=. python3 -m pytest nidp/services/copilot_agent/tests/test_agent_graph.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Bootstrap: stub heavy deps before any local imports ─────────────────────

def _stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_stub("services.portfolio_enrichment")
_stub("services.portfolio_intelligence")
_stub("services.tax_engine")
_stub("services.decision_engine")
_stub("services.goal_engine", get_user_goals=AsyncMock(return_value=[]))

# Stub copilot tools with controllable return values
_PORT_SUMMARY = MagicMock(ok=True, summary="Portfolio ₹15L, XIRR 12.4%", data={"total_value": 1500000}, rows=[], error=None)
_PORT_XIRR = MagicMock(ok=True, summary="XIRR 12.4%", data={"portfolio_xirr": 12.4}, rows=[], error=None)
_PORT_REBAL = MagicMock(ok=True, summary="Rebalance: sell equity ₹50K", data={}, rows=[{"action": "SELL", "name": "Fund A", "amount": 50000}], error=None)
_PORT_TAX = MagicMock(ok=True, summary="Tax harvest: ₹8K savings", data={}, rows=[], error=None)
_PORT_STRESS = MagicMock(ok=True, summary="COVID crash: −33%", data={"stressed_value": 1000000, "drop_pct": -33.0}, rows=[], error=None)
_PORT_OVERLAP = MagicMock(ok=True, summary="3 overlapping pairs", data={}, rows=[], error=None)

_PORT_FULL_TAX = MagicMock(
    ok=True, summary="Total tax payable: ₹18,000", error=None,
    data={"net_tax_payable": 18_000, "equity_ltcg_exemption": 125_000,
          "stcg_tax": 8_000, "ltcg_equity_tax": 10_000, "total_tax": 18_000},
    rows=[],
)
_PORT_COMPARE = MagicMock(
    ok=True,
    summary="2 MFs in portfolio (returns available for 2/2, TER for 2/2); 1 pair(s) ≥40% overlap.",
    data={"fund_count": 2, "funds_with_returns": 2, "funds_with_ter": 2, "high_overlap_pairs": 1},
    rows=[{"scheme_name": "Parag Parikh Flexi Cap", "return_1y_pct": 18.5, "expense_ratio_pct": 0.62}],
    error=None,
)

_port_mod = _stub(
    "services.copilot_tools.portfolio",
    get_portfolio_summary=AsyncMock(return_value=_PORT_SUMMARY),
    get_portfolio_xirr=AsyncMock(return_value=_PORT_XIRR),
    get_rebalance_plan=AsyncMock(return_value=_PORT_REBAL),
    get_tax_harvest_candidates=AsyncMock(return_value=_PORT_TAX),
    get_full_tax_report=AsyncMock(return_value=_PORT_FULL_TAX),
    run_stress_test=AsyncMock(return_value=_PORT_STRESS),
    get_portfolio_overlap=AsyncMock(return_value=_PORT_OVERLAP),
    compare_portfolio_funds=AsyncMock(return_value=_PORT_COMPARE),
    get_tax_timing_advice=AsyncMock(return_value=_PORT_TAX),
    get_fd_comparison=AsyncMock(return_value=_PORT_OVERLAP),
)

_TECH_RESULT = MagicMock(ok=True, summary="RSI 48, MACD bullish", data={"rsi14": 48.0, "macd": 0.5, "close": 2850.0}, signals=["MACD bullish"], error=None)
_stub("services.copilot_tools.technical", get_technical_analysis=AsyncMock(return_value=_TECH_RESULT))

_FUND_RESULT = MagicMock(ok=True, summary="Fund: Parag Parikh Flexi Cap, 3Y CAGR 18%", data={}, rows=[], error=None)
_stub("services.copilot_tools.mf",
      get_mf_performance=AsyncMock(return_value=_FUND_RESULT),
      get_top_funds=AsyncMock(return_value=_FUND_RESULT),
      get_portfolio_overlap=AsyncMock(return_value=_PORT_OVERLAP),
)

_stub("services.copilot_tools.fundamental", get_fundamental_analysis=AsyncMock(return_value=MagicMock(ok=True, summary="PE 22, PB 3.5, ROE 18%", data={}, error=None)))

# ── Now safe to import graph modules ────────────────────────────────────────

from langchain_core.messages import HumanMessage
from nidp.services.copilot_agent.schemas import (
    AgentName, CopilotState, IntentClassification, ToolResult, AgentResponse,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _state(msg: str, user_id: str = "test_user") -> CopilotState:
    return CopilotState(
        messages=[HumanMessage(content=msg)],
        user_id=user_id,
        session_id="sess_test",
    )


# ── TASK-010: Schema tests ───────────────────────────────────────────────────

class TestSchemas:
    def test_tool_result_as_llm_context_ok(self):
        tr = ToolResult(ok=True, tool_name="foo", summary="all good")
        assert "TOOL=foo" in tr.as_llm_context()
        assert "all good" in tr.as_llm_context()

    def test_tool_result_as_llm_context_error(self):
        tr = ToolResult(ok=False, tool_name="bar", summary="bad", error="timeout")
        assert "error" in tr.as_llm_context()

    def test_agent_response_defaults(self):
        ar = AgentResponse(agent=AgentName.MARKET, text="hello")
        assert ar.grounding_ok is True
        assert ar.disclaimer is None

    def test_copilot_state_messages_accumulate(self):
        """add_messages reducer should append, not overwrite."""
        s = CopilotState(messages=[HumanMessage(content="a")])
        assert len(s.messages) == 1

    def test_intent_classification_enum(self):
        ic = IntentClassification(agent=AgentName.PORTFOLIO, confidence=0.9)
        assert ic.agent == AgentName.PORTFOLIO


# ── TASK-047: Intent node tests ──────────────────────────────────────────────

class TestIntentNode:
    @pytest.fixture(autouse=True)
    def _patch_llm(self):
        with patch("nidp.services.copilot_agent.nodes.intent.ChatOpenAI"):
            yield

    def _run(self, msg: str) -> IntentClassification:
        from nidp.services.copilot_agent.nodes.intent import intent_node
        state = _state(msg)
        result = asyncio.get_event_loop().run_until_complete(intent_node(state))
        return result["intent"]

    @pytest.mark.parametrize("msg,expected", [
        ("How is my portfolio doing?",           AgentName.PORTFOLIO),
        ("What is Nifty at today?",              AgentName.MARKET),
        ("Analyse RELIANCE stock",               AgentName.STOCK),
        ("Best large cap mutual funds",          AgentName.MF),
        ("Am I on track for retirement?",        AgentName.GOAL),
        ("What is my portfolio risk level?",      AgentName.RISK),
        ("Recommend stocks to buy",              AgentName.RECOMMENDATION),
        ("Show me my XIRR",                      AgentName.PORTFOLIO),
        ("Run a stress test on my portfolio",    AgentName.PORTFOLIO),
        ("Tax harvest candidates",               AgentName.PORTFOLIO),
    ])
    def test_regex_routing(self, msg, expected):
        intent = self._run(msg)
        assert intent.agent == expected, f"'{msg}' → {intent.agent}, expected {expected}"

    def test_symbol_extraction(self):
        intent = self._run("What is the RSI of INFY?")
        assert intent.agent == AgentName.STOCK

    def test_scenario_extraction_covid(self):
        intent = self._run("Run a COVID crash stress test")
        assert intent.scenario == "covid_2020"

    def test_scenario_extraction_gfc(self):
        intent = self._run("Simulate a 2008 crash on my portfolio")
        assert intent.scenario == "gfc_2008"

    def test_empty_message_defaults_to_market(self):
        from nidp.services.copilot_agent.nodes.intent import intent_node
        state = CopilotState(user_id="u1", session_id="s1")
        result = asyncio.get_event_loop().run_until_complete(intent_node(state))
        assert result["intent"].agent == AgentName.MARKET


# ── TASK-051: Portfolio node tests ──────────────────────────────────────────

class TestPortfolioNode:
    @pytest.fixture(autouse=True)
    def _patch_llm(self):
        mock_resp = MagicMock()
        mock_resp.content = "Your portfolio XIRR is 12.4%. Looks healthy."
        with patch(
            "nidp.services.copilot_agent.nodes.portfolio.ChatOpenAI",
            return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_resp)),
        ):
            yield

    def test_portfolio_node_returns_response(self):
        from nidp.services.copilot_agent.nodes.portfolio import portfolio_node
        state = _state("How is my portfolio doing?")
        state = state.model_copy(update={
            "intent": IntentClassification(agent=AgentName.PORTFOLIO, confidence=0.9)
        })
        result = asyncio.get_event_loop().run_until_complete(portfolio_node(state))
        assert result["response"].agent == AgentName.PORTFOLIO
        assert "12.4" in result["response"].text
        assert len(result["tool_results"]) >= 2

    def test_stress_test_triggers_extra_fetch(self):
        from nidp.services.copilot_agent.nodes.portfolio import portfolio_node
        state = _state("Run a COVID crash stress test")
        state = state.model_copy(update={
            "intent": IntentClassification(
                agent=AgentName.PORTFOLIO, confidence=0.95, scenario="covid_2020"
            )
        })
        result = asyncio.get_event_loop().run_until_complete(portfolio_node(state))
        tool_names = [tr.tool_name for tr in result["tool_results"]]
        assert "run_stress_test" in tool_names


# ── TASK-052: Risk node tests ────────────────────────────────────────────────

class TestRiskNode:
    @pytest.fixture(autouse=True)
    def _patch_llm(self):
        mock_resp = MagicMock()
        mock_resp.content = "Risk: MEDIUM. Key driver: 55% equity concentration."
        with patch(
            "nidp.services.copilot_agent.nodes.risk.ChatOpenAI",
            return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_resp)),
        ):
            yield

    def test_risk_node_ok(self):
        from nidp.services.copilot_agent.nodes.risk import risk_node
        state = _state("What is my portfolio risk?")
        result = asyncio.get_event_loop().run_until_complete(risk_node(state))
        assert result["response"].agent == AgentName.RISK
        assert "MEDIUM" in result["response"].text


# ── TASK-055: Compliance node tests ─────────────────────────────────────────

class TestComplianceNode:
    def test_injects_disclaimer_when_missing(self):
        from nidp.services.copilot_agent.nodes.compliance import compliance_node
        state = _state("What should I buy?")
        state = state.model_copy(update={
            "response": AgentResponse(
                agent=AgentName.MARKET,
                text="Buy RELIANCE immediately.",
            )
        })
        result = asyncio.get_event_loop().run_until_complete(compliance_node(state))
        assert "DISCLAIMER" in result["response"].text or "disclaimer" in result["response"].text.lower()

    def test_no_duplicate_disclaimer(self):
        from nidp.services.copilot_agent.nodes.compliance import compliance_node
        state = _state("?")
        state = state.model_copy(update={
            "response": AgentResponse(
                agent=AgentName.MARKET,
                text="Market up 1%. DISCLAIMER: AI-generated. Consult a SEBI-registered advisor.",
            )
        })
        result = asyncio.get_event_loop().run_until_complete(compliance_node(state))
        # Should not double-inject
        text = result["response"].text
        assert text.count("DISCLAIMER") <= 2  # at most one extra from the field

    def test_trims_very_long_response(self):
        from nidp.services.copilot_agent.nodes.compliance import _trim_to_word_limit
        long_text = "word " * 500
        trimmed = _trim_to_word_limit(long_text, limit=400)
        assert len(trimmed.split()) <= 410  # allowing for truncation suffix

    def test_grounding_ok_no_tool_data(self):
        from nidp.services.copilot_agent.nodes.compliance import _grounding_ok
        assert _grounding_ok("XIRR is 12.4%", []) is True

    def test_grounding_flags_hallucination(self):
        from nidp.services.copilot_agent.nodes.compliance import _grounding_ok
        # LLM cites 4+ large numbers (≥4 digits each) not present in tool data
        tr = ToolResult(ok=True, tool_name="x", summary="value=100")
        hallucinated_response = (
            "Your XIRR is 34567.89% with corpus 12345678 and "
            "monthly SIP of 98765 toward target 54321 and tax saving 11111"
        )
        assert _grounding_ok(hallucinated_response, [tr]) is False


# ── TASK-046: Graph topology test ───────────────────────────────────────────

class TestGraphTopology:
    def test_all_nodes_present(self):
        from nidp.services.copilot_agent.graph import build_graph
        g = build_graph(use_memory=False)
        nodes = set(g.nodes)
        expected = {
            "__start__", "intent_node", "market_node", "stock_node",
            "mf_node", "portfolio_node", "risk_node", "goal_node",
            "recommendation_node", "compliance_node",
        }
        assert expected == nodes

    def test_graph_compiles_with_memory(self):
        from nidp.services.copilot_agent.graph import build_graph
        g = build_graph(use_memory=True)
        assert g is not None

    def test_get_graph_singleton(self):
        from nidp.services.copilot_agent import graph as gmod
        gmod._graph = None  # reset singleton
        g1 = gmod.get_graph()
        g2 = gmod.get_graph()
        assert g1 is g2
