"""Insight generator — OpenAI function-calling over a filing's parsed PDF text.

Mirrors announcement_classifier's proven OpenAI path (structured output via a
`strict` function tool, key via nidp.shared.openai_key). NOT the Anthropic
pattern of event_analyzer/d1_prep — the project has an OpenAI license only, and
those Claude services have never actually run (see FILINGS_HOME_SPEC §5 / repo
memory nidp-openai-only-no-anthropic).

The one thing this must get right (FILINGS_HOME_SPEC §4.2/§4.3): the summary and
the headline number come ONLY from the document text. If a number is not stated
in the filing, `headline_metric` is null — never estimated, never inferred from
the boilerplate subject line.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from openai import OpenAI

from nidp.shared.openai_key import get_openai_api_key

logger = logging.getLogger(__name__)

MODEL = os.environ.get("FILING_INSIGHTS_MODEL", "gpt-4o-mini")

# Provider indirection — this generator speaks the OpenAI chat-completions +
# function-calling protocol, which most hosted open-weight providers
# (Together / Fireworks / Groq / DeepInfra / OpenRouter) expose verbatim. To run
# an open model instead of OpenAI, set:
#   FILING_INSIGHTS_BASE_URL   the provider's OpenAI-compatible endpoint
#   FILING_INSIGHTS_API_KEY    that provider's key (falls back to OPENAI_API_KEY)
#   FILING_INSIGHTS_MODEL      e.g. "meta-llama/Llama-3.3-70B-Instruct-Turbo"
# Unset base_url → plain OpenAI, unchanged. Nothing else in the pipeline changes:
# insights are independent per filing, so switching the model here carries none of
# the vector-space lock-in that made the embedding model hard to switch.
_BASE_URL = os.environ.get("FILING_INSIGHTS_BASE_URL") or None

# strict-mode function-calling is an OpenAI extension; some open-weight providers
# support tools but reject `strict`. Default on (OpenAI), set FILING_INSIGHTS_STRICT=0
# for a provider that 400s on it — tool-calling still forces structured output.
_STRICT = os.environ.get("FILING_INSIGHTS_STRICT", "1").lower() not in ("0", "false", "no")


def _resolve_key() -> str:
    """Provider key first (for a non-OpenAI endpoint), else the OpenAI key."""
    return os.environ.get("FILING_INSIGHTS_API_KEY") or get_openai_api_key() or ""

# Cap the document text fed to the model. ~24k chars ≈ ~6k tokens — plenty for a
# results/press-release filing, and a hard bound on cost + latency for the rare
# 200-page annual report (which we truncate rather than skip).
MAX_TEXT_CHARS = 24_000

SENTIMENTS = ("positive", "neutral", "negative")

# The expanded AI-Insights panel's tabs (docs/ai_research/designs — desktop +
# mobile). An annual report answers different questions than a results filing, so
# the tab set is doc-type aware; the design shows exactly these two sets.
_AR_TABS = ("Business Overview", "MD & A", "Financial Statements", "Accounting Notes")
_GENERIC_TABS = ("Quick Summary", "Sentiment", "Business Outlook", "Potential Risks")


def tabs_for(doc_type: Optional[str]) -> tuple[str, ...]:
    return _AR_TABS if (doc_type or "") == "annual_report" else _GENERIC_TABS

# Placeholder strings a model may return INSTEAD of a real JSON null. Measured on
# staging 2026-07-19: the open-weight provider (Llama-3.3-70B) returns the literal
# string "null" for nullable union fields rather than a null — 79/120 live rows had
# period == "null", and units like "null" were being concatenated onto the metric
# ("Acquisition: Hyatt Regency Mumbai hotel null"). Any nullable text field coming
# back from the model must go through _nullish, not just the metric value.
_NULLISH = {"null", "none", "nan", "n/a", "na", "nil", "not disclosed", "undisclosed",
            "not specified", "not applicable", "not available", "unknown", "-", "--", ""}


def _nullish(v: Any) -> bool:
    """True when a model returned a placeholder where it should have sent null."""
    return v is None or str(v).strip().lower() in _NULLISH

_SYSTEM_PROMPT = """You summarise a single Indian-market corporate filing (an NSE/BSE disclosure) for an investor feed.

You are given the company, the filing's event category, and the FULL PARSED TEXT of the filing's PDF. Produce a tight, factual insight grounded ONLY in that text.

Hard rules:
- Ground every word in the provided document text. Do NOT use outside knowledge, and do NOT infer from the company name or category alone.
- one_liner: ONE sentence, <= 200 chars, stating what actually happened and the concrete detail an investor cares about (e.g. the order value and client, the revenue/PAT and its change, the rating action and agency). No hype, no recommendation.
- headline_metric: the single most important FINANCIAL figure explicitly stated in the filing — money (order value, revenue, PAT, default amount), shares, a percentage/ratio, a dividend per share, or a credit-rating grade. It must be an actual figure. Return null if the filing states no such figure, OR only says a value exists without the amount (e.g. an "undisclosed" order). Do NOT return procedural numbers (meeting/notice/agenda numbers, dates, clause numbers) and do NOT put words like "Not disclosed" in the value — those mean null. NEVER estimate, round from nothing, or fabricate a figure.
- period: the reporting/effective period if the filing states one (e.g. "Q1 FY26", "FY25", "for the quarter ended June 30, 2026"); else null.
- sentiment: market-impact directionality for shareholders (positive/neutral/negative), from the facts in the document.
- confidence: 0-100 — how well the document supports this insight. Low if the text is thin, garbled, or off-topic (e.g. only a cover letter linking an audio recording).
- sections: the expanded panel. Populate the tabs listed in the user message, in that order. Each section carries a short heading, 1-4 bullet items, and the page range the facts came from.
  * Every bullet must be a fact the document states. If the document does not support a tab, EMIT NO SECTION for that tab — an absent tab is correct and expected; a padded or hedged one ("no specific risks were mentioned", "outlook appears stable") is a failure.
  * cite_page_start/cite_page_end: the 1-based page numbers of the FILING TEXT you drew that section from. The text is marked with [[page N]] rules — use those numbers, never guess. Omit both if you cannot point to a page.
  * Bullets are terse and factual (<= 220 chars), no hype, no recommendation, no repetition of the one_liner.
- Output ONLY via the emit_insight function. Never produce free text."""

_EMIT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "emit_insight",
        "description": "Emit the structured insight for one corporate filing.",
        "parameters": {
            "type": "object",
            "properties": {
                "one_liner":  {"type": "string", "description": "<=200 char factual one-sentence summary, grounded in the document"},
                "period":     {"type": ["string", "null"], "description": "reporting/effective period stated in the filing, else null"},
                "headline_metric": {
                    "type": ["object", "null"],
                    "description": "the single most important number explicitly stated in the filing, or null",
                    "properties": {
                        "label": {"type": "string", "description": "what the number is, e.g. 'Order value', 'Revenue', 'PAT', 'Dividend'"},
                        "value": {"type": "string", "description": "the number exactly as stated, e.g. '507.24'"},
                        "unit":  {"type": "string", "description": "unit/currency as stated, e.g. '₹ Cr', '₹/share', '%'"},
                    },
                    "required": ["label", "value", "unit"],
                    "additionalProperties": False,
                },
                "sentiment":  {"type": "string", "enum": list(SENTIMENTS)},
                "confidence": {"type": "number", "description": "0-100 confidence that the document supports this insight"},
                "sections": {
                    "type": "array",
                    "description": "expanded-panel sections; omit a tab the document does not support",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tab":   {"type": "string", "description": "one of the tab names given in the user message"},
                            "h":     {"type": "string", "description": "short section heading, e.g. 'Financial results'"},
                            "items": {"type": "array", "items": {"type": "string"}, "description": "1-4 factual bullets grounded in the document"},
                            "cite_page_start": {"type": ["integer", "null"], "description": "1-based first page these facts came from, else null"},
                            "cite_page_end":   {"type": ["integer", "null"], "description": "1-based last page these facts came from, else null"},
                        },
                        "required": ["tab", "h", "items", "cite_page_start", "cite_page_end"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["one_liner", "period", "headline_metric", "sentiment", "confidence", "sections"],
            "additionalProperties": False,
        },
        "strict": _STRICT,
    },
}


@dataclass
class Insight:
    one_liner: str
    period: Optional[str]
    headline_metric: Optional[dict]
    sentiment: str
    confidence: float
    # [{tab, h, items[], cite_page_start|None, cite_page_end|None}] — page numbers
    # already validated against the document's real page range.
    sections: list[dict]


def _clean_sections(raw: Any, *, tabs: tuple[str, ...], max_page: Optional[int]) -> list[dict]:
    """Keep only sections that are real: a known tab, a heading, at least one
    non-empty bullet, and a page citation that actually exists in the document.

    An out-of-range citation is DROPPED (set to null) rather than shown — a
    plausible-looking "pp. 12-14" pointing past the end of an 8-page filing is
    exactly the kind of confident-but-wrong detail this product cannot ship. The
    section itself survives; only its unverifiable citation is removed.
    """
    known = {t.lower(): t for t in tabs}
    out: list[dict] = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        tab = known.get(str(s.get("tab", "")).strip().lower())
        head = str(s.get("h") or "").strip()
        items = [str(i).strip() for i in (s.get("items") or []) if str(i).strip()]
        if not (tab and head and items):
            continue

        start, end = s.get("cite_page_start"), s.get("cite_page_end")
        try:
            start = int(start) if start is not None else None
            end = int(end) if end is not None else None
        except (TypeError, ValueError):
            start = end = None
        if start is not None and end is not None and end < start:
            start, end = end, start
        # a citation is only kept if every page it names is inside the document
        if start is not None:
            upper = end if end is not None else start
            if start < 1 or (max_page is not None and upper > max_page):
                logger.debug("dropping out-of-range citation pp.%s-%s (doc has %s pages)",
                             start, end, max_page)
                start = end = None

        out.append({"tab": tab, "h": head, "items": items[:4],
                    "cite_page_start": start, "cite_page_end": end})
    return out


def _model_version() -> str:
    return MODEL.replace("-", "").replace(".", "").lower()


class InsightGenerator:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or _resolve_key()
        if not key:
            raise RuntimeError(
                "No API key for filing_insights. Set FILING_INSIGHTS_API_KEY "
                "(open-weight provider) or OPENAI_API_KEY in /opt/nidp/nidp.env (or GSM)."
            )
        # base_url=None → OpenAI; set FILING_INSIGHTS_BASE_URL for an open-weight
        # provider's OpenAI-compatible endpoint.
        self._client = OpenAI(api_key=key, base_url=_BASE_URL)
        logger.info("filing_insights model=%s endpoint=%s strict=%s",
                    MODEL, _BASE_URL or "openai-default", _STRICT)

    def generate(self, *, company: str, ticker: str, event_category: str,
                 doc_type: str, subject: str, text: str,
                 max_page: Optional[int] = None) -> Insight:
        if not text or not text.strip():
            raise ValueError("empty document text")
        tabs = tabs_for(doc_type)
        user = (
            f"Company: {company or '(unknown)'}\n"
            f"NSE Ticker: {ticker or '(n/a)'}\n"
            f"Event category: {event_category}\n"
            f"Document type: {doc_type}\n"
            f"Filing subject: {subject or '(none)'}\n"
            f"Tabs to populate (in order, omitting any the document cannot support): "
            f"{', '.join(tabs)}\n\n"
            f"--- FILING TEXT (parsed from the PDF) ---\n{text[:MAX_TEXT_CHARS]}"
        )
        resp = self._client.chat.completions.create(
            model=MODEL,
            max_tokens=500,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            tools=[_EMIT_TOOL],
            tool_choice={"type": "function", "function": {"name": "emit_insight"}},
        )
        choice = resp.choices[0]
        for tc in (choice.message.tool_calls or []):
            if tc.function and tc.function.name == "emit_insight":
                try:
                    p = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"generator returned invalid JSON: {e}")
                metric = p.get("headline_metric")
                # A metric needs a label AND a value to mean anything; either one
                # missing or placeholder means "no figure", not a partial figure.
                if metric and (_nullish(metric.get("label")) or _nullish(metric.get("value"))):
                    metric = None
                # The unit is optional: a placeholder unit is blanked rather than
                # sinking the whole metric, so a real number keeps its label
                # instead of rendering as "... null".
                if metric:
                    metric = {
                        "label": str(metric["label"]).strip(),
                        "value": str(metric["value"]).strip(),
                        "unit": "" if _nullish(metric.get("unit")) else str(metric["unit"]).strip(),
                    }
                period = p.get("period")
                return Insight(
                    one_liner=(p.get("one_liner") or "").strip(),
                    period=None if _nullish(period) else str(period).strip(),
                    headline_metric=metric,
                    sentiment=p.get("sentiment") or "neutral",
                    confidence=float(p.get("confidence") or 0),
                    sections=_clean_sections(p.get("sections"),
                                             tabs=tabs, max_page=max_page),
                )
        raise RuntimeError(
            f"generator returned no tool_call (finish_reason={choice.finish_reason})"
        )
