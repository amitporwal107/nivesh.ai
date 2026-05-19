"""Risk Analyst agent node.

Handles: risk suitability check, portfolio VaR, volatility assessment.
Tools:  services.copilot_tools.risk (get_risk_suitability, get_portfolio_var)
"""
from __future__ import annotations

import logging
import os
from typing import List

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Risk Analyst for Nivesh AI, an Indian investment platform.

You assess portfolio risk using the data in TOOL_DATA below.

Style:
- ≤ 200 words, markdown
- Risk rating: LOW / MEDIUM / HIGH / VERY HIGH with brief justification
- Key risk drivers (top 2-3 bullet points)
- VaR figures: "1-day 95% VaR: ₹X means on a bad day you could lose ₹X"
- Misalignment alerts (if any) with specific suggested action
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_risk_data(state: CopilotState) -> List[ToolResult]:
    results: List[ToolResult] = []
    try:
        import importlib
        risk_mod = importlib.import_module("services.copilot_tools.risk")
        user_id = state.user_id

        # ── Risk suitability ──────────────────────────────────────────────────
        suitability = await risk_mod.get_risk_suitability(user_id)
        results.append(ToolResult(
            ok=suitability.ok,
            tool_name="get_risk_suitability",
            summary=suitability.summary,
            data={
                "risk_rating":          suitability.risk_rating,
                "risk_score":           suitability.risk_score_0_to_10,
                "user_profile":         suitability.user_profile_category,
                "misalignment":         suitability.misalignment,
                **suitability.data,
            },
            rows=suitability.rows,
            widget_type=WidgetType.STRESS_TEST,
            error=suitability.error,
        ))

        # ── Portfolio VaR ─────────────────────────────────────────────────────
        var_result = await risk_mod.get_portfolio_var(user_id, confidence=0.95)
        results.append(ToolResult(
            ok=var_result.ok,
            tool_name="get_portfolio_var",
            summary=var_result.summary,
            data=var_result.data,
            rows=var_result.rows,
            error=var_result.error,
        ))

    except Exception as exc:
        logger.warning("risk data fetch failed: %s", exc)
        results.append(ToolResult(
            ok=False,
            tool_name="risk_tools",
            summary="Risk data unavailable",
            error=str(exc),
        ))

    return results


async def risk_node(state: CopilotState) -> dict:
    tool_results = await _fetch_risk_data(state)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What is my portfolio risk?",
    )

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=0.1,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    suitability_tr = next(
        (r for r in tool_results if r.tool_name == "get_risk_suitability" and r.ok),
        None,
    )
    response = AgentResponse(
        agent=AgentName.RISK,
        text=answer_text,
        widget_type=WidgetType.STRESS_TEST if suitability_tr else WidgetType.NONE,
        widget_data={"rows": suitability_tr.rows, **suitability_tr.data} if suitability_tr else {},
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response":     response,
        "messages":     [AIMessage(content=answer_text)],
    }
