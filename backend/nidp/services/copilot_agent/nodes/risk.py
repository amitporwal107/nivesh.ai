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

from .._llm import ANTI_HALLUCINATION_RULES, make_chat_llm, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Risk Analyst for Nivesh AI, an Indian investment platform.

You assess portfolio risk using the data in TOOL_DATA below.

Style:
- ≤ 220 words, plain text (no markdown)
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

        # ── Canonical precomputed risk (VaR/volatility/beta/max-DD) ──────────
        # Same PRA source the Risk dashboard uses — prefer it over the
        # parametric estimate so the copilot agrees with the dashboard.
        pra_risk = await risk_mod.get_portfolio_risk_pra(user_id)
        pra_ok = pra_risk.ok
        if pra_ok:
            results.append(ToolResult(
                ok=True,
                tool_name="get_portfolio_risk",
                summary=pra_risk.summary,
                data=pra_risk.data,
            ))

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

        # ── Portfolio VaR (parametric) — ONLY when PRA is unavailable ────────
        # The parametric estimate is noisy and disagrees with the dashboard, so
        # we skip it whenever the canonical PRA result above is present.
        if not pra_ok:
            var_result = await risk_mod.get_portfolio_var(user_id, confidence=0.95)
            results.append(ToolResult(
                ok=var_result.ok,
                tool_name="get_portfolio_var",
                summary=var_result.summary,
                data=var_result.data,
                rows=var_result.rows,
                error=var_result.error,
            ))

        # ── Stress test scenarios ────────────────────────────────────────────
        # Always run so the risk-assessment widget can show the downside per
        # scenario. If the user named specific scenarios, use those; otherwise
        # the full default set (GFC / COVID / inflation / rate shock).
        scen_keys = _select_scenarios(user_text) if _wants_stress_test(user_text) else None
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
    pra_tr = next(
        (r for r in tool_results if r.tool_name == "get_portfolio_risk" and r.ok),
        None,
    )
    # Parametric VaR fallback — fetched by _fetch_risk_data when PRA is absent;
    # supplies the 1-day / 10-day VaR + annual vol the PRA result would have.
    var_tr = next(
        (r for r in tool_results if r.tool_name == "get_portfolio_var" and r.ok),
        None,
    )
    if suitability_tr or pra_tr or var_tr:
        # Comprehensive risk view: suitability rating + VaR/vol KPIs + stress
        # downside + drivers + misalignment, in one widget.
        from services.copilot_tools.risk import build_risk_assessment_widget
        widget_type = WidgetType.RISK_ASSESSMENT
        widget_data = build_risk_assessment_widget(pra_tr, suitability_tr, stress_tr, var_tr)
    elif stress_tr:
        widget_type = WidgetType.STRESS_TEST
        widget_data = {**stress_tr.data, "rows": stress_tr.rows}
    else:
        widget_type = WidgetType.NONE
        widget_data = {}

    # Widget data is ready (built from the tools, not the LLM) — push it now so
    # the client renders it first and streams the narrative underneath.
    from .._stream import emit_widget
    await emit_widget(widget_type, widget_data)

    llm = make_chat_llm(temperature_for(0.1))
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

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
