"""Backtest Analyst agent node.

Handles the historical "what-if": *"if I'd invested ₹X across these stocks/funds
N years ago, what's it worth today — lump-sum and SIP?"*

Calls: services.copilot_tools.backtest.get_historical_backtest (BACKTEST engine).
The engine parses the basket / amount / lookback from the message, resolves each
instrument, and computes point-to-point lump-sum CAGR + monthly-SIP XIRR from the
real total-return price / NAV series.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from .._llm import ANTI_HALLUCINATION_RULES, make_chat_llm, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Backtest Analyst for Nivesh AI.

TOOL_DATA below holds a historical "what-if": a fixed amount notionally invested
across the named stocks / funds, valued today, computed from real adjusted prices
(stocks: total-return) and NAVs (funds). Both a lump-sum and a monthly-SIP result
are given per lookback period.

Ground EVERY figure in TOOL_DATA — never invent returns.

Style:
- ≤ 300 words, plain text (no markdown headings)
- Lead with the direct answer: for each period, the lump-sum value today + CAGR,
  and the SIP XIRR.
- Then a per-instrument comparison so the user sees which performed best/worst —
  use the instrument names verbatim from TOOL_DATA, with each one's CAGR (and SIP
  XIRR where present). Use ₹ for amounts, % for rates.
- If an instrument or period is marked "insufficient_history", SAY SO plainly
  (e.g. "3-year history isn't available for <name> — data only since <date>") and
  do not fabricate a number for it. Note that such instruments are excluded from
  that period's portfolio total.
- If a "benchmark" block is present and ok, compare each period's portfolio CAGR
  against the benchmark index (e.g. "Nifty 500") so the user sees whether the
  basket beat the market. If the benchmark is "unavailable", omit it silently.
- This is a historical illustration, not a prediction — say so in one short line.
- Do NOT append any SEBI disclaimer — the UI renders one below the chat input.
""" + ANTI_HALLUCINATION_RULES


async def backtest_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )

    tool_results: list = []
    widget_type = WidgetType.NONE
    widget_data: dict = {}
    try:
        import importlib
        bt_mod = importlib.import_module("services.copilot_tools.backtest")
        res = await bt_mod.get_historical_backtest(user_msg)
        tr = ToolResult(
            ok=res.ok, tool_name="get_historical_backtest",
            summary=res.summary, data=res.data, rows=res.rows,
            widget_type=WidgetType.BACKTEST_COMPARISON if res.ok else WidgetType.NONE,
            error=res.error,
        )
        tool_results.append(tr)
        if res.ok:
            widget_type = WidgetType.BACKTEST_COMPARISON
            widget_data = {"rows": res.rows, **res.data}
    except Exception as exc:  # noqa: BLE001 — degrade to a graceful message
        logger.warning("backtest node failed: %s", exc)
        tool_results.append(ToolResult(
            ok=False, tool_name="get_historical_backtest",
            summary="Backtest could not be computed", error=str(exc),
        ))

    tool_context = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    # Push the widget before the narrative so the client renders it first.
    from .._stream import emit_widget
    await emit_widget(widget_type, widget_data)

    # The LLM only writes the narrative; the widget (above) is already the answer.
    # Never let an LLM hiccup crash the chat stream — fall back to a deterministic
    # summary built from the tool result so the user still gets a usable reply.
    primary = tool_results[0] if tool_results else None
    answer_text = ""
    try:
        llm = make_chat_llm(temperature_for(0.1))
        resp = await llm.ainvoke([
            {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
            {"role": "user", "content": user_msg or "Run the backtest."},
        ])
        answer_text = (resp.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — never crash the stream on the narrative
        logger.warning("backtest node LLM narrative failed: %s", exc)

    if not answer_text:
        if primary and primary.ok:
            answer_text = (
                f"Here's the historical backtest — {primary.summary}. "
                "This is a historical illustration, not a prediction."
            )
        else:
            answer_text = (
                "I couldn't run the backtest just now — the price/NAV data didn't load. "
                "Please try again in a moment."
            )

    response = AgentResponse(
        agent=AgentName.BACKTEST,
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
