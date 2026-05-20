"""Risk Analyst agent node.

Handles: risk suitability check, portfolio VaR, volatility assessment,
stress-test scenarios (2008 GFC, rate shock, inflation spike, COVID).
Tools: services.copilot_tools.risk (get_risk_suitability, get_portfolio_var,
       get_stress_scenarios).
"""
from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Risk Analyst for Nivesh AI, an Indian investment platform.

You assess portfolio risk using the data in TOOL_DATA below.

Style:
- ≤ 220 words, markdown
- Risk rating: LOW / MEDIUM / HIGH / VERY HIGH with brief justification
- Key risk drivers (top 2-3 bullet points)
- VaR figures: "1-day 95% VaR: ₹X means on a bad day you could lose ₹X"
- When stress-test scenarios are present, report each scenario's expected
  drop in ₹ and %, and the recovery horizon (years). Cite ONLY the numbers
  from TOOL_DATA — never invent scenario impacts.
- Misalignment alerts (if any) with specific suggested action
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


# Triggers that indicate the user wants a stress-test view (vs. plain risk
# suitability). Matches "stress test", "crash", "shock", "drawdown", named
# events ("2008", "covid", "rate shock", "inflation spike"), and bearish
# what-if phrasing.
_STRESS_TRIGGERS = re.compile(
    r"stress|crash|drawdown|shock|crisis|recession|"
    r"2008|gfc|covid|rate\s+(?:shock|hike)|inflation\s+spike|"
    r"what.s\s+the\s+(?:expected\s+)?(?:drop|drawdown|fall|loss)|"
    r"what\s+(?:happens|would\s+happen)\s+(?:to\s+my\s+portfolio|if)|"
    r"how\s+much\s+(?:would|will|could)\s+i\s+lose",
    re.IGNORECASE,
)

# Scenario-name → key. The user can ask about a subset; we pass these keys
# into get_stress_scenarios so we don't waste compute on irrelevant ones.
_SCENARIO_KEYWORDS = (
    ("gfc_2008",         re.compile(r"\b(2008|gfc|global\s+financial\s+crisis)\b", re.IGNORECASE)),
    ("covid_2020",       re.compile(r"\bcovid\b", re.IGNORECASE)),
    ("rate_shock",       re.compile(r"\brate\s+(?:shock|hike)\b", re.IGNORECASE)),
    ("inflation_spike",  re.compile(r"\binflation\s+(?:spike|shock)|sticky\s+inflation\b", re.IGNORECASE)),
)


def _user_message(state: CopilotState) -> str:
    return next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What is my portfolio risk?",
    )


def _wants_stress_test(text: str) -> bool:
    return bool(_STRESS_TRIGGERS.search(text or ""))


def _select_scenarios(text: str) -> Optional[List[str]]:
    """Return the explicit scenarios the user asked about, or None for all."""
    hits = [key for key, pat in _SCENARIO_KEYWORDS if pat.search(text or "")]
    return hits or None


async def _fetch_risk_data(state: CopilotState, user_text: str) -> List[ToolResult]:
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

        # ── Stress test scenarios (only when the user asked) ─────────────────
        if _wants_stress_test(user_text):
            scen_keys = _select_scenarios(user_text)
            stress = await risk_mod.get_stress_scenarios(user_id, scenario_keys=scen_keys)
            results.append(ToolResult(
                ok=stress.ok,
                tool_name="get_stress_scenarios",
                summary=stress.summary,
                data=stress.data,
                rows=stress.rows,
                widget_type=WidgetType.STRESS_TEST,
                error=stress.error,
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
    user_msg = _user_message(state)
    tool_results = await _fetch_risk_data(state, user_msg)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
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

    # Prefer the stress-test widget when the user asked for it; otherwise
    # the risk-suitability widget (data shape comes from the matching tool).
    stress_tr = next(
        (r for r in tool_results if r.tool_name == "get_stress_scenarios" and r.ok),
        None,
    )
    suitability_tr = next(
        (r for r in tool_results if r.tool_name == "get_risk_suitability" and r.ok),
        None,
    )
    if stress_tr:
        widget_type = WidgetType.STRESS_TEST
        widget_data = {**stress_tr.data, "rows": stress_tr.rows}
    elif suitability_tr:
        widget_type = WidgetType.NONE
        widget_data = {}
    else:
        widget_type = WidgetType.NONE
        widget_data = {}

    response = AgentResponse(
        agent=AgentName.RISK,
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
