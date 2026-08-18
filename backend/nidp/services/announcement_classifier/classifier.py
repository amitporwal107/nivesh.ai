"""GPT-based corporate-announcement classifier (OpenAI-wire function calling).

Forces structured output via tool/function-calling so the response is always
parseable. Replaces the Haiku/Anthropic implementation — kept the same
`HaikuClassifier` class name so the calling code in service.py doesn't need to
change. Naming is now historic; behaviour is identical.

Two OpenAI-wire-compatible providers are wired, selected at CALL time (no code
change to switch):
  * groq   — Groq's OpenAI-compatible endpoint running the free
             `openai/gpt-oss-120b`. AUTO-selected whenever a GROQ_API_KEY
             resolves. This is the same selector `ai_engine` and the NIDP
             copilot use, so all three surfaces agree on provider.
  * openai — the OpenAI account (`gpt-4o-mini`); the fallback when no Groq key.

Why the switch (2026-08): the OpenAI account hit `credit_balance_exhausted` on
2026-07-30 and EVERY classify call has failed since, which froze
`event_category`/`impact_score`/`sentiment` and made the /v5/research corporate
events feed serve pre-Jul-30 filings at the top. See
test_reports/announcement_classifier_groq.md.

Cost envelope at NSE+BSE volume (~500 announcements/day):
    groq   — `openai/gpt-oss-120b` is free at current tiers (rate-limited).
    openai — `gpt-4o-mini` ($0.15/M input, $0.60/M output): ~1.6K system + ~150
             user tokens in, ~80 out → ~₹0.10/row, ~₹350/week.

Why not emergentintegrations? `nidp` services run in their own venv on
the VM and are deployed without the wealth-advisor backend's heavier
dependency tree. Using the official `openai` SDK keeps the install
small and the path to swap models trivial — and because Groq speaks the
OpenAI wire format, supporting it adds NO new dependency.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from nidp.shared.groq_key import get_groq_api_key
from nidp.shared.openai_key import get_openai_api_key
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"   # free on Groq (product choice, 2026-07)
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"         # known-good OpenAI default


def resolve_provider() -> str:
    """'groq' or 'openai'. An explicit ANNOUNCEMENT_CLASSIFIER_PROVIDER wins;
    otherwise Groq is auto-selected whenever a GROQ_API_KEY is resolvable."""
    p = os.environ.get("ANNOUNCEMENT_CLASSIFIER_PROVIDER", "").strip().lower()
    if p in ("groq", "openai"):
        return p
    return "groq" if get_groq_api_key() else "openai"


def resolve_model(provider: str | None = None) -> str:
    """The model id for `provider`.

    On Groq we read ANNOUNCEMENT_CLASSIFIER_GROQ_MODEL and deliberately IGNORE
    ANNOUNCEMENT_CLASSIFIER_MODEL: that var holds an OpenAI id, and a stale
    OpenAI pin left in the deployed env would be rejected by Groq. (This is the
    exact failure that took the copilot down twice — see _llm.py's history.)
    """
    if (provider or resolve_provider()) == "groq":
        return os.environ.get("ANNOUNCEMENT_CLASSIFIER_GROQ_MODEL", "").strip() or _GROQ_DEFAULT_MODEL
    return os.environ.get("ANNOUNCEMENT_CLASSIFIER_MODEL", "").strip() or _OPENAI_DEFAULT_MODEL


# Back-compat module constant: the model this process would use right now.
MODEL = resolve_model()

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

def build_classify_tool(provider: str) -> dict[str, Any]:
    """The function spec, shaped for `provider`.

    `strict` is an OpenAI structured-outputs flag. Groq's OpenAI-compatible layer
    does not implement it, so we omit it there rather than send a field the
    endpoint may reject — the enums in the schema plus a forced tool_choice are
    what actually constrain the output, and `classify()` validates the values on
    the way out regardless.
    """
    fn: dict[str, Any] = {
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
    }
    if provider != "groq":
        fn["strict"] = True
    return {"type": "function", "function": fn}


# Back-compat module constant (OpenAI shape).
CLASSIFY_TOOL: dict[str, Any] = build_classify_tool("openai")


@dataclass
class Classification:
    event_category: str
    impact_score: str
    sentiment: str
    rationale: str
    classifier_version: str


def _classifier_version(model: str | None = None) -> str:
    """Hash of model + system prompt so re-classification is deterministic.

    Provider-distinct by construction: the model id is part of both the hash and
    the prefix, so Groq-classified rows are attributable separately from
    OpenAI-classified ones. Note this does NOT cause a re-classification sweep —
    db.py fetches strictly on `event_category IS NULL`, never on version.
    """
    m = model or MODEL
    h = hashlib.sha1()
    h.update(m.encode())
    h.update(b"|")
    h.update(_SYSTEM_PROMPT.encode())
    # `<model_short>-<sha10>` → e.g. "gpt4omini-1234567890"
    short = m.replace("-", "").replace(".", "").replace("/", "").lower()
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
    """Class name retained for back-compat; powered by GPT/Groq now."""

    def __init__(self, api_key: str | None = None, provider: str | None = None) -> None:
        self.provider = (provider or resolve_provider()).lower()
        self.model = resolve_model(self.provider)
        self.classifier_version = _classifier_version(self.model)
        self._tool = build_classify_tool(self.provider)

        if self.provider == "groq":
            key = api_key or get_groq_api_key()
            if not key:
                raise RuntimeError(
                    "GROQ_API_KEY not set — required for the corporate-announcement "
                    "classifier when provider=groq. Set it in /opt/nidp/nidp.env "
                    "(the nidp venv cannot read Secret Manager)."
                )
            self._client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
        else:
            key = api_key or get_openai_api_key()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY not set — required for the corporate-"
                    "announcement classifier. Set it in /opt/nidp/nidp.env."
                )
            self._client = OpenAI(api_key=key)

        logger.info("announcement_classifier provider=%s model=%s version=%s",
                    self.provider, self.model, self.classifier_version)

    def classify(self, row: dict) -> Classification:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=1024 if self.provider == "groq" else 400,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_message(row)},
            ],
            tools=[self._tool],
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
                # Validate against the taxonomy before returning. On Groq we
                # cannot send `strict`, so the enums are advisory to the model —
                # an out-of-taxonomy value would land in the DB and surface as a
                # junk facet chip on /v5/research (event_category is the feed's
                # facet key). Raising leaves the row unclassified so a later run
                # retries it, which is the safe direction.
                for field, allowed in (
                    ("event_category", EVENT_CATEGORIES),
                    ("impact_score",   IMPACT_LEVELS),
                    ("sentiment",      SENTIMENTS),
                ):
                    value = payload.get(field)
                    if value not in allowed:
                        raise RuntimeError(
                            f"classifier returned out-of-taxonomy {field}={value!r} "
                            f"(model={self.model}, allowed={list(allowed)})"
                        )
                return Classification(
                    event_category=payload["event_category"],
                    impact_score=payload["impact_score"],
                    sentiment=payload["sentiment"],
                    rationale=payload.get("rationale", ""),
                    classifier_version=self.classifier_version,
                )
        raise RuntimeError(
            f"classifier returned no tool_call (finish_reason={choice.finish_reason})"
        )
