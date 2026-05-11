"""Nivesh Copilot — agent router + multi-model dispatcher.

Doc 02 (Chat as Intelligence Hub) introduces 6 specialist NIDP agents.
Each is a lightweight wrapper around the existing LLM stack plus an
agent-specific system prompt + suggestion chip set + widget envelope
the frontend renders.

Architecture: this module is intentionally additive. It does NOT
replace `routes/chat.py` or `services/ai_engine.py`. Instead it exposes
two pure functions:

  - `route_intent(message)` -> AgentId
  - `agent_metadata()`      -> [AgentSpec, ...]

…plus a stub `run_agent()` that wraps emergentintegrations LlmChat to
support the three supported models (gpt-4o / claude-sonnet / gemini-flash).

Streaming is delegated to the existing `/api/chat/stream` route which
already streams OpenAI tokens. The model picker UI talks to `/api/copilot/models`
here; the chat stream route reads the `model` field off the request.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Literal, Optional
import re
import os
import logging

logger = logging.getLogger(__name__)

# ── Agent catalog (Doc 02 §2.2) ────────────────────────────────────

AgentId = Literal[
    "auto",
    "portfolio_analyzer",
    "mf_research",
    "market_strategist",
    "tax_agent",
    "compliance_agent",
    "report_generator",
]


@dataclass(frozen=True)
class AgentSpec:
    id: str
    label: str
    icon: str               # lucide icon name OR emoji per Doc 02 picker
    one_liner: str
    triggers: List[str]     # regex patterns
    default_suggestions: List[str]


_AGENTS: List[AgentSpec] = [
    AgentSpec(
        id="auto",
        label="Auto-route",
        icon="compass",
        one_liner="Picks the right specialist automatically.",
        triggers=[],
        default_suggestions=[
            "How is my portfolio doing?",
            "What can I harvest this FY?",
            "What changed in the markets today?",
            "Compare my flexi-cap funds",
        ],
    ),
    AgentSpec(
        id="portfolio_analyzer",
        label="Portfolio Analyzer",
        icon="bar-chart-3",
        one_liner="Health score, drift, rebalance, holding insights.",
        triggers=[
            r"\b(my portfolio|how (is|am)|health score|rebalance|drift|allocation)\b",
            r"\b(overweight|concentration|exposure)\b",
        ],
        default_suggestions=[
            "Explain my health score",
            "Where am I over-concentrated?",
            "Show me a rebalance plan",
        ],
    ),
    AgentSpec(
        id="mf_research",
        label="Mutual Fund Research",
        icon="search",
        one_liner="Fund verdicts, compare, screener, overlap.",
        triggers=[
            r"\b(tell me about|verdict on|rating of|how good is)\b.+\b(fund|mf|scheme)\b",
            r"\b(compare|find|screen|screener|overlap|alternative)\b.+\b(fund|funds|flexi|large ?cap|mid ?cap|small ?cap|index)\b",
            r"\bparag parikh|hdfc|axis|quant|nippon|sbi|kotak|mirae|icici\b",
        ],
        default_suggestions=[
            "Find consistent flexi-cap funds under 1% expense",
            "Compare my flexi-cap holdings",
            "Cheaper alternatives to my regular funds",
        ],
    ),
    AgentSpec(
        id="market_strategist",
        label="Market Strategist",
        icon="line-chart",
        one_liner="Today's brief, sector rotation, FII/DII flows.",
        triggers=[
            r"\b(market|markets|nifty|sensex|index|sectors?|fii|dii|flow|breadth)\b",
            r"\bwhat (happened|moved|changed) (today|this week)\b",
            r"\b(rotation|leaders?|leading|movers|gainers|losers|52[- ]week)\b",
        ],
        default_suggestions=[
            "What happened in the markets today?",
            "Which sectors are leading?",
            "Impact on my portfolio",
        ],
    ),
    AgentSpec(
        id="tax_agent",
        label="Tax Agent",
        icon="receipt",
        one_liner="Capital gains, harvesting, FY planning.",
        triggers=[
            r"\b(tax|ltcg|stcg|harvest|capital gain|wash sale|fy\d|exempt|80c)\b",
            r"\bcapital gains? statement\b",
        ],
        default_suggestions=[
            "How much LTCG do I have this FY?",
            "What can I harvest before year-end?",
            "Generate my capital gains statement",
        ],
    ),
    AgentSpec(
        id="compliance_agent",
        label="Compliance Agent",
        icon="shield",
        one_liner="Risk profile fit, suitability, SEBI disclosures.",
        triggers=[
            r"\b(suitable|suitability|risk profile|sebi|disclosure|compliance|too much risk)\b",
            r"\b(am i taking|how risky)\b",
        ],
        default_suggestions=[
            "Am I taking too much risk?",
            "Does my portfolio match my risk profile?",
            "Show suitability disclosures",
        ],
    ),
    AgentSpec(
        id="report_generator",
        label="Report Generator",
        icon="file-text",
        one_liner="Downloadable statements & summaries.",
        triggers=[
            r"\b(generate|download|export).*(report|statement|summary|pdf|excel|csv)\b",
            r"\b(year[- ]end|annual|quarterly|q[1-4]) (report|summary|statement)\b",
        ],
        default_suggestions=[
            "Generate my Q4 portfolio summary",
            "Export capital gains as PDF",
            "Annual SIP report",
        ],
    ),
]

_AGENTS_BY_ID = {a.id: a for a in _AGENTS}


def agent_metadata() -> List[dict]:
    """Return all agent specs as JSON-friendly dicts. Used by GET /agents."""
    return [asdict(a) for a in _AGENTS]


def get_agent(agent_id: str) -> Optional[AgentSpec]:
    return _AGENTS_BY_ID.get(agent_id)


def route_intent(message: str) -> str:
    """Auto-route a free-text message to the most appropriate specialist.

    Returns the agent_id. Falls back to `portfolio_analyzer` for anything
    that mentions the user's portfolio without other strong signal, else
    `mf_research` (the most common ask).
    """
    if not message:
        return "portfolio_analyzer"
    msg = message.lower().strip()
    scores: dict[str, int] = {}
    for agent in _AGENTS:
        if agent.id == "auto":
            continue
        hits = sum(1 for pat in agent.triggers if re.search(pat, msg, re.IGNORECASE))
        if hits:
            scores[agent.id] = hits
    if not scores:
        # Default: if the message references "my", lean to portfolio analyzer
        if re.search(r"\b(my|i (have|own|hold))\b", msg):
            return "portfolio_analyzer"
        return "mf_research"
    return max(scores.items(), key=lambda kv: kv[1])[0]


# ── Model picker (Doc 06 — model param flows from frontend) ────────

@dataclass(frozen=True)
class ModelSpec:
    id: str             # frontend-visible id
    provider: str       # openai | anthropic | gemini
    label: str
    is_default: bool
    underlying: str     # actual model name passed to provider
    notes: str = ""


_MODELS: List[ModelSpec] = [
    ModelSpec(id="gpt-4o", provider="openai", label="GPT-4o (default)", is_default=True,
              underlying="gpt-4o", notes="Fast, balanced. Wired through the existing AI engine."),
    ModelSpec(id="claude-sonnet-4-5", provider="anthropic", label="Claude Sonnet 4.5", is_default=False,
              underlying="claude-sonnet-4-5-20250929",
              notes="Stronger long-form rationale. Via Emergent universal key."),
    ModelSpec(id="gemini-2.5-flash", provider="gemini", label="Gemini 2.5 Flash", is_default=False,
              underlying="gemini-2.5-flash",
              notes="Lowest latency for simple queries. Via Emergent universal key."),
]


def model_metadata() -> List[dict]:
    return [asdict(m) for m in _MODELS]


def resolve_model(model_id: Optional[str]) -> ModelSpec:
    """Look up a model spec by id. Falls back to the default (`gpt-4o`)."""
    if model_id:
        for m in _MODELS:
            if m.id == model_id:
                return m
    return next(m for m in _MODELS if m.is_default)


async def run_agent_oneshot(
    *,
    agent_id: str,
    model_id: str,
    system_prompt: str,
    user_message: str,
    session_id: str,
) -> str:
    """Single-turn agent execution via emergentintegrations.

    Used by widget-producing endpoints that want a quick LLM call
    outside the main /chat/stream loop. Streaming chat continues to use
    the existing ai_engine OpenAI path; this is for short structured
    answers (rationale text, screener summaries, etc).

    Falls back to a deterministic stub when the universal key is absent
    so tests don't hit the network.
    """
    spec = resolve_model(model_id)
    key = os.environ.get("EMERGENT_LLM_KEY") or ""
    if not key:
        logger.warning("EMERGENT_LLM_KEY missing — returning stub answer for agent=%s", agent_id)
        return f"[{agent_id}] (stub — LLM key missing) {user_message[:120]}"

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.error("emergentintegrations import failed: %s", e)
        return f"[{agent_id}] (stub — emergentintegrations unavailable)"

    chat = LlmChat(
        api_key=key, session_id=session_id, system_message=system_prompt,
    ).with_model(spec.provider, spec.underlying)
    try:
        resp = await chat.send_message(UserMessage(text=user_message))
        return resp if isinstance(resp, str) else str(resp)
    except Exception as e:  # noqa: BLE001
        logger.error("agent=%s model=%s LLM call failed: %s", agent_id, spec.id, e)
        return f"[{agent_id}] LLM error — please retry."
