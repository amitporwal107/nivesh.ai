"""Nivesh Copilot LangGraph graph — wires all agent nodes into a single
compiled graph that can be called from the FastAPI stream_chat endpoint.

Architecture
────────────
  START
    └─► intent_node          ← classifies query, sets CopilotState.intent
          ├─► market_node
          ├─► stock_node
          ├─► mf_node
          ├─► portfolio_node
          ├─► risk_node
          ├─► goal_node
          └─► recommendation_node
                └─► (all specialist nodes) ──► compliance_node ──► END

Usage
─────
  from nidp.services.copilot_agent.graph import build_graph

  graph = build_graph()                    # compile once at startup
  config = {"configurable": {"thread_id": session_id}}
  async for event in graph.astream_events(
      {"messages": [HumanMessage(content=user_msg)], "user_id": uid},
      config=config, version="v2"
  ):
      ...
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .schemas import AgentName, CopilotState

# node imports — each module is a thin async function
from .nodes.intent import intent_node
from .nodes.market import market_node
from .nodes.stock import stock_node
from .nodes.mf import mf_node
from .nodes.portfolio import portfolio_node
from .nodes.risk import risk_node
from .nodes.goal import goal_node
from .nodes.recommendation import recommendation_node
from .nodes.backtest import backtest_node
from .nodes.compliance import compliance_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing function (called after intent_node)
# ---------------------------------------------------------------------------

def _route_after_intent(state: CopilotState) -> str:
    """Map the classified intent to the appropriate specialist node name."""
    agent = (state.intent.agent if state.intent else AgentName.MARKET)
    _MAP = {
        AgentName.MARKET:          "market_node",
        AgentName.STOCK:           "stock_node",
        AgentName.MF:              "mf_node",
        AgentName.PORTFOLIO:       "portfolio_node",
        AgentName.RISK:            "risk_node",
        AgentName.GOAL:            "goal_node",
        AgentName.RECOMMENDATION:  "recommendation_node",
        AgentName.BACKTEST:        "backtest_node",
    }
    destination = _MAP.get(agent, "market_node")
    logger.debug("routing intent=%s → %s", agent, destination)
    return destination


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(*, use_memory: bool = True) -> "CompiledStateGraph":
    """Build and compile the copilot state graph.

    Parameters
    ----------
    use_memory:
        If True (default) wire an in-process MemorySaver checkpointer so
        conversation history persists across turns within the same session.
        Pass False in unit tests where you want stateless invocations.
    """
    builder = StateGraph(CopilotState)

    # ── nodes ───────────────────────────────────────────────────────────────
    builder.add_node("intent_node",         intent_node)
    builder.add_node("market_node",         market_node)
    builder.add_node("stock_node",          stock_node)
    builder.add_node("mf_node",             mf_node)
    builder.add_node("portfolio_node",      portfolio_node)
    builder.add_node("risk_node",           risk_node)
    builder.add_node("goal_node",           goal_node)
    builder.add_node("recommendation_node", recommendation_node)
    builder.add_node("backtest_node",       backtest_node)
    builder.add_node("compliance_node",     compliance_node)

    # ── edges ───────────────────────────────────────────────────────────────
    builder.add_edge(START, "intent_node")

    builder.add_conditional_edges(
        "intent_node",
        _route_after_intent,
        {
            "market_node":         "market_node",
            "stock_node":          "stock_node",
            "mf_node":             "mf_node",
            "portfolio_node":      "portfolio_node",
            "risk_node":           "risk_node",
            "goal_node":           "goal_node",
            "recommendation_node": "recommendation_node",
            "backtest_node":       "backtest_node",
        },
    )

    # all specialist nodes converge to compliance then END
    for node in (
        "market_node", "stock_node", "mf_node", "portfolio_node",
        "risk_node", "goal_node", "recommendation_node", "backtest_node",
    ):
        builder.add_edge(node, "compliance_node")

    builder.add_edge("compliance_node", END)

    # ── compile ─────────────────────────────────────────────────────────────
    checkpointer = MemorySaver() if use_memory else None
    return builder.compile(checkpointer=checkpointer)


# Module-level singleton — imported by the FastAPI route at startup.
# Tests that need a fresh graph should call build_graph() directly.
_graph: "CompiledStateGraph | None" = None


def get_graph() -> "CompiledStateGraph":
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
