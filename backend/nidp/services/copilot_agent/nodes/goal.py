"""Goal Planner agent node.

Handles: financial goals, retirement corpus, SIP adequacy, goal progress.
Calls: services.goal_engine (if available) + SIP calculator.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Goal Planner for Nivesh AI, an Indian investment platform.

You help users plan for financial goals like retirement, education, home purchase.
Use the data in TOOL_DATA where available.

Style:
- ≤ 250 words, markdown
- Show: Goal | Target ₹ | Current corpus | Gap | Monthly SIP needed
- Assume 12% CAGR for equity, 7% for debt, 10% for balanced
- Use Indian numbering (lakhs, crores)
- End with: DISCLAIMER: AI-generated projection. Actual returns may vary. Consult a financial planner.

If no goal data is available, perform the calculation from the user's stated inputs."""


def _sip_needed(target: float, current: float, years: float, rate_annual: float) -> float:
    """Monthly SIP required to reach target given current corpus."""
    if years <= 0:
        return max(0.0, target - current)
    r = rate_annual / 12
    n = years * 12
    # future value of current corpus
    fv_current = current * (1 + r) ** n
    gap = max(0.0, target - fv_current)
    if r == 0:
        return gap / n
    return gap * r / ((1 + r) ** n - 1)


async def _fetch_goal_data(state: CopilotState) -> List[ToolResult]:
    results: List[ToolResult] = []
    try:
        import importlib
        # try loading goal engine if it exists
        try:
            goal_mod = importlib.import_module("services.goal_engine")
            goals = await goal_mod.get_user_goals(state.user_id)
            results.append(ToolResult(
                ok=True,
                tool_name="get_user_goals",
                summary=f"Found {len(goals)} goals",
                data={"goals": goals},
                rows=goals,
                widget_type=WidgetType.GOAL_TRACKER,
            ))
        except (ImportError, AttributeError, Exception) as exc:
            logger.debug("goal_engine unavailable: %s", exc)
            results.append(ToolResult(
                ok=False,
                tool_name="get_user_goals",
                summary="Goal data unavailable — will compute from user inputs",
                error=str(exc),
            ))

        # also fetch portfolio summary for current corpus estimate
        port_mod = importlib.import_module("services.copilot_tools.portfolio")
        summary = await port_mod.get_portfolio_summary(state.user_id)
        results.append(ToolResult(
            ok=summary.ok,
            tool_name="get_portfolio_summary",
            summary=summary.summary,
            data=summary.data,
            rows=summary.rows,
        ))
    except Exception as exc:
        logger.warning("goal data fetch error: %s", exc)
        results.append(ToolResult(
            ok=False, tool_name="goal_tools",
            summary="Goal/portfolio data unavailable", error=str(exc),
        ))
    return results


async def goal_node(state: CopilotState) -> dict:
    tool_results = await _fetch_goal_data(state)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "Am I on track for my financial goals?",
    )

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.15,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    goal_tr = next((r for r in tool_results if r.widget_type == WidgetType.GOAL_TRACKER and r.ok), None)
    response = AgentResponse(
        agent=AgentName.GOAL,
        text=answer_text,
        widget_type=WidgetType.GOAL_TRACKER if goal_tr else WidgetType.NONE,
        widget_data={"rows": goal_tr.rows, **goal_tr.data} if goal_tr else {},
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response": response,
        "messages": [AIMessage(content=answer_text)],
    }
