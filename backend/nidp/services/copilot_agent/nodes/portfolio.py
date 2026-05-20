"""Portfolio Analyst agent node.

Handles: portfolio XIRR, rebalancing, stress test, tax harvest, overlap.
Calls: services.copilot_tools.portfolio (PORT)
"""
from __future__ import annotations

import logging
import os

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Portfolio Analyst for Nivesh AI.

You have the user's personal portfolio data in TOOL_DATA below.
Ground every figure in that data. Do not use generic percentages.

Style:
- ≤ 300 words, markdown
- Lead with the direct answer to what they asked (XIRR / rebalance actions / tax savings / stress impact)
- Use ₹ for rupee amounts, % for rates
- If rebalance: show a table with Action | Fund | Amount
- If stress test: show portfolio value before/after and % drop
- If tax harvest: show Loss | Gain-offset | Est. tax saving
- If `compare_portfolio_funds` ran, render a markdown table with columns:
  Fund | Category | 1Y | 3Y | 5Y | TER | Allocation. Use scheme names verbatim from TOOL_DATA (never UUIDs).
  Then list the top 3 overlap pairs by name (from TOP_OVERLAP block) with %.
  If returns/TER are missing for some funds, mark those cells "—" — do not write "data unavailable" for the whole answer when partial data exists.
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_portfolio_data(state: CopilotState) -> list:
    try:
        import importlib
        port_mod = importlib.import_module("services.copilot_tools.portfolio")

        user_id = state.user_id
        intent = state.intent
        scenario = (intent.scenario if intent and intent.scenario else "covid_2020")

        results = []

        # always fetch summary + XIRR
        summary = await port_mod.get_portfolio_summary(user_id)
        results.append(ToolResult(
            ok=summary.ok, tool_name="get_portfolio_summary",
            summary=summary.summary, data=summary.data, rows=summary.rows,
            widget_type=WidgetType.PORTFOLIO_OVERVIEW,
        ))

        xirr = await port_mod.get_portfolio_xirr(user_id)
        results.append(ToolResult(
            ok=xirr.ok, tool_name="get_portfolio_xirr",
            summary=xirr.summary, data=xirr.data, rows=xirr.rows,
        ))

        # additional data based on what intent detected
        user_msg = next(
            (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
            "",
        ).lower()

        if any(kw in user_msg for kw in ("rebalanc", "drift", "allocation", "trim", "overweight", "underweight", "which sector", "which fund", "which stock", "which holding")):
            rb = await port_mod.get_rebalance_plan(user_id)
            results.append(ToolResult(
                ok=rb.ok, tool_name="get_rebalance_plan",
                summary=rb.summary, data=rb.data, rows=rb.rows,
                widget_type=WidgetType.REBALANCE_PLAN,
            ))

        if any(kw in user_msg for kw in ("tax", "harvest", "ltcg", "stcg", "capital gain")):
            # Full report for general tax queries; harvest-specific for loss queries
            harvest_kws = ("harvest", "loss", "sell for tax", "save tax")
            if any(kw in user_msg for kw in harvest_kws):
                tax = await port_mod.get_tax_harvest_candidates(user_id)
            else:
                tax = await port_mod.get_full_tax_report(user_id)
            results.append(ToolResult(
                ok=tax.ok,
                tool_name="get_full_tax_report" if "net_tax_payable" in tax.data else "get_tax_harvest_candidates",
                summary=tax.summary, data=tax.data, rows=tax.rows,
                widget_type=WidgetType.TAX_HARVEST,
            ))

        if any(kw in user_msg for kw in ("stress", "crash", "covid", "2008", "rate shock", "lose", "falls", "drops", "what if market")):
            # Extract custom percentage if present (e.g. "falls 20%")
            import re as _re
            pct_m = _re.search(r"(\d{1,3})\s*%", user_msg)
            if pct_m:
                stress = await port_mod.run_stress_test(
                    user_id, scenario="custom", custom_equity_drop=-float(pct_m.group(1))
                )
            else:
                stress = await port_mod.run_stress_test(user_id, scenario=scenario)
            results.append(ToolResult(
                ok=stress.ok, tool_name="run_stress_test",
                summary=stress.summary, data=stress.data, rows=stress.rows,
                widget_type=WidgetType.STRESS_TEST,
            ))

        if any(kw in user_msg for kw in ("fd", "fixed deposit", "beat fd", "vs fd", "compare to fd", "better than fd")):
            fd = await port_mod.get_fd_comparison(user_id)
            results.append(ToolResult(
                ok=fd.ok, tool_name="get_fd_comparison",
                summary=fd.summary, data=fd.data, rows=fd.rows,
            ))

        if any(kw in user_msg for kw in ("when to sell", "tax timing", "ltcg flip", "minimise tax", "minimize tax", "save tax on", "long-term eligib", "long term eligib", "wait to sell")):
            timing = await port_mod.get_tax_timing_advice(user_id)
            results.append(ToolResult(
                ok=timing.ok, tool_name="get_tax_timing_advice",
                summary=timing.summary, data=timing.data, rows=timing.rows,
                widget_type=WidgetType.TAX_HARVEST,
            ))

        # Side-by-side MF comparison: returns + TER + overlap together.
        # Word-boundary match so "MF" / "TER" hit regardless of punctuation
        # ("Compare MFs", "What's the TER?", "expense ratio vs TER").
        import re as _re_kw
        _padded = f" {user_msg} "
        def _has_word(words):
            return any(_re_kw.search(rf"\b{w}\b", _padded) for w in words)
        wants_compare = (
            _has_word(["compare", "comparison", "vs", "versus"])
            or any(p in user_msg for p in (
                "side by side", "side-by-side", "rolling return", "expense ratio", "ter%"
            ))
            or _has_word(["ter"])
        )
        wants_fund_ctx = (
            _has_word(["fund", "funds", "mf", "mfs", "mutual", "scheme", "schemes"])
        )
        if wants_compare and wants_fund_ctx:
            cmp = await port_mod.compare_portfolio_funds(user_id)
            results.append(ToolResult(
                ok=cmp.ok, tool_name="compare_portfolio_funds",
                summary=cmp.summary, data=cmp.data, rows=cmp.rows,
                widget_type=WidgetType.FUND_COMPARISON,
            ))

        if any(kw in user_msg for kw in ("overlap", "duplicate", "similar fund")):
            ov = await port_mod.get_portfolio_overlap(user_id)
            results.append(ToolResult(
                ok=ov.ok, tool_name="get_portfolio_overlap",
                summary=ov.summary, data=ov.data, rows=ov.rows,
                widget_type=WidgetType.OVERLAP_REVEAL,
            ))

        return results
    except Exception as exc:
        logger.warning("portfolio data fetch failed: %s", exc)
        return [ToolResult(ok=False, tool_name="portfolio_tools", summary="Portfolio data unavailable", error=str(exc))]


async def portfolio_node(state: CopilotState) -> dict:
    tool_results = await _fetch_portfolio_data(state)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "How is my portfolio doing?",
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

    # pick the richest widget to surface
    _PRIORITY = [
        WidgetType.STRESS_TEST, WidgetType.TAX_HARVEST, WidgetType.REBALANCE_PLAN,
        WidgetType.FUND_COMPARISON, WidgetType.OVERLAP_REVEAL, WidgetType.PORTFOLIO_OVERVIEW,
    ]
    widget_type = WidgetType.NONE
    widget_data: dict = {}
    for wt in _PRIORITY:
        tr = next((r for r in tool_results if r.widget_type == wt and r.ok), None)
        if tr:
            widget_type = wt
            widget_data = {"rows": tr.rows, **tr.data}
            break

    response = AgentResponse(
        agent=AgentName.PORTFOLIO,
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
