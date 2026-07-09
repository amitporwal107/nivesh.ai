"""Portfolio Analyst agent node.

Handles: portfolio XIRR, rebalancing, stress test, tax harvest, overlap.
Calls: services.copilot_tools.portfolio (PORT)
"""
from __future__ import annotations

import logging
import os
import re

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Portfolio Analyst for Nivesh AI.

You have the user's personal portfolio data in TOOL_DATA below.
Ground every figure in that data. Do not use generic percentages.

Style:
- ≤ 300 words, plain text (no markdown)
- Lead with the direct answer to what they asked (XIRR / rebalance actions / tax savings / stress impact)
- Use ₹ for rupee amounts, % for rates
- If rebalance: show a table with Action | Fund | Amount
- If stress test: show portfolio value before/after and % drop
- If tax harvest: show Loss | Gain-offset | Est. tax saving
- If `compare_portfolio_funds` ran, render a markdown table with columns:
  Fund | Category | 1Y | 3Y | 5Y | TER | Allocation. Use scheme names verbatim from TOOL_DATA (never UUIDs).
  Then list the top 3 overlap pairs by name (from TOP_OVERLAP block) with %.
  If returns/TER are missing for some funds, mark those cells "—" — do not write "data unavailable" for the whole answer when partial data exists.
- If `get_concentration_breakdown` ran, ANSWER FROM IT. It gives, in order:
  SECTOR ALLOCATION (each sector's % with the underlying companies and their %
  inside the parentheses), AMC CONCENTRATION (each fund house's % and the funds
  under it), TOP COMPANIES (look-through), and FUND-WISE ALLOCATION. For "which
  sector is highest and which companies are in it", read the first sector and
  the companies in its parentheses verbatim. For "which AMC", read AMC
  CONCENTRATION. NEVER say company-within-sector / AMC / fund-wise data is
  unavailable when this block is present — it is the data.
- If `get_portfolio_health_score` ran, lead with the exact score and grade from
  it (it matches the user's overview page), then name the biggest fixes.
- If `get_top_recommendations` ran, present the ranked list verbatim (number,
  title, action, ₹ impact) — these are the dashboard's real recommendations.
- For rebalancing, name the specific funds to EXIT FIRST and the funds/stocks to
  ADD from `get_rebalance_plan` (the summary lists both) — do not answer with
  only the equity/debt split.
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_portfolio_data(state: CopilotState) -> list:
    # `results` lives OUTSIDE the try so a tool that throws mid-way doesn't
    # discard what already succeeded (e.g. summary + XIRR). One failing tool
    # must not turn the whole answer into a "couldn't retrieve" fallback.
    results: list = []
    try:
        import importlib
        port_mod = importlib.import_module("services.copilot_tools.portfolio")

        user_id = state.user_id
        intent = state.intent
        scenario = (intent.scenario if intent and intent.scenario else "covid_2020")

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

        if any(kw in user_msg for kw in ("rebalanc", "drift", "allocation", "trim", "overweight", "underweight", "which sector", "which fund", "which stock", "which holding", "exit", "sell first", "what should i exit", "redeploy")):
            rb = await port_mod.get_rebalance_plan(user_id, state.risk_profile)
            results.append(ToolResult(
                ok=rb.ok, tool_name="get_rebalance_plan",
                summary=rb.summary, data=rb.data, rows=rb.rows,
                widget_type=WidgetType.REBALANCE_PLAN,
            ))

        # AMC / sector→company / company / fund-wise concentration drill-down.
        # This is the only tool that surfaces companies-within-a-sector, AMC
        # concentration, and fund-wise allocation in the LLM context.
        if any(kw in user_msg for kw in (
            "sector", "amc", "fund house", "fund-house", "company", "companies",
            "concentrat", "exposure", "fund-wise", "fund wise", "allocation breakdown",
            "which companies", "highest allocation", "distribution", "breakdown",
            "diversif", "most exposed",
        )):
            conc = await port_mod.get_concentration_breakdown(user_id)
            results.append(ToolResult(
                ok=conc.ok, tool_name="get_concentration_breakdown",
                summary=conc.summary, data=conc.data, rows=conc.rows,
                widget_type=WidgetType.CONCENTRATION,
            ))

        # Portfolio Health score — same number the overview page shows.
        if any(kw in user_msg for kw in (
            "health score", "portfolio score", "portfolio health", "how healthy",
            "overview score", "my score", "health of my",
        )):
            health = await port_mod.get_portfolio_health_score(user_id)
            results.append(ToolResult(
                ok=health.ok, tool_name="get_portfolio_health_score",
                summary=health.summary, data=health.data, rows=health.rows,
                widget_type=WidgetType.PORTFOLIO_OVERVIEW,
            ))

        # Top prioritised recommendations — same list as the dashboard Top-Actions.
        if any(kw in user_msg for kw in (
            "recommend", "what should i", "fix first", "top action", "top recommendation",
            "improve my portfolio", "suggestion", "next step", "what to do",
        )):
            recs = await port_mod.get_top_recommendations(user_id)
            results.append(ToolResult(
                ok=recs.ok, tool_name="get_top_recommendations",
                summary=recs.summary, data=recs.data, rows=recs.rows,
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

        if any(kw in user_msg for kw in ("overlap", "duplicate", "similar fund",
                                         "concentrat", "diversif", "most exposed",
                                         "biggest holding", "top holding", "where is")):
            ov = await port_mod.get_portfolio_overlap(user_id)
            results.append(ToolResult(
                ok=ov.ok, tool_name="get_portfolio_overlap",
                summary=ov.summary, data=ov.data, rows=ov.rows,
                widget_type=WidgetType.OVERLAP_REVEAL,
            ))

        return results
    except Exception as exc:
        logger.warning("portfolio data fetch failed after %d tool(s): %s", len(results), exc)
        # Preserve whatever succeeded (summary/XIRR/…) so the copilot answers
        # from partial data instead of the blunt "couldn't retrieve" fallback.
        if results:
            return results
        return [ToolResult(ok=False, tool_name="portfolio_tools", summary="Portfolio data unavailable", error=str(exc))]


# ── Capital-Gains STATEMENT sub-intent (WF-04-07) ────────────────────────────
# _P_PORTFOLIO already routes "capital gains / stcg / ltcg" here; this guard picks
# the STATEMENT (realised/booked gains) and renders the capital_gains widget,
# distinct from tax-LOSS-harvest (which keeps the tax_harvest widget).
_CG_CUE = re.compile(
    r"\bcapital\s+gains?\b|\bcg\s+statement\b|\breali[sz]ed?\s+(?:capital\s+)?gains?\b|"
    r"\bstcg\b|\bltcg\b|\btax\s+(?:if|when)\s+i\s+(?:book|sell|redeem)\b|"
    r"\bbook(?:ed|ing)?\s+(?:my\s+)?(?:gains?|profits?)\b",
    re.IGNORECASE,
)
_CG_EXCLUDE = re.compile(r"harvest|tax[\s-]?loss|loss[\s-]?harvest", re.IGNORECASE)

_CG_SYSTEM = """You are the Tax Analyst for Nivesh AI.

TOOL_DATA holds the user's REALISED capital-gains statement for a financial year,
computed FIFO: Section A short-term (Sec 111A), Section B long-term (Sec 112A,
first Rs 1.25L exempt), plus a summary and estimated tax. Ground EVERY number in
TOOL_DATA — never invent gains or tax.

Style:
- <= 180 words, plain text (no markdown headings), Indian numbering (lakh/crore).
- Lead with the FY, total STCG and LTCG, the Rs 1.25L LTCG exemption, and the
  estimated tax. Then one line on the biggest contributor if useful.
- If there are NO realised gains, say so plainly (no sell/redeem transactions in
  the FY) and note this covers realised (booked) gains only, not unrealised.
- Indicative planning statement, not a tax-filing document — say so in one line.
  Do NOT append any SEBI disclaimer — the UI renders one below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def _capital_gains_turn(state: CopilotState, user_msg: str) -> dict:
    """Realised capital-gains statement turn — emits the capital_gains widget."""
    import importlib
    cg_mod = importlib.import_module("services.copilot_tools.cg")
    fy = cg_mod.parse_fy(user_msg)
    try:
        res = await cg_mod.get_capital_gains(state.user_id, fy=fy)
    except Exception as exc:  # noqa: BLE001 — never crash the stream
        logger.warning("cg turn failed: %s", exc)
        res = None

    if res is not None and res.ok:
        tr = ToolResult(ok=True, tool_name="get_capital_gains", summary=res.summary,
                        data=res.data, rows=res.rows, widget_type=WidgetType.CAPITAL_GAINS)
        widget_type, widget_data = WidgetType.CAPITAL_GAINS, {"rows": res.rows, **res.data}
    else:
        tr = ToolResult(ok=False, tool_name="get_capital_gains",
                        summary="Capital-gains statement unavailable",
                        error=(res.error if res is not None else "unavailable"))
        widget_type, widget_data = WidgetType.NONE, {}

    from .._stream import emit_widget
    await emit_widget(widget_type, widget_data)

    tool_context = "TOOL_DATA:\n  [get_capital_gains] " + tr.as_llm_context()
    answer_text = ""
    try:
        llm = ChatOpenAI(model=COPILOT_LLM_MODEL, temperature=temperature_for(0.1),
                         api_key=get_openai_api_key())
        resp = await llm.ainvoke([
            {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _CG_SYSTEM + "\n\n" + tool_context},
            {"role": "user", "content": user_msg},
        ])
        answer_text = (resp.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — never crash the stream on the narrative
        logger.warning("cg narrative failed: %s", exc)
    if not answer_text:
        answer_text = (f"Here's your realised capital-gains statement — {tr.summary}"
                       if tr.ok else
                       "I couldn't pull your capital-gains statement just now — please try again in a moment.")

    response = AgentResponse(agent=AgentName.PORTFOLIO, text=answer_text,
                             widget_type=widget_type, widget_data=widget_data, tool_results=[tr])
    return {"tool_results": [tr], "response": response, "messages": [AIMessage(content=answer_text)]}


async def portfolio_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "How is my portfolio doing?",
    )
    # Capital-gains STATEMENT (realised STCG/LTCG A/B/C) short-circuits the general
    # portfolio fetch — distinct from tax-loss-harvest.
    if _CG_CUE.search(user_msg) and not _CG_EXCLUDE.search(user_msg):
        return await _capital_gains_turn(state, user_msg)

    tool_results = await _fetch_portfolio_data(state)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    _msg = user_msg.lower()
    # "Is my wealth allocation optimal?" → the allocation-review verdict widget.
    is_allocation = bool(re.search(
        r"allocation\s+optimal|optimal\s+allocation|wealth\s+allocation|"
        r"is\s+my\s+(?:asset\s+)?allocation|(?:asset\s+)?allocation\s+(?:optimal|right|good|ok|balanced)|"
        r"review\s+my\s+allocation|how(?:'s| is)\s+my\s+allocation|am\s+i\s+well\s+allocated|asset\s+mix",
        _msg,
    ))
    # "Where is concentration risk highest?" gets the dedicated concentration
    # widget (V5-native), built from the summary + overlap tool results.
    is_concentration = any(
        kw in _msg
        for kw in ("concentrat", "where is the risk", "where is risk", "most exposed",
                   "biggest risk", "diversif")
    )
    summary_tr = next((r for r in tool_results if r.tool_name == "get_portfolio_summary" and r.ok), None)
    overlap_tr = next((r for r in tool_results if r.tool_name == "get_portfolio_overlap" and r.ok), None)
    rebalance_tr = next((r for r in tool_results if r.tool_name == "get_rebalance_plan" and r.ok), None)
    xirr_tr = next((r for r in tool_results if r.tool_name == "get_portfolio_xirr" and r.ok), None)

    if is_allocation and summary_tr:
        from services.copilot_tools.portfolio import build_allocation_review_widget
        widget_type = WidgetType.ALLOCATION_REVIEW
        widget_data = build_allocation_review_widget(summary_tr, rebalance_tr, xirr_tr)
    elif is_concentration and summary_tr:
        from services.copilot_tools.portfolio import build_concentration_widget
        widget_type = WidgetType.CONCENTRATION
        widget_data = build_concentration_widget(summary_tr, overlap_tr)
    else:
        # pick the richest widget to surface
        _PRIORITY = [
            WidgetType.STRESS_TEST, WidgetType.TAX_HARVEST, WidgetType.REBALANCE_PLAN,
            WidgetType.FUND_COMPARISON, WidgetType.OVERLAP_REVEAL, WidgetType.PORTFOLIO_OVERVIEW,
        ]
        widget_type = WidgetType.NONE
        widget_data = {}
        for wt in _PRIORITY:
            tr = next((r for r in tool_results if r.widget_type == wt and r.ok), None)
            if tr:
                widget_type = wt
                widget_data = {"rows": tr.rows, **tr.data}
                break

    # The widget data is ready now (built from the tools, not the LLM). Push it
    # to the stream BEFORE generating the narrative so the client renders it
    # first and streams the text underneath.
    from .._stream import emit_widget
    await emit_widget(widget_type, widget_data)

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=temperature_for(0.1),
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

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
