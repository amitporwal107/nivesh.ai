"""Intent classifier node — first node in the LangGraph graph.

Uses a two-tier approach:
  1. Fast regex patterns (deterministic, <1 ms) — covers 90% of queries
  2. LLM structured output fallback for ambiguous cases

The node reads the latest user message from state.messages, sets
state.intent (IntentClassification), and returns. The graph's conditional
edge then routes to the correct specialist node.

The regex routing table lives in `intent_patterns.py` (langchain-free, so the
deterministic fast path is unit-testable on its own); this module maps its agent
keys onto AgentName and owns slot extraction + the LLM fallback.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from .._llm import COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..schemas import AgentName, CopilotState, IntentClassification
from .intent_patterns import match_agent

logger = logging.getLogger(__name__)

# Agent-key (intent_patterns string) → AgentName enum member.
_AGENT_BY_KEY: Dict[str, AgentName] = {a.value: a for a in AgentName}


# ---------------------------------------------------------------------------
# Slot extractors
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r"\b([A-Z]{2,10})\b")
_SCHEME_RE = re.compile(r"\b(\d{6})\b")                  # 6-digit AMFI code
_SCENARIO_RE = re.compile(
    r"\b(covid|gfc|2008|rate.shock|bear.market)\b", re.IGNORECASE
)
_N_RESULTS_RE = re.compile(r"\b(?:top|best|worst)\s+(\d+)\b", re.IGNORECASE)


def _extract_slots(text: str, agent: AgentName) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    if agent == AgentName.STOCK:
        # Resolve via the shared resolver (lazy import — keeps this module free of
        # a hard dependency on the app-level copilot_tools package at import time).
        # Handles lowercase tickers ("hdfc"), company names ("reliance"), and
        # uppercase pass-through; the old case-sensitive `[A-Z]{2,10}` regex
        # silently dropped anything not typed in capitals.
        try:
            from services.copilot_tools.symbol_resolver import resolve_symbol
            res = resolve_symbol(text)
            if res.symbol:
                slots["symbol"] = res.symbol
        except Exception:  # noqa: BLE001 — never let resolution break routing
            m = _SYMBOL_RE.search(text)
            if m:
                slots["symbol"] = m.group(1)
    if agent == AgentName.MF:
        m = _SCHEME_RE.search(text)
        if m:
            slots["scheme_code"] = m.group(1)
    if agent == AgentName.PORTFOLIO:
        m = _SCENARIO_RE.search(text)
        if m:
            raw = m.group(1).lower()
            slots["scenario"] = (
                "covid_2020" if "covid" in raw else
                "gfc_2008" if ("gfc" in raw or "2008" in raw) else
                "rate_shock"
            )
    n_m = _N_RESULTS_RE.search(text)
    if n_m:
        slots["top_n"] = int(n_m.group(1))
    return slots


# ---------------------------------------------------------------------------
# LLM fallback (structured output)
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """You are a financial intent classifier for an Indian investment app.
Classify the user message into exactly one agent and return JSON.

Agents:
- market_analyst: market indices, FII/DII, macro, sector performance
- stock_analyst: individual stock technical/fundamental analysis
- mf_analyst: mutual funds, NAV, fund comparison, overlap
- portfolio_analyst: user's portfolio XIRR, rebalancing, stress test, tax harvest
- risk_analyst: risk suitability, VaR, portfolio risk assessment
- goal_planner: financial goals, retirement, SIP adequacy
- recommendation: buy/invest recommendations, stock screener
- stocks_insights: a company's corporate disclosures/filings, order wins, results, M&A, concall/management commentary, AND regulatory/legal events it disclosed (SEBI action, RBI/IRDAI order, insolvency, NCLT, IBC, litigation)
- policy_analyst: how a tax/trade/budget POLICY affects a sector or which companies it affects (GST rate change, anti-dumping/safeguard duty, import/export tariffs, Union Budget, PLI/subsidy)

Return JSON: {"agent": "<agent_name>", "confidence": 0.9, "symbol": null, "scheme_code": null}
"""


async def _llm_classify(text: str) -> IntentClassification:
    """Call the LLM for ambiguous queries. Falls back to market_analyst on any error."""
    try:
        llm = ChatOpenAI(
            model=COPILOT_LLM_MODEL,
            temperature=temperature_for(0),
            api_key=get_openai_api_key(),
        )
        # Tag this LLM call so the SSE consumer can filter its tokens out of
        # the user-facing stream — otherwise the routing JSON leaks into the
        # chat bubble before the agent's prose starts.
        resp = await llm.ainvoke(
            [
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": text},
            ],
            config={"tags": ["intent_internal"]},
        )
        import json
        data = json.loads(resp.content)
        agent_str = data.get("agent", "market_analyst")
        # normalise to enum value
        agent = next(
            (a for a in AgentName if a.value == agent_str),
            AgentName.MARKET,
        )
        return IntentClassification(
            agent=agent,
            confidence=float(data.get("confidence", 0.6)),
            symbol=data.get("symbol"),
            scheme_code=data.get("scheme_code"),
        )
    except Exception as exc:
        logger.warning("LLM intent classify failed: %s — defaulting to market_analyst", exc)
        return IntentClassification(agent=AgentName.MARKET, confidence=0.4)


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------

async def intent_node(state: CopilotState) -> dict:
    """Classify the latest user message and return updated state fields."""
    # pull latest human message
    user_text = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_text = msg.content
            break

    # 0. Agent pin — a dedicated surface (the Filings Home ask bar) has already
    #    decided the agent, so classification is not merely overridden but
    #    SKIPPED: no regex table, no LLM call. Slots are still extracted (regex
    #    only, cheap) so the specialist node still gets its symbol.
    if state.pinned_agent is not None:
        slots = _extract_slots(user_text, state.pinned_agent) if user_text else {}
        intent = IntentClassification(
            agent=state.pinned_agent,
            confidence=1.0,
            symbol=slots.get("symbol"),
            scheme_code=slots.get("scheme_code"),
            scenario=slots.get("scenario"),
            extras={k: v for k, v in slots.items() if k not in ("symbol", "scheme_code", "scenario")},
        )
        logger.debug("intent(pinned): agent=%s text=%r", intent.agent, user_text[:60])
        return {"intent": intent}

    if not user_text:
        return {"intent": IntentClassification(agent=AgentName.MARKET, confidence=0.5)}

    # 1. Fast regex pass (deterministic routing table in intent_patterns).
    agent_key = match_agent(user_text)
    matched_agent: Optional[AgentName] = _AGENT_BY_KEY.get(agent_key) if agent_key else None

    if matched_agent is not None:
        slots = _extract_slots(user_text, matched_agent)
        intent = IntentClassification(
            agent=matched_agent,
            confidence=0.92,
            symbol=slots.get("symbol"),
            scheme_code=slots.get("scheme_code"),
            scenario=slots.get("scenario"),
            extras={k: v for k, v in slots.items() if k not in ("symbol", "scheme_code", "scenario")},
        )
        logger.debug("intent(regex): agent=%s text=%r", intent.agent, user_text[:60])
    else:
        # 2. LLM fallback for genuinely ambiguous queries
        intent = await _llm_classify(user_text)
        logger.debug("intent(llm): agent=%s text=%r", intent.agent, user_text[:60])

    return {"intent": intent}
