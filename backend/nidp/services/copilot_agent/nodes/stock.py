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

You have live technical indicators and fundamental data for the stock in TOOL_DATA.
Ground every claim in those numbers. Flag clearly if data is unavailable.

Style:
- ≤ 250 words
- Section: **Technical** — RSI, MACD, SMA signals, trend
- Section: **Fundamental** — PE/PB vs sector, ROE, debt/equity, PAT growth
- Section: **Verdict** — BULLISH / BEARISH / NEUTRAL with one key reason
- End with: DISCLAIMER: AI-generated. Not SEBI registered investment advice.

Never fabricate figures. If a metric is missing, say "data unavailable"."""


async def _fetch_stock_data(symbol: str) -> list:
    # import app-level tools
    try:
        # add backend dir to path if needed
        import importlib
        tech_mod = importlib.import_module("services.copilot_tools.technical")
        fund_mod = importlib.import_module("services.copilot_tools.fundamental")

        tech = await tech_mod.get_technical_analysis(symbol)
        fund = await fund_mod.get_fundamental_analysis(symbol)

        results = [
            ToolResult(
                ok=tech.ok,
                tool_name="get_technical_analysis",
                summary=tech.summary,
                data=tech.data,
                rows=[],
                error=tech.error,
            ),
        ]

        if hasattr(fund, "ok"):
            results.append(ToolResult(
                ok=fund.ok,
                tool_name="get_fundamental_analysis",
                summary=fund.summary,
                data=fund.data if hasattr(fund, "data") else {},
                rows=[],
                error=fund.error if hasattr(fund, "error") else None,
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
