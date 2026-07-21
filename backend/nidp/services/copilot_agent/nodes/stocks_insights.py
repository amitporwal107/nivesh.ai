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
import re

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are Nivesh Copilot — an Indian equity research assistant that answers ONLY from
authenticated exchange disclosures. TOOL_DATA gives you a numbered list of a company's RECENT
EXCHANGE FILINGS (each with a short summary) and, for a specific company, a `quarterly_financials`
block (revenue, PAT, margins, YoY). Answer using ONLY this provided data.

CITATIONS
- Every factual claim from a filing carries an inline [n] (n = the filing number). No citation → the
  claim doesn't appear. Never cite a number not in the list.
- State `quarterly_financials` figures plainly (no [n] needed).

ATTRIBUTION
- Present management/forward-looking statements as theirs — "management said", "the filing notes" —
  never as your own view or prediction.

MANAGEMENT COMMENTARY
- If TOOL_DATA has a `management_commentary` block, those passages ARE real transcript / investor-presentation
  / annual-report text. Quote them, attribute to management ("management said…", "the presentation notes…"),
  and cite [n]. Prefer them for "what did management say" / guidance / "why did X change" / risks questions.
- If there is NO `management_commentary` block and the user asks what management SAID / guidance / concall
  detail, say so plainly — e.g. "the earnings-call transcript / presentation commentary isn't in our sources
  yet, so I can't quote what management said" — then give the filings + financials you DO have. This is a
  trust feature. NEVER fabricate quotes, guidance numbers, slide/page references, or a causal explanation the
  data doesn't contain.

EMPTY / VERIFICATION
- If no relevant filing is found, say so plainly and state it's from recent filings. For order/deal/bonus
  "is this true / did they file" questions, add: under SEBI LODR Reg 30 a material event must be disclosed
  within 24 hours, so if real it should appear soon — and offer to widen the window or alert on new filings.
- Never invent events, numbers, dates, or filings.

REGULATORY / LEGAL SCOPE (SEBI action, RBI/IRDAI order, insolvency, NCLT, IBC, litigation)
- Your only source is the company's OWN exchange disclosures (SEBI LODR self-disclosure). You do NOT have
  SEBI's order database, NCLT/IBBI cause-lists, or court records. So a regulatory/insolvency filing appears
  here ONLY if the company itself disclosed it to the exchange.
- If you find such a self-disclosure, report it with [n]. If you find NONE, you MUST NOT say "there is no
  case" / "no action exists". Say exactly the scoped truth: "I don't see any self-disclosed SEBI/insolvency
  filing for <company> in the recent exchange disclosures I can access. I don't have SEBI's or the NCLT's own
  records, so this doesn't rule one out — check the SEBI/NCLT/IBBI portals to confirm." This scope caveat is
  mandatory for these questions — a false "no case" is the worst possible answer.

MISSING TICKER
- If the question needs a company and none was resolved, ask: "Which company? Type $TICKER (e.g. $INFY)."

FORMAT
- ≤ 170 words, plain text. Use a numbered list only for "summarize / N points" requests (each point cited).

NO ADVICE (hard rule)
- Never give buy/sell/hold advice, price targets, "worth buying", or predicted price movements, and never
  say whether news is good/bad for the price. If asked, refuse briefly and redirect: "I can't give
  investment advice or price targets — I can show the filed results, guidance, and recent announcements,
  all cited. Want that?"
- Do NOT append a SEBI disclaimer — the UI renders one canonically.
""" + ANTI_HALLUCINATION_RULES


def _resolve_symbol(text: str):
    try:
        from services.copilot_tools.symbol_resolver import resolve_symbol
        return resolve_symbol(text)
    except Exception as exc:  # noqa: BLE001 — never let resolution break the turn
        logger.debug("symbol resolution failed: %s", exc)
        return None


# Cross-company / thematic questions ("which companies…", "who are the
# beneficiaries…") must run the thematic cross-company search, NOT collapse to a
# single ticker even when the resolver finds one (a stray acronym or sector word).
# When the phrasing is clearly about *a set of companies*, force thematic mode.
_THEMATIC_RE = re.compile(
    r"\bwhich\s+(?:\w+\s+){0,3}(?:companies|company|stocks?|firms?|players?|names|"
    r"smallcaps?|midcaps?|largecaps?|makers?|exporters?|beneficiar\w*)\b"
    r"|\bwhat\s+companies\b"
    r"|\bcompan(?:y|ies)\s+(?:that|which|are|is|investing|talking|mention\w*|"
    r"announc\w*|expand\w*|winning|won|affected|exposed|involved|adding)\b"
    r"|\bwho\s+(?:are|is)\s+(?:the\s+)?(?:beneficiar\w*|companies|players)\b"
    r"|\blist\s+(?:of\s+|me\s+)?(?:the\s+)?compan(?:y|ies)\b"
    r"|\bbeneficiar\w*\s+of\b|\bacross\s+(?:the\s+)?(?:sector|companies|market)\b",
    re.IGNORECASE,
)


def _is_thematic(text: str) -> bool:
    return bool(_THEMATIC_RE.search(text or ""))


# A SECTOR mention ("pharma sector", "IT companies", "banking stocks") is a
# cross-company question. The lexical symbol resolver would collapse the sector
# word to one ticker ("pharma" → SUNPHARMA, "IT" → a ticker), so force thematic
# whenever a sector word is followed by a set-noun. The DaaS events/search then
# resolves the sector to its constituents from nidp.sector_master (keyed on ISIN).
_SECTOR_RE = re.compile(
    r"\b(?:it|information technology|software|infotech|pharma|pharmaceutical|healthcare|"
    r"bank(?:s|ing)?|nbfc|financ\w*|auto\w*|fmcg|metal\w*|steel|mining|power|energy|"
    r"oil|gas|cement|realty|real estate|telecom\w*|chemical\w*|media|textile\w*|"
    r"capital goods|infra\w*|consumer\s+\w+)\s+"
    r"(?:sector|space|companies|company|stocks?|shares?|firms?|players?|majors?|names|pack|index|industry)\b",
    re.IGNORECASE,
)


def _names_sector(text: str) -> bool:
    return bool(_SECTOR_RE.search(text or ""))


async def stocks_insights_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What's the latest corporate news?",
    )

    # Resolve a ticker; None → thematic cross-company search.
    resolved = _resolve_symbol(user_msg)
    symbol = getattr(resolved, "symbol", None) if resolved else None
    company = getattr(resolved, "name", None) if resolved else None
    # A clearly cross-company question — explicit "which companies…" phrasing or a
    # SECTOR mention ("pharma sector", "IT companies") — overrides a spurious
    # single-ticker match (e.g. "pharma"→SUNPHARMA, "AI"→a ticker) so it runs the
    # thematic / sector search instead of collapsing to one company.
    if symbol and (_is_thematic(user_msg) or _names_sector(user_msg)):
        symbol = None
        company = None

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
    # Honest empty-case for a thematic (cross-company) query: finding nothing means
    # "no match in the current, still-building corpus" — NOT a system failure. Without
    # this, the shared ANTI_HALLUCINATION rule #4 makes the LLM emit a misleading
    # "please try again or contact support" line on empty thematic data. Deterministic,
    # and skips a pointless LLM call. (A real failure leaves result=None → generic path.)
    forced_answer = None
    if (result is not None and result.mode == "thematic"
            and not result.events and not result.commentary and not result.financials
            and (result.error or "") == "no_filings"):
        forced_answer = (
            "I searched recent exchange filings and management commentary across companies "
            "for that, but nothing matched in the current window yet. Cross-company thematic "
            "answers lean on concall transcripts and investor presentations, which are still "
            "being added to our sources — so coverage is partial here for now.\n\n"
            "For a specific company, type its ticker (e.g. $INFY) — its filed disclosures, "
            "results and announcements are fully covered."
        )

    if forced_answer is not None:
        answer_text = forced_answer
    else:
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
