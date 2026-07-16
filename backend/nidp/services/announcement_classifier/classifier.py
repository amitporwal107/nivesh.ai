"""GPT-based corporate-announcement classifier (OpenAI function calling).

Forces structured output via OpenAI tool/function-calling so the response
is always parseable. Replaces the Haiku/Anthropic implementation — kept
the same `HaikuClassifier` class name so the calling code in service.py
doesn't need to change. Naming is now historic; behaviour is identical.

Cost envelope at NSE+BSE volume (~500 announcements/day):
    Default model: `gpt-4o-mini` ($0.15/M input, $0.60/M output).
    Per-row: ~1.6K system + ~150 user tokens in, ~80 out → ~₹0.10/row.
    500 rows × 7 days/week ≈ ₹350/week. ~5× cheaper than Haiku.

Why not emergentintegrations? `nidp` services run in their own venv on
the VM and are deployed without the wealth-advisor backend's heavier
dependency tree. Using the official `openai` SDK keeps the install
small and the path to swap models trivial.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# Model + prompt are versioned so we can re-classify just the rows whose
# classifier_version is older than a new release.
MODEL = os.environ.get("ANNOUNCEMENT_CLASSIFIER_MODEL", "gpt-4o-mini")

EVENT_CATEGORIES = (
    "orders", "mna", "earnings", "capex", "regulatory", "management",
    "dividend", "buyback", "qip", "rating", "litigation", "other",
)
IMPACT_LEVELS = ("high", "medium", "low")
SENTIMENTS = ("positive", "neutral", "negative")

_SYSTEM_PROMPT = """You classify Indian-market corporate announcements (NSE/BSE filings).

Taxonomy — pick exactly ONE event_category:
- orders     : new contract wins, large order receipts, LOI/LOA from clients
- mna        : mergers, acquisitions, divestitures, joint ventures, scheme of arrangement
- earnings   : quarterly/annual results, audited results, profit/loss statements, results press release
- capex      : new capacity, expansion, plant commissioning, capital projects
- regulatory : SEBI/RBI/IRDA orders, show-cause notices, compliance certificates, regulation 30 disclosures
- management : MD/CEO/CFO/director appointments, resignations, key personnel changes
- dividend   : dividend declaration, record date, ex-dividend
- buyback    : share buyback announcements, buyback offers, buyback closure
- qip        : QIP, preferential allotment, rights issue, FPO, equity raise
- rating     : credit-rating actions (upgrade/downgrade/affirmation) by CRISIL/ICRA/CARE/Fitch/Moody
- litigation : lawsuits filed, settlements, court orders, insolvency/bankruptcy proceedings (NCLT/NCLAT/IBC/CIRP petitions, winding-up, liquidation, moratorium)
- other      : everything else (newspaper publications, postal ballots, scrutinizer reports, AGM notices, investor presentations without earnings)

impact_score:
- high   : earnings beats/misses, large M&A, ratings change ≥1 notch, regulatory penalties, MD/CEO change at large company, order ≥10% of revenue
- medium : capex announcement, dividend declaration, mid-rank management change, smaller orders, regulation 30 routine
- low    : newspaper publications, AGM notices, postal ballots, scrutinizer reports, routine compliance certificates, board-meeting notices without results

sentiment: market-impact directionality, NOT corporate-language polarity.
- positive : favourable for shareholders (order win, profit beat, rating upgrade, accretive M&A, dividend hike)
- negative : unfavourable for shareholders (loss, rating downgrade, regulatory penalty, order loss, dilutive equity raise, key-person resignation without succession)
- neutral  : routine disclosures, ambiguous, or genuinely mixed

Rules:
- Output ONLY via the classify_announcement function. Never produce free text.
- Be conservative on "high": a board-meeting notice IS NOT high impact even if results follow later.
- "Newspaper publication of results" is low impact (regulatory boilerplate); the actual results filing is what counts."""

CLASSIFY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "classify_announcement",
        "description": "Emit the classification for one corporate announcement.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_category": {"type": "string", "enum": list(EVENT_CATEGORIES)},
                "impact_score":   {"type": "string", "enum": list(IMPACT_LEVELS)},
                "sentiment":      {"type": "string", "enum": list(SENTIMENTS)},
                "rationale":      {"type": "string", "description": "1-sentence justification for debugging"},
            },
            "required": ["event_category", "impact_score", "sentiment", "rationale"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


@dataclass
class Classification:
    event_category: str
    impact_score: str
    sentiment: str
    rationale: str
    classifier_version: str


def _classifier_version() -> str:
    """Hash of model + system prompt so re-classification is deterministic."""
    h = hashlib.sha1()
    h.update(MODEL.encode())
    h.update(b"|")
    h.update(_SYSTEM_PROMPT.encode())
    # `<model_short>-<sha10>` → e.g. "gpt4omini-1234567890"
    short = MODEL.replace("-", "").replace(".", "").lower()
    return f"{short}-{h.hexdigest()[:10]}"


CLASSIFIER_VERSION = _classifier_version()


def _build_user_message(row: dict) -> str:
    parts = []
    if row.get("company_name"):
        parts.append(f"Company: {row['company_name']}")
    if row.get("ticker_symbol"):
        parts.append(f"NSE Ticker: {row['ticker_symbol']}")
    if row.get("scrip_code"):
        parts.append(f"BSE Scrip: {row['scrip_code']}")
    if row.get("raw_category"):
        parts.append(f"Exchange Category: {row['raw_category']}")
    parts.append(f"Subject: {row.get('subject') or '(no subject)'}")
    if row.get("description") and row["description"] != row.get("subject"):
        parts.append(f"Body: {row['description'][:1500]}")
    return "\n".join(parts)


class HaikuClassifier:
    """Class name retained for back-compat; powered by GPT now."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — required for the corporate-"
                "announcement classifier. Set it in /opt/nidp/nidp.env."
            )
        self._client = OpenAI(api_key=key)

    def classify(self, row: dict) -> Classification:
        resp = self._client.chat.completions.create(
            model=MODEL,
            max_tokens=400,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_message(row)},
            ],
            tools=[CLASSIFY_TOOL],
            tool_choice={
                "type": "function",
                "function": {"name": "classify_announcement"},
            },
        )
        choice = resp.choices[0]
        tool_calls = choice.message.tool_calls or []
        for tc in tool_calls:
            if tc.function and tc.function.name == "classify_announcement":
                try:
                    payload = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"classifier returned invalid JSON: {e} "
                        f"(raw={tc.function.arguments[:200]})"
                    )
                return Classification(
                    event_category=payload["event_category"],
                    impact_score=payload["impact_score"],
                    sentiment=payload["sentiment"],
                    rationale=payload.get("rationale", ""),
                    classifier_version=CLASSIFIER_VERSION,
                )
        raise RuntimeError(
            f"classifier returned no tool_call (finish_reason={choice.finish_reason})"
        )
