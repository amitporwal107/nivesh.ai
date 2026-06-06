"""MF Analyst agent node.

Handles: mutual fund performance, overlap, comparison, fund recommendations.
Calls: copilot_tools.mf  +  copilot_tools.mf_intelligence (4-layer NIDP data)
"""
from __future__ import annotations

import asyncio
import logging
import os

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Mutual Fund Analyst for Nivesh AI, an Indian investment platform.

You have fund performance, risk metrics, category rankings, lifecycle events,
top holdings, and disclosure data in TOOL_DATA. Ground every claim in those
numbers. All figures in INR or % as appropriate.

INTELLIGENCE LAYERS in TOOL_DATA:
1. scorecard — composite_score (0-100), quality_label, quartile ranks
2. lifecycle_events — red-flag events (⚠️): MANAGER_CHANGE, RISK_INCREASE, MERGER, TER_INCREASE
3. top_holdings — top equity positions + sector allocation
4. disclosure — current TER, fund manager, risk-o-meter

When asked "Is this a good fund?" or "Should I continue?":
1. State quality_label and composite_score
2. composite_rank / total_in_category e.g. "#5 of 31 Large Cap funds"
3. Call out any Q1 strengths or Q4 red flags in quartile data
4. Flag ⚠️ red-flag lifecycle events prominently (manager changes, TER hikes, mergers)
5. Mention if TER is creeping up from disclosure trail
6. Give a clear CONTINUE / REVIEW / EXIT recommendation with reasoning

Style:
- ≤ 350 words, markdown
- 1-year, 3-year, 5-year CAGR comparisons where available
- Risk metrics (Sharpe, max drawdown) if available
- Overlap % between funds if user asked about overlap
- Top-3 recommendation table if user asked for best funds
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_mf_intelligence(scheme_code: str) -> list[ToolResult]:
    """Fetch 4-layer MF intelligence from NIDP concurrently."""
    try:
        import importlib
        intel_mod = importlib.import_module("services.copilot_tools.mf_intelligence")
        result = await intel_mod.get_mf_intelligence(scheme_code)

        tool_results = [
            ToolResult(
                ok=result.ok,
                tool_name="mf_scorecard",
                summary=result.summary,
                data={
                    "composite_score":    result.composite_score,
                    "quality_label":      result.quality_label,
                    "composite_rank":     result.composite_rank,
                    "total_in_category":  result.total_in_category,
                    "top_position_pct":   result.top_position_pct,
                    **result.scorecard,
                },
                rows=[],
            ),
            ToolResult(
                ok=True,
                tool_name="mf_lifecycle_events",
                summary=(
                    f"{len(result.events)} lifecycle events, "
                    f"red_flags={result.has_red_flags}"
                ),
                data={"has_red_flags": result.has_red_flags, "count": len(result.events)},
                rows=result.events,
            ),
            ToolResult(
                ok=True,
                tool_name="mf_holdings",
                summary=f"{len(result.top_holdings)} holdings, top sectors: " + ", ".join(
                    f"{s.get('sector','?')} {s.get('total_weight',0):.1f}%"
                    for s in result.top_sectors[:3]
                ),
                data={"top_sectors": result.top_sectors},
                rows=result.top_holdings,
            ),
            ToolResult(
                ok=True,
                tool_name="mf_disclosure",
                summary=(
                    f"TER={result.current_ter:.2f}% " if result.current_ter else "TER=N/A "
                ) + f"manager={result.current_manager or '?'} risk={result.risk_o_meter or '?'}",
                data={
                    "current_ter":     result.current_ter,
                    "current_manager": result.current_manager,
                    "risk_o_meter":    result.risk_o_meter,
                },
                rows=result.disclosures,
            ),
        ]
        return tool_results
    except Exception as exc:
        logger.warning("mf_intelligence fetch failed for %s: %s", scheme_code, exc)
        return [ToolResult(
            ok=False, tool_name="mf_intelligence",
            summary=f"MF intelligence unavailable for {scheme_code}",
            error=str(exc),
        )]


async def _fetch_mf_data(state: CopilotState) -> list[ToolResult]:
    try:
        import importlib
        mf_mod = importlib.import_module("services.copilot_tools.mf")

        user_id    = state.user_id
        scheme_code = state.intent.scheme_code if state.intent else None
        category    = state.intent.category    if state.intent else None

        results: list[ToolResult] = []

        if scheme_code:
            # Fetch basic performance + 4-layer intelligence concurrently
            perf_task  = mf_mod.get_mf_performance(scheme_code)
            intel_task = _fetch_mf_intelligence(scheme_code)
            perf, intel_results = await asyncio.gather(perf_task, intel_task)

            results.append(ToolResult(
                ok=perf.ok, tool_name="get_mf_performance",
                summary=perf.summary, data=perf.data, rows=perf.rows,
                error=perf.error,
            ))
            results.extend(intel_results)

        elif category:
            top = await mf_mod.get_top_funds(category=category)
            results.append(ToolResult(
                ok=top.ok, tool_name="get_top_funds",
                summary=top.summary, data=top.data, rows=top.rows,
                error=top.error,
                widget_type=WidgetType.FUND_COMPARISON,
            ))
        else:
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


def _build_intel_context(results: list[ToolResult]) -> str:
    """Build a compact LLM context block from intelligence ToolResults."""
    lines = ["TOOL_DATA:"]
    for tr in results:
        lines.append(f"  [{tr.tool_name}] {tr.as_llm_context()}")
    return "\n".join(lines)


async def mf_node(state: CopilotState) -> dict:
    tool_results = await _fetch_mf_data(state)
    tool_context = _build_intel_context(tool_results)

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "Tell me about mutual funds",
    )

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=0.1,
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

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
        "response":     response,
        "messages":     [AIMessage(content=answer_text)],
    }
