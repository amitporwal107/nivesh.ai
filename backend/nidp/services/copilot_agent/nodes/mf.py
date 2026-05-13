"""MF Analyst agent node.

Handles: mutual fund performance, overlap, comparison, fund recommendations.
Calls: copilot_tools.mf
"""
from __future__ import annotations

import logging
import os

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Mutual Fund Analyst for Nivesh AI, an Indian investment platform.

You have fund performance, risk metrics and overlap data in TOOL_DATA.
Ground every claim in those numbers. All figures in INR or % as appropriate.

Style:
- ≤ 250 words, markdown
- 1-year, 3-year, 5-year CAGR comparisons where available
- Risk metrics (Sharpe, max drawdown) if available
- Overlap % between funds if user asked about overlap
- Top-3 recommendation table if user asked for best funds
- End with: DISCLAIMER: AI-generated. Mutual Fund investments are subject to market risks.

Never fabricate NAV or return figures."""


async def _fetch_mf_data(state: CopilotState) -> list:
    try:
        import importlib
        mf_mod = importlib.import_module("services.copilot_tools.mf")

        user_id = state.user_id
        scheme_code = state.intent.scheme_code if state.intent else None
        category = state.intent.category if state.intent else None

        results = []

        if scheme_code:
            perf = await mf_mod.get_mf_performance(scheme_code)
            results.append(ToolResult(
                ok=perf.ok, tool_name="get_mf_performance",
                summary=perf.summary, data=perf.data, rows=perf.rows,
                error=perf.error,
            ))
        elif category:
            top = await mf_mod.get_top_funds(category=category)
            results.append(ToolResult(
                ok=top.ok, tool_name="get_top_funds",
                summary=top.summary, data=top.data, rows=top.rows,
                error=top.error,
                widget_type=WidgetType.FUND_COMPARISON,
            ))
        else:
            # default: portfolio overlap if user_id available
            if user_id:
                overlap = await mf_mod.get_portfolio_overlap(user_id)
                results.append(ToolResult(
                    ok=overlap.ok, tool_name="get_portfolio_overlap",
                    summary=overlap.summary, data=overlap.data, rows=overlap.rows,
                    widget_type=WidgetType.OVERLAP_REVEAL,
                ))
            else:
                results.append(ToolResult(
                    ok=False, tool_name="get_mf_performance",
                    summary="No scheme code or category provided",
                    error="missing_params",
                ))
        return results
    except Exception as exc:
        logger.warning("mf data fetch failed: %s", exc)
        return [ToolResult(ok=False, tool_name="mf_tools", summary="MF data unavailable", error=str(exc))]


async def mf_node(state: CopilotState) -> dict:
    tool_results = await _fetch_mf_data(state)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "Tell me about mutual funds",
    )

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    # pick widget type from tool_results if any have one
    widget_type = WidgetType.NONE
    widget_data: dict = {}
    for tr in tool_results:
        if tr.widget_type and tr.widget_type != WidgetType.NONE:
            widget_type = tr.widget_type
            widget_data = {"rows": tr.rows, **tr.data}
            break

    response = AgentResponse(
        agent=AgentName.MF,
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
