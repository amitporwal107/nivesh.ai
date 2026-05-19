"""Intent classifier node — first node in the LangGraph graph.

Uses a two-tier approach:
  1. Fast regex patterns (deterministic, <1 ms) — covers 90% of queries
  2. LLM structured output fallback for ambiguous cases

The node reads the latest user message from state.messages, sets
state.intent (IntentClassification), and returns. The graph's conditional
edge then routes to the correct specialist node.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI

from ..schemas import AgentName, CopilotState, IntentClassification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns (priority-ordered — first match wins)
# ---------------------------------------------------------------------------

_P_MARKET = re.compile(
    r"\b(market|nifty|sensex|nse|bse|fii|dii|macro|rbi|inflation|gdp|"
    r"index|sectoral|sector\s+performance|breadth|advance.decline|vix|"
    r"flows?|fii.dii|foreign\s+inflow|domestic\s+flow|today.s\s+market|"
    r"market\s+(?:outlook|update|summary|today|open|close|movement))\b",
    re.IGNORECASE,
)

_P_STOCK = re.compile(
    r"\b((?:what|how|analyse|analyze|tell me about|research|buy|sell|hold)\s+"
    r"(?:is\s+)?[A-Z]{2,10}\b|"
    r"technical\s+(?:analysis|view|setup|signal|chart|indicator)|"
    r"fundamentals?\s+(?:of|for)|"
    r"pe\s+ratio|pb\s+ratio|roe|eps|revenue|pat|ebitda|"
    r"rsi|macd|sma|ema|support|resistance|breakout|"
    r"[A-Z]{2,10}\s+(?:stock|share|equity|target|price))\b",
    re.IGNORECASE,
)

_P_MF = re.compile(
    r"\b(mutual\s+funds?|mf\b|scheme|nav|amc|fund\s+house|"
    r"sip|lump\s*sum|invest\s+in\s+(?:a\s+)?fund|"
    r"top\s+funds?|best\s+funds?|fund\s+comparison|compare\s+funds?|"
    r"overlap\s+(?:between|of|in)\s+(?:my\s+)?funds?|"
    r"(?:large|mid|small)\s*cap\s+(?:mutual\s+)?funds?|flexi\s*cap|"
    r"index\s+fund|elss|debt\s+fund|liquid\s+fund|"
    r"direct\s+plan|regular\s+plan|switch\s+to\s+direct|"
    r"expense\s+ratio|ter\b|fund\s+manager|"
    r"too\s+many\s+(?:mutual\s+)?funds?|sip\s+allocation)\b",
    re.IGNORECASE,
)

_P_PORTFOLIO = re.compile(
    r"\b((?:my\s+)?portfolio|my\s+investments?|my\s+holdings?|"
    r"xirr|portfolio\s+(?:return|performance|summary|health|snapshot)|"
    r"rebalance|rebalancing|drift|concentration|overlap(?:ping)?|"
    r"which\s+(?:sectors?|funds?|stocks?|holdings?|positions?)\s+(?:should|to)\s+(?:i|we)\s+(?:trim|exit|sell|reduce|book|remove|cut|drop|hold|keep)|"
    r"(?:trim|exit|book\s+profit\s+(?:in|on)|cut|reduce|sell)\s+(?:my\s+)?(?:sectors?|funds?|stocks?|holdings?|positions?)|"
    r"tax(?:[\s-]+loss)?[\s-]+harvest(?:ing)?|harvest\s+loss|loss[\s-]+harvest(?:ing)?|"
    r"capital\s+gains?|ltcg|stcg|tax\s+liability|tax(?:.|-)?efficien|"
    r"idcw|growth\s+plan|growth\s+(?:vs|or)\s+idcw|"
    r"stress\s+test|portfolio\s+under\s+(?:crash|crisis)|"
    r"covid\s*crash|2008\s*crash|rate\s+shock|"
    r"fd\b|fixed\s+deposit|beat\s+fd|vs\s+fd|better\s+than\s+fd|"
    r"unrealized\s+(?:capital\s+)?gains?|unrealised\s+(?:capital\s+)?gains?|"
    r"realized\s+(?:vs|or)\s+unrealized|realised\s+(?:vs|or)\s+unrealised|"
    r"p\s*&\s*l|pnl|p_and_l|profit\s+and\s+loss|"
    r"earmark(?:ed)?|currency\s+exposure|india(?:.|-)?focus|"
    r"(?:how\s+much|what)\s+(?:would|will)\s+i\s+(?:lose|gain))\b",
    re.IGNORECASE,
)

_P_RISK = re.compile(
    r"\b(risk\s+(?:profile|suitability|capacity|tolerance)|"
    r"portfolio\s+risk|my\s+risk|too\s+(?:much|aggressive|risky)|"
    r"var\b|value\s+at\s+risk|volatility|drawdown|beta|"
    r"am\s+i\s+(?:over|under)(?:weight|invested|exposed)|"
    r"risk(?:y|ier)?\s+(?:stocks?|funds?|portfolio)|"
    r"safe(?:r|ty)?\s+(?:investment|option|fund|choice)|"
    r"manage\s+risk|risk\s+management|risk\s+reward|"
    r"market\s+(?:falls?|drops?|crash(?:es)?)\s*\d*\s*%?|"
    r"what\s+if\s+(?:markets?|nifty|sensex)\s+(?:falls?|drops?|crash(?:es)?)|"
    r"downside\s+(?:risk|protect|in)|max(?:imum)?\s+drawdown|"
    r"diversif(?:y|ied|ication))\b",
    re.IGNORECASE,
)

_P_GOAL = re.compile(
    r"\b(goal|goals|retirement|education(?:\s+(?:fund|corpus|cost|goal))?|corpus|target\s+amount|"
    r"on\s+track|sip\s+(?:gap|needed|required|adequacy)|sip\s+sufficient|"
    r"will\s+i\s+(?:reach|achieve|meet)|"
    r"shortfall|monthly\s+income|withdrawal\s+rate|safe\s+withdrawal|"
    r"annuit(?:y|ies)|preserve\s+capital|preserve\s+wealth|"
    r"inflation\s+protect|protect.+against\s+inflation|"
    r"child(?:ren)?\s+education|higher\s+education|"
    r"running\s+out\s+of\s+money|long(?:.|-)?term\s+wealth|"
    r"how\s+much\s+(?:should|do)\s+i\s+(?:invest|save|need))\b",
    re.IGNORECASE,
)

_P_RECOMMENDATION = re.compile(
    r"\b(recommend|recommendation|suggest|what\s+(?:should|can)\s+i\s+(?:buy|invest)|"
    r"what\s+stocks?\s+should\s+(?:i|we)\s+(?:buy|invest)|"
    r"where\s+(?:should|can)\s+i\s+invest|screen\s+stocks?|screener|"
    r"top\s+stocks?|best\s+stocks?|fresh\s+investment|new\s+investment|"
    r"deploy\s+(?:money|capital|funds?)|invest\s+(?:fresh|new|\d)|"
    r"pms\b|aif\b|estate\s+planning|tax\s+treat(?:y|ies)|dtaa|"
    r"swing\s+trading|position\s+size|trading\s+discipline|"
    r"international\s+etfs?|us\s+etfs?|global\s+(?:fund|etf|allocation|diversif)|"
    r"undervalued\s+(?:stocks?|funds?)|valuation\s+metrics?|"
    r"safe\s+investment\s+option|annuity\s+(?:vs|or))\b",
    re.IGNORECASE,
)


# Pattern → agent mapping (priority order)
# RISK before PORTFOLIO so "portfolio risk" → risk_analyst
# MARKET before STOCK so "What is Nifty?" → market_analyst (not stock_analyst)
_PATTERNS = [
    (_P_RISK,            AgentName.RISK),
    (_P_GOAL,            AgentName.GOAL),
    (_P_PORTFOLIO,       AgentName.PORTFOLIO),
    (_P_RECOMMENDATION,  AgentName.RECOMMENDATION),
    (_P_MF,              AgentName.MF),
    (_P_MARKET,          AgentName.MARKET),
    (_P_STOCK,           AgentName.STOCK),
]


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

Return JSON: {"agent": "<agent_name>", "confidence": 0.9, "symbol": null, "scheme_code": null}
"""


async def _llm_classify(text: str) -> IntentClassification:
    """Call the LLM for ambiguous queries. Falls back to market_analyst on any error."""
    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
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

    if not user_text:
        return {"intent": IntentClassification(agent=AgentName.MARKET, confidence=0.5)}

    # 1. Fast regex pass
    matched_agent: Optional[AgentName] = None
    for pattern, agent in _PATTERNS:
        if pattern.search(user_text):
            matched_agent = agent
            break

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
