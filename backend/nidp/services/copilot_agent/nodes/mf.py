"""MF Analyst agent node.

Handles: mutual fund performance, overlap, comparison, fund recommendations.
Calls: copilot_tools.mf  +  copilot_tools.mf_intelligence (4-layer NIDP data)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from langchain_core.messages import AIMessage

from .._llm import ANTI_HALLUCINATION_RULES, make_chat_llm, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Mutual Fund Analyst for Nivesh AI, an Indian investment platform.

You have fund performance, risk metrics, category rankings, lifecycle events,
top holdings, and disclosure data in TOOL_DATA. Ground every claim in those
numbers. All figures in INR or % as appropriate.

INTELLIGENCE LAYERS in TOOL_DATA:
1. scorecard — composite_score (0-100), quality_label, quartile ranks
2. lifecycle_events — red-flag events (⚠️): MANAGER_CHANGE, RISK_INCREASE, MERGER, TER_INCREASE
3. top_holdings — top equity positions + sector allocation
4. disclosure — current TER, fund manager, risk-o-meter

When asked "Is this a good fund?" or "Should I continue?":
1. State quality_label and composite_score
2. composite_rank / total_in_category e.g. "#5 of 31 Large Cap funds"
3. Call out any Q1 strengths or Q4 red flags in quartile data
4. Flag ⚠️ red-flag lifecycle events prominently (manager changes, TER hikes, mergers)
5. Mention if TER is creeping up from disclosure trail
6. Give a clear CONTINUE / REVIEW / EXIT recommendation with reasoning

Style:
- ≤ 350 words, plain text (no markdown)
- 1-year, 3-year, 5-year CAGR comparisons where available
- Risk metrics (Sharpe, max drawdown) if available
- Overlap % between funds if user asked about overlap
- Top-3 recommendation as plain lines if user asked for best funds
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


# Detects count / portfolio-size questions ("do I have too many funds?").
_COUNT_Q = re.compile(
    r"too many|how many (?:mutual )?funds|consolidat|over[\s-]?diversif|"
    r"trim (?:my )?(?:funds|portfolio)|reduce (?:my )?(?:number of )?funds|"
    r"portfolio size|how many schemes",
    re.IGNORECASE,
)


def _is_count_question(text: str) -> bool:
    return bool(_COUNT_Q.search(text or ""))


# Detects "fix the overlap" / consolidation requests (action-led, distinct from
# the count question). Checked BEFORE the count question so "consolidate" routes
# here.
_FIX_Q = re.compile(
    r"fix (?:the )?overlap|reduce (?:the )?overlap|consolidat|overlap|"
    r"clean up (?:my )?(?:funds|portfolio)|merge (?:my )?funds|redundan|"
    r"what should i do about (?:the )?overlap|de[\s-]?duplicat|switch to direct",
    re.IGNORECASE,
)


def _is_fix_question(text: str) -> bool:
    return bool(_FIX_Q.search(text or ""))


# Detects an overlap-SEVERITY/assessment question ("are my funds overlapping
# significantly?") — checked before the action-oriented fix question.
_SEVERITY_Q = re.compile(
    r"overlap\w*\s+significan|significan\w*\s+overlap|how much overlap|"
    r"(?:are|do)\s+my funds?\s+overlap|is (?:my|the)\s+overlap|"
    r"overlap\w*\s+(?:bad|serious|a problem|too much)",
    re.IGNORECASE,
)


def _is_severity_question(text: str) -> bool:
    return bool(_SEVERITY_Q.search(text or ""))


# Detects a cap-category comparison/education question ("large-cap vs flexi-cap
# vs mid-cap", "which category should I use").
_CAP_Q = re.compile(
    r"(?:large|mid|small|flexi|multi)[\s-]?cap.{0,40}\b(?:vs|versus|or)\b.{0,40}(?:large|mid|small|flexi|multi)[\s-]?cap|"
    r"large[\s-]?cap\s+vs|flexi[\s-]?cap\s+vs|which (?:cap|category|type of fund)|"
    r"difference between (?:large|mid|small|flexi)[\s-]?cap",
    re.IGNORECASE,
)


def _is_cap_question(text: str) -> bool:
    return bool(_CAP_Q.search(text or ""))


# Detects a single-fund query (vs portfolio-level overlap/count questions) and,
# when present, WHICH detail card the user wants. Drives name→scheme_code
# resolution and the instrument_detail / mf_detail widget choice.
_SINGLE_FUND_Q = re.compile(
    r"tell me about|good fund|should i (?:invest in|continue|buy|hold|pick)|"
    r"start\s+a?\s*sip\s+in|direct\s+(?:or|vs)\s+regular\s+plan|"
    r"(?:overview|returns?|holdings?|ratios?|peers?|full\s+analysis|allocation)\s+of\s+\w|"
    r"with\s+its\s+peers|full\s+analysis",
    re.IGNORECASE,
)
_V_PEERS = re.compile(r"\bpeers?\b|compare\b.+\b(?:with|to|vs|versus)\b|\bversus\b", re.IGNORECASE)
_V_HOLDINGS = re.compile(r"\bholdings?\b|what\s+does\s+it\s+(?:own|hold)|\ballocation\b|sector\s+breakdown", re.IGNORECASE)
_V_RETURNS = re.compile(r"\breturns?\b|\bcagr\b|trailing|\bperformance\s+(?:across|over)", re.IGNORECASE)
_V_OVERVIEW = re.compile(r"\boverview\b|full\s+analysis", re.IGNORECASE)


def _detect_mf_view(text: str) -> str | None:
    """Map a prompt to a detail view, or None for the default summary card."""
    t = text or ""
    if _V_PEERS.search(t):
        return "peers"
    if _V_HOLDINGS.search(t):
        return "holdings"
    if _V_RETURNS.search(t):
        return "returns"
    if _V_OVERVIEW.search(t):
        return "overview"
    return None


# Leaderboard / category-ranking queries ("best large-cap funds", "top funds",
# "which category") — these want get_top_funds, NOT a single-fund card, so we
# must never try to resolve them to one scheme.
_LEADERBOARD_Q = re.compile(
    r"\b(?:best|top|worst|recommend|suggest)\b.*\bfunds?\b|"
    r"\bfunds?\b.*\b(?:best|top|worst)\b|"
    r"\b(?:large|mid|small|flexi|multi)[\s-]?cap\s+(?:mutual\s+)?funds?\b|"
    r"which\s+(?:fund|category)",
    re.IGNORECASE,
)

# Questions about ONE fund's composition ("{fund} top-10 concentration", "top 10
# holdings of {fund}") — they contain "top"/"holdings" so the broad leaderboard
# heuristic ("fund … top") mis-reads them as a "top funds" list and skips
# single-fund resolution. Checked BEFORE _LEADERBOARD_Q to force resolution.
# Note "top-N concentration/holdings/stocks" ≠ "top-N funds" (the leaderboard).
_SINGLE_FUND_METRIC = re.compile(
    r"top[\s-]?\d+\s+(?:holdings?|concentration|stocks?|positions?)|"
    r"\bconcentration\b|portfolio\s+turnover|sector\s+allocation",
    re.IGNORECASE,
)

# Generic / educational MF questions ("what is NAV", "how do mutual funds work",
# "explain SIP") — no specific fund named; resolution would only mis-match.
_GENERIC_MF_Q = re.compile(
    r"what\s+(?:is|are)\s+(?:a\s+|an\s+)?(?:mutual\s+funds?|nav|sip|elss|"
    r"expense\s+ratio|ter|aum|exit\s+load|lump\s*sum)\b|"
    r"how\s+(?:do|does)\s+(?:mutual\s+funds?|sips?|nav)\b|"
    r"explain\s+(?:mutual\s+funds?|sips?|nav|elss)\b|"
    r"difference\s+between\s+(?:sip|lump)",
    re.IGNORECASE,
)


def _should_resolve_scheme(
    text: str,
    *,
    is_single_fund: bool,
    is_portfolio_q: bool,
    has_scheme_code: bool,
) -> bool:
    """Decide whether to attempt fund NAME → scheme_code resolution.

    The intent node only extracts 6-digit AMFI codes, so a fund named in prose
    ("HDFC Balanced Advantage Fund", "How is <fund>?") arrives with no code.
    Those queries match neither `_SINGLE_FUND_Q` nor a portfolio question and
    used to fall through to the portfolio-overlap catch-all → a "data
    unavailable" answer with no MF card. We let a SUCCESSFUL resolution promote
    such a query to a single-fund card, while still skipping portfolio,
    leaderboard, and generic/educational questions so those keep their paths.
    """
    if has_scheme_code:
        return False
    if is_single_fund:          # explicit single-fund phrasing — always resolve
        return True
    if is_portfolio_q:          # count / fix / severity / cap → not a single fund
        return False
    t = text or ""
    # A single-fund composition metric ("top-10 concentration") names one fund —
    # resolve it, before the leaderboard heuristic mistakes "fund … top" for a list.
    if _SINGLE_FUND_METRIC.search(t):
        return True
    if _LEADERBOARD_Q.search(t) or _GENERIC_MF_Q.search(t):
        return False
    return True


# Plain-text answer format for "do I have too many funds?" and similar
# count/portfolio-size questions. Replaces the default markdown style because
# the V5 chat surface renders Markdown as literal characters.
_COUNT_FORMAT = """You are answering a COUNT / portfolio-size question (e.g. "do I have too many funds?").

OUTPUT IN PLAIN TEXT ONLY. This surface does NOT render Markdown. Never use
'#', the asterisk character, backticks, or pipe ('|') tables — they appear as
literal characters. The ONLY formatting permitted: line breaks, the block-bar
characters █ and ░, and the arrow →.

ANSWER THE QUESTION ASKED. "Too many funds" is about COUNT and manageability,
not overlap. Lead with how many distinct strategies the user holds and whether
that count is reasonable. Overlap is only EVIDENCE that supports trimming — it
is never the headline.

Use ONLY values from TOOL_DATA: mf_count, regular_direct_duplicate_pairs,
cross_fund_overlap_pairs, removable_fund_count, and the overlap rows (each has
is_plan_duplicate). Never invent a count.

REQUIRED ORDER (do not reorder):
1. Verdict — one sentence: "Not too many" / "About right" / "More than you need
   — it's a consolidation (or concentration) issue, not a bad-funds issue."
2. Count block — a block-bar, then one reading sentence:
     Holdings you own:     ████████  {N}
     Distinct strategies:  █████     {D}   ({why they collapse})
     Could trim to:        ████      {T}
   Then: "{N} funds, but {D} real bets; {T} would lose nothing."
   N = mf_count. D = N minus the Regular+Direct duplicates and near-identical
   funds. T = N minus removable_fund_count.
3. Fix 1 — ONLY if regular_direct_duplicate_pairs > 0 — one framing line, then
   one "→ {Scheme} — Regular to Direct" per duplicate scheme. Close: "Identical
   fund, lower cost. Check exit load and capital-gains tax before switching."
4. Fix 2 — ONLY if cross_fund_overlap_pairs > 0 — one framing line, then
   "→ {Fund A} and {Fund B}: ~{x}% overlap. {one question to ask}".
5. Caveat (fixed, verbatim): "Based on holdings overlap only — no returns, fees,
   fund size or manager record here. Not financial advice; confirm the tax points."

RULES:
- Total under ~120 words. Verdict ≤ 1 sentence. Each fix block ≤ 1 framing line
  plus its arrows.
- Blocks 3 and 4 are conditional. If an issue does not exist, omit the block
  entirely — never write "no duplicates found". Match the verdict (e.g. "About
  right" when nothing needs trimming).
- Treat Regular vs Direct of the same scheme as a COST issue, not overlap:
  identical portfolio, lower-cost plan. Never frame it as redundant
  diversification.
- If a full pair-by-pair list is requested, say it will follow as a separate
  reply. Never inline the full list here.

FAILURE CASE — if TOOL_DATA has overlap pairs but mf_count is missing or 0, do
NOT estimate the count. Output exactly one line:
"I can see which funds overlap, but not your total fund count — so I can flag
redundancy but not strictly whether you hold too many."
""" + ANTI_HALLUCINATION_RULES


# Plain-text answer format for "fix the overlap" / consolidation requests.
# Action-led (state the fix first); overlap numbers are justification, not the
# headline.
_FIX_FORMAT = """You are answering a "fix the overlap" / consolidation request.

OUTPUT IN PLAIN TEXT ONLY. No '#', the asterisk character, backticks, or pipe
('|') tables — they render as literal characters here. Allowed: line breaks,
the arrow →, and block-bar characters █ ░.

LEAD WITH THE ACTION, not the analysis. The user wants to know what to DO. State
the fix first; the overlap numbers are the justification, not the headline.

SEPARATE THE TWO PROBLEM TYPES — they have different fixes (use TOOL_DATA:
each overlap row has is_plan_duplicate; counts are regular_direct_duplicate_pairs
and cross_fund_overlap_pairs):
- Regular vs Direct of the SAME scheme = a COST fix, not overlap. Identical
  portfolio; the Direct plan just costs less. Action: redirect future SIPs to
  Direct and switch existing units to Direct. NEVER call this "duplicate
  exposure" or "diversification overlap."
- Two DIFFERENT funds with high overlap = a genuine redundancy review. Action:
  keep one, ask whether the second earns its place.

REQUIRED ORDER:
1. One-line summary: how many pairs overlap and the single biggest fix.
2. Cost fix (only if regular_direct_duplicate_pairs > 0), one "→" line per scheme:
   → {Scheme}: redirect SIP to Direct, switch existing units across.
   Close: "Same fund, lower cost. Switching is a sell+rebuy — check exit load
   and capital-gains tax first."
3. Redundancy review (only if cross_fund_overlap_pairs > 0), one "→" line each:
   → {Fund A} vs {Fund B}: ~{x}% overlap — keep one. {one-line question}
4. How to execute (one sentence): redirect SIPs now (free, immediate); move
   existing units gradually, not in one large redemption, to manage tax.
5. Caveat (fixed, verbatim): "Based on holdings overlap only — no returns, fees
   or manager record here. Not financial advice; confirm tax and exit load
   before acting."

RULES:
- Total under ~140 words. Each action line is one line.
- Omit any block whose issue does not exist — never write "none found."
- Do NOT create a column/row for a value you do not have. If switch or
  redemption amounts are unavailable, say so ONCE at the end: "Exact switch
  amounts aren't available here." Never repeat "data unavailable" cell by cell.
- If total_value_rs or equity_pct IS available in TOOL_DATA, use it to frame
  pacing (a large equity-heavy book means stagger the switches), but NEVER
  invent per-fund amounts from a total.

PRIORITY when multiple fixes apply: cost duplicates (Regular→Direct) first —
free and unambiguous — then active-vs-index overlap, then multiple same-index
funds.
""" + ANTI_HALLUCINATION_RULES


async def _fetch_mf_intelligence(scheme_code: str) -> list[ToolResult]:
    """Fetch 4-layer MF intelligence from NIDP concurrently."""
    try:
        import importlib
        intel_mod = importlib.import_module("services.copilot_tools.mf_intelligence")
        result = await intel_mod.get_mf_intelligence(scheme_code)

        tool_results = [
            ToolResult(
                ok=result.ok,
                tool_name="mf_scorecard",
                summary=result.summary,
                data={
                    "composite_score":    result.composite_score,
                    "quality_label":      result.quality_label,
                    "composite_rank":     result.composite_rank,
                    "total_in_category":  result.total_in_category,
                    "top_position_pct":   result.top_position_pct,
                    **result.scorecard,
                },
                rows=[],
            ),
            ToolResult(
                ok=True,
                tool_name="mf_lifecycle_events",
                summary=(
                    f"{len(result.events)} lifecycle events, "
                    f"red_flags={result.has_red_flags}"
                ),
                data={"has_red_flags": result.has_red_flags, "count": len(result.events)},
                rows=result.events,
            ),
            ToolResult(
                ok=True,
                tool_name="mf_holdings",
                summary=f"{len(result.top_holdings)} holdings, top sectors: " + ", ".join(
                    f"{s.get('sector','?')} {s.get('total_weight',0):.1f}%"
                    for s in result.top_sectors[:3]
                ),
                data={"top_sectors": result.top_sectors},
                rows=result.top_holdings,
            ),
            ToolResult(
                ok=True,
                tool_name="mf_disclosure",
                summary=(
                    f"TER={result.current_ter:.2f}% " if result.current_ter else "TER=N/A "
                ) + f"manager={result.current_manager or '?'} risk={result.risk_o_meter or '?'}",
                data={
                    "current_ter":     result.current_ter,
                    "current_manager": result.current_manager,
                    "risk_o_meter":    result.risk_o_meter,
                },
                rows=result.disclosures,
            ),
        ]
        return tool_results
    except Exception as exc:
        logger.warning("mf_intelligence fetch failed for %s: %s", scheme_code, exc)
        return [ToolResult(
            ok=False, tool_name="mf_intelligence",
            summary=f"MF intelligence unavailable for {scheme_code}",
            error=str(exc),
        )]


async def _fetch_mf_data(state: CopilotState) -> list[ToolResult]:
    try:
        import importlib
        mf_mod = importlib.import_module("services.copilot_tools.mf")

        user_id    = state.user_id
        scheme_code = state.intent.scheme_code if state.intent else None
        category    = state.intent.category    if state.intent else None

        results: list[ToolResult] = []

        if scheme_code:
            # Fetch basic performance + 4-layer intelligence concurrently
            perf_task  = mf_mod.get_mf_performance(scheme_code)
            intel_task = _fetch_mf_intelligence(scheme_code)
            perf, intel_results = await asyncio.gather(perf_task, intel_task)

            results.append(ToolResult(
                ok=perf.ok, tool_name="get_mf_performance",
                summary=perf.summary, data=perf.data, rows=perf.rows,
                error=perf.error,
            ))
            results.extend(intel_results)

        elif category:
            top = await mf_mod.get_top_funds(category=category)
            results.append(ToolResult(
                ok=top.ok, tool_name="get_top_funds",
                summary=top.summary, data=top.data, rows=top.rows,
                error=top.error,
                widget_type=WidgetType.FUND_COMPARISON,
            ))
        else:
            if user_id:
                # Portfolio-level overlap lives in the portfolio tool, not mf
                # (mf.py only has get_fund_overlap(scheme_codes)). Calling the
                # wrong module raised AttributeError → empty TOOL_DATA → the
                # "couldn't retrieve the data" reply.
                portfolio_mod = importlib.import_module("services.copilot_tools.portfolio")
                overlap = await portfolio_mod.get_portfolio_overlap(user_id)
                results.append(ToolResult(
                    ok=overlap.ok, tool_name="get_portfolio_overlap",
                    summary=overlap.summary, data=overlap.data, rows=overlap.rows,
                    widget_type=WidgetType.OVERLAP_REVEAL,
                ))
            else:
                results.append(ToolResult(
                    ok=False, tool_name="get_mf_performance",
                    summary="No scheme code or category provided",
                    error="missing_params",
                ))
        return results
    except Exception as exc:
        logger.warning("mf data fetch failed: %s", exc)
        return [ToolResult(ok=False, tool_name="mf_tools", summary="MF data unavailable", error=str(exc))]


def _build_intel_context(results: list[ToolResult]) -> str:
    """Build a compact LLM context block from intelligence ToolResults."""
    lines = ["TOOL_DATA:"]
    for tr in results:
        lines.append(f"  [{tr.tool_name}] {tr.as_llm_context()}")
    return "\n".join(lines)


async def mf_node(state: CopilotState) -> dict:
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "Tell me about mutual funds",
    )

    # "Fix overlap"/consolidate and "too many funds" questions answer with a
    # structured consolidation widget (the V5 chat renders it natively); the
    # text is a short plain-text fallback. Other MF questions use _SYSTEM.
    is_cap = _is_cap_question(user_msg)
    is_count = _is_count_question(user_msg)
    is_severity = _is_severity_question(user_msg)
    is_fix = _is_fix_question(user_msg)
    style = _COUNT_FORMAT if is_count else (_FIX_FORMAT if (is_fix or is_severity) else _SYSTEM)

    # Single-fund query? (distinct from portfolio overlap/count). If so, figure
    # out the detail view and resolve a fund NAME → scheme_code so the card
    # builders have a code to query (the intent node only catches 6-digit codes).
    is_portfolio_q = is_count or is_fix or is_severity or is_cap
    mf_view = _detect_mf_view(user_msg)
    is_single_fund = (not is_portfolio_q) and bool(mf_view or _SINGLE_FUND_Q.search(user_msg))

    scheme_code = state.intent.scheme_code if state.intent else None
    if _should_resolve_scheme(
        user_msg,
        is_single_fund=is_single_fund,
        is_portfolio_q=is_portfolio_q,
        has_scheme_code=bool(scheme_code),
    ):
        try:
            from services.copilot_tools.scheme_resolver import resolve_scheme
            match = await resolve_scheme(user_msg)
            if match:
                scheme_code = match.scheme_code
                # A bare fund name ("HDFC Balanced Advantage Fund") that only
                # resolved here is still a single-fund card; promote it so the
                # MF_DETAIL tile gets built and the data fetch queries the code
                # instead of falling through to portfolio overlap.
                is_single_fund = True
                if mf_view is None:
                    mf_view = "summary"
                if state.intent is not None:
                    state.intent.scheme_code = scheme_code  # so _fetch_mf_data queries it
        except Exception as exc:  # noqa: BLE001
            logger.warning("mf scheme resolution failed: %s", exc)

    tool_results = await _fetch_mf_data(state)
    tool_context = _build_intel_context(tool_results)

    widget_type = WidgetType.NONE
    widget_data: dict = {}
    overlap_tr = next(
        (tr for tr in tool_results if tr.tool_name == "get_portfolio_overlap" and tr.ok),
        None,
    )
    if is_cap:
        # Cap-category education ("large-cap vs flexi-cap vs mid-cap"). The
        # widget is mostly general guidance; overlap_tr (may be None) only
        # personalises the large-cap-doubling insight.
        from services.copilot_tools.portfolio import build_cap_education_widget
        widget_type = WidgetType.CAP_EDUCATION
        widget_data = build_cap_education_widget(overlap_tr)
    elif is_count and overlap_tr:
        from services.copilot_tools.portfolio import build_consolidation_widget
        widget_type = WidgetType.FUND_CONSOLIDATION
        widget_data = build_consolidation_widget(overlap_tr)
    elif is_severity and overlap_tr:
        from services.copilot_tools.portfolio import build_overlap_severity_widget
        widget_type = WidgetType.OVERLAP_SEVERITY
        widget_data = build_overlap_severity_widget(overlap_tr)
    elif is_fix and overlap_tr:
        from services.copilot_tools.portfolio import build_overlap_widget
        widget_type = WidgetType.FUND_OVERLAP
        widget_data = build_overlap_widget(overlap_tr)
    elif not is_single_fund:
        for tr in tool_results:
            if tr.widget_type and tr.widget_type != WidgetType.NONE:
                widget_type = tr.widget_type
                widget_data = {"rows": tr.rows, **tr.data}
                break

    # Single-fund card. ONE mf_detail widget holds every tab (summary + overview/
    # returns/holdings/peers); the client switches tabs locally with no re-fetch.
    # `active` is the tab the user asked for ("show the holdings of X" → holdings),
    # defaulting to summary. Holdings/peers tabs are present only when they have
    # real data (gated inside get_mf_full_card).
    if widget_type == WidgetType.NONE and scheme_code and is_single_fund:
        try:
            from services.copilot_tools.mf_cards import get_mf_full_card
            card = await get_mf_full_card(scheme_code, active=mf_view or "summary")
            if card.ok and card.widget:
                widget_type = WidgetType.MF_DETAIL
                widget_data = card.widget
        except Exception as exc:  # noqa: BLE001
            logger.warning("mf card build failed for %s (%s): %s", scheme_code, mf_view, exc)

    # Attach the question-first research rail (chips + lens views) to the single-fund
    # card so it renders as a Research Hub. No-op for portfolio/overlap widgets.
    if widget_type == WidgetType.MF_DETAIL and widget_data:
        from services.copilot_tools.research_lenses import build_research_hub
        build_research_hub("mf", widget_data)

    # Widget data is ready (built from the tools, not the LLM) — push it now so
    # the client renders it first and streams the narrative underneath.
    from .._stream import emit_widget
    await emit_widget(widget_type, widget_data)

    llm = make_chat_llm(temperature_for(0.1))
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + style + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    response = AgentResponse(
        agent=AgentName.MF,
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
