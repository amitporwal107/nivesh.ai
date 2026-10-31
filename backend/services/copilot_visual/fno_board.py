"""What the F&O setups answer adds to the desk's board (owner, 31 Oct 2026): the lots a structure is priced for, its margin,
the profit that is a real target, and live premiums while the market is open. Read only: nothing here places, modifies or
cancels an order.

    lots_text            "1 lot × 30": the quantity every figure on the row is for (the board prices one lot)
    profit_cell          a bought option's profit is not capped in practice; the theoretical top of a put (the index at
                         ZERO) is a tooltip, never a figure to read as a target (same rule as the loss at the stop, PR #415)
    read_live_legs       Kite REST quote() for the named contracts of the ideas on screen, only contracts that traded TODAY
    reprice              an idea's payoff at live premiums, by the board's own engine (regime_fit.metrics_for). All option
                         legs live or none: a part-live total belongs to no moment. The RANKING is not recomputed (it was
                         produced from the end-of-day chain and says so), as in the desk's top-live.ts.
    margin_calculators   Zerodha's margin calculator through (1) the platform's Kite login of the day, else (2) the asking
                         user's own connected Zerodha session. No other broker has a calculator wired, and that is said.
    margins              one basket-margin call per structure (no per-leg hedge calls), bounded and cached for two minutes
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .payload import num, price

logger = logging.getLogger(__name__)

#: Single bought options: no practical cap on the profit (a call's is unbounded; a put's top assumes the index at zero).
NOT_CAPPED = ("long_call", "long_put")
NOT_CAPPED_TEXT = "Not capped"
MARGIN_MAX_CALLS = 24
MARGIN_CONCURRENCY = 3
MARGIN_TIMEOUT_S = 8.0
MARGIN_TTL_S = 120.0
MAX_CONTRACTS = 120
NO_CALCULATOR = "no margin calculator is available"
SRC_LIVE = "Kite live option premiums (REST quote, contracts traded today)"
LABEL_PLATFORM = "Zerodha margin calculator · the platform's Kite login"
LABEL_OWN = "Zerodha margin calculator · your Zerodha account"
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


# ── what a row shows ─────────────────────────────────────────────────────────

def lots_text(legs: List[Dict[str, Any]]) -> Optional[str]:
    """"1 lot × 30" when every option leg is the same lots × lot size, else None (never a guess)."""
    pairs = set()
    for l in legs or []:
        if not isinstance(l, dict) or l.get("kind") != "option":
            continue
        try:
            pairs.add((int(l.get("quantity") or 0), int(l.get("lot_size") or 0)))
        except (TypeError, ValueError):
            return None
    if len(pairs) != 1:
        return None
    lots, size = next(iter(pairs))
    if lots < 1 or size < 1:
        return None
    return f"{lots} lot{'' if lots == 1 else 's'} × {size}"


def profit_cell(structure: Optional[str], f: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """(the Max profit cell, its tooltip). A single bought option shows "Not capped" and the profit at the expected move
    sits in its own column; a capped structure (a spread, a condor) shows its real maximum."""
    top = num(f.get("max_profit"))
    if structure in NOT_CAPPED or f.get("profit_unbounded"):
        if structure == "long_put" and top is not None:
            return NOT_CAPPED_TEXT, (f"The theoretical top is {price(top)}, with the index at zero. That is not a realistic "
                                     "target, so the profit at the expected move is shown instead.")
        return NOT_CAPPED_TEXT, "The profit has no upper limit; the profit at the expected move is shown instead."
    return (round(top, 2) if top is not None else None), None


# ── live premiums ────────────────────────────────────────────────────────────

def leg_requests(ideas: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[Tuple[int, int], int]]:
    """The distinct option contracts of `ideas` as /api/live/fno-quotes names them, and (idea, leg) → index in that list."""
    flat: List[Dict[str, Any]] = []
    at: Dict[Tuple[int, int], int] = {}
    seen: Dict[Tuple[Any, ...], int] = {}
    for i, idea in enumerate(ideas):
        for j, l in enumerate(idea.get("legs") or []):
            if not isinstance(l, dict) or l.get("kind") != "option":
                continue
            key = (idea.get("underlying"), str(l.get("expiry"))[:10], l.get("strike"), l.get("option_type"))
            if key not in seen:
                if len(flat) >= MAX_CONTRACTS:
                    continue
                seen[key] = len(flat)
                flat.append({"underlying": idea.get("underlying"), "kind": "option", "expiry": str(l.get("expiry"))[:10],
                             "strike": l.get("strike"), "option_type": l.get("option_type")})
            at[(i, j)] = seen[key]
    return flat, at


async def read_live_legs(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Kite REST quote() for the named contracts: {available, reason, quotes {index: {last_price, ...}}, unresolved, as_of,
    source}. Always answers; with no login or a refused call it says why and carries NO prices. Only a contract that traded
    today is priced ("live" means live; a price from an earlier session is the end-of-day figure the board already has)."""
    from datetime import datetime, timezone

    from services import market_freshness
    from services.kite_live_feed import config as cfg, fno_quotes as fq, gateway as gw, platform_token as pt
    from services.kite_live_feed.feed import get_feed

    def off(reason: str) -> Dict[str, Any]:
        return {"available": False, "reason": reason, "quotes": {}, "unresolved": [], "source": None}

    if not legs:
        return off("no option contracts to price")
    if not cfg.enabled():
        return off("the live feed is disabled")
    feed = get_feed()
    try:
        await pt.refresh_cache(feed.db)          # a non-leader worker never reloads the day's token by itself
    except Exception as e:  # noqa: BLE001
        logger.warning("fno board: the platform token could not be reloaded (%s)", type(e).__name__)
    token = await pt.token_status(feed.db)
    if not token.get("stored") or token.get("expired"):
        return off("no Kite login today: the platform's Kite token is missing or has expired")
    key, access = cfg.get_api_key(), cfg.get_token()
    if not key or not access:
        return off("the Kite API key or access token is not configured")
    try:
        kite = gw.default_kite_factory(key, access)
        nfo = await asyncio.to_thread(kite.instruments, "NFO")
    except Exception as e:  # noqa: BLE001
        return off(f"the contract list could not be read ({type(e).__name__})")
    keys, unresolved = fq.resolve(legs, fq.index_instruments(nfo))
    if not keys:
        return {**off("none of the contracts is listed"), "unresolved": unresolved}
    try:
        answer = await asyncio.to_thread(kite.quote, sorted(set(keys.values())))
    except Exception as e:  # noqa: BLE001
        return off(f"the quote request failed ({type(e).__name__})")
    window = await market_freshness.window()
    priced = fq.prices_from(answer, keys, floor=window.today)
    return {"available": bool(priced), "reason": None if priced else "no contract has traded today",
            "quotes": {str(i): v for i, v in priced.items()}, "unresolved": unresolved,
            "as_of": datetime.now(timezone.utc).isoformat(), "source": SRC_LIVE}


def reprice(idea: Dict[str, Any], idx: int, quotes: Dict[int, Dict[str, Any]], at: Dict[Tuple[int, int], int],
            spot: Optional[float], move: Optional[float], today_iso: str) -> Optional[Dict[str, Any]]:
    """The idea's figures at live premiums, or None unless EVERY option leg has one and the live spot is known."""
    from services.strategy_plan.regime_fit import _expected_move_price, metrics_for

    if spot is None:
        return None
    legs: List[Dict[str, Any]] = []
    for j, l in enumerate(idea.get("legs") or []):
        if not isinstance(l, dict):
            return None
        if l.get("kind") != "option":
            legs.append(l)
            continue
        q = quotes.get(at.get((idx, j), -1))
        px = num((q or {}).get("last_price"))
        if px is None or px <= 0:
            return None
        legs.append({**l, "entry_price": px, "price_source": "Kite live quote"})
    m = metrics_for(str(idea.get("underlying")), legs, float(spot), today_iso,
                    scenario_price=_expected_move_price(str(idea.get("view")), {"spot": spot, "expected_move": move}))
    if not m.get("ok"):
        return None
    return {"max_profit": m["max_profit"], "max_loss": m["max_loss"], "profit_unbounded": m["profit_unbounded"],
            "loss_unbounded": m["loss_unbounded"], "net_at_expected_move": m["net_at_expected_move"],
            "reward_risk": m["reward_risk_at_expected_move"], "net_premium": m["net_premium"]}


# ── margin ───────────────────────────────────────────────────────────────────

def margin_legs(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The idea's legs in the margin calculator's own shape (routes/fno.py MarginLeg)."""
    return [{"side": l["side"], "option_type": l["option_type"], "expiry": str(l["expiry"])[:10], "strike": l.get("strike"),
             "lots": int(l.get("quantity") or 1)} for l in legs or [] if isinstance(l, dict) and l.get("kind") == "option"]


def legs_key(underlying: str, legs: List[Dict[str, Any]]) -> str:
    return json.dumps([underlying, margin_legs(legs)], sort_keys=True, default=str)


async def margin_calculators(request: Any, user_id: Optional[str]) -> Tuple[List[Tuple[str, Any]], Dict[str, Any]]:
    """([(label, Calculator)] in the order to try, facts for the "log in" notice). Never raises."""
    from services import fno_margin

    calcs: List[Tuple[str, Any]] = []
    facts: Dict[str, Any] = {"platform_login": True, "zerodha_connected": 0, "zerodha_live": 0, "others": []}
    try:
        from deps import db
        from services.kite_live_feed import platform_token
        await platform_token.refresh_cache(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("fno board: the platform token could not be reloaded (%s)", type(e).__name__)
    try:
        calcs.append((LABEL_PLATFORM, fno_margin.default_calculator()))
    except fno_margin.NoSession:
        facts["platform_login"] = False
    except Exception as e:  # noqa: BLE001
        facts["platform_login"] = False
        logger.warning("fno board: platform calculator unavailable (%s)", type(e).__name__)
    if not user_id:
        return calcs, facts
    try:
        from routes import broker_connect as bc
        from services.brokers import sessions, zerodha
        await bc._hub_user(request)
        for doc in await bc._user_accounts(user_id):
            slug = str(doc.get("broker") or "").lower()
            if slug != "zerodha":
                if slug and slug not in facts["others"]:
                    facts["others"].append(slug)
                continue
            facts["zerodha_connected"] += 1
            if doc.get("native") and sessions.is_live(doc):
                facts["zerodha_live"] += 1
                calcs.append((LABEL_OWN, fno_margin.Calculator(zerodha._kite(sessions.load_token(doc).token))))
    except Exception as e:  # noqa: BLE001 — no broker hub for this user is an answer, not a failure
        logger.info("fno board: no broker accounts read for margin (%s)", type(e).__name__)
    return calcs, facts


def _one_margin(calc: Any, underlying: str, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from services import fno_margin as fm

    params, missing = fm.map_legs(fm.instruments_today(calc), margin_legs(legs), underlying)
    if missing:
        return {"estimate": None, "reason": "not listed: " + ", ".join(missing)}
    out = fm.shape(calc.basket_margins(params), date.today().isoformat())
    est = out.get("required_margin")
    return {"estimate": est, "reason": None if est is not None else "the calculator returned no total"}


def _session_refused(e: BaseException) -> bool:
    return type(e).__name__ in ("TokenException", "PermissionException")


async def margins(calcs: List[Tuple[str, Any]], items: List[Tuple[str, str, List[Dict[str, Any]]]]) -> Dict[str, Dict[str, Any]]:
    """{key: {estimate, reason, source}} for each (key, underlying, legs). One basket call per structure; a calculator whose
    session Kite refuses is dropped and the next one is tried; at most MARGIN_MAX_CALLS calls in all."""
    out: Dict[str, Dict[str, Any]] = {}
    alive = list(calcs)
    gate = asyncio.Semaphore(MARGIN_CONCURRENCY)
    budget = {"left": MARGIN_MAX_CALLS}

    async def one(key: str, underlying: str, legs: List[Dict[str, Any]]) -> None:
        ck = legs_key(underlying, legs)
        hit = _CACHE.get(ck)
        if hit and time.monotonic() - hit[0] < MARGIN_TTL_S:
            out[key] = hit[1]
            return
        async with gate:
            while alive:
                if budget["left"] <= 0:
                    out[key] = {"estimate": None, "reason": "not requested: the per-answer margin call limit was reached", "source": None}
                    return
                label, calc = alive[0]
                budget["left"] -= 1
                try:
                    res = await asyncio.wait_for(asyncio.to_thread(_one_margin, calc, underlying, legs), MARGIN_TIMEOUT_S)
                except asyncio.TimeoutError:
                    out[key] = {"estimate": None, "reason": f"the calculator did not answer in {MARGIN_TIMEOUT_S:g}s", "source": label}
                    return
                except Exception as e:  # noqa: BLE001
                    if _session_refused(e):
                        if alive and alive[0][1] is calc:
                            alive.pop(0)
                        continue
                    logger.warning("fno board: margin calculator failed (%s)", type(e).__name__)
                    out[key] = {"estimate": None, "reason": f"the calculator failed ({type(e).__name__})", "source": label}
                    return
                res = {**res, "source": label}
                if res["estimate"] is not None:
                    _CACHE[ck] = (time.monotonic(), res)
                out[key] = res
                return
            out[key] = {"estimate": None, "reason": NO_CALCULATOR, "source": None}

    await asyncio.gather(*(one(k, u, l) for k, u, l in items))
    return out


def login_text(facts: Dict[str, Any], need: str) -> str:
    """Why a figure is missing and what to do: the platform's Kite login, or the user's own Zerodha account. `need` names
    what is missing ("Margin", "Live premiums", "Margin and live premiums")."""
    steps = ["ask an admin to log in to Kite for the day (the header's Log in to Kite)"]
    if facts.get("zerodha_connected") and not facts.get("zerodha_live"):
        steps.append("sign in to your Zerodha account again in Brokers: its session has ended")
    elif not facts.get("zerodha_connected"):
        steps.append("connect your own Zerodha account in Brokers")
    verb = "need" if " and " in need or need.endswith("premiums") else "needs"
    text = f"{need} {verb} a Kite login: " + ", or ".join(steps) + "."
    others = [s for s in facts.get("others") or []]
    if others:
        text += (f" {', '.join(o.replace('_', ' ').title() for o in others)} {'has' if len(others) == 1 else 'have'} "
                 "no margin calculator wired here, so it cannot supply this.")
    return text
