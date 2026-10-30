"""The Copilot's trade idea for a stock (owner, 29 Oct 2026: "User can ask any questions about a stocks and we can put idea
how to trade if conditions are favourable and signals are recieved").

When a Copilot question about a stock is a trading question, the chat route (routes/chat.py stream_chat) asks this module
for the desk's own StrategyPlan for that stock. It is built exactly as POST /api/desk/strategy/plan builds it: the same
inputs (normalise_inputs), the same live read-only sources read as the signed-in user (collect_snapshots), the same rules
(build_plan), the same TradePlans stored insert-once (so a paper trade can cite one), and the same finishing step. The
Copilot does not invent a level: it is handed the plan's facts as data and quotes them.

What the answer gets (`TradeIdea`):
    widget   the `trade_plan` card, ONLY when the plan has a setup (status `plan`) or a setup waiting for its confirmation
             (status `wait`) AND at least one candidate carries a TradePlan. The card shows the desk's DecisionCard of
             each plan id (frontend components/chat/TradePlanChatCard.tsx).
    context  the plan's facts for the stock analyst (`explain_plan_context`), with what was assumed. With no card it
             still says why there is no setup, so the answer can tell the user what would have to change.

Assumed, and said so: a direction the user did not state is LONG (the cash scanner's side) and marked "assumed"; the size
is the account's saved risk profile (the risk service sizes every TradePlan); the horizon is positional unless the words
say intraday, which the builder answers with insufficient_data (there is no intraday history).

Ideas, not recommendations; nothing here places an order.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BUILD_TIMEOUT_S = 25.0
MAX_PLANS_ON_CARD = 3
SHOWN_STATUSES = ("plan", "wait")

# Words that make a question about a stock a trading question in any persona. Not "plan" alone: "my SIP plan" is not a
# trade; "trade plan" / "trading plan" are caught by "trade" / "trading".
_TRADE_WORDS = re.compile(
    r"\b(trade|trades|trading|setup|set[- ]up|entry|enter|exit|stop[- ]?loss|stoploss|sl|targets?|breakout|"
    r"break[- ]?out|position siz(?:e|ing)|risk[- ]?reward|how (?:should|do|can|to) i (?:buy|sell|trade|play)|"
    r"go long|go short|swing|positional|intraday|options? strategy|spread|straddle|strangle|call option|put option)\b",
    re.I)
# Option structures name their own direction ("bull put spread" is bullish, "buy a put" is bearish).
_BULL_STRUCT = re.compile(r"\bbull(?:ish)?\s+(?:call|put)s?\b|\b(?:buy|buying|long)\s+(?:an?\s+)?calls?\b", re.I)
_BEAR_STRUCT = re.compile(r"\bbear(?:ish)?\s+(?:call|put)s?\b|\b(?:buy|buying|long)\s+(?:an?\s+)?puts?\b", re.I)
# "short-term" / "long-term" are horizons, not sides.
_BEARISH = re.compile(r"\b(bearish|short(?![- ]?term)|shorting|sell|selling|fall|falls|falling|drop|downside|downtrend|"
                      r"decline|breakdown)\b", re.I)
_BULLISH = re.compile(r"\b(bullish|long(?![- ]?term)|buy|buying|upside|up ?move|rally|rise|rising|breakout|break ?out|"
                      r"uptrend)\b", re.I)
_NEUTRAL = re.compile(r"\b(range[- ]?bound|rangebound|sideways|neutral|consolidat\w*)\b", re.I)
_INTRADAY = re.compile(r"\b(intraday|intra-day|today only|scalp\w*|same day)\b", re.I)

TRADER_PERSONA = "trader"


@dataclass
class TradeIdea:
    widget: Optional[Dict[str, Any]]
    context: str
    status: Optional[str] = None
    # The built StrategyPlan and the risk service's sizing of its preferred TradePlan, kept so the Copilot's visual
    # answer (services/copilot_visual) reads the same plan instead of building it twice. None when not built / not sized.
    plan: Optional[Dict[str, Any]] = None
    sized: Optional[Dict[str, Any]] = None


def is_trade_question(message: str, persona: Optional[str], desk_persona: Optional[str]) -> bool:
    """A trading question: the Trader persona, the trading desk's Copilot panel, or trading words in any persona."""
    if (persona or "").lower() == TRADER_PERSONA or desk_persona == TRADER_PERSONA:
        return True
    return bool(_TRADE_WORDS.search(message or ""))


def direction_of(message: str) -> Tuple[str, bool]:
    """(direction for the plan builder, whether the user stated it). In this order: range-bound words → neutral; an
    option structure's own side ("bull put spread", "buy a put"); bearish words only when no bullish word is present
    (a "breakout" question that mentions selling at a target is still long); bullish words; nothing → long, assumed."""
    text = message or ""
    if _NEUTRAL.search(text):
        return "neutral", True
    if _BULL_STRUCT.search(text):
        return "bullish", True
    if _BEAR_STRUCT.search(text):
        return "bearish", True
    bear, bull = bool(_BEARISH.search(text)), bool(_BULLISH.search(text))
    if bear and not bull:
        return "bearish", True
    if bull:
        return "bullish", True
    return "bullish", False


def horizon_of(message: str) -> str:
    return "intraday" if _INTRADAY.search(message or "") else "positional"


def symbol_for(message: str) -> Optional[str]:
    """The NSE symbol a message names (the stock analyst's own resolver), or None."""
    from services.copilot_tools.symbol_resolver import resolve_symbol
    try:
        return resolve_symbol(message).symbol
    except Exception:  # noqa: BLE001 — no symbol means no plan, never a failed answer
        logger.warning("copilot trade idea: symbol resolution failed", exc_info=True)
        return None


def _plan_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The candidates that carry a TradePlan, preferred first, at most MAX_PLANS_ON_CARD."""
    cands = [c for c in plan.get("candidates") or [] if isinstance(c, dict) and (c.get("trade_plan") or {}).get("plan_id")]
    preferred = plan.get("preferred")
    cands.sort(key=lambda c: (c.get("id") != preferred, c.get("status") != "candidate"))
    return [{"plan_id": c["trade_plan"]["plan_id"], "candidate_id": c.get("id"), "label": c.get("label"),
             "segment": c.get("segment"), "family": c.get("family"), "status": c.get("status"),
             "preferred": c.get("id") == preferred and preferred is not None}
            for c in cands[:MAX_PLANS_ON_CARD]]


def widget_for(plan: Dict[str, Any], direction_stated: bool) -> Optional[Dict[str, Any]]:
    """The `trade_plan` card's envelope, or None when the plan has nothing to show."""
    status = plan.get("status")
    rows = _plan_rows(plan)
    if status not in SHOWN_STATUSES or not rows:
        return None
    summary = plan.get("summary") or {}
    inputs = plan.get("inputs") or {}
    data_as_of = plan.get("data_as_of") or {}
    data = {
        "symbol": summary.get("underlying") or inputs.get("underlying"),
        "status": status,
        "status_reasons": [{"code": r.get("code"), "message": r.get("message")} for r in plan.get("status_reasons") or []
                           if isinstance(r, dict)][:5],
        "would_change_if": list(plan.get("would_change_if") or [])[:5],
        "direction": summary.get("direction") or inputs.get("direction"),
        "direction_stated": direction_stated,
        "horizon": summary.get("horizon") or inputs.get("horizon"),
        "horizon_days": summary.get("horizon_days") or inputs.get("horizon_days"),
        "plans": rows,
        "preferred_plan_id": rows[0]["plan_id"],
        "strategy_plan_id": plan.get("plan_id"),
        "data_as_of": {"price": data_as_of.get("price"), "fno": data_as_of.get("fno")},
        "defaults_applied": list(inputs.get("defaults_applied") or []),
        "sizing": "risk_profile",
    }
    title = f"Trade idea · {data['symbol']}"
    return {"widget_type": "trade_plan", "data": data, "title": title,
            "freshness": {"state": "end_of_day", "last_updated": plan.get("generated_at"),
                          "source": ["NIDP", "NSE bhavcopy"]},
            "agent": {"id": "stock_analyst", "confidence": None}}


def _num(v: Any) -> Optional[str]:
    return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def trade_plan_lines(tp: Dict[str, Any], label: Optional[str]) -> List[str]:
    """One TradePlan's levels in words, exactly as stored (services/strategy_plan/trade_plan.py): the entry trigger and
    its order type, how long it stays valid, the stop and what it invalidates, the targets in R, the eligibility state,
    and the evidence and warnings it carries. Missing values say "unavailable"."""
    e, s = tp.get("entry") or {}, tp.get("stop") or {}
    out = [f"TradePlan {tp.get('plan_id')} ({label or 'candidate'}):"]
    out.append(f"  entry: {_num(e.get('price')) or 'unavailable'} ({e.get('order_type') or 'order type unavailable'}"
               + (f"; desk entry rule {e.get('desk_entry_rule')}" if e.get("desk_entry_rule") else "")
               + (f"; valid for {e.get('valid_for_sessions')} sessions" if e.get("valid_for_sessions") else "") + ")"
               + (f" — {e.get('logic')}" if e.get("logic") else ""))
    out.append(f"  stop: {_num(s.get('price')) or _num(s.get('premium_stop')) or 'unavailable'} (method {s.get('method') or 'unknown'})"
               + (f" — invalidation: {s.get('invalidation')}" if s.get("invalidation") else "")
               + (f" — {s.get('rationale')}" if s.get("rationale") else ""))
    if _num(tp.get("r_per_unit")):
        out.append(f"  risk per unit (|entry − stop|): {_num(tp.get('r_per_unit'))}")
    for t in tp.get("targets") or []:
        if isinstance(t, dict) and _num(t.get("price")):
            out.append(f"  target {t.get('name')}: {_num(t.get('price'))}"
                       + (f" ({_num(t.get('r_multiple'))}R)" if _num(t.get("r_multiple")) else "")
                       + (" — primary" if t.get("primary") else "") + (f" — {t.get('rule')}" if t.get("rule") else ""))
    elig = tp.get("eligibility") or {}
    if elig.get("state"):
        out.append(f"  state: {elig.get('state')}"
                   + "".join(f"; {r.get('message') or r.get('code')}" for r in (elig.get("reasons") or [])[:3] if isinstance(r, dict)))
    for it in ((tp.get("evidence") or {}).get("items") or [])[:6]:
        if isinstance(it, dict) and it.get("status") == "ok" and it.get("text"):
            out.append(f"  evidence {it.get('label') or it.get('key')} ({it.get('direction') or 'n/a'}): {it.get('text')}")
    for w in tp.get("warnings") or []:
        if isinstance(w, dict) and w.get("status") == "flagged" and w.get("text"):
            out.append(f"  warning {w.get('label') or w.get('key')}: {w.get('text')}")
    return out


def sizing_lines(sized: Dict[str, Any]) -> List[str]:
    """The risk service's sizing of the preferred plan for this account (what the card shows), in words."""
    st = sized.get("status")
    if st in ("sized", "not_confirmed"):
        n = sized.get("quantity") if sized.get("quantity") is not None else sized.get("lots")
        risk = ((sized.get("estimated_risk_rs") or {}).get("total")) if isinstance(sized.get("estimated_risk_rs"), dict) else None
        return [f"Account sizing (risk service, saved risk profile): {n} {sized.get('unit') or ''}".rstrip()
                + (f"; estimated risk ₹{_num(risk)}" if _num(risk) else "")
                + (f" = {_num(sized.get('risk_pct_of_equity'))}% of paper equity ₹{_num(sized.get('equity_rs'))}"
                   if _num(sized.get("risk_pct_of_equity")) and _num(sized.get("equity_rs")) else "")
                + ("" if st == "sized" else " (not confirmed)") + "."]
    if st == "not_sizable":
        return ["Account sizing: the risk service would refuse this plan on the user's account; say so."]
    return [f"Account sizing: unavailable ({sized.get('reason') or 'unknown reason'}); do not state a quantity or rupee risk."]


def context_for(plan: Dict[str, Any], direction: str, direction_stated: bool, shown: bool,
                extra: Optional[List[str]] = None) -> str:
    """The plan's facts for the stock analyst (read as data), with what was assumed and whether a card is shown."""
    from services.strategy_plan import explain_plan_context
    lines = [
        "TRADE_PLAN: the desk's own rule-based plan for this stock, built for this answer from end-of-day data. "
        "Quote only these figures; do not compute or invent other levels or prices.",
        f"Direction used: {direction}" + ("" if direction_stated else " (ASSUMED: the user did not say; say so and offer "
                                                                       "the opposite view)") + ".",
        "Size: the user's saved risk profile (the risk service sizes the plan; the card shows the rupee risk).",
        "A card with this plan is shown above the answer." if shown else
        "No card is shown: there is no setup to trade now. Say why (the reasons below) and what would have to change.",
    ]
    try:
        lines.append(explain_plan_context(plan))
    except Exception:  # noqa: BLE001 — the facts summary is best-effort; the status line still tells the analyst enough
        logger.warning("copilot trade idea: explain_plan_context failed", exc_info=True)
        lines.append(f"Status: {plan.get('status')}")
        for r in plan.get("status_reasons") or []:
            if isinstance(r, dict):
                lines.append(f"Reason [{r.get('code')}]: {r.get('message')}")
    for w in plan.get("would_change_if") or []:
        lines.append(f"Would change if: {w}")
    lines.extend(extra or [])
    return "\n".join(lines)


async def build(request: Any, user_id: str, symbol: str, message: str) -> Optional[TradeIdea]:
    """The desk's StrategyPlan for `symbol`, as POST /api/desk/strategy/plan builds it, turned into a card and the facts
    for the answer. None when the builder refuses the inputs. Never raises: a failure is said in the context."""
    from routes import strategy_plan as route
    from services.strategy_plan import build_plan, normalise_inputs
    from services.strategy_plan.sources import attach_symbol_suggestions, collect_snapshots, finish_plan

    direction, stated = direction_of(message)
    inputs, problems = normalise_inputs({"underlying": symbol, "direction": direction, "horizon": horizon_of(message)})
    if problems or not inputs:
        logger.info("copilot trade idea: inputs refused for %s: %s", symbol, problems)
        return None

    async def run() -> Dict[str, Any]:
        snaps = await collect_snapshots(request, user_id, inputs, route.today())
        plan = await asyncio.to_thread(build_plan, inputs, snaps, route.utcnow(), route.today())
        plan = await attach_symbol_suggestions(plan)
        await route.store_trade_plans([c.get("trade_plan") for c in plan.get("candidates") or []], user_id)
        return await finish_plan(plan, user_id)

    try:
        plan = await asyncio.wait_for(run(), timeout=BUILD_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without a plan, and says so
        logger.warning("copilot trade idea: plan for %s could not be built: %s", symbol, exc)
        return TradeIdea(widget=None, status=None, context=(
            "TRADE_PLAN: the desk's plan for this stock could not be built just now. Do not describe entry, stop or "
            "target levels; say a plan was not available and suggest opening the Strategy Builder on the trading desk."))
    widget = widget_for(plan, stated)
    extra: List[str] = []
    sized: Optional[Dict[str, Any]] = None
    if widget is not None:
        by_id = {(c.get("trade_plan") or {}).get("plan_id"): c for c in plan.get("candidates") or [] if isinstance(c, dict)}
        for row in widget["data"]["plans"]:
            cand = by_id.get(row["plan_id"]) or {}
            extra.extend(trade_plan_lines(cand.get("trade_plan") or {}, row.get("label")))
        preferred = (by_id.get(widget["data"]["preferred_plan_id"]) or {}).get("trade_plan")
        if preferred:
            sized = await _size(preferred, user_id)
            extra.extend(sizing_lines(sized))
    return TradeIdea(widget=widget, status=plan.get("status"),
                     context=context_for(plan, direction, stated, shown=widget is not None, extra=extra),
                     plan=plan, sized=sized)


async def _size(tp: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """The risk service's sizing of a TradePlan for this account (routes/strategy_plan.account_sizer); never raises."""
    try:
        from deps import db
        from services.risk_gate import plan_sizing
        return await asyncio.wait_for(plan_sizing.size_for(db, tp, user_id), timeout=10.0)
    except Exception as exc:  # noqa: BLE001 — the card shows its own sizing; the answer then states no rupee figure
        return {"status": "unavailable", "reason": f"the sizing could not be worked out ({type(exc).__name__})"}
