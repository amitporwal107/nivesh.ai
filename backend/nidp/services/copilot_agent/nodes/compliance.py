"""Compliance filter + hallucination guard node.

This is the last node before END. It:
  1. Injects a mandatory SEBI disclaimer if not already present
  2. Runs a numeric grounding check — flags if LLM cited figures that don't
     appear anywhere in the tool_results (basic hallucination guard)
  3. Caps response length to 400 words
"""
from __future__ import annotations

import logging
import re
from typing import List

from langchain_core.messages import AIMessage

from ..schemas import AgentResponse, CopilotState, ToolResult

logger = logging.getLogger(__name__)

# ── Wording rule (owner, 3 Nov 2026: "do not use words like buy, stop loss, target") ─────────────────────
# Nivesh is not a SEBI-registered Research Analyst, so no answer may read like a trading call. One instruction, shared by
# every answer prompt (persona_framing.frame_for_persona adds it to each specialist node's system prompt); _ADVICE_RE
# below is the deterministic backstop for the imperative forms. Each line that names a word to avoid says "never use",
# so the prompt lint (tests/test_chat_compliance_delivery.py cc6) can tell a ban from a demand.
VOCABULARY_RULE = (
    "WORDING RULE (Nivesh is not a SEBI-registered Research Analyst, so nothing may read like a trading call):\n"
    "- Never use these words as calls or labels: buy, sell, stop loss, SL, target, T1, T2, entry, exit, book profits, "
    "accumulate, trim, upside, downside, price target, recommend, recommendation, pick, suggested trade, best trade.\n"
    "- Say instead: 'long' / 'short' for a side or a leg (e.g. 'Long 1 NIFTY 24000 CE'); 'reference price' for an entry "
    "level; 'risk level' for a stop; 'reward level' (reward level 1 / 2) for a target; 'loss at risk level' for the loss "
    "at a stop; 'close' only for the user's own paper position.\n"
    "- Call candidates ideas that fit the rules, ordered for review; describe, never instruct."
)

_DISCLAIMER = (
    "\n\n---\n*⚠️ DISCLAIMER: AI-generated analysis for educational purposes only. "
    "Past performance does not guarantee future results. "
    "Consult a SEBI-registered investment advisor before making investment decisions.*"
)

# Short, contextually-relevant follow-ups offered as chips under each AI
# bubble. Keyed by AgentName.value. Kept generic — agents that want to
# overwrite these should populate `response.follow_ups` directly.
_DEFAULT_FOLLOW_UPS = {
    "market_analyst": [
        "Show sector rotation today",
        "Which indices are leading?",
        "FII vs DII flows this week",
    ],
    "stock_analyst": [
        "Compare with sector peers",
        "Show the 5-year fundamentals",
        "Latest news and brokerage views",
    ],
    "mf_analyst": [
        "Check overlap with my funds",
        "Show better alternatives",
        "How does this fit my risk profile?",
    ],
    "portfolio_analyst": [
        "Run a rebalance simulation",
        "Run a stress test",
        "Show tax-loss harvest candidates",
    ],
    "risk_analyst": [
        "How can I lower this risk?",
        "Run a stress test",
        "Suggest a hedge",
    ],
    "goal_planner": [
        "Increase my SIP by 10%",
        "Add a new goal",
        "Show me a goal trade-off",
    ],
    "recommendation": [
        "Show one-click SIP for the first idea",
        "Compare the top 3 ideas",
        "Why this and not the second idea?",
    ],
}

# Patterns that look like INR figures in the LLM response
_INR_RE = re.compile(r"₹\s*[\d,]+(?:\.\d+)?(?:\s*(?:lakh|crore|cr|L|K))?", re.IGNORECASE)
_PCT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")


def _extract_numbers_from_text(text: str) -> set:
    """Extract bare numeric strings from text for grounding comparison."""
    nums = set()
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", text):
        nums.add(m.group(1))
    return nums


def _extract_numbers_from_tools(tool_results: List[ToolResult]) -> set:
    """Extract all numeric values from tool result data + summaries."""
    nums = set()
    for tr in tool_results:
        for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", tr.summary or ""):
            nums.add(m.group(1))
        for v in tr.data.values():
            for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", str(v)):
                nums.add(m.group(1))
        for row in tr.rows:
            for v in row.values():
                for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", str(v)):
                    nums.add(m.group(1))
    return nums


def _grounding_ok(response_text: str, tool_results: List[ToolResult]) -> bool:
    """Returns False if the LLM cited > 3 financial figures not in tool data.

    This is a heuristic — it fires on numbers ≥ 4 digits (rupee amounts,
    percentages rounded to 2 dp) to avoid false positives on common small
    numbers like years, counts, etc.
    """
    if not tool_results or all(not tr.ok for tr in tool_results):
        # no tool data at all — can't check, assume OK
        return True

    response_nums = {n for n in _extract_numbers_from_text(response_text) if len(n.replace(".", "")) >= 4}
    tool_nums = _extract_numbers_from_tools(tool_results)

    hallucinated = response_nums - tool_nums
    if len(hallucinated) > 3:
        logger.warning("grounding check: %d unmatched figures: %s", len(hallucinated), list(hallucinated)[:5])
        return False
    return True


def _trim_to_word_limit(text: str, limit: int = 400) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    trimmed = " ".join(words[:limit])
    return trimmed + "…\n\n*(Response truncated for brevity.)*"


# Matches a trailing SEBI / "AI-generated" disclaimer paragraph the LLM may
# have appended in response to the system-prompt instruction. Conservative —
# only strips if the line contains both "DISCLAIMER" and a SEBI keyword so
# legitimate prose isn't truncated.
_INLINE_DISCLAIMER_RE = re.compile(
    r"(?:\n+-{2,}\s*)?\n*\*?\s*⚠?\s*DISCLAIMER[\s\S]*?(?:SEBI|advisor|investment advice|market risks|professional advice|investment decisions)[\s\S]*$",
    re.IGNORECASE,
)


def _strip_inline_disclaimer(text: str) -> str:
    stripped = _INLINE_DISCLAIMER_RE.sub("", text)
    return stripped.rstrip()


# ── No-advice guard (PRD non-goal + Appendix B §G) ─────────────────────────
# The copilot must NEVER emit buy/sell/hold calls, price targets, or price
# predictions. Some upstream nodes (esp. the stock analyst) can slip these in;
# this scrubs them as a deterministic backstop, independent of prompt discipline.
_ADVICE_RE = re.compile(
    r"\b(?:short|long|near)[- ]term\s+(?:view|call|stance)\s*(?:is|:)?\s*(?:buy|sell|hold|reduce|accumulate)\b"
    r"|\brecommendation\s*:?\s*(?:strong\s+)?(?:buy|sell|hold|reduce|accumulate)\b"
    r"|\b(?:strong\s+)?(?:buy|sell|hold|reduce|accumulate)\s+(?:rating|call|recommendation|signal)\b"
    r"|\btarget\s+price\b|\bprice\s+target\b"
    r"|\b(?:you|we|i)\s+(?:should|would|could)\s+(?:buy|sell|book|exit|accumulate|reduce)\b"
    r"|\b(?:we|i)\s+recommend\b|\brecommend\s+(?:buy|sell|hold|ing|ed)\b"
    r"|\bwill\s+(?:likely\s+)?(?:rise|fall|go\s+up|go\s+down|drop|surge|rally|crash|decline|climb)\b"
    r"|\b(?:looks?|is|are|turning|remains?)\s+(?:bullish|bearish)\b|\bbullish\b|\bbearish\b"
    r"|\bgood\s+time\s+to\s+(?:buy|sell|enter|exit)\b|\bwhether\s+to\s+(?:buy|sell)\b"
    # Added 3 Nov 2026 (wording rule): imperative levels and calls the patterns above missed.
    r"|\bprice\s+targets\b|\b(?:buy|sell)\s+signals?\b|\b(?:buy|sell)\s+(?:now|today|here|on\s+dips?)\b"
    r"|\b(?:buy|sell|enter|exit|accumulate)\s+(?:at|above|below|near|around|on\s+dips?)\b"
    r"|\bstop[- ]?loss\s*(?:at|of|near|around|below|above|is|[:=@])\s*(?:₹|rs\.?|inr)?\s*\d"
    r"|\b(?:sl|t1|t2|target)\s*(?:at|of|is|[:=@])?\s*(?:₹|rs\.?|inr)\s*\d|\b(?:sl|t1|t2)\s*[:=@]\s*\d"
    r"|\b(?:place|keep|set|put|use)\s+(?:a\s+|your\s+|the\s+)?(?:stop[- ]?loss|sl)\b"
    r"|\bbook(?:ing)?\s+(?:your\s+|some\s+|partial\s+)?profits?\b|\bexit\s+(?:now|today|here)\b",
    re.IGNORECASE,
)
_ADVICE_NOTE = ("\n\n*Factual filings/data only — Nivesh Copilot does not give investment advice, "
                "trading calls, price levels to act on or price predictions.*")


def _scrub_advice(text: str) -> tuple[str, bool]:
    """Neutralise any buy/sell/hold / price-target / price-prediction phrasing.
    Returns (scrubbed_text, had_advice)."""
    if not _ADVICE_RE.search(text):
        return text, False
    return _ADVICE_RE.sub("[factual data only — not advice]", text), True


async def compliance_node(state: CopilotState) -> dict:
    response: AgentResponse | None = state.response
    if response is None:
        # nothing to check — create an empty safe response
        response = AgentResponse(
            agent=state.intent.agent if state.intent else "market_analyst",
            text="I'm sorry, I couldn't generate a response. Please try again.",
        )

    text = response.text or ""

    # 1. Trim excessive length
    text = _trim_to_word_limit(text, limit=400)

    # 2. Strip any in-body SEBI disclaimer the LLM volunteered. The frontend
    # already shows a single canonical disclaimer below the input box; a
    # duplicate inside every bubble adds visual noise without helping the
    # user. The audit-trail copy lives on `response.disclaimer`.
    text = _strip_inline_disclaimer(text)

    # 2b. No-advice guard — scrub any buy/sell/hold / target / price-prediction language.
    text, had_advice = _scrub_advice(text)
    if had_advice:
        text = text.rstrip() + _ADVICE_NOTE

    # 3. Grounding check
    grounding = _grounding_ok(text, state.tool_results or [])

    # 4. If grounding failed, prepend a caveat
    if not grounding:
        text = (
            "⚠️ *Some figures in this response could not be verified against live data. "
            "Please treat them as illustrative only.*\n\n"
        ) + text

    # 5. Provide follow-ups if the agent didn't supply its own
    follow_ups = list(response.follow_ups or [])
    if not follow_ups:
        agent_key = response.agent if isinstance(response.agent, str) else getattr(response.agent, "value", str(response.agent))
        follow_ups = list(_DEFAULT_FOLLOW_UPS.get(agent_key, []))[:3]

    # Build updated response
    updated_response = response.model_copy(update={
        "text": text,
        "disclaimer": _DISCLAIMER.strip(),
        "grounding_ok": grounding,
        "follow_ups": follow_ups,
    })

    return {
        "response": updated_response,
        "messages": [AIMessage(content=text)],
    }
