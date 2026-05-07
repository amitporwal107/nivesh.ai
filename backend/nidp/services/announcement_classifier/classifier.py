"""Haiku-based corporate-announcement classifier.

Forces structured output via Anthropic tool_use so the response is always
parseable. Uses prompt caching on the system block (taxonomy + few-shot
examples) so the per-call cost is dominated by the short user message.

Cost envelope at NSE+BSE volume (~500 announcements/day):
    System prompt ~1.6K input tokens, cached after first call.
    Per-row user message ~150 tokens in, ~80 tokens out.
    With 5-min cache TTL and 10-min cron cadence, every 2nd cron pays
    the full prompt; the others hit the cache. Net ~₹15-25/day.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# Model + prompt are versioned so we can re-classify just the rows whose
# classifier_version is older than a new release.
MODEL = "claude-haiku-4-5-20251001"

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
- litigation : lawsuits filed, settlements, court orders
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
- Output ONLY via the classify_announcement tool. Never produce free text.
- Be conservative on "high": a board-meeting notice IS NOT high impact even if results follow later.
- "Newspaper publication of results" is low impact (regulatory boilerplate); the actual results filing is what counts."""

CLASSIFY_TOOL: dict[str, Any] = {
    "name": "classify_announcement",
    "description": "Emit the classification for one corporate announcement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_category": {"type": "string", "enum": list(EVENT_CATEGORIES)},
            "impact_score":   {"type": "string", "enum": list(IMPACT_LEVELS)},
            "sentiment":      {"type": "string", "enum": list(SENTIMENTS)},
            "rationale":      {"type": "string", "description": "1-sentence justification for debugging"},
        },
        "required": ["event_category", "impact_score", "sentiment", "rationale"],
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
    return MODEL.split("-")[1] + "-" + h.hexdigest()[:10]


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
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=key)

    def classify(self, row: dict) -> Classification:
        msg = self._client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_announcement"},
            messages=[{"role": "user", "content": _build_user_message(row)}],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "classify_announcement":
                payload = block.input
                return Classification(
                    event_category=payload["event_category"],
                    impact_score=payload["impact_score"],
                    sentiment=payload["sentiment"],
                    rationale=payload.get("rationale", ""),
                    classifier_version=CLASSIFIER_VERSION,
                )
        raise RuntimeError("classifier returned no tool_use block")
