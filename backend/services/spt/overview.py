"""The Paper Trading › Overview body (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.01, §4 item 1, §7). Reads only.

STATUS STRIP
    feed_state      the live feed's chip rule (services/paper_pnl/prices.feed_mode, the same as routes/live_quotes.mode_of):
                    live → "live"; delayed → "stale"; closed → "closed"; expired / not_connected / disabled → "down"
    last_tick_age_s seconds since the feed's snapshot data (`data_at`); null when there is none
    session         "open" when the feed reports the NSE session open, else "closed"
    kill_switch     services/spt/risk.kill_switch_state: {state, entries_blocked, text}
    policy_version  the combined policy version (services/spt/policy_view.combined_version)
    mode            the SPT mode
KPIS (services/spt/allocation.account_state; null when a figure is unknown, never 0)
    equity_rs / start_equity_rs (the paper account's starting capital) / day_pnl_rs / day_loss_limit_pct (profile
    daily_loss_pct) / day_loss_used_pct (loss today ÷ start-of-day equity, % of the limit is for the screen) / deployed_rs
    / deployed_pct (of equity) / cash_rs / open_risk_pct (risk service estimate ÷ equity) / open_risk_limit_pct (profile
    max_open_risk_pct) / drawdown_pct / drawdown_warn_pct (the SPT ladder's first band, reduce_at_pct: from there new
    trade risk is cut) / positions_open / positions_max / orders_pending (SPT entry orders not yet filled)
PIPELINE (today, IST)
    signals         spt_signal_events of the day (market-wide)
    opportunities   spt_opportunities first seen that day (market-wide)
    qualified       those of them QUALIFIED (state, or the validation's decision before a later expiry)
    risk_approved   the caller's proposals of the day whose risk decision is APPROVE / APPROVE_REDUCED / CONDITIONAL
    orders_filled   the caller's SPT entry orders with a fill that day
    open_positions  the caller's SPT positions not CLOSED
WARNINGS [{level, title, code, at, symbol?}]
    danger  each risk refusal of the day (the proposal's risk decision REJECT / BLOCKED / HALT_ACCOUNT, code
            RISK_REJECTED); the kill switch blocking entries (its own code); the feed down in session (FEED_DOWN); the
            account unreadable (ACCOUNT_UNREADABLE); an exit-watch alert of the day with severity danger
    amber   a limit used above NEAR_LIMIT (80 %) of its value (NEAR_LIMIT_*); the feed stale in session (FEED_STALE);
            an SPT position whose mark is within NEAR_STOP_PCT of its stop (STOP_APPROACHING); other exit-watch alerts
    mint    FEEDS_HEALTHY when the feed is live (or the session is closed and nothing is wrong with it)
HEADLINE
    setups_cleared = risk_approved; blocked / reduced = today's proposals refused / APPROVE_REDUCED by the risk engine;
    worst_concentration = the sector whose exposure uses the largest share of the max-sector limit, reported only above
    NEAR_LIMIT of it, with its share of the open risk: the account state's open-risk rows (allocation.open_risk_rows, the
    same rows GET /api/v1/risk/account sums by bucket) summed by sector, ÷ all of them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services import data_freshness as fresh

from . import constants as C

logger = logging.getLogger(__name__)

NEAR_LIMIT = 0.8
NEAR_STOP_PCT = 2.0
APPROVED = (C.RISK_APPROVE, C.RISK_APPROVE_REDUCED, C.RISK_CONDITIONAL)
REFUSED = (C.RISK_REJECT, C.RISK_BLOCKED, C.RISK_HALT)
STAGES = (("signals", "Scanner signals"), ("opportunities", "Opportunities"), ("qualified", "Qualified"),
          ("risk_approved", "Risk approved"), ("orders_filled", "Orders filled"), ("open_positions", "Open positions"))
FEED_STATE = {"live": "live", "delayed": "stale", "closed": "closed"}
MAX_ROWS = 2000


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return None if part is None or not whole else round(part / whole * 100.0, 4)


def feed_state(mode: str) -> str:
    return FEED_STATE.get(mode, "down")


def status_block(feed: Dict[str, Any], ks: Dict[str, Any], policy_version: Optional[int], mode: Optional[str]
                 ) -> Dict[str, Any]:
    return {"feed_state": feed_state(feed.get("mode") or "disabled"), "feed_mode": feed.get("mode"),
            "last_tick_age_s": feed.get("age_s"), "session": "open" if feed.get("session") == "open" else "closed",
            "kill_switch": {"state": ks.get("state"), "entries_blocked": bool(ks.get("entries_blocked")),
                            "text": ks.get("text"), "code": ks.get("code"), "reason": ks.get("reason")},
            "policy_version": policy_version, "mode": mode}


def kpis(state: Dict[str, Any]) -> Dict[str, Any]:
    limits = (state.get("profile") or {}).get("limits") or {}
    eq = _f(state.get("equity_rs"))
    day_pnl, day_start = _f(state.get("day_pnl_rs")), _f(state.get("day_start_equity_rs"))
    lad = ((state.get("config") or {}).get("extras") or {}).get("drawdown_ladder") or {}
    account = ((state.get("book") or {}).get("account")) or {}
    open_risk = _f(state.get("open_risk_rs"))
    return {"equity_rs": eq, "start_equity_rs": _f(account.get("starting_capital_rs")),
            "day_pnl_rs": day_pnl, "day_loss_limit_pct": limits.get("daily_loss_pct"),
            "day_loss_used_pct": (round(max(0.0, -day_pnl) / day_start * 100.0, 4)
                                  if day_pnl is not None and day_start else None),
            "deployed_rs": _f(state.get("deployed_rs")), "deployed_pct": _pct(_f(state.get("deployed_rs")), eq),
            "cash_rs": _f(state.get("cash_rs")), "open_risk_pct": _pct(open_risk, eq),
            "open_risk_limit_pct": limits.get("max_open_risk_pct"), "drawdown_pct": _f(state.get("drawdown_pct")),
            "drawdown_warn_pct": lad.get("reduce_at_pct"), "positions_open": state.get("positions_open"),
            "positions_max": state.get("max_positions"), "orders_pending": len(state.get("pending_entries") or [])
            if not state.get("error") else None}


def concentration(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The sector nearest its exposure limit, when above NEAR_LIMIT of it (module docstring)."""
    eq = _f(state.get("equity_rs"))
    limits = (state.get("profile") or {}).get("limits") or {}
    cap_pct = _f(limits.get("max_sector_pct"))
    sectors = state.get("sector_rs") or {}
    if not eq or not cap_pct or not sectors:
        return None
    name, used = max(sectors.items(), key=lambda kv: float(kv[1] or 0.0))
    use = float(used or 0.0) / (eq * cap_pct / 100.0)
    if use <= NEAR_LIMIT:
        return None
    from .allocation import risk_by
    by_sector = risk_by(state.get("open_risk_rows") or [], "sector")
    total = sum(by_sector.values())
    mine = by_sector.get(name, 0.0)
    return {"name": name, "pct_of_open_risk": round(mine / total * 100.0, 2) if total > 0 else None,
            "exposure_rs": round(float(used), 2), "pct_of_sector_limit": round(use * 100.0, 2)}


def limit_warnings(state: Dict[str, Any], at: str) -> List[Dict[str, Any]]:
    """NEAR_LIMIT_* (amber) and *_BREACH (danger) for the account's limits."""
    out: List[Dict[str, Any]] = []
    k = kpis(state)
    rows = [("OPEN_RISK", "Open planned risk", k["open_risk_pct"], k["open_risk_limit_pct"]),
            ("DAILY_LOSS", "Daily loss", k["day_loss_used_pct"], k["day_loss_limit_pct"]),
            ("DRAWDOWN", "Drawdown", k["drawdown_pct"], (state.get("profile") or {}).get("limits", {}).get("max_drawdown_pct")),
            ("POSITIONS", "Open positions", _f(k["positions_open"]), _f(k["positions_max"]))]
    for code, name, used, limit in rows:
        if used is None or not limit:
            continue
        frac = float(used) / float(limit)
        if frac >= 1.0 - 1e-9:
            out.append({"level": "danger", "title": f"{name} is at its limit ({used:g} of {float(limit):g}).",
                        "code": f"LIMIT_BREACH_{code}", "at": at})
        elif frac > NEAR_LIMIT:
            out.append({"level": "amber", "title": f"{name} is near its limit ({used:g} of {float(limit):g}).",
                        "code": f"NEAR_LIMIT_{code}", "at": at})
    return out


def near_stop(positions: List[Dict[str, Any]], at: str) -> List[Dict[str, Any]]:
    out = []
    for p in positions:
        m = p.get("mark") or {}
        price, stop = _f(m.get("price")), _f(p.get("stop_loss"))
        if price is None or stop is None or price <= 0:
            continue
        dist = (price - stop) / price * 100.0
        if dist <= NEAR_STOP_PCT:
            out.append({"level": "amber" if dist > 0 else "danger", "symbol": p.get("symbol"),
                        "title": f"{p.get('symbol')}: {dist:.2f}% above its stop ₹{stop:,.2f} (mark ₹{price:,.2f})."
                        if dist > 0 else f"{p.get('symbol')}: the mark ₹{price:,.2f} is at or below its stop ₹{stop:,.2f}.",
                        "code": "STOP_APPROACHING", "at": m.get("at") or at})
    return out


def refusal_warnings(proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for p in proposals:
        r = p.get("risk") or {}
        if r.get("decision") not in REFUSED:
            continue
        why = next((x for x in r.get("explanations") or [] if x), None) or ", ".join(r.get("reason_codes") or []) \
            or str(r.get("decision"))
        out.append({"level": "danger", "title": f"{p.get('symbol')}: {why}", "code": "RISK_REJECTED",
                    "at": r.get("at") or p.get("updated_at"), "symbol": p.get("symbol"), "decision": r.get("decision")})
    return out


def alert_warnings(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Exit-watch alerts of the day (services/exit_watch/runner.SEVERITY): CRITICAL → danger, WARNING → amber; INFO
    (a stop raised, results soon) is not a warning and is left out."""
    out = []
    for a in alerts:
        sev = str(a.get("severity") or "").upper()
        if sev not in ("CRITICAL", "WARNING"):
            continue
        out.append({"level": "danger" if sev == "CRITICAL" else "amber",
                    "title": a.get("text") or f"{a.get('underlying')}: {a.get('kind')}",
                    "code": str(a.get("kind") or "EXIT_ALERT"), "at": a.get("at"), "symbol": a.get("underlying")})
    return out


def feed_warnings(status: Dict[str, Any], at: str) -> List[Dict[str, Any]]:
    st, session = status["feed_state"], status["session"]
    age = status.get("last_tick_age_s")
    if session == "open" and st == "down":
        return [{"level": "danger", "title": "The live feed is down: prices and fills are not current.", "code": "FEED_DOWN",
                 "at": at}]
    if session == "open" and st == "stale":
        return [{"level": "amber", "title": f"Live data is stale (last tick {age:g}s ago)." if age is not None
                 else "Live data is stale.", "code": "FEED_STALE", "at": at}]
    return []


def build(*, state: Dict[str, Any], ks: Dict[str, Any], feed: Dict[str, Any], policy_version: Optional[int],
          counts: Dict[str, Optional[int]], proposals_today: List[Dict[str, Any]], alerts: List[Dict[str, Any]],
          positions: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """The §7 body from what was read. Pure."""
    at = now.astimezone(timezone.utc).isoformat()
    mode = (state.get("config") or {}).get("mode")
    status = status_block(feed, ks, policy_version, mode)
    warnings: List[Dict[str, Any]] = []
    if state.get("error"):
        warnings.append({"level": "danger", "title": f"The paper account could not be read: {state['error']}.",
                         "code": "ACCOUNT_UNREADABLE", "at": at})
    if ks.get("entries_blocked"):
        warnings.append({"level": "danger", "title": ks.get("reason") or ks.get("text") or "New entries are blocked.",
                         "code": str(ks.get("code") or ks.get("state") or "ENTRIES_BLOCKED"), "at": at})
    warnings += refusal_warnings(proposals_today)
    if not state.get("error"):
        warnings += limit_warnings(state, at)
    warnings += near_stop(positions, at)
    warnings += alert_warnings(alerts)
    fw = feed_warnings(status, at)
    warnings += fw
    order = {"danger": 0, "amber": 1, "mint": 2}
    warnings.sort(key=lambda w: (order.get(w["level"], 3), str(w.get("at") or "")))
    if not fw and status["feed_state"] in ("live", "closed"):
        warnings.append({"level": "mint", "title": "All feeds healthy" if status["feed_state"] == "live"
                         else "All feeds healthy (market closed)", "code": "FEEDS_HEALTHY", "at": at})
    approved = [p for p in proposals_today if (p.get("risk") or {}).get("decision") in APPROVED]
    blocked = [p for p in proposals_today if (p.get("risk") or {}).get("decision") in REFUSED]
    reduced = [p for p in proposals_today if (p.get("risk") or {}).get("decision") == C.RISK_APPROVE_REDUCED]
    pipeline = [{"stage": key, "label": label, "count": counts.get(key)} for key, label in STAGES]
    return {"account_id": state.get("user_id"), "as_of": at, "status": status,
            "kpis": kpis(state) if not state.get("error") else {k: None for k in kpis({})},
            "pipeline": pipeline, "warnings": warnings,
            "headline": {"setups_cleared": len(approved),
                         "worst_concentration": concentration(state) if not state.get("error") else None,
                         "signals": counts.get("signals"), "opportunities": counts.get("opportunities"),
                         "blocked": len(blocked), "reduced": len(reduced)},
            "basis": {"pipeline": "signals, opportunities and qualified are market-wide counts for the IST day; risk "
                                  "approved, orders filled and open positions are this account's",
                      "warnings": f"near a limit = above {int(NEAR_LIMIT * 100)}% of it; stop approaching = the mark "
                                  f"within {NEAR_STOP_PCT:g}% of the stop"},
            "notes": [n for n in [state.get("error")] if n]}


# ── reads ────────────────────────────────────────────────────────────────────
async def _feed(now: datetime) -> Dict[str, Any]:
    from services.kite_live_feed import day_quote
    from services.kite_live_feed.feed import get_feed
    from services.paper_pnl import prices
    # The session from the clock when the feed has no status (a feed that is down must still read as down in session).
    clock_session = "open" if day_quote.in_session(now) else "closed"
    try:
        feed = get_feed()
        status = await feed.read_status()
        snap = await feed.read_snapshot() or {}
    except Exception as e:  # noqa: BLE001 — reported as down, never as live
        logger.warning("paper overview: feed status unreadable (%s)", type(e).__name__)
        return {"mode": "not_connected", "age_s": None, "session": clock_session, "error": type(e).__name__}
    data_at = prices._when(snap.get("data_at"))
    age = round((now - data_at).total_seconds(), 1) if data_at else None
    return {"mode": prices.feed_mode(status, age, prices.stale_after_seconds(status)), "age_s": age,
            "session": (status or {}).get("session") or clock_session}


async def counts_for(db, user_id: str, now: datetime) -> Dict[str, Optional[int]]:
    day = fresh.ist_today(now).isoformat()
    out: Dict[str, Optional[int]] = {}

    async def count(key: str, coll: str, q: Dict[str, Any]) -> None:
        try:
            out[key] = int(await db[coll].count_documents(q))
        except Exception as e:  # noqa: BLE001 — unknown, said so by null
            logger.warning("paper overview: %s count failed (%s)", key, type(e).__name__)
            out[key] = None

    await count("signals", C.SIGNAL_EVENTS, {"day": day})
    await count("opportunities", C.OPPORTUNITIES, {"day": day})
    await count("qualified", C.OPPORTUNITIES, {"day": day, "$or": [{"state": C.OPP_QUALIFIED},
                                                                    {"validation.decision": C.OPP_QUALIFIED}]})
    await count("risk_approved", C.PROPOSALS, {"user_id": user_id, "day": day, "risk.decision": {"$in": list(APPROVED)}})
    start = datetime.combine(fresh.ist_today(now), datetime.min.time(), tzinfo=fresh.IST).astimezone(timezone.utc).isoformat()
    try:
        orders = await db[C.ORDERS].find({"user_id": user_id, "purpose": "ENTRY",
                                          "state": {"$in": [C.ORD_FILLED, C.ORD_PARTIAL]}}).to_list(MAX_ROWS)
        out["orders_filled"] = sum(1 for o in orders if any(_day_of(f.get("at")) == day for f in o.get("fills") or [])
                                   or (not o.get("fills") and str(o.get("updated_at") or "") >= start))
    except Exception as e:  # noqa: BLE001
        logger.warning("paper overview: orders count failed (%s)", type(e).__name__)
        out["orders_filled"] = None
    await count("open_positions", C.POSITIONS, {"user_id": user_id, "state": {"$in": list(C.POS_OPEN_STATES)}})
    return out


def _day_of(stamp: Any) -> Optional[str]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:10]
    if d.tzinfo is None:
        d = d.replace(tzinfo=fresh.IST)
    return d.astimezone(fresh.IST).date().isoformat()


async def read(db, user_id: str, *, now: datetime,
               feed_reader: Optional[Callable[[datetime], Awaitable[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    from services.exit_watch import store as exit_store

    from . import allocation, policy_view, risk
    state = await allocation.account_state(db, user_id, now=now)
    ks = await risk.kill_switch_state(db, user_id, now=now, state=state)
    feed = await (feed_reader or _feed)(now)
    try:
        pv = policy_view.combined_version((state.get("book") or {}).get("profile") or {"version": 0},
                                          state.get("config") or {"version": 0}) if not state.get("error") else None
    except Exception:  # noqa: BLE001 — the strip shows no version rather than a wrong one
        pv = None
    day = fresh.ist_today(now).isoformat()
    props = await db[C.PROPOSALS].find({"user_id": user_id, "day": day}).to_list(MAX_ROWS)
    positions = await db[C.POSITIONS].find({"user_id": user_id, "state": {"$in": list(C.POS_OPEN_STATES)}}).to_list(MAX_ROWS)
    try:
        alerts = await exit_store.recent_alerts(db, user_id, day)
    except Exception as e:  # noqa: BLE001 — the alerts are one source of warnings; their absence is said in notes
        logger.warning("paper overview: exit alerts unreadable (%s)", type(e).__name__)
        alerts = []
    body = build(state=state, ks=ks, feed=feed, policy_version=pv, counts=await counts_for(db, user_id, now),
                 proposals_today=props, alerts=alerts, positions=positions, now=now)
    return body
