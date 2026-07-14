"""Stocks-Insights agent node (Nivesh Copilot).

Handles questions about a company's *corporate disclosures* — recent filings,
order wins, results, M&A, board outcomes, fund raises — plus thematic
cross-company queries ("which companies announced buybacks?").

Grounds a concise LLM answer in the recent filings returned by
``copilot_tools.stocks_insights`` (DAAS) and renders a ``stock_insights`` card
with the answer, a recent-events list, and a numbered Sources register whose
[n] markers resolve to the source filing (filing-level "View Source" → PDF).

Guardrails: NO buy/sell/hold, price target, or predicted price movement
(Nivesh Copilot is factual, cited disclosure info only). If no filings are
found, the answer refuses ("no recent filings found") rather than inventing.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Corporate Disclosures analyst for Nivesh Copilot, an Indian equity research assistant.

You are given (in TOOL_DATA) a numbered list of a company's RECENT EXCHANGE FILINGS
(order wins, results, M&A, board outcomes, fund raises, etc.) — each with a short summary —
and, for a specific company, a `quarterly_financials` block (revenue, PAT, margins, YoY).
Answer the user's question using ONLY this provided data.

Rules:
- For anything drawn from a filing, cite it inline as [n] (n = the filing number). Never
  cite a number that isn't in the list.
- Use the `quarterly_financials` block for results / numbers / margin / trend questions;
  state those figures plainly (financials do NOT need an [n] citation).
- If the filings say "NONE FOUND" AND there is no financials block, say plainly you found
  no recent filings or data — do NOT invent events, numbers, or dates.
- ≤ 160 words, plain text (no markdown headers).
- FACTUAL ONLY. Do NOT give buy/sell/hold advice, price targets, or predicted price
  movements. Do NOT say whether the news is good or bad for the stock price. Report what
  was filed and let the filing speak.
- Do NOT append a SEBI disclaimer — the UI renders one canonically.
""" + ANTI_HALLUCINATION_RULES


def _resolve_symbol(text: str):
    try:
        from services.copilot_tools.symbol_resolver import resolve_symbol
        return resolve_symbol(text)
    except Exception as exc:  # noqa: BLE001 — never let resolution break the turn
        logger.debug("symbol resolution failed: %s", exc)
        return None


async def stocks_insights_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What's the latest corporate news?",
    )

    # Resolve a ticker; None → thematic cross-company search.
    resolved = _resolve_symbol(user_msg)
    symbol = getattr(resolved, "symbol", None) if resolved else None
    company = getattr(resolved, "name", None) if resolved else None

    tool_results: list[ToolResult] = []
    widget_type = WidgetType.NONE
    widget_data: dict = {}
    result = None
    try:
        import importlib
        si = importlib.import_module("services.copilot_tools.stocks_insights")
        result = await si.get_stocks_insights(query=user_msg, symbol=symbol)
        tool_results.append(ToolResult(
            ok=result.ok, tool_name="stocks_insights",
            summary=result.summary, data={"ticker": result.ticker, "mode": result.mode},
            rows=result.events, error=result.error,
        ))
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("stocks_insights tool failed: %s", exc)
        tool_results.append(ToolResult(
            ok=False, tool_name="stocks_insights",
            summary="Corporate filings unavailable", error=str(exc),
        ))

    # Compose the grounded answer over the retrieved filings.
    tool_context = "TOOL_DATA:\n" + (result.as_llm_context() if result else "recent_filings: UNAVAILABLE")
    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=temperature_for(0.1),
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = (resp.content or "").strip()

    # Guard against citing a filing number that doesn't exist (zero-fabrication):
    # strip any [n] whose n is out of range of the sources list.
    if result and result.events:
        answer_text = _strip_dangling_citations(answer_text, len(result.events))

    # Build + emit the card (the widget carries the answer — the UI renders the
    # card in place of the text bubble).
    if result is not None:
        widget_data = si.build_widget_data(result, answer_text, company=company)
        widget_type = WidgetType.STOCK_INSIGHTS
        from .._stream import emit_widget
        await emit_widget(widget_type, widget_data)

    response = AgentResponse(
        agent=AgentName.STOCKS_INSIGHTS,
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


def _strip_dangling_citations(text: str, n_sources: int) -> str:
    """Remove inline [n] markers whose n exceeds the number of real sources, so a
    citation can never point at a filing that isn't in the Sources register."""
    import re

    def _keep(m: "re.Match") -> str:
        try:
            return m.group(0) if 1 <= int(m.group(1)) <= n_sources else ""
        except ValueError:
            return ""

    return re.sub(r"\[(\d{1,2})\]", _keep, text)
