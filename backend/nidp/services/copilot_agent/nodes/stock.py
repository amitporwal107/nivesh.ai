"""Stock Analyst agent node.

Handles: individual stock technical + fundamental analysis.
Calls: copilot_tools.technical, copilot_tools.fundamental
"""
from __future__ import annotations

import logging
import os
import sys

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Stock Analyst for Nivesh AI, an Indian investment platform.

You have live technical indicators, fundamental data, and quarterly financial
trends for the stock in TOOL_DATA. Ground every claim in those numbers. Flag
clearly if data is unavailable.

Style:
- ≤ 300 words
- Section: **Technical** — RSI, MACD, SMA signals, trend
- Section: **Fundamental** — PE/PB vs sector, ROE, debt/equity, PAT growth
- Section: **Quarterly Trend** — revenue/PAT trajectory + margin direction
- Section: **Smart Money** — FII/DII flows + promoter pledge if non-zero
- Section: **Verdict** — BULLISH / BEARISH / NEUTRAL with one key reason
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.

If asked about price targets, analyst estimates or future guidance, say plainly
that we do not have analyst feeds — only historical exchange filings.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_stock_data(symbol: str) -> list:
    # import app-level tools
    try:
        # add backend dir to path if needed
        import importlib, asyncio
        tech_mod = importlib.import_module("services.copilot_tools.technical")
        fund_mod = importlib.import_module("services.copilot_tools.fundamental")
        cf_mod   = importlib.import_module("services.copilot_tools.company_financials")

        tech_task = asyncio.create_task(tech_mod.get_technical_analysis(symbol))
        fund_task = asyncio.create_task(fund_mod.get_fundamental_analysis(symbol))
        cf_task   = asyncio.create_task(cf_mod.get_company_financials(symbol, limit=8))
        shr_task  = asyncio.create_task(cf_mod.get_shareholding_analysis(symbol))

        tech, fund, cf_res, shr_res = await asyncio.gather(
            tech_task, fund_task, cf_task, shr_task, return_exceptions=True,
        )

        results: list = []

        if not isinstance(tech, Exception):
            results.append(ToolResult(
                ok=tech.ok,
                tool_name="get_technical_analysis",
                summary=tech.summary,
                data=tech.data,
                rows=[],
                error=tech.error,
            ))

        if not isinstance(fund, Exception) and hasattr(fund, "ok"):
            results.append(ToolResult(
                ok=fund.ok,
                tool_name="get_fundamental_analysis",
                summary=fund.summary,
                data=fund.data if hasattr(fund, "data") else {},
                rows=[],
                error=fund.error if hasattr(fund, "error") else None,
            ))

        if not isinstance(cf_res, Exception) and hasattr(cf_res, "ok"):
            results.append(ToolResult(
                ok=cf_res.ok,
                tool_name="get_company_financials",
                summary=cf_res.summary,
                data=cf_res.data,
                rows=cf_res.rows[:6],
                error=cf_res.error,
            ))

        if not isinstance(shr_res, Exception) and hasattr(shr_res, "ok"):
            results.append(ToolResult(
                ok=shr_res.ok,
                tool_name="get_shareholding_analysis",
                summary=shr_res.summary,
                data=shr_res.data,
                rows=shr_res.rows[:4],
                error=shr_res.error,
            ))

        return results
    except Exception as exc:
        logger.warning("stock data fetch failed for %s: %s", symbol, exc)
        return [ToolResult(
            ok=False,
            tool_name="get_technical_analysis",
            summary=f"Data unavailable for {symbol}",
            error=str(exc),
        )]


async def stock_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )
    # The intent classifier already resolves a symbol when it can; if it didn't
    # (e.g. an ambiguous message), resolve from the raw text here too. Both paths
    # use the same resolver so lowercase tickers and company names work.
    symbol = state.intent.symbol if state.intent else None
    if not symbol:
        from services.copilot_tools.symbol_resolver import resolve_symbol
        symbol = resolve_symbol(user_msg).symbol

    if not symbol:
        # No identifiable stock — ask rather than silently analysing an index
        # (the old NIFTY50 default produced a misleading "couldn't retrieve data"
        # error because index symbols have no per-stock fundamentals/technicals).
        clarify = (
            "Which stock would you like me to look at? You can use the company "
            "name or its NSE symbol — for example: Reliance, TCS, HDFC Bank, "
            "Infosys, or RELIANCE."
        )
        return {
            "tool_results": [],
            "response": AgentResponse(
                agent=AgentName.STOCK,
                text=clarify,
                widget_type=WidgetType.NONE,
                widget_data={},
                tool_results=[],
            ),
            "messages": [AIMessage(content=clarify)],
        }

    # Fetch the per-section tool data AND the composed research card (quality
    # score + sector rank + fundamental/technical) concurrently. The research
    # card drives the instrument_detail widget; its summary also grounds the LLM.
    import asyncio as _asyncio
    research = None
    try:
        research_mod = __import__("services.copilot_tools.instrument_research", fromlist=["get_stock_research"])
        tool_results, research = await _asyncio.gather(
            _fetch_stock_data(symbol),
            research_mod.get_stock_research(symbol),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock research fetch failed for %s: %s", symbol, exc)
        tool_results = await _fetch_stock_data(symbol)

    # A transient data-source outage (DaaS 5xx / DB in recovery) must NOT fall
    # through to the LLM, where empty TOOL_DATA triggers the generic anti-
    # hallucination "couldn't retrieve the data" line — that reads as "this stock
    # is unsupported" when the feed is simply down. Surface it honestly and as
    # retryable instead. (Coverage itself is ~100% for features+scores; this path
    # only fires when the source is unreachable, not when a stock lacks data.)
    if research is not None and getattr(research, "error", None) == "source_unavailable":
        outage = (
            f"I couldn't reach our market-data service just now, so I can't pull "
            f"{symbol}'s numbers this moment. This is a temporary issue on our end, "
            f"not a gap in coverage — please try again in a few moments."
        )
        return {
            "tool_results": tool_results,
            "response": AgentResponse(
                agent=AgentName.STOCK,
                text=outage,
                widget_type=WidgetType.NONE,
                widget_data={},
                tool_results=tool_results,
            ),
            "messages": [AIMessage(content=outage)],
        }

    ctx_lines = [f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results]
    if research is not None and research.ok:
        ctx_lines.insert(0, f"  [instrument_research] {research.as_llm_context()}")
    tool_context = "TOOL_DATA:\n" + "\n".join(ctx_lines)

    llm_user_msg = user_msg or f"Analyse {symbol}"

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=temperature_for(0.1),
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": llm_user_msg},
    ])
    answer_text = resp.content

    widget_type = WidgetType.NONE
    widget_data: dict = {}
    if research is not None and research.ok and research.widget:
        widget_type = WidgetType.INSTRUMENT_DETAIL
        widget_data = research.widget
        # Attach the question-first research rail (chips + lens views) so the card
        # renders as a Research Hub. No-op if the widget has no lens data.
        from services.copilot_tools.research_lenses import build_research_hub
        build_research_hub("stock", widget_data)

    response = AgentResponse(
        agent=AgentName.STOCK,
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
