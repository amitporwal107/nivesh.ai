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

_DISCLAIMER = (
    "\n\n---\n*⚠️ DISCLAIMER: AI-generated analysis for educational purposes only. "
    "Past performance does not guarantee future results. "
    "Consult a SEBI-registered investment advisor before making investment decisions.*"
)

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

    # 2. Inject disclaimer if missing
    disclaimer_present = any(kw in text.lower() for kw in ("disclaimer", "sebi", "investment advice", "consult"))
    if not disclaimer_present:
        text = text + _DISCLAIMER

    # 3. Grounding check
    grounding = _grounding_ok(text, state.tool_results or [])

    # 4. If grounding failed, prepend a caveat
    if not grounding:
        text = (
            "⚠️ *Some figures in this response could not be verified against live data. "
            "Please treat them as illustrative only.*\n\n"
        ) + text

    # Build updated response
    updated_response = response.model_copy(update={
        "text": text,
        "disclaimer": _DISCLAIMER.strip(),
        "grounding_ok": grounding,
    })

    return {
        "response": updated_response,
        "messages": [AIMessage(content=text)],
    }
