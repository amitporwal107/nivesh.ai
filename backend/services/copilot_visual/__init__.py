"""The Copilot's visual answer (Daily Trader Copilot, owner 30 Oct 2026): a trader's daily question answered with a
decision dashboard built from the platform's own data, not paragraphs. Contract and blocks:
docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md; the frontend renders it (components/chat/visual/VisualAnswer.tsx).

    question ─► resolve_intent (intents.py) ─► build (builders.py, readers.py) ─► payload (payload.py)
                                                                        └─► facts ─► the specialist node explains it

`prepare` is the chat route's pre-step (routes/chat.py stream_chat). It returns None for any question that is not one
of the Release-1 intents, or when the answer could not be built, so the chat then takes its usual path unchanged.

Which node explains each answer (the pin):
    market_view, smart_money, expected_move   market_analyst — it has the market snapshot the answer sits in.
    top_opportunities, breakouts, unusual_volume, open_trades, fno_setups, position_size
                                              market_analyst, not recommendation: the recommendation node runs its own
                                              stock screener and would put a second, different list (and a screener
                                              card) beside the dashboard's, in "picks" wording; the market analyst only
                                              explains the list it is handed, in the day's market context. open_trades
                                              and position_size are the account's own book and budget, not a stock's
                                              rules, so they stay off the stock analyst too.
    stock_decision, trade_validity, exit_options
                                              stock_analyst — it has the TRADE_PLAN rules ("How to trade it, an idea").
    daily_review                              market_analyst — the account's own record of closed trades and risk
                                              checks; it explains the figures it is handed and gives no advice.

stock_decision builds the desk's plan ONCE (services/copilot_trade_idea.build, which stores its TradePlans as the
trade-idea pre-step always has). The dashboard carries the plan as a `trade_plan` block, so the separate trade_plan card
is not sent: one card per answer. The plan's TRADE_PLAN facts still go to the stock analyst.

trade_validity and exit_options (Release 2) build their own plan read inside the builder (not eagerly here, unlike
stock_decision), since they also read the account's paper book or a stored plan and a `trade_idea` built ahead of
knowing that would go unused on half the questions. No separate trade_plan card is attached for them either: `prepare`
only eagerly builds `idea` for stock_decision, so `VisualAnswer.trade_idea` stays None for the other four and the chat
route sends no second card.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import readers
from .builders import BUILDERS, build
from .intents import INTENTS, Intent, last_symbol_from, resolve_intent, stock_in, wants_thread_symbol
from .payload import facts, validate

logger = logging.getLogger(__name__)

__all__ = ["INTENTS", "Intent", "VisualAnswer", "build", "facts", "last_symbol_from", "prepare", "resolve_intent",
           "stock_in", "validate", "wants_thread_symbol", "BUILDERS"]

AGENT_FOR = {"market_view": "market_analyst", "smart_money": "market_analyst", "expected_move": "market_analyst",
             "top_opportunities": "market_analyst", "breakouts": "market_analyst", "unusual_volume": "market_analyst",
             "stock_decision": "stock_analyst", "open_trades": "market_analyst", "fno_setups": "market_analyst",
             "position_size": "market_analyst", "trade_validity": "stock_analyst", "exit_options": "stock_analyst",
             "daily_review": "market_analyst", "portfolio_hedge": "portfolio_analyst"}
BUILD_TIMEOUT_S = 30.0
THREAD_MESSAGES = 10


@dataclass
class VisualAnswer:
    intent: Intent
    agent: str                                # the node the engine is pinned to
    widget: Optional[Dict[str, Any]]          # the `visual_answer` widget envelope; None when the payload failed
    facts: Optional[str]                      # the payload's figures for the engine, as a data block
    trade_idea: Any = None                    # stock_decision: the desk plan, built once


def widget_for(payload: Dict[str, Any], agent: str) -> Dict[str, Any]:
    return {"widget_type": "visual_answer", "data": payload, "title": payload.get("title"),
            "freshness": {"state": "end_of_day", "last_updated": payload.get("generated_at"),
                          "source": [s["name"] for s in (payload.get("data_quality") or {}).get("sources") or []]},
            "agent": {"id": agent, "confidence": None}}


async def _thread_symbol(db: Any, user_id: str, session_id: Optional[str]) -> Optional[str]:
    if not session_id or db is None:
        return None
    try:
        prior = await db.chat_messages.find(
            {"user_id": user_id, "session_id": session_id}, {"_id": 0, "role": 1, "content": 1, "widget": 1}
        ).sort("created_at", -1).to_list(THREAD_MESSAGES)
    except Exception:  # noqa: BLE001 — without the thread the question is simply not about a known stock
        logger.warning("copilot visual: the thread could not be read", exc_info=True)
        return None
    return last_symbol_from(prior)


async def prepare(request: Any, user: Dict[str, Any], message: str, persona: Optional[str], surface: Optional[str],
                  session_id: Optional[str], db: Any = None) -> Optional[VisualAnswer]:
    """The visual answer for a chat question, or None (the usual path). Never raises."""
    try:
        uid = user["user_id"]
        last = await _thread_symbol(db, uid, session_id) if wants_thread_symbol(message, persona, surface) else None
        intent = resolve_intent(message, persona, surface, last)
    except Exception:  # noqa: BLE001
        logger.warning("copilot visual: intent resolution failed", exc_info=True)
        return None
    if intent is None:
        return None
    if intent.name == "portfolio_hedge" and not await readers.hedge_enabled(user):
        return None                                   # flag off for this person: the question takes the usual chat path
    agent = AGENT_FOR[intent.name]
    idea = None
    try:
        if intent.name == "stock_decision":
            idea = await readers.trade_idea(request, uid, intent.symbol, message)
        payload = await asyncio.wait_for(build(intent, user, request=request, message=message, trade_idea=idea),
                                         timeout=BUILD_TIMEOUT_S)
        problems = validate(payload)
        if problems:
            logger.error("copilot visual: %s payload breaks the contract: %s", intent.name, problems[:5])
            raise ValueError("contract")
    except Exception as e:  # noqa: BLE001 — the question then takes the usual path (with the plan, if one was built)
        logger.warning("copilot visual: %s answer not built: %s", intent.name, type(e).__name__, exc_info=True)
        return VisualAnswer(intent, agent, None, None, idea) if idea is not None else None
    subject = intent.symbol if intent.name == "stock_decision" else None
    return VisualAnswer(intent, agent, widget_for(payload, agent), facts(payload, subject=subject), idea)
