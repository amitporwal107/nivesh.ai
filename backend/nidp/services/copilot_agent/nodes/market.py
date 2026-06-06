"""Market Analyst agent node.

Handles: market indices, FII/DII flows, macro indicators, sector performance.
Calls DAAS /v1/indices/*, /v1/macro/*, /v1/flows/fii-dii via daas_client.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType
from ..tools.daas_bridge import call_daas

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Market Analyst for Nivesh AI, an Indian investment platform.

You have access to live NSE/BSE indices, FII/DII flows and macro indicators
provided in the TOOL_DATA block below. Ground every statement in those numbers.

Style:
- ≤ 200 words, markdown bullet points
- Always include a one-line market sentiment call (bullish/bearish/neutral)
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.

If asked about index targets, analyst consensus or future market forecasts,
say plainly that we do not have analyst feeds — only historical exchange data
and macro indicators.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_market_data(state: CopilotState) -> List[ToolResult]:
    results: List[ToolResult] = []

    # indices
    idx = await call_daas("GET", "/v1/indices/summary")
    results.append(ToolResult(
        ok=idx.get("ok", False),
        tool_name="get_indices_summary",
        summary=idx.get("summary", "Indices data unavailable"),
        data=idx.get("data", {}),
        rows=idx.get("rows", []),
        widget_type=WidgetType.NONE,
    ))

    # FII/DII flows
    flows = await call_daas("GET", "/v1/flows/fii-dii")
    results.append(ToolResult(
        ok=flows.get("ok", False),
        tool_name="get_fii_dii_flows",
        summary=flows.get("summary", "Flows data unavailable"),
        data=flows.get("data", {}),
        rows=flows.get("rows", []),
    ))

    # macro
    macro = await call_daas("GET", "/v1/macro/latest")
    results.append(ToolResult(
        ok=macro.get("ok", False),
        tool_name="get_macro_indicators",
        summary=macro.get("summary", "Macro data unavailable"),
        data=macro.get("data", {}),
        rows=macro.get("rows", []),
    ))

    return results


def _build_tool_context(results: List[ToolResult]) -> str:
    lines = ["TOOL_DATA:"]
    for tr in results:
        lines.append(f"  [{tr.tool_name}] {tr.as_llm_context()}")
    return "\n".join(lines)


async def market_node(state: CopilotState) -> dict:
    tool_results = await _fetch_market_data(state)
    tool_context = _build_tool_context(tool_results)

    # get latest user message
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What is the market doing today?",
    )

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=temperature_for(0.2),
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    response = AgentResponse(
        agent=AgentName.MARKET,
        text=answer_text,
        widget_type=WidgetType.NONE,
        tool_results=tool_results,
    )

    return {
        "tool_results": tool_results,
        "response": response,
        "messages": [AIMessage(content=answer_text)],
    }
