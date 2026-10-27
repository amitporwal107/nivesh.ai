"""AI scanner watchlist — building one day's lists (scripts/build_ai_watchlist.py runs it nightly).

  cash   the ideas engine's top TOP setups and the strategy that fits each: the same answer as
         POST /api/desk/strategy/ideas {limit: TOP} (services/strategy_plan/ideas.build_ideas)
  fno    NIFTY, BANKNIFTY and F&O stocks, one row each, ranked by fit to the measured regime then reward : risk: the same
         answer as POST /api/desk/strategy/top {limit: TOP, classes: [index_options, stock_fno], distinct: true}
         (services/strategy_plan/regime_fit.build_top), both classes merged by the route's own rule and cut to TOP

  levels each F&O entry also keeps `strategy_levels`: the strategy-levels engine's answer for that idea on the list day
         (services/strategy_levels.compute, in-process, the engine behind POST /api/desk/strategy/levels), worked out
         from the same payoff request and references the browser sends for a live board's row, so a past day's row can
         show the levels it had without recomputing them on a later day's prices. Display only and hypothetical.

Both builders call the desk's route functions, which check the signed-in user, so the build runs inside
`deps.system_caller(SYSTEM_USER)` with an internal request object. Nothing is recomputed here: each entry is the route's
answer for that day, kept as it was. Ideas for review, not recommendations; nothing places an order.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TOP = 10
SYSTEM_USER: Dict[str, Any] = {"user_id": "system:ai-watchlist", "name": "AI scanner watchlist job", "email": None,
                               "is_admin": False, "role": "user"}
RULES = {
    "cash": f"The AI scanner's merged setup list ranked by its evidence score, top {TOP}, each with the strategy the plan "
            "builder found fits it (POST /api/desk/strategy/ideas).",
    "fno": f"NIFTY, BANKNIFTY and F&O stocks from the AI scanner, one row per instrument, ranked by fit to the measured "
           f"market regime then reward : risk, top {TOP} (POST /api/desk/strategy/top, distinct).",
}


def internal_request():
    """A request object for in-process route calls. Carries no cookie or token: the system caller is the identity."""
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/internal/ai-watchlist", "raw_path": b"/internal/ai-watchlist",
                    "query_string": b"", "headers": [], "client": ("127.0.0.1", 0), "server": ("internal", 80),
                    "scheme": "http", "root_path": ""})


def _strategy(s: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    keep = ("id", "segment", "family", "label", "status", "legs_text", "max_loss", "max_loss_basis", "capital_at_risk",
            "max_profit", "profit_unbounded", "breakeven", "reward_risk_net", "reward_risk_gross")
    return {k: s.get(k) for k in keep}


def cash_entry(idea: Dict[str, Any], rank: int) -> Dict[str, Any]:
    """One cash idea as stored: the scanner's view, the plan's status, the strategy that fits and what the Strategy
    Builder link needs. Every figure is the ideas route's."""
    sc = idea.get("scanner") or {}
    strategies = idea.get("strategies") or []
    preferred = next((s for s in strategies if s.get("id") == idea.get("preferred")), None) if idea.get("preferred") else None
    cash = next((s for s in strategies if s.get("segment") == "cash"), None)
    sized = ((cash or {}).get("sizing") or {}).get("quantity")
    return {
        "rank": rank, "symbol": idea.get("symbol"), "name": idea.get("name"), "sector": sc.get("sector"),
        "direction": idea.get("direction"), "fno_eligible": idea.get("fno_eligible"), "source": idea.get("source"),
        "scanner": {k: sc.get(k) for k in ("bucket", "status", "score", "close", "close_date", "entry", "stop", "target",
                                            "risk_reward", "horizon_days", "atr_pct", "liquidity_cr", "reason", "reasons")},
        "plan_status": idea.get("plan_status"),
        "status_reasons": [r.get("message") for r in idea.get("status_reasons") or [] if isinstance(r, dict) and r.get("message")],
        "preferred": _strategy(preferred),
        "sized_shares": sized if isinstance(sized, int) and sized >= 1 else None,
        "plan_inputs": idea.get("plan_inputs") or {},
    }


def _rank_key(i: Dict[str, Any]):
    return (-((i.get("fit") or {}).get("score") or 0.0), -(i.get("reward_risk") or 0.0))


def fno_entries(top: Dict[str, Any], limit: int = TOP) -> List[Dict[str, Any]]:
    """The two option classes merged by the route's own rule (regime_fit._rank_key: fit, then reward : risk; a missing
    reward : risk last; a tie keeps the index class first) and cut to `limit`. Alternatives are not kept."""
    classes = top.get("classes") or {}
    rows = [({**i, "kind": "index"}) for i in (classes.get("index_options") or {}).get("ideas") or []]
    rows += [({**i, "kind": "stock"}) for i in (classes.get("stock_fno") or {}).get("ideas") or []]
    rows.sort(key=_rank_key)
    out = []
    for n, r in enumerate(rows[:limit], 1):
        r = {k: v for k, v in r.items() if k != "alternatives"}
        r["rank"] = n
        out.append(r)
    return out


# The idea's legs as the payoff request takes them (frontend-v5 strategy/top-actions.ts payoffRequestFor, same keys).
LEVEL_LEG_KEYS = ("kind", "side", "quantity", "lot_size", "entry_price", "expiry", "strike", "option_type", "price_source", "iv_pct")


def payoff_request_for(idea: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The payoff request for one F&O idea, the same body the browser builds for a live board's row
    (frontend-v5 strategy/top-actions.ts payoffRequestFor): the idea's own legs, its reference price and its chain date;
    a missing field is left out, as JSON drops it there. None without a reference price or legs."""
    legs = idea.get("legs") or []
    if idea.get("reference_price") is None or not legs:
        return None
    req: Dict[str, Any] = {"underlying": idea.get("underlying"), "reference_price": idea.get("reference_price")}
    as_of = (idea.get("data_as_of") or {}).get("chain")
    if as_of:
        req["as_of"] = as_of
    req["legs"] = [{k: leg.get(k) for k in LEVEL_LEG_KEYS if leg.get(k) is not None} for leg in legs if isinstance(leg, dict)]
    return req


def levels_refs_for(top: Dict[str, Any], underlying: Optional[str]) -> Dict[str, Any]:
    """The references the levels engine gets for an idea, as the browser sends them (strategy/top-actions.ts
    levelsRefsFor): no open-interest walls (the board does not carry them) and the expected move the board measured
    for the underlying (the index class first, then stock F&O)."""
    classes = top.get("classes") or {}
    move = None
    for cls in ("index_options", "stock_fno"):
        for u in (classes.get(cls) or {}).get("underlyings") or []:
            if move is None and u.get("underlying") == underlying and u.get("expected_move") is not None:
                move = u["expected_move"]
    return {"put_wall": None, "call_wall": None, "expected_move": move}


def levels_for(idea: Dict[str, Any], refs: Dict[str, Any], list_date: str, now: datetime) -> Dict[str, Any]:
    """The levels stored with one F&O entry: {as_of (the chain date), computed_at, refs, result (the engine's answer,
    valid or not, kept as it was), error}. One idea the engine cannot work out never loses the day's list: the reason
    is stored and logged instead."""
    from services import strategy_levels

    out: Dict[str, Any] = {"as_of": (idea.get("data_as_of") or {}).get("chain"), "computed_at": now.isoformat(),
                           "refs": refs, "result": None, "error": None}
    req = payoff_request_for(idea)
    if req is None:
        out["error"] = "The idea has no reference price or no priced legs, so no levels were worked out."
        return out
    try:
        out["result"] = strategy_levels.compute(req, refs, date.fromisoformat(list_date))
    except Exception as exc:  # noqa: BLE001 — recorded on the entry and logged, never dropped
        logger.warning("ai-watchlist %s: levels for %s failed: %s: %s", list_date, idea.get("underlying"),
                       type(exc).__name__, str(exc)[:200])
        out["error"] = f"The levels could not be worked out on the list day ({type(exc).__name__})."
    return out


def shape_day(list_date: str, ideas: Dict[str, Any], top: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    classes = top.get("classes") or {}
    stock = classes.get("stock_fno") or {}
    fno = fno_entries(top)
    for e in fno:
        e["strategy_levels"] = levels_for(e, levels_refs_for(top, e.get("underlying")), list_date, now)
    return {
        "list_date": list_date,
        "built_at": now.isoformat(),
        "rules": RULES,
        "cash": [cash_entry(i, n) for n, i in enumerate((ideas.get("ideas") or [])[:TOP], 1)],
        "fno": fno,
        "notes": {
            "cash_ranking": ideas.get("ranking_note"),
            "cash_caveats": ideas.get("caveats") or [],
            "cash_data_as_of": ideas.get("data_as_of"),
            "cash_rules_version": ideas.get("rules_version"),
            "fno_ranking": top.get("ranking_note"),
            "fno_gaps": top.get("gaps") or [],
            "fno_rules_version": top.get("rules_version"),
            "fno_staleness": top.get("staleness_note"),
            "fno_chain_as_of": (classes.get("index_options") or {}).get("as_of") or stock.get("as_of"),
            "fno_skipped": (stock.get("universe") or {}).get("skipped") or [],
            "fno_unavailable": [*((classes.get("index_options") or {}).get("unavailable") or []), *(stock.get("unavailable") or [])],
            "regime": {k: (top.get("regime") or {}).get(k) for k in ("available", "key", "label", "as_of", "trend", "india_vix",
                                                                      "vix_high_threshold", "breadth", "reason")},
        },
        "sent_to_broker": False,
    }


async def build_day(list_date: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Run both builders as the system caller and shape the day's document. Writes nothing."""
    from deps import system_caller
    from services.strategy_plan import ideas as ideas_mod
    from services.strategy_plan import regime_fit

    now = now or datetime.now(timezone.utc)
    req = internal_request()
    limit, passed, problems, applied = ideas_mod.parse_body({"limit": TOP})
    if problems or limit is None:
        raise RuntimeError(f"ideas body refused: {problems}")
    with system_caller(SYSTEM_USER):
        ideas, top = await asyncio.gather(
            ideas_mod.build_ideas(req, SYSTEM_USER["user_id"], limit, passed or {}, applied, now, date.fromisoformat(list_date)),
            regime_fit.build_top(req, SYSTEM_USER["user_id"], limit=TOP, classes=["index_options", "stock_fno"], distinct=True),
        )
    return shape_day(list_date, ideas, top, now)
