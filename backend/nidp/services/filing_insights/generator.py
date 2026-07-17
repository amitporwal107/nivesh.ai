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

# Cap the document text fed to the model. ~24k chars ≈ ~6k tokens — plenty for a
# results/press-release filing, and a hard bound on cost + latency for the rare
# 200-page annual report (which we truncate rather than skip).
MAX_TEXT_CHARS = 24_000

SENTIMENTS = ("positive", "neutral", "negative")

_SYSTEM_PROMPT = """You summarise a single Indian-market corporate filing (an NSE/BSE disclosure) for an investor feed.

You are given the company, the filing's event category, and the FULL PARSED TEXT of the filing's PDF. Produce a tight, factual insight grounded ONLY in that text.

Hard rules:
- Ground every word in the provided document text. Do NOT use outside knowledge, and do NOT infer from the company name or category alone.
- one_liner: ONE sentence, <= 200 chars, stating what actually happened and the concrete detail an investor cares about (e.g. the order value and client, the revenue/PAT and its change, the rating action and agency). No hype, no recommendation.
- headline_metric: the single most important NUMBER explicitly stated in the filing (order value, revenue, PAT, dividend/share, rating). If the document does not state a clear headline number, return null. NEVER estimate, round from nothing, or fabricate a figure.
- period: the reporting/effective period if the filing states one (e.g. "Q1 FY26", "FY25", "for the quarter ended June 30, 2026"); else null.
- sentiment: market-impact directionality for shareholders (positive/neutral/negative), from the facts in the document.
- confidence: 0-100 — how well the document supports this insight. Low if the text is thin, garbled, or off-topic (e.g. only a cover letter linking an audio recording).
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
            },
            "required": ["one_liner", "period", "headline_metric", "sentiment", "confidence"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


@dataclass
class Insight:
    one_liner: str
    period: Optional[str]
    headline_metric: Optional[dict]
    sentiment: str
    confidence: float


def _model_version() -> str:
    return MODEL.replace("-", "").replace(".", "").lower()


class InsightGenerator:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or get_openai_api_key()
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — required for filing_insights. "
                "Set it in /opt/nidp/nidp.env (or GSM)."
            )
        self._client = OpenAI(api_key=key)

    def generate(self, *, company: str, ticker: str, event_category: str,
                 doc_type: str, subject: str, text: str) -> Insight:
        if not text or not text.strip():
            raise ValueError("empty document text")
        user = (
            f"Company: {company or '(unknown)'}\n"
            f"NSE Ticker: {ticker or '(n/a)'}\n"
            f"Event category: {event_category}\n"
            f"Document type: {doc_type}\n"
            f"Filing subject: {subject or '(none)'}\n\n"
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
                # normalise: a metric missing any field is treated as absent
                # rather than half-populated (honesty: no partial numbers).
                if metric and not all(metric.get(k) for k in ("label", "value", "unit")):
                    metric = None
                return Insight(
                    one_liner=(p.get("one_liner") or "").strip(),
                    period=(p.get("period") or None),
                    headline_metric=metric,
                    sentiment=p.get("sentiment") or "neutral",
                    confidence=float(p.get("confidence") or 0),
                )
        raise RuntimeError(
            f"generator returned no tool_call (finish_reason={choice.finish_reason})"
        )
