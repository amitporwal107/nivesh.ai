"""Goal Planner agent node.

Handles: financial goals, retirement corpus, SIP adequacy, goal progress.
Calls: services.goal_engine (if available) + services.copilot_tools.sip.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Goal Planner for Nivesh AI, an Indian investment platform.

You help users plan for financial goals like retirement, education, home purchase.
Use the data in TOOL_DATA where available.

Style:
- ≤ 250 words, markdown
- Show: Goal | Target ₹ | Current corpus | Gap | Monthly SIP needed
- Use Indian numbering (lakhs, crores)
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.

If no goal data is available, perform the calculation from the user's stated inputs.
When SIP_PROJECTION data is present, quote its numbers verbatim — do not recompute.
""" + ANTI_HALLUCINATION_RULES

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_sip_intent(user_msg: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of SIP parameters from free-form user text."""
    msg = user_msg.lower()
    params: Dict[str, Any] = {}

    # monthly amount: ₹10,000 / 10000/month / 10k per month
    m = re.search(r"(?:₹|rs\.?\s*)?(\d[\d,]*)(k)?\s*/?\s*(?:month|mo|monthly)?", msg)
    if m:
        raw = m.group(1).replace(",", "")
        amt = int(raw) * 1000 if m.group(2) else int(raw)
        if 500 <= amt <= 10_000_000:
            params["monthly_amount"] = float(amt)

    # years / horizon
    m = re.search(r"(\d+)\s*(?:year|yr|years|yrs)", msg)
    if m:
        params["years"] = int(m.group(1))

    # goal amount (crores / lakhs)
    for pat, mul in [(r"(\d+(?:\.\d+)?)\s*cr(?:ore)?", 1e7),
                     (r"(\d+(?:\.\d+)?)\s*lakh", 1e5),
                     (r"(\d+(?:\.\d+)?)\s*l\b", 1e5)]:
        gm = re.search(pat, msg)
        if gm:
            params["goal_amount"] = float(gm.group(1)) * mul
            break

    # step-up percentage
    su = re.search(r"(\d+)%?\s*(?:step.?up|annual.*increase|increase.*annual)", msg)
    if su:
        params["step_up_pct"] = float(su.group(1)) / 100

    # fund category hint
    for cat in ("equity", "debt", "balanced", "hybrid"):
        if cat in msg:
            params["fund_category"] = cat
            break

    return params if params else None


async def _run_sip_projection(
    user_msg: str,
    portfolio_total: float = 0.0,
) -> Optional[ToolResult]:
    """Call the SIP projection tool with parameters extracted from user message."""
    try:
        from services.copilot_tools.sip import get_sip_projection
    except ImportError:
        logger.debug("sip tool not available")
        return None

    params = _parse_sip_intent(user_msg) or {}
    monthly = params.get("monthly_amount", 10_000.0)
    years = int(params.get("years", 10))
    goal = params.get("goal_amount")
    step_up = params.get("step_up_pct", 0.0)
    category = params.get("fund_category", "equity")

    result = await get_sip_projection(
        monthly_amount=monthly,
        years=years,
        goal_amount=goal,
        current_corpus=portfolio_total,
        step_up_pct=step_up,
        fund_category=category,
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            tool_name="sip_projection",
            summary=f"SIP calculation failed: {result.error}",
            error=result.error,
        )
    return ToolResult(
        ok=True,
        tool_name="sip_projection",
        summary=result.summary,
        data=result.data,
        rows=result.rows,
        widget_type=WidgetType.SIP_PLAN,
    )


async def _fetch_goal_data(state: CopilotState) -> List[ToolResult]:
    results: List[ToolResult] = []
    portfolio_total = 0.0

    try:
        import importlib

        # 1. Existing goals from goal_engine
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

        # 2. Portfolio summary for current corpus estimate
        port_mod = importlib.import_module("services.copilot_tools.portfolio")
        summary = await port_mod.get_portfolio_summary(state.user_id)
        portfolio_total = float(summary.data.get("total_value", 0) or 0)
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

    # 3. SIP projection from the user's message (uses sip.py — never re-invents math)
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )
    sip_result = await _run_sip_projection(user_msg, portfolio_total=portfolio_total)
    if sip_result:
        results.append(sip_result)

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
        model=COPILOT_LLM_MODEL,
        temperature=0.15,
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    # Prefer SIP_PLAN widget over GOAL_TRACKER when a projection was computed
    sip_tr = next((r for r in tool_results if r.widget_type == WidgetType.SIP_PLAN and r.ok), None)
    goal_tr = next((r for r in tool_results if r.widget_type == WidgetType.GOAL_TRACKER and r.ok), None)

    if sip_tr:
        widget_type = WidgetType.SIP_PLAN
        # Build SipPlanData-compatible structure that SipPlanWidget can render.
        # The raw SipResult has projection math; we wrap it into allocations format.
        monthly = sip_tr.data.get("monthly_sip", 0)
        fv = sip_tr.data.get("future_value", 0)
        years_val = sip_tr.data.get("years", 10)
        rate_pct = sip_tr.data.get("annual_rate_pct", 12.0)
        invested = sip_tr.data.get("invested_amount", 0)
        gain = sip_tr.data.get("wealth_gained", 0)
        fv_lakh = f"₹{fv/1e7:.1f}Cr" if fv >= 1e7 else f"₹{fv/1e5:.1f}L" if fv >= 1e5 else f"₹{fv:,.0f}"
        why = [
            sip_tr.summary,
            f"Total invested: ₹{invested/1e5:.1f}L → Corpus: {fv_lakh} (gain ₹{gain/1e5:.1f}L)" if invested >= 1e5 else f"Gain: ₹{gain:,.0f}",
        ]
        if sip_tr.data.get("goal_feasible") is True:
            why.append("✓ Goal is achievable at this monthly SIP")
        elif sip_tr.data.get("goal_feasible") is False:
            why.append("⚠ Consider increasing SIP or extending your horizon")
        if sip_tr.data.get("step_up_pct"):
            why.append(f"Includes {sip_tr.data['step_up_pct']:.0f}% annual step-up")
        widget_data = {
            "monthly_budget": monthly,
            "allocations": [
                {
                    "scheme_name": "Recommended SIP allocation",
                    "monthly_amount": monthly,
                    "rationale": f"Equity fund → {fv_lakh} in {years_val}yr @ {rate_pct:.0f}% CAGR",
                }
            ],
            "why_these": why,
            "counter_points": [
                "Returns are indicative — actual performance varies by fund",
                "STCG applies on equity units redeemed within 12 months",
            ],
        }
    elif goal_tr:
        widget_type = WidgetType.GOAL_TRACKER
        widget_data = {"rows": goal_tr.rows, **goal_tr.data}
    else:
        widget_type = WidgetType.NONE
        widget_data = {}

    response = AgentResponse(
        agent=AgentName.GOAL,
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
