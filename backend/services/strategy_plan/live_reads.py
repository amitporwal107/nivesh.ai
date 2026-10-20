"""Optional live broker reads on a BUILT plan: required margin of the F&O candidates and bid/ask of the preferred options legs.

Only when the plan asked for it (`inputs.live_broker_reads`, default false; the ideas route never does) and only through the user's own
live broker sessions. Read only: margin comes from Kite's margin calculator (margin.py), quotes from the broker's quote API (quotes.py);
no order, modify or cancel call exists in either. Every failure degrades to a null with the reason and the plan stands. Calls are bounded:
at most `MAX_MARGIN_CANDIDATES` candidates, one calculator call per distinct set of legs, at most `CONCURRENCY` at once, each under a timeout,
and none at all when the user has no live session for the broker.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import margin as mg
from . import quotes as qt
from . import plan as pl
from .rules import RULES

MAX_MARGIN_CANDIDATES = 6
CONCURRENCY = 3
FNO_SEGMENTS = ("futures", "options")
OLD_FUTURES_WARNING = "Futures losses can exceed the initial margin; no margin estimate exists in this system, so the notional is used for the allocation cap."
NEW_FUTURES_WARNING = ("Futures losses can exceed the initial margin. The broker's margin estimate is shown separately and is not the maximum loss; "
                       "the notional is still used for the allocation cap.")


def _legs_key(legs: List[Dict[str, Any]]) -> str:
    return json.dumps([{k: l.get(k) for k in ("kind", "side", "quantity", "lot_size", "strike", "option_type", "expiry")} for l in legs], sort_keys=True, default=str)


def _viable(c: Dict[str, Any]) -> bool:
    return c.get("status") == "candidate" and c.get("segment") in FNO_SEGMENTS and bool(c.get("legs"))


async def _margins(plan: Dict[str, Any], accounts: List[Dict[str, Any]], load_token, is_live, kite_factory, now, timeout) -> int:
    cands = [c for c in plan.get("candidates") or [] if _viable(c)]
    cands.sort(key=lambda c: c.get("id") != plan.get("preferred"))
    cands = cands[:MAX_MARGIN_CANDIDATES]
    if not cands:
        return 0
    cache: Dict[str, asyncio.Future] = {}
    sem = asyncio.Semaphore(CONCURRENCY)
    sym = plan["inputs"]["underlying"]

    async def one(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
        async with sem:
            try:
                return await asyncio.wait_for(mg.read_margin_estimate(accounts, sym, legs, load_token=load_token, is_live=is_live, kite_factory=kite_factory, now=now), timeout)
            except asyncio.TimeoutError:
                return mg._result(f"Zerodha's margin calculator timed out after {timeout:g}s", now=now, n=len(legs))

    tasks: Dict[str, asyncio.Task] = {}
    for c in cands:
        k = _legs_key(c["legs"])
        if k not in tasks:
            tasks[k] = asyncio.ensure_future(one(c["legs"]))
    results = dict(zip(tasks, await asyncio.gather(*tasks.values())))
    attached = False
    for c in cands:
        r = results[_legs_key(c["legs"])]
        pay = c.get("payoff")
        if not isinstance(pay, dict):
            continue
        if r["estimate"] is not None:
            pay["margin"] = {"estimate": r["estimate"], "before_offset": r["before_offset"], "broker": r["broker"], "source": r["source"], "as_of": r["as_of"]}
            pay["margin_reason"] = None
            attached = True
            c["warnings"] = [NEW_FUTURES_WARNING if w == OLD_FUTURES_WARNING else w for w in c.get("warnings") or []]
        else:
            pay["margin"] = None
            pay["margin_reason"] = r["reason"]
    first = results[_legs_key(cands[0]["legs"])]
    it = mg.margin_item(first)
    plan.setdefault("evidence", []).append(it)
    summ = plan.get("evidence_summary", {}).get(it["group"])
    if isinstance(summ, dict):
        summ[it["direction"]] = summ.get(it["direction"], 0) + 1
    if attached:
        plan["caveats"] = [pl.MARGIN_LIVE_CAVEAT if c == pl.MARGIN_CAVEAT else c for c in plan.get("caveats") or []]
    return sum(1 for r in results.values() if r.get("called"))


def _contracts(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for l in c.get("legs") or []:
        if l.get("kind") != "option" or l.get("strike") is None:
            continue
        kind = {"call": "CE", "put": "PE"}.get(str(l.get("option_type")))
        key = (kind, float(l["strike"]), str(l.get("expiry"))[:10])
        if kind and key not in seen:
            seen.add(key)
            out.append({"label": f"{l.get('option_type')} {l['strike']:g}", "instrument_type": kind, "strike": float(l["strike"]), "expiry": key[2]})
    return out


async def _leg_quotes(plan: Dict[str, Any], accounts, isin, load_token, is_live, readers, now, timeout) -> int:
    pref = next((c for c in plan.get("candidates") or [] if c.get("id") == plan.get("preferred")), None)
    if not pref or pref.get("segment") != "options" or not isinstance(pref.get("options_selection"), dict):
        return 0
    contracts = _contracts(pref)
    if not contracts:
        return 0
    snap = await qt.read_option_bid_ask(accounts, plan["inputs"]["underlying"], isin, contracts, load_token=load_token, is_live=is_live, readers=readers, now=now, timeout=timeout)
    sel = pref["options_selection"]
    if not snap["ok"] or not snap["data"]["quotes"]:
        why = snap["error"] if not snap["ok"] else "; ".join(snap["data"]["skipped"]) or "the broker returned no usable quote"
        sel["bid_ask"] = {"status": "unavailable", "reason": why}
        return 0 if not snap["ok"] and "no connected broker" in (snap["error"] or "") else 1
    data = snap["data"]
    modes = {q["mode"] for q in data["quotes"]}
    mode = "live" if modes == {"live"} else "delayed" if "delayed" in modes else "untimed"
    sel["bid_ask"] = {"status": "ok", "mode": mode, "broker": data["display"], "read_at": data["read_at"], "quotes": data["quotes"], "skipped": data["skipped"],
                      "note": "Read-only quote from the user's own broker session; no order is placed. Fills are not assumed at mid."}
    flags = sel.setdefault("preferred_flags", [])
    wide = RULES["quotes"]["wide_spread_pct"]
    for q in data["quotes"]:
        if q["spread_pct"] > wide:
            flags.append(f"Wide spread at {q['strike']:g} {q['instrument_type']}: bid {q['bid']:g} x ask {q['ask']:g} is {q['spread_pct']:g}% of mid (over {wide:g}%); {mode} quote.")
    for row in plan.get("alternatives") or []:
        if row.get("id") == pref["id"]:
            row["liquidity_flags"] = flags
    plan.setdefault("data_as_of", {})["bid_ask"] = {"mode": mode, "broker": data["display"], "read_at": data["read_at"]}
    if mode != "untimed":
        plan["caveats"] = [pl.LIVE_CAVEAT if c == pl.EOD_CAVEAT else c for c in plan.get("caveats") or []]
    return 1


async def attach_live_reads(plan: Dict[str, Any], accounts: List[Dict[str, Any]], isin: Optional[str], *, load_token: Callable, is_live: Callable,
                            readers: Optional[Dict[str, Tuple[str, Any]]] = None, kite_factory: Optional[Callable] = None, now=None,
                            timeout: Optional[float] = None) -> Dict[str, int]:
    """Mutates `plan` (candidates' payoff.margin, the ledger, options_selection.bid_ask, flags, caveats). Never raises."""
    stats = {"margin_calls": 0, "quote_calls": 0}
    if not (plan.get("inputs") or {}).get("live_broker_reads"):
        return stats
    timeout = timeout if timeout is not None else RULES["quotes"]["read_timeout_seconds"]
    try:
        stats["margin_calls"] = await _margins(plan, accounts, load_token, is_live, kite_factory, now, timeout)
    except Exception as e:  # noqa: BLE001 — optional read: the plan stands without it
        stats["margin_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    try:
        stats["quote_calls"] = await _leg_quotes(plan, accounts, isin, load_token, is_live, readers, now, timeout)
    except Exception as e:  # noqa: BLE001
        stats["quote_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return stats
