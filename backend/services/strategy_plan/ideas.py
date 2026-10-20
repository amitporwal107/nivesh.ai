"""Strategy ideas from the AI opportunities (user requirement 2026-10-20). One call selects the top scanner setups
(selection.py) and builds a full strategy plan for each with instrument "all" (cash, futures, options and combinations), from the
scanner data already read for the request. Read-only; nothing is sent to a broker; nothing is written.

The response carries, per idea, the strategies side by side with the payoff engine's figures (max loss, max profit, breakevens, net
reward : risk, capital at risk): nothing is calculated again here. `plan_inputs` is the exact body that rebuilds the idea's plan through
POST /api/desk/strategy/plan (deterministic: same inputs and same end-of-day data give the same plan id).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request

from . import evidence as ev
from .engine import CALCULATION_VERSION
from .plan import build_plan, normalise_inputs
from .rules import STRATEGY_RULES_VERSION
from .selection import DEFAULT_LIMIT, MAX_LIMIT, scanner_view, select_opportunities
from .sources import collect_snapshots, company_name, scanner_snapshot, shared_for_ideas

logger = logging.getLogger(__name__)

CONCURRENCY = 4
PASS_KEYS = ("capital", "risk_budget_inr", "risk_pct", "max_allocation_pct", "min_reward_risk", "avoid_events", "allow_multi_leg",
             "include_combinations", "horizon", "horizon_days", "costs")

RANKING_NOTE = ("Ideas keep the scanner's rank: its rules-based score, which is a rank and not a probability. Within an idea, `preferred` is the "
                "viable strategy with the best net reward : risk at the conservative level. Reward : risk of a hedged or income structure "
                "(a long put or a short call changes the loss at the stop) is not comparable with an unhedged one: read max loss and capital "
                "at risk beside it. No probability and no composite score is produced.")


def parse_body(body: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]], List[Dict[str, str]], List[str]]:
    """(limit, pass-through plan body without symbol, problems, applied defaults). Validation is the plan builder's own."""
    if not isinstance(body, dict):
        return None, None, [{"field": "body", "code": "bad_body", "message": "The request must be a JSON object."}], []
    probs: List[Dict[str, str]] = []
    applied: List[str] = []
    limit = body.get("limit")
    if limit is None:
        limit = DEFAULT_LIMIT
        applied.append("limit")
    elif isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        probs.append({"field": "limit", "code": "bad_limit", "message": f"limit must be a whole number from 1 to {MAX_LIMIT}."})
        limit = None
    passed = {k: body[k] for k in PASS_KEYS if body.get(k) is not None}
    _, plan_probs = normalise_inputs({"underlying": "TEMPLATE", "direction": "bullish", "instrument": "all", **passed})
    return limit, passed, probs + plan_probs, applied


def plan_body(symbol: str, passed: Dict[str, Any]) -> Dict[str, Any]:
    """The exact body that rebuilds this idea's plan through POST /api/desk/strategy/plan."""
    return {"underlying": symbol, "direction": "bullish", "instrument": "all", **passed}


def _fmt_day(v: Optional[str]) -> str:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").strftime("%-d %b")
    except ValueError:
        return str(v)


def legs_text(symbol: str, legs: List[Dict[str, Any]]) -> str:
    """'Buy 250 shares RELIANCE + Sell 1 lot RELIANCE 1250 call, 24 Nov'."""
    parts: List[str] = []
    days = {l.get("expiry") for l in legs if l.get("expiry")}
    for l in legs:
        verb, q = ("Buy" if l["side"] == "buy" else "Sell"), l["quantity"]
        if l["kind"] == "cash":
            parts.append(f"{verb} {q:g} shares {symbol}")
        elif l["kind"] == "future":
            parts.append(f"{verb} {q:g} lot{'' if q == 1 else 's'} {symbol} future")
        else:
            parts.append(f"{verb} {q:g} lot{'' if q == 1 else 's'} {symbol} {l['strike']:g} {l['option_type']}")
    text = " + ".join(parts)
    if len(days) == 1:
        text += f", {_fmt_day(next(iter(days)))}"
    elif len(days) > 1:
        text = " + ".join(p + (f", {_fmt_day(l['expiry'])}" if l.get("expiry") else "") for p, l in zip(parts, legs))
    return text


def _sizing_view(c: Dict[str, Any]) -> Dict[str, Any]:
    sz = c.get("sizing") or {}
    done = sz.get("status") == "complete"
    legs = c.get("legs") or []
    qty = sz.get("quantity") if done else None
    first = legs[0] if legs else None
    units = (first["quantity"] * first["lot_size"]) if first and done else None
    return {"status": sz.get("status"), "quantity": units, "lots": None if c["segment"] == "cash" else qty, "binding": sz.get("binding") if done else None,
            "unit": sz.get("unit"), "risk_budget_inr": sz.get("risk_budget_inr"), "risk_at_stop_inr": sz.get("risk_at_stop_inr"),
            "deployed_inr": sz.get("deployed_inr"), "missing": sz.get("missing") or []}


def _loss(v: Optional[float]) -> Optional[float]:
    """A loss as a negative P&L, the engine's convention (the plan's comparison rows give a cash or futures loss as a positive risk figure)."""
    return None if v is None else -abs(v)


def strategies_of(plan: Dict[str, Any], symbol: str) -> List[Dict[str, Any]]:
    rows = {a["id"]: a for a in plan.get("alternatives") or []}
    out = []
    for c in plan.get("candidates") or []:
        a = rows.get(c["id"], {})
        ex = ((c.get("payoff") or {}).get("expiry")) or {}
        why = (c.get("why_qualifies") or [None])[0] or next((r["message"] for r in c.get("reasons") or []), "")
        out.append({"id": c["id"], "segment": c["segment"], "family": c["family"], "label": c["label"], "status": c["status"],
                    "reasons": [{"code": r.get("code"), "message": r.get("message")} for r in c.get("reasons") or []],
                    "legs_text": legs_text(symbol, c.get("legs") or []), "max_loss": _loss(a.get("max_loss")), "max_loss_basis": a.get("max_loss_basis"),
                    "capital_at_risk": a.get("capital_at_risk"), "max_profit": ex.get("max_profit"), "profit_unbounded": bool(ex.get("profit_unbounded")),
                    "breakeven": a.get("breakeven") or [], "reward_risk_net": a.get("reward_risk_net"), "reward_risk_gross": a.get("reward_risk_gross"),
                    "sizing": _sizing_view(c), "liquidity_flags": a.get("liquidity_flags") or [], "why": why, "flags": list(c.get("warnings") or []),
                    "actionable": bool(c.get("actionable"))})
    return out


def oi_view(snaps: Dict[str, Any]) -> Dict[str, Any]:
    bu, ch = ev.snap(snaps, "buildup"), ev.snap(snaps, "chain")
    row = (bu["data"] or {}) if bu["ok"] else {}
    S = ((ch["data"] or {}).get("summary") or {}) if ch["ok"] else {}
    return {"buildup": row.get("label"), "cash_confirmation": row.get("cash_confirmation"), "pcr": S.get("pcr"), "max_pain": S.get("max_pain"),
            "call_wall": (S.get("max_call_oi") or {}).get("strike"), "put_wall": (S.get("max_put_oi") or {}).get("strike"),
            "expected_move": S.get("expected_move"), "chain_expiry": S.get("expiry"), "atm_iv": S.get("atm_iv"),
            "source_as_of": (ch["as_of"] if ch["ok"] else None) or (bu["as_of"] if bu["ok"] else None),
            "unavailable": ([f"build-up: {bu['error']}"] if not bu["ok"] else []) + ([f"option chain: {ch['error']}"] if not ch["ok"] else [])}


def fno_eligible(snaps: Dict[str, Any]) -> Optional[bool]:
    sr = ev.snap(snaps, "scan_row")
    flag = (sr["data"] or {}).get("fno_eligible") if sr["ok"] else None
    if isinstance(flag, bool):
        return flag
    ex = ev.snap(snaps, "expiries")
    return True if ex["ok"] and (ex["data"] or {}).get("expiries") else None


def idea_of(rank: int, setup: Dict[str, Any], plan: Dict[str, Any], snaps: Dict[str, Any], passed: Dict[str, Any], ms: int) -> Dict[str, Any]:
    sym = setup["symbol"]
    sm = plan.get("evidence_summary") or {}
    return {"rank": rank, "symbol": sym, "name": setup.get("name"), "scanner": scanner_view(setup), "direction": "bullish",
            "fno_eligible": fno_eligible(snaps), "plan_id": plan["plan_id"], "plan_status": plan["status"], "status_reasons": plan.get("status_reasons") or [],
            "would_change_if": plan.get("would_change_if") or [], "headline": plan.get("headline"),
            "evidence_summary": {g: sm.get(g) for g in ev.GROUPS if g in sm}, "oi_view": oi_view(snaps), "preferred": plan.get("preferred"),
            "strategies": strategies_of(plan, sym), "data_as_of": plan.get("data_as_of"), "plan_inputs": plan_body(sym, passed), "build_ms": ms}


def failed_idea(rank: int, setup: Dict[str, Any], passed: Dict[str, Any], err: BaseException, ms: int) -> Dict[str, Any]:
    msg = f"{type(err).__name__}: {str(err)[:200]}"
    return {"rank": rank, "symbol": setup["symbol"], "name": setup.get("name"), "scanner": scanner_view(setup), "direction": "bullish", "fno_eligible": None,
            "plan_id": None, "plan_status": "insufficient_data",
            "status_reasons": [{"code": "idea_build_failed", "message": f"The strategies for this stock could not be built: {msg}"}],
            "would_change_if": ["idea_build_failed: The data sources answering; rebuild the plan from the Strategy Builder."], "headline": None,
            "evidence_summary": {}, "oi_view": None, "preferred": None, "strategies": [], "data_as_of": None,
            "plan_inputs": plan_body(setup["symbol"], passed), "build_ms": ms}


async def build_ideas(request: Request, user_id: str, limit: int, passed: Dict[str, Any], applied: List[str], now: datetime, today: date) -> Dict[str, Any]:
    t0 = time.monotonic()
    sel = await select_opportunities(request, limit)
    template, _ = normalise_inputs({"underlying": "TEMPLATE", "direction": "bullish", "instrument": "all", **passed})
    inputs = {k: v for k, v in (template or {}).items() if k not in ("underlying", "expiry")}
    inputs["limit"] = limit
    inputs["defaults_applied"] = sorted(set(inputs.get("defaults_applied") or []) - {"instrument"} | set(applied))
    setups = sel["setups"]
    ideas: List[Dict[str, Any]] = []
    if setups:
        shared = await shared_for_ideas(user_id)
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(rank: int, setup: Dict[str, Any]) -> Dict[str, Any]:
            async with sem:
                t1 = time.monotonic()
                try:
                    plan_in, probs = normalise_inputs(plan_body(setup["symbol"], passed))
                    if probs:
                        raise ValueError("; ".join(p["code"] for p in probs))
                    snap = scanner_snapshot(setup["symbol"], setup["bucket"], setup.get("watch_item"), setup.get("pick"),
                                            sel["watchlist_as_of"] or sel["signal_date"], sel["watchlist_version"])
                    snaps, name = await asyncio.gather(collect_snapshots(request, user_id, plan_in, today, {**shared, "scanner_bucket": {setup["symbol"]: snap}}),
                                                       company_name(setup["symbol"]))
                    setup = {**setup, "name": setup.get("name") or name}
                    plan = await asyncio.to_thread(build_plan, plan_in, snaps, now, today)
                    return idea_of(rank, setup, plan, snaps, passed, int((time.monotonic() - t1) * 1000))
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — one stock failing must not lose the others: it becomes an insufficient_data idea
                    logger.warning("ideas: %s failed: %s", setup["symbol"], e, exc_info=True)
                    return failed_idea(rank, setup, passed, e, int((time.monotonic() - t1) * 1000))

        ideas = list(await asyncio.gather(*(one(i + 1, s) for i, s in enumerate(setups))))
    prices = [i["data_as_of"]["price"] for i in ideas if i.get("data_as_of") and i["data_as_of"].get("price")]
    fnos = [i["data_as_of"]["fno"] for i in ideas if i.get("data_as_of") and i["data_as_of"].get("fno")]
    return {
        "generated_at": now.isoformat(),
        "data_as_of": {"mode": "end_of_day", "scanner_watchlist": sel["watchlist_as_of"], "scanner_picks": sel["signal_date"],
                       "scan_eligibility": sel["gate_as_of"], "price": max(prices) if prices else None, "fno": max(fnos) if fnos else None},
        "rules_version": STRATEGY_RULES_VERSION, "calculation_version": CALCULATION_VERSION, "sent_to_broker": False,
        "selection": {"source": sel["source"], "scan_date": sel["scan_date"], "rule": sel["rule"], "considered": sel["considered"],
                      "selected": sel["selected"], "excluded": [{"symbol": x["symbol"], "reason": x["reason"], "code": x["code"]} for x in sel["excluded"]],
                      "excluded_note": "Only setups ranked above the last selected one are listed.", "limit": limit, "empty_reason": sel["empty_reason"],
                      "gate": sel["gate"], "source_failures": sel["source_failures"]},
        "inputs": inputs, "ranking_note": RANKING_NOTE, "ideas": ideas, "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "caveats": ["Conditional research ideas, not advice and not an instruction to trade.",
                    "End-of-day data: nothing here is live. F&O data is one NSE bhavcopy per day.",
                    "Payoff figures are calculations at the prices shown, not forecasts; taxes, statutory charges, dividends and funding are excluded.",
                    "Margin is not estimated (no source exists in this system) and is not the maximum loss.", "Nothing is sent to a broker."],
    }
