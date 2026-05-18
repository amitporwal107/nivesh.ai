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
- End with: DISCLAIMER: AI-generated. Not SEBI registered investment advice.

Never fabricate figures. If a metric is missing, say "data unavailable".
If asked about price targets, analyst estimates or future guidance, say plainly
that we do not have analyst feeds — only historical exchange filings."""


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
    symbol = state.intent.symbol if state.intent else None
    if not symbol:
        # try to extract from last user message
        import re
        user_msg = next(
            (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
            "",
        )
        m = re.search(r"\b([A-Z]{2,10})\b", user_msg)
        symbol = m.group(1) if m else "NIFTY50"

    tool_results = await _fetch_stock_data(symbol)
    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        f"Analyse {symbol}",
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

    response = AgentResponse(
        agent=AgentName.STOCK,
        text=answer_text,
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response": response,
        "messages": [AIMessage(content=answer_text)],
    }
