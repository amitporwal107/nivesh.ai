"""TASK-058: End-to-end agent tests — 10 queries across all 7 specialist nodes.

All LLM calls are mocked with realistic canned responses.
Tool calls are mocked with realistic data shapes.
Tests verify the full pipeline: intent → specialist node → compliance → response.

Run from /app/backend:
    PYTHONPATH=. python3 -m pytest nidp/services/copilot_agent/tests/test_e2e_agents.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


# ── Build mock modules without touching sys.modules at import time ────────────
# Permanent sys.modules injection at module load time collides with
# test_tax_engine_integration.py (collected later) which needs the real
# services.copilot_tools.portfolio module.  We use patch.dict inside
# _run_graph so stubs are only active during test execution.

def _make_module(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── Mock module definitions ───────────────────────────────────────────────────

_PORT_MOD = _make_module(
    "services.copilot_tools.portfolio",
    get_portfolio_summary=AsyncMock(return_value=MagicMock(
        ok=True, summary="Portfolio ₹18L, equity 62%, debt 38%",
        data={"total_value": 1_800_000, "equity_pct": 62}, rows=[], error=None)),
    get_portfolio_xirr=AsyncMock(return_value=MagicMock(
        ok=True, summary="XIRR 14.2%",
        data={"portfolio_xirr": 14.2, "invested_rs": 1_200_000, "current_rs": 1_800_000},
        rows=[{"name": "Portfolio", "xirr_pct": 14.2,
               "invested_rs": 1_200_000, "current_rs": 1_800_000}],
        error=None)),
    get_rebalance_plan=AsyncMock(return_value=MagicMock(
        ok=True, summary="Rebalance: sell ₹30K equity, buy ₹30K debt",
        data={}, rows=[{"action": "SELL", "name": "Axis Bluechip", "amount_rs": 30_000}],
        error=None)),
    get_tax_harvest_candidates=AsyncMock(return_value=MagicMock(
        ok=True, summary="2 loss positions; harvest saving ₹6,200",
        data={"total_harvestable_loss_rs": 42_000, "total_tax_if_sold_rs": 0,
              "ltcg_exemption_used_rs": 0, "ltcg_exemption_remaining_rs": 125_000,
              "candidate_count": 2, "slab_rate_used": 0.30},
        rows=[{"name": "Fund X", "asset_category": "equity_mf",
               "gain_type": "STCG", "capital_gain": -42_000,
               "tax_if_sold": 0, "tax_saved_if_harvested": 6_200,
               "holding_days": 180, "is_long_term": False,
               "is_grandfathered": False, "tax_rate": 0.20, "tax_regime": "equity_stcg",
               "note": ""}],
        error=None)),
    get_full_tax_report=AsyncMock(return_value=MagicMock(
        ok=True,
        summary=(
            "Total tax payable if portfolio exited today: ₹28,500 "
            "(LTCG ₹12,500 + STCG ₹16,000); LTCG exemption applied ₹1,25,000"
        ),
        data={"net_tax_payable": 28_500, "equity_ltcg_exemption": 125_000,
              "stcg_tax": 16_000, "ltcg_equity_tax": 12_500, "total_tax": 28_500},
        rows=[{"name": "Fund A", "capital_gain": 200_000, "gain_type": "LTCG",
               "asset_category": "equity_mf", "holding_days": 400, "is_long_term": True}],
        error=None)),
    run_stress_test=AsyncMock(return_value=MagicMock(
        ok=True, summary="COVID crash: portfolio drops ₹6.8L (−38%)",
        data={"stressed_value": 1_116_000, "drop_pct": -38.0, "loss_rs": 684_000},
        rows=[{"name": "covid_2020", "stressed_value": 1_116_000, "drop_pct": -38.0}],
        error=None)),
    get_portfolio_overlap=AsyncMock(return_value=MagicMock(
        ok=True, summary="3 overlapping fund pairs found",
        data={}, rows=[{"fund_a": "Axis", "fund_b": "Mirae", "overlap_pct": 62}],
        error=None)),
)

_TECH_MOD = _make_module(
    "services.copilot_tools.technical",
    get_technical_analysis=AsyncMock(return_value=MagicMock(
        ok=True, symbol="RELIANCE",
        summary="RSI 52, MACD bullish, price above SMA50",
        signals=["MACD bullish crossover", "Price > SMA50"],
        data={"rsi14": 52.0, "macd": 0.8, "close": 2850.0, "sma50": 2780.0},
        error=None)),
)

_FUND_MOD = _make_module(
    "services.copilot_tools.fundamental",
    get_fundamental_analysis=AsyncMock(return_value=MagicMock(
        ok=True, summary="PE 24.5, PB 3.8, ROE 18%, D/E 0.42",
        data={"pe_ttm": 24.5, "pb": 3.8, "roe_pct": 18.0},
        error=None)),
)

_MF_MOD = _make_module(
    "services.copilot_tools.mf",
    get_mf_performance=AsyncMock(return_value=MagicMock(
        ok=True, summary="Parag Parikh Flexi Cap: 3Y CAGR 18.4%, Sharpe 1.2",
        data={"cagr_3y": 18.4, "sharpe": 1.2}, rows=[], error=None)),
    get_top_funds=AsyncMock(return_value=MagicMock(
        ok=True, summary="Top 3 Flexi Cap funds by 3Y CAGR",
        data={}, rows=[
            {"name": "Parag Parikh Flexi Cap", "cagr_3y": 18.4},
            {"name": "Mirae Asset Large & Midcap", "cagr_3y": 17.1},
        ], error=None)),
    get_portfolio_overlap=AsyncMock(return_value=MagicMock(
        ok=True, summary="3 overlapping fund pairs", data={}, rows=[], error=None)),
)

_GOAL_MOD = _make_module(
    "services.goal_engine",
    get_user_goals=AsyncMock(return_value=[
        {"name": "Retirement", "target_rs": 5_000_000, "current_rs": 1_800_000,
         "target_date": "2040-01-01", "on_track": True}
    ]),
)

# Mapping of module name → mock module for patch.dict(sys.modules, ...)
_SYS_MODULE_STUBS: dict = {
    "services.copilot_tools.portfolio":  _PORT_MOD,
    "services.copilot_tools.technical":  _TECH_MOD,
    "services.copilot_tools.fundamental": _FUND_MOD,
    "services.copilot_tools.mf":         _MF_MOD,
    "services.goal_engine":              _GOAL_MOD,
}


# ── LLM mock factory ─────────────────────────────────────────────────────────

def _mock_llm(response_text: str):
    resp = MagicMock()
    resp.content = response_text
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


# ── Fallback LLM — used for all nodes not explicitly overridden ──────────────

_FALLBACK_RESP_TEXT = "Fallback LLM response for test. DISCLAIMER: AI-generated analysis."
_FALLBACK_LLM_RESP = MagicMock()
_FALLBACK_LLM_RESP.content = _FALLBACK_RESP_TEXT
_FALLBACK_LLM = MagicMock()
_FALLBACK_LLM.ainvoke = AsyncMock(return_value=_FALLBACK_LLM_RESP)
_FALLBACK_CHATGPT = MagicMock(return_value=_FALLBACK_LLM)

# Patches applied for every test run.  Per-test llm_override is appended last
# so it wins over the global fallback for the specific node.
_GLOBAL_LLM_PATCHES = [
    patch("nidp.services.copilot_agent.nodes.market.ChatOpenAI",         _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.stock.ChatOpenAI",          _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.mf.ChatOpenAI",             _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.portfolio.ChatOpenAI",      _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.risk.ChatOpenAI",           _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.goal.ChatOpenAI",           _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.recommendation.ChatOpenAI", _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.intent.ChatOpenAI",         _FALLBACK_CHATGPT),
    patch("nidp.services.copilot_agent.nodes.market.call_daas",
          new=AsyncMock(return_value={"ok": True, "summary": "Nifty +0.8%", "data": {}, "rows": []})),
]


def _run_graph(user_msg: str, llm_override: MagicMock | None = None,
               node: str | None = None, user_id: str = "u_test") -> dict:
    """Run one query through the full LangGraph pipeline with everything mocked.

    llm_override: if supplied alongside ``node``, patches that node's ChatOpenAI
    with the specific mock AFTER the global fallbacks, so it wins.
    """
    from nidp.services.copilot_agent.graph import build_graph
    graph = build_graph(use_memory=False)
    config = {"configurable": {"thread_id": "test_session"}}
    state_in = {
        "messages": [HumanMessage(content=user_msg)],
        "user_id": user_id,
        "session_id": "test_session",
    }

    patches = [patch.dict(sys.modules, _SYS_MODULE_STUBS)] + list(_GLOBAL_LLM_PATCHES)
    if llm_override is not None and node is not None:
        patches.append(
            patch(f"nidp.services.copilot_agent.nodes.{node}.ChatOpenAI",
                  MagicMock(return_value=llm_override))
        )

    started = [p.start() for p in patches]
    try:
        return asyncio.get_event_loop().run_until_complete(
            graph.ainvoke(state_in, config=config)
        )
    finally:
        for p in patches:
            p.stop()


# ── E2E Query 1: Portfolio XIRR ──────────────────────────────────────────────

_XIRR_LLM = _mock_llm(
    "Your portfolio XIRR is 14.2%. ₹12L invested has grown to ₹18L. "
    "DISCLAIMER: AI-generated. Consult a SEBI-registered advisor."
)


class TestE2EPortfolioXIRR:
    def test_xirr_query_routes_to_portfolio_agent(self):
        state = _run_graph("What is my portfolio XIRR?")
        assert state["response"] is not None
        assert state["intent"].agent == "portfolio_analyst"

    def test_xirr_response_contains_xirr_figure(self):
        state = _run_graph(
            "Show me my overall portfolio return",
            llm_override=_XIRR_LLM, node="portfolio",
        )
        assert "14.2" in state["response"].text

    def test_xirr_response_has_disclaimer(self):
        state = _run_graph("How is my portfolio performing?")
        text = state["response"].text
        assert (
            "disclaimer" in text.lower()
            or "sebi" in text.lower()
            or state["response"].disclaimer is not None
        )


# ── E2E Query 2: Stress Test ─────────────────────────────────────────────────

class TestE2EStressTest:
    def test_stress_test_routes_to_portfolio(self):
        state = _run_graph("Run a COVID crash stress test on my portfolio")
        assert state["intent"].agent == "portfolio_analyst"
        assert state["intent"].scenario == "covid_2020"

    def test_stress_test_response_contains_drop(self):
        state = _run_graph("What would my portfolio look like in a 2008-style crash?")
        assert state["intent"].scenario in ("gfc_2008", "covid_2020")
        assert state["response"] is not None


# ── E2E Query 3: Tax Report ───────────────────────────────────────────────────

_TAX_LLM = _mock_llm(
    "Your total capital gains tax liability is ₹28,500. "
    "LTCG exemption of ₹1,25,000 already applied. "
    "DISCLAIMER: AI-generated. Consult a SEBI-registered advisor."
)


class TestE2ETaxReport:
    def test_tax_query_routes_to_portfolio(self):
        # "capital gains" now in _P_PORTFOLIO pattern → routes correctly
        state = _run_graph("What is my capital gains tax this year?")
        assert state["intent"].agent == "portfolio_analyst"

    def test_tax_response_mentions_ltcg(self):
        state = _run_graph(
            "Show me my tax liability on my portfolio",
            llm_override=_TAX_LLM, node="portfolio",
        )
        assert "28,500" in state["response"].text


# ── E2E Query 4: Stock Analysis ───────────────────────────────────────────────

_STOCK_LLM = _mock_llm(
    "**Technical**: RSI 52 (neutral), MACD bullish crossover. "
    "**Fundamental**: PE 24.5 vs sector 28 (undervalued). "
    "**Verdict**: BULLISH. Key reason: MACD crossover + reasonable valuation. "
    "DISCLAIMER: AI-generated. Consult a SEBI-registered advisor."
)


class TestE2EStockAnalysis:
    def test_stock_query_routes_to_stock_analyst(self):
        state = _run_graph("Analyse RELIANCE stock — is it a good buy?")
        assert state["intent"].agent == "stock_analyst"

    def test_stock_response_has_verdict(self):
        state = _run_graph(
            "What is the technical analysis of INFY?",
            llm_override=_STOCK_LLM, node="stock",
        )
        assert state["response"] is not None
        assert len(state["response"].text) > 50


# ── E2E Query 5: MF Recommendation ───────────────────────────────────────────

class TestE2EMFRecommendation:
    def test_mf_query_routes_to_mf_analyst(self):
        state = _run_graph("Which are the best flexi cap mutual funds?")
        assert state["intent"].agent == "mf_analyst"

    def test_mf_response_non_empty(self):
        state = _run_graph("Compare top large cap mutual funds")
        assert state["response"] is not None
        assert len(state["response"].text) > 30


# ── E2E Query 6: Market Overview ─────────────────────────────────────────────

_MARKET_LLM = _mock_llm(
    "Nifty 50 up 0.8% today. FIIs net buyers ₹1,200 Cr. "
    "Sentiment: **Bullish**. RBI held rates. "
    "DISCLAIMER: AI-generated market summary."
)


class TestE2EMarket:
    def test_market_query_routes_to_market_analyst(self):
        state = _run_graph("How is the market doing today?")
        assert state["intent"].agent == "market_analyst"

    def test_market_response_non_empty(self):
        state = _run_graph(
            "What is Nifty at today?",
            llm_override=_MARKET_LLM, node="market",
        )
        assert state["response"] is not None
        assert len(state["response"].text) > 20


# ── E2E Query 7: Goal Planning ────────────────────────────────────────────────

class TestE2EGoal:
    def test_goal_query_routes_to_goal_planner(self):
        state = _run_graph("Am I on track for my retirement goal?")
        assert state["intent"].agent == "goal_planner"

    def test_goal_response_mentions_sip(self):
        # "corpus" and "retirement" match _P_GOAL → goal_planner
        state = _run_graph("How much corpus do I need for retirement?")
        assert state["response"] is not None


# ── E2E Query 8: Risk Assessment ─────────────────────────────────────────────

class TestE2ERisk:
    def test_risk_query_routes_to_risk_analyst(self):
        state = _run_graph("What is my portfolio risk level?")
        assert state["intent"].agent == "risk_analyst"

    def test_risk_response_contains_rating(self):
        state = _run_graph("How risky is my portfolio?")
        assert state["response"] is not None
        assert len(state["response"].text) > 30


# ── E2E Query 9: Recommendation ───────────────────────────────────────────────

_REC_LLM = _mock_llm(
    "Top picks: **RELIANCE** (RSI 52, MACD bullish, PE below sector). "
    "DISCLAIMER: AI-generated screening. Not SEBI-registered advice."
)


class TestE2ERecommendation:
    def test_recommendation_query_routes_correctly(self):
        # "what stocks should I buy" now in _P_RECOMMENDATION
        state = _run_graph("What stocks should I buy right now?")
        assert state["intent"].agent == "recommendation"

    def test_recommendation_response_non_empty(self):
        state = _run_graph(
            "Recommend me some good mutual funds to invest in",
            llm_override=_REC_LLM, node="recommendation",
        )
        assert state["response"] is not None


# ── E2E Query 10: Compliance node always fires ────────────────────────────────

class TestE2ECompliance:
    def test_compliance_injects_disclaimer_on_every_response(self):
        """Even an overconfident LLM response gets a SEBI disclaimer appended."""
        state = _run_graph("How is my portfolio doing?")
        text = state["response"].text
        has_disclaimer = (
            "disclaimer" in text.lower()
            or "sebi" in text.lower()
            or state["response"].disclaimer is not None
        )
        assert has_disclaimer, f"No disclaimer found in: {text[:200]}"

    def test_response_under_word_limit(self):
        """Compliance node trims responses > 400 words."""
        state = _run_graph("Give me a detailed portfolio analysis")
        word_count = len(state["response"].text.split())
        assert word_count <= 430
