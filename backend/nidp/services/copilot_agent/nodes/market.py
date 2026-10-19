"""Market Analyst agent node.

Handles: market indices, FII/DII flows, macro indicators, breadth, top movers.
Builds a `market_detail` research widget from the NIDP market snapshot
(`/v1/snapshots/market`) + top movers (`/v1/market-pulse/movers`) via
copilot_tools.market_research, and grounds the LLM answer in that data.
"""
from __future__ import annotations

import logging
from typing import List

from langchain_core.messages import AIMessage

from .._llm import ANTI_HALLUCINATION_RULES, make_chat_llm, temperature_for, text_of
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Market Analyst for Nivesh AI, an Indian investment platform.

You have a live NSE/BSE market snapshot in the TOOL_DATA block: index levels
(Nifty 50, Bank Nifty, Nifty 500), India VIX, market breadth (advances/declines),
FII/DII cash flows, G-Sec yields, top movers, and the NSE sector indices ranked by
1-day return (with 1-week and 1-month). It also holds, each as its own block:
the event calendar for the next 5 NSE sessions (results meetings, other events,
NSE holidays, and the Nifty 50 companies reporting), global markets and
commodities (US/Europe/Asia indices, USD/INR, US 10Y, Brent, gold), the
5-session trend of breadth, FII/DII, India VIX and the 10Y yield, F&O
positioning (index futures build-up, Nifty/Bank Nifty PCR and max pain), and
an AIF/PMS line. Ground every statement in those numbers.
Every block carries its own tag ("[end of day, as of <date>]", "[scheduled, as
of <date>]", or the vendor-quote tag): quote that date and mode when you state
the figure, and never call a figure live. Use each block that is present, with
its date. If a block says "<x> unavailable: <reason>" or "date not provided" or
"not available", say exactly that.

Risk questions ("key risks this week"): the calendar entries are facts, so
state them as facts with their dates (and say a day is a holiday when the
block says so); your read of risk is interpretation, so label it as your read
and tie each risk to a block (breadth, flows, VIX, yields, calendar, global
tape, USD/INR, crude, F&O positioning). End by saying plainly
which blocks are missing or unavailable, and name only those; never claim a block is missing
when it is present.

Style:
- ≤ 200 words, plain text (no markdown)
- Always include a one-line market sentiment call (bullish/bearish/neutral),
  justified by breadth + VIX + flows
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.

If asked about index targets, analyst consensus, or future forecasts, say plainly
we have only historical exchange data and macro indicators — no analyst feeds.
If a specific metric isn't in TOOL_DATA, say so, and never invent it.
""" + ANTI_HALLUCINATION_RULES


def _build_tool_context(results: List[ToolResult]) -> str:
    lines = ["TOOL_DATA:"]
    for tr in results:
        lines.append(f"  [{tr.tool_name}] {tr.as_llm_context()}")
    return "\n".join(lines)


async def market_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What is the market doing today?",
    )

    widget_type = WidgetType.NONE
    widget_data: dict = {}
    tool_results: List[ToolResult] = []
    try:
        import importlib
        mr = importlib.import_module("services.copilot_tools.market_research")
        res = await mr.get_market_research()
        tool_results.append(ToolResult(
            ok=res.ok, tool_name="market_research",
            summary=res.summary, data=res.data, rows=[], error=res.error,
        ))
        if res.ok and res.widget:
            widget_type = WidgetType.MARKET_DETAIL
            widget_data = res.widget
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("market_research failed: %s", exc)
        tool_results.append(ToolResult(
            ok=False, tool_name="market_research",
            summary="Market data unavailable", error=str(exc),
        ))

    # Push the widget first so the client renders it while the narrative streams.
    if widget_type != WidgetType.NONE:
        from .._stream import emit_widget
        await emit_widget(widget_type, widget_data)

    tool_context = _build_tool_context(tool_results)
    llm = make_chat_llm(temperature_for(0.2))
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona, state.desk_persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = text_of(resp)

    response = AgentResponse(
        agent=AgentName.MARKET,
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
