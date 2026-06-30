"""Market Analyst agent node.

Handles: market indices, FII/DII flows, macro indicators, breadth, top movers.
Builds a `market_detail` research widget from the NIDP market snapshot
(`/v1/snapshots/market`) + top movers (`/v1/market-pulse/movers`) via
copilot_tools.market_research, and grounds the LLM answer in that data.
"""
from __future__ import annotations

import logging
from typing import List

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Market Analyst for Nivesh AI, an Indian investment platform.

You have a live NSE/BSE market snapshot in the TOOL_DATA block: index levels
(Nifty 50, Bank Nifty, Nifty 500), India VIX, market breadth (advances/declines),
FII/DII cash flows, G-Sec yields, and top movers. Ground every statement in those
numbers.

Style:
- ≤ 200 words, plain text (no markdown)
- Always include a one-line market sentiment call (bullish/bearish/neutral),
  justified by breadth + VIX + flows
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.

If asked about index targets, analyst consensus, or future forecasts, say plainly
we have only historical exchange data and macro indicators — no analyst feeds.
If a specific metric isn't in TOOL_DATA (e.g. global markets, commodities), say so.
""" + ANTI_HALLUCINATION_RULES


def _build_tool_context(results: List[ToolResult]) -> str:
    lines = ["TOOL_DATA:"]
    for tr in results:
        lines.append(f"  [{tr.tool_name}] {tr.as_llm_context()}")
    return "\n".join(lines)


async def market_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What is the market doing today?",
    )

    widget_type = WidgetType.NONE
    widget_data: dict = {}
    tool_results: List[ToolResult] = []
    try:
        import importlib
        mr = importlib.import_module("services.copilot_tools.market_research")
        res = await mr.get_market_research()
        tool_results.append(ToolResult(
            ok=res.ok, tool_name="market_research",
            summary=res.summary, data=res.data, rows=[], error=res.error,
        ))
        if res.ok and res.widget:
            widget_type = WidgetType.MARKET_DETAIL
            widget_data = res.widget
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("market_research failed: %s", exc)
        tool_results.append(ToolResult(
            ok=False, tool_name="market_research",
            summary="Market data unavailable", error=str(exc),
        ))

    # Push the widget first so the client renders it while the narrative streams.
    if widget_type != WidgetType.NONE:
        from .._stream import emit_widget
        await emit_widget(widget_type, widget_data)

    tool_context = _build_tool_context(tool_results)
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
        widget_type=widget_type,
        widget_data=widget_data,
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response": response,
        "messages": [AIMessage(content=answer_text)],
    }
