"""The user's BROKER book for the Copilot's "open trades" answer (owner, 31 Oct 2026): every connected broker account's net
positions, their account funds, the user's own stop/target (or the plan they recorded), the live price of what they hold, and
what each account's state is — signed in and live, signed out with a last stored read, not readable, or not connected.
Read-only towards brokers: nothing here can place, modify or cancel an order (hub_reads has no such call).

Built on services/positions (PR #428): `service.broker_groups` does the contract naming (ICICI SONBLW = NSE SONACOMS), the
pricing and the analytics (payoff, loss at the stop, Greeks, warnings); this module adds what an always-open screen needs.

Account states (`accounts[].state`):
    live           native account with a live session: positions read now, or from the read of at most BOOK_TTL_S ago
    session_ended  the broker session has ended (or the broker refused it): the LAST STORED read, dated, never as live
    read_failed    the session is live but this read failed: the last stored read, dated, and the reason
    not_supported  no reader for this broker's positions
    not_readable   a legacy account that holds no broker session

Broker limits (the design the owner asked for: "live data refreshed every 5 seconds"):
    The page asks every 5 s; the BROKER is not. Positions are re-read from a broker at most once per BOOK_TTL_S per account
    however many tabs or workers ask: the newest stored read (position_snapshots.last_seen_at in Mongo, shared by the four
    uvicorn workers) is the cache, with one in-process lock so concurrent requests coalesce. Funds are cached FUNDS_TTL_S
    in the worker. Between broker reads, a share's price comes from the platform's Kite feed (Redis, no call to any broker)
    and its P&L moves by quantity × the price change; a futures or options leg keeps the broker's own price of its last read
    and says when that was.

Prices and P&L:
    broker      the broker's own figure, as read
    live        the broker's figure moved by quantity × (live price − the price in that read) — shares only
    marked      quantity × (last price − average) when the broker sent NO P&L for the row (ICICI Direct sends null for futures
                and options rows, which the adapter reads as 0.0); gross, labelled as marked
Nothing is invented: a row with no price and no P&L has none.
"""
from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from . import analytics, service, store, symbols

logger = logging.getLogger(__name__)

BOOK_TTL_S = 15.0            # a broker is asked for an account's positions at most this often
FUNDS_TTL_S = 60.0           # ... and for its funds at most this often (per worker)
ANALYSIS_TTL_S = 90.0        # the chains, payoff and margin behind a book are worked out at most this often (per worker)
BROKER_CONCURRENCY = 4

LIVE, ENDED, FAILED, UNSUPPORTED, UNREADABLE = "live", "session_ended", "read_failed", "not_supported", "not_readable"
PNL_BROKER, PNL_LIVE, PNL_MARKED, PNL_NONE = "broker", "live", "marked", "none"

_LOCKS: Dict[str, asyncio.Lock] = {}
_FUNDS: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_ANALYSIS: Dict[str, Tuple[float, str, List[Dict[str, Any]]]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mono() -> float:
    return time.monotonic()


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _num(v: Any) -> Optional[float]:
    return service._num(v)


def _age_s(iso: Any, now: datetime) -> Optional[float]:
    if not isinstance(iso, str):
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds()


def reset_caches() -> None:
    """Forget every in-process cache (tests)."""
    _LOCKS.clear()
    _FUNDS.clear()
    _ANALYSIS.clear()


def _lock(account_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(account_id)
    if lock is None:
        lock = _LOCKS[account_id] = asyncio.Lock()
    return lock


# ── what a row's P&L is ──────────────────────────────────────────────────────

def broker_pnl(row: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """(P&L, basis) of one position row. The broker's figure stands unless it is a 0.0 the adapter made of a missing one: a
    position whose last price differs from its average cannot have exactly nothing to show, and ICICI Direct's futures and
    options rows carry `pnl: null` (seen on the live API, 31 Oct 2026). Those are marked at the last price and said so."""
    qty, avg, ltp, pnl = _num(row.get("quantity")), _num(row.get("avg_price")), _num(row.get("last_price")), _num(row.get("pnl"))
    sent_none = pnl is None or (pnl == 0 and ltp is not None and avg is not None and bool(qty) and abs(ltp - avg) > 1e-9)
    if not sent_none:
        return pnl, PNL_BROKER
    if ltp is not None and avg is not None and qty:
        return round(qty * (ltp - avg), 2), PNL_MARKED
    return None, PNL_NONE


# ── the accounts ─────────────────────────────────────────────────────────────

def _failure(hub: Any, exc: BaseException, slug: str, what: str) -> Dict[str, str]:
    code, message = hub.describe_failure(exc, slug, what)
    return {"code": code, "message": message}


async def _funds(db: Any, hub: Any, doc: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]], Optional[str]]:
    """(funds, error, read time). Cached FUNDS_TTL_S per account; a failure is reported and never cached."""
    key = doc["account_id"]
    hit = _FUNDS.get(key)
    if hit and _mono() - hit[0] < FUNDS_TTL_S:
        return hit[1]["funds"], None, hit[1]["at"]
    try:
        funds = await hub.read_account_funds(db, doc)
    except Exception as e:  # noqa: BLE001 — reported on the account; the positions stand
        return None, _failure(hub, e, doc.get("broker") or "", "funds"), None
    at = _iso(_now())
    _FUNDS[key] = (_mono(), {"funds": funds, "at": at})
    return funds, None, at


async def _read_positions(db: Any, hub: Any, user_id: str, doc: Dict[str, Any], acct: Dict[str, Any],
                          snap: Optional[Dict[str, Any]]) -> None:
    """Fill `acct` (state, rows, rows_at, error) for a native account with a live session. Mutates `acct`."""
    from services.brokers import sessions
    from services.brokers.fenix_reader import BrokerNotSupported
    now = _now()
    age = _age_s((snap or {}).get("last_seen_at"), now)
    if snap and age is not None and 0 <= age < BOOK_TTL_S:
        acct.update(state=LIVE, rows=snap.get("rows") or [], rows_at=snap["last_seen_at"], cached=True)
        return
    async with _lock(doc["account_id"]):
        snap2 = await store.latest_snapshot(db, user_id, doc["account_id"])       # another request may have read meanwhile
        age2 = _age_s((snap2 or {}).get("last_seen_at"), _now())
        if snap2 and age2 is not None and 0 <= age2 < BOOK_TTL_S:
            acct.update(state=LIVE, rows=snap2.get("rows") or [], rows_at=snap2["last_seen_at"], cached=True)
            return
        try:
            rows = await hub.read_account_positions(db, doc, "net")
        except (sessions.SessionEnded, hub.BrokerSessionExpired) as e:
            acct.update(state=ENDED, error=_failure(hub, e, doc.get("broker") or "", "net positions"))
        except BrokerNotSupported as e:
            acct.update(state=UNSUPPORTED, error=_failure(hub, e, doc.get("broker") or "", "net positions"), rows=[])
        except Exception as e:  # noqa: BLE001 — this account fails alone
            acct.update(state=FAILED, error=_failure(hub, e, doc.get("broker") or "", "net positions"))
        else:
            read_at = _iso(_now())
            acct.update(state=LIVE, rows=rows, rows_at=read_at, cached=False)
            try:
                await store.record_book_snapshot(db, user_id=user_id, account_id=doc["account_id"], broker=doc.get("broker") or "",
                                                 read_at=read_at, rows=rows)
            except Exception as e:  # noqa: BLE001 — the read stands; only the history is missing
                logger.warning("open book: snapshot not stored (%s)", type(e).__name__)
            return
        # Not live: the newest stored read stands in, dated.
        if snap2 and snap2.get("rows") is not None:
            acct.update(rows=snap2["rows"], rows_at=snap2.get("last_seen_at") or snap2.get("read_at"))


async def _one_account(db: Any, user_id: str, doc: Dict[str, Any], gate: asyncio.Semaphore) -> Dict[str, Any]:
    from routes import broker_connect as bc
    from services.brokers import hub_reads as hub, sessions
    acct: Dict[str, Any] = {**bc._account_entry(doc), "state": None, "error": None, "rows": [], "rows_at": None, "cached": False,
                            "funds": None, "funds_error": None, "funds_at": None}
    if not doc.get("native"):
        acct.update(state=UNREADABLE, error={"code": hub.CODE_NOT_SUPPORTED, "message": bc._NOT_NATIVE_POSITIONS})
        return acct
    snap = await store.latest_snapshot(db, user_id, doc["account_id"])
    if not sessions.is_live(doc):
        acct.update(state=ENDED, error=_failure(hub, sessions.SessionEnded("ended"), doc.get("broker") or "", "net positions"))
        if snap:
            acct.update(rows=snap.get("rows") or [], rows_at=snap.get("last_seen_at") or snap.get("read_at"))
        return acct
    async with gate:
        await _read_positions(db, hub, user_id, doc, acct, snap)
        if acct["state"] == LIVE:
            acct["funds"], acct["funds_error"], acct["funds_at"] = await _funds(db, hub, doc)
    return acct


async def read_accounts(request: Any, db: Any, user_id: str) -> Dict[str, Any]:
    """{hub: "on"|"off", accounts: [...]} — every connected account of the user and its state. An account that cannot be read
    says why; it never fails the others. Strictly the user's own accounts (`_user_accounts` filters on user_id)."""
    from routes import broker_connect as bc
    try:
        await bc._hub_user(request)
    except HTTPException as e:
        if e.status_code == 403:
            return {"hub": "off", "accounts": []}
        raise
    docs = await bc._user_accounts(user_id)
    gate = asyncio.Semaphore(BROKER_CONCURRENCY)
    return {"hub": "on", "accounts": list(await asyncio.gather(*(_one_account(db, user_id, d, gate) for d in docs)))}


def prepared_rows(accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The open rows of every account that has any (live, or the stored read of an ended one), in `service.broker_groups`'s
    input shape, each with its P&L and the basis of it."""
    out: List[Dict[str, Any]] = []
    for a in accounts:
        if a["state"] in (UNSUPPORTED, UNREADABLE):
            continue
        for r in a["rows"] or []:
            if not _num(r.get("quantity")):
                continue
            r = dict(r)
            r["pnl"], r["_pnl_basis"] = broker_pnl(r)
            r["_account_id"], r["_broker"], r["_broker_display"] = a["account_id"], a["broker"] or "", a["broker_display"]
            r["_read_at"], r["_state"] = a["rows_at"], "live" if a["state"] == LIVE else "snapshot"
            out.append(r)
    return out


# ── the plan the user recorded ───────────────────────────────────────────────

async def plans_for(db: Any, user_id: str, underlyings: List[str]) -> Dict[str, Dict[str, Any]]:
    """The newest TradePlan THE USER holds (trade_plans.owners has their id: they built or opened it) for each underlying.
    A plan only the system built (the AI watchlist) is not theirs and is never read as their plan."""
    out: Dict[str, Dict[str, Any]] = {}
    for u in underlyings:
        try:
            doc = await db["trade_plans"].find_one({"instrument.symbol": u, "owners": user_id}, sort=[("created_at", -1)])
        except Exception as e:  # noqa: BLE001 — no plan is an answer; a failed read is logged
            logger.warning("open book: plan read failed (%s)", type(e).__name__)
            continue
        if doc:
            out[u] = plan_view(doc)
    return out


def plan_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The few plan fields the book compares a position with."""
    inst, strat = doc.get("instrument") or {}, doc.get("strategy") or {}
    primary = next((t for t in doc.get("targets") or [] if isinstance(t, dict) and t.get("primary")), None)
    return {"plan_id": doc.get("plan_id") or doc.get("_id"), "created_at": doc.get("created_at"), "segment": inst.get("segment"),
            "direction": strat.get("direction"), "entry": _num((doc.get("entry") or {}).get("price")),
            "stop": _num((doc.get("stop") or {}).get("price")), "stop_method": (doc.get("stop") or {}).get("method"),
            "target": _num((primary or {}).get("price")), "label": strat.get("label"),
            "state": ((doc.get("lifecycle") or {}).get("state"))}


def plan_levels(plan: Dict[str, Any], direction: Optional[str]) -> Optional[Dict[str, Any]]:
    """The plan's stop and target as the levels of a position, only when they can apply: a price-level plan (cash or futures,
    or a structure with a stop on the underlying), a direction that AGREES with the position, and a stop on the right side of
    the entry. Otherwise None — a plan that points the other way is a conflict to report, not a level to borrow."""
    if direction not in ("long", "short"):
        return None
    if plan.get("direction") != {"long": "bullish", "short": "bearish"}[direction]:
        return None
    if not (plan.get("segment") in ("cash", "equity", "futures") or plan.get("stop_method") == "underlying"):
        return None
    stop, target, entry = plan.get("stop"), plan.get("target"), plan.get("entry")
    if stop is None:
        return None
    sign = 1 if direction == "long" else -1
    if entry is not None and (entry - stop) * sign <= 0:
        return None
    if target is not None and entry is not None and (target - entry) * sign <= 0:
        target = None
    return {"_id": f"plan|{plan.get('plan_id')}", "stop": stop, "target": target, "trail_pct": None,
            "updated_at": plan.get("created_at"), "_plan_id": plan.get("plan_id")}


# ── the analysed book ────────────────────────────────────────────────────────

def _row_index(rows: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any], List[Dict[str, Any]]]:
    idx: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
    for r in rows:
        idx.setdefault((r["_account_id"], r.get("symbol")), []).append(r)
    return idx


def _row_of(leg: Dict[str, Any], idx: Dict[Tuple[Any, Any], List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The broker row behind a group leg: same account and broker code, and where one code names several contracts (ICICI's
    stock code covers the share, the future and every option), the same instrument, strike and expiry."""
    cands = idx.get((leg.get("account_id"), leg.get("broker_code")), [])
    if len(cands) == 1:
        return cands[0]

    def same(r: Dict[str, Any]) -> bool:
        kind = r.get("instrument_type") or ("EQ" if str(r.get("segment") or "equity") != "fno" else None)
        if kind and leg.get("instrument") and kind != leg["instrument"]:
            return False
        if _num(r.get("strike")) and leg.get("strike") and abs(_num(r["strike"]) - leg["strike"]) > 1e-6:
            return False
        return not (r.get("expiry") and leg.get("expiry") and str(r["expiry"])[:10] != leg["expiry"])
    return next((r for r in cands if same(r)), None)


def _annotate(groups: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> None:
    """Put each row's P&L basis, its state (live read or stored) and its own price/P&L as read onto the group's legs."""
    idx = _row_index(rows)
    for g in groups:
        states = set()
        for leg in g["legs"]:
            r = _row_of(leg, idx) or {}
            leg["pnl_basis"] = r.get("_pnl_basis", PNL_BROKER)
            leg["state"] = r.get("_state", "live")
            leg["ltp0"], leg["pnl0"] = leg.get("ltp"), leg.get("pnl_rs")
            if leg["pnl_basis"] == PNL_NONE:
                leg["pnl_rs"] = None
            states.add(leg["state"])
        g["state"] = "mixed" if len(states) > 1 else (next(iter(states)) if states else "live")
        _sum_pnl(g)


def _sum_pnl(g: Dict[str, Any]) -> None:
    pnls = [l.get("pnl_rs") for l in g["legs"]]
    g["pnl_rs"] = analytics.r2(sum(pnls)) if g["legs"] and all(p is not None for p in pnls) else None
    bases = {l.get("pnl_basis") for l in g["legs"]}
    g["pnl_source"] = PNL_BROKER if bases <= {PNL_BROKER} else (PNL_MARKED if bases <= {PNL_MARKED} else "mixed")


def structure_key(rows: List[Dict[str, Any]], accounts: List[Dict[str, Any]]) -> str:
    states = sorted((a["account_id"], a["state"]) for a in accounts)
    return f"{store.structure_hash(rows)}|{states}"


async def analyse(request: Any, db: Any, user_id: str, accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The broker groups of the book (one per NSE underlying, plus a group of rows that could not be named), each annotated
    with its legs' P&L basis and state. Levels: the user's own, else the plan they recorded when it points the same way."""
    rows = prepared_rows(accounts)
    if not rows:
        return []
    levels_by_u = await store.read_levels(db, user_id)
    named = [(symbols.normalise(r, r["_broker"]), r) for r in rows]
    unders = sorted({c.underlying for c, _ in named if c.mapped})
    live_rows = any(r["_state"] == "live" for r in rows)
    quotes = await service.underlying_quotes(unders) if (unders and live_rows) else {"quotes": {}, "source": None}
    groups = await service.broker_groups(request, db, user_id, rows, quotes, levels_by_u)
    for g in groups:
        g["stop_dir"] = stop_direction(g)
        reflag(g)
    # A group the user set no levels for borrows the plan they recorded, when it points the same way as the position.
    want = [g for g in groups if g["kind"] != "unmapped" and not g.get("levels")]
    if want:
        plans = await plans_for(db, user_id, [g["underlying"] for g in want])
        extra: Dict[str, Dict[str, Any]] = {}
        for g in want:
            plan = plans.get(g["underlying"])
            lv = plan_levels(plan, g.get("stop_dir")) if plan else None
            g["plan"] = plan
            if lv:
                extra[g["underlying"]] = lv
        if extra:
            sub = [r for c, r in named if c.mapped and c.underlying in extra]
            redo = await service.broker_groups(request, db, user_id, sub, quotes, {**levels_by_u, **extra})
            by_u = {g["underlying"]: g for g in redo if g["kind"] != "unmapped"}
            for i, g in enumerate(groups):
                if g["underlying"] in by_u and g["underlying"] in extra:
                    new = by_u[g["underlying"]]
                    new["plan"], new["stop_dir"] = g.get("plan"), g.get("stop_dir")
                    if new.get("levels"):
                        new["levels"] = {**new["levels"], "set_by": "plan", "plan_id": extra[g["underlying"]]["_plan_id"]}
                    reflag(new)
                    groups[i] = new
    for g in groups:
        g.setdefault("plan", None)
    _annotate(groups, rows)
    for g in groups:
        g["quote_source"] = quotes.get("source")
    return groups


async def build(request: Any, db: Any, user_id: str, *, use_cache: bool = False) -> Dict[str, Any]:
    """{hub, accounts, groups, quotes}. With `use_cache` a book whose rows and account states are unchanged since a build of at
    most ANALYSIS_TTL_S ago reuses that analysis (the live ticks); otherwise it is worked out again."""
    st = await read_accounts(request, db, user_id)
    accounts = st["accounts"]
    key = structure_key(prepared_rows(accounts), accounts)
    hit = _ANALYSIS.get(user_id)
    if use_cache and hit and hit[1] == key and _mono() - hit[0] < ANALYSIS_TTL_S:
        groups = deepcopy(hit[2])
        # Prices and P&L as of the newest read, over the cached analysis.
        _refresh_legs(groups, prepared_rows(accounts))
    else:
        groups = await analyse(request, db, user_id, accounts)
        _ANALYSIS[user_id] = (_mono(), key, deepcopy(groups))
    return {"hub": st["hub"], "accounts": accounts, "groups": groups}


def _refresh_legs(groups: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> None:
    """The cached analysis, with each leg's price and P&L taken from the newest read of the same position."""
    idx = _row_index(rows)
    for g in groups:
        for leg in g["legs"]:
            r = _row_of(leg, idx)
            if not r:
                continue
            leg["ltp"] = _num(r.get("last_price"))
            leg["pnl_rs"], leg["pnl_basis"], leg["state"] = r["pnl"], r["_pnl_basis"], r["_state"]
            leg["ltp0"], leg["pnl0"], leg["read_at"] = leg["ltp"], leg["pnl_rs"], r["_read_at"]
            if leg["pnl_basis"] == PNL_NONE:
                leg["pnl_rs"] = None
        _sum_pnl(g)


# ── live marks ───────────────────────────────────────────────────────────────

def stop_direction(g: Dict[str, Any]) -> Optional[str]:
    """Which way the user's stop faces. A stop is a level of the UNDERLYING, so a group that holds shares or a future is long or
    short by those (a share position bought with a put under it is long, though the put's delta can outweigh the shares');
    a group of options only is long or short by its net delta (analytics.analyse)."""
    net = sum(num_ for num_ in (_num(l.get("quantity")) for l in g.get("legs") or [] if l.get("instrument") in ("EQ", "FUT")) if num_)
    if net:
        return "long" if net > 0 else "short"
    d = (g.get("analytics") or {}).get("direction")
    return d if d in ("long", "short") else None


def reflag(g: Dict[str, Any]) -> None:
    """Distance to the stop and target, and the warnings that depend on them, at the group's current spot (pure arithmetic on
    the group's own spot, stop direction and levels; same rule as analytics.analyse)."""
    a = g.get("analytics")
    if not a:
        return
    spot, lv = (g.get("price") or {}).get("spot"), g.get("levels")
    d = {"long": 1, "short": -1}.get(g.get("stop_dir") or "")
    keep = [w for w in g["warnings"] if w["code"] not in ("near_stop", "stop_breached", "target_reached")]
    a["distance_to_stop_pct"] = a["distance_to_target_pct"] = None
    if not spot or not lv or not d:
        g["warnings"] = keep
        return
    stop, target = lv.get("effective_stop"), lv.get("target")
    if stop:
        dist = (spot - stop) / spot * 100 * d
        a["distance_to_stop_pct"] = analytics.r2(dist)
        if dist < 0:
            keep.append({"code": "stop_breached", "tone": "danger", "text": f"The price ({spot:,.2f}) is past your stop ({stop:,.2f})."})
        elif dist <= analytics.NEAR_STOP_PCT:
            keep.append({"code": "near_stop", "tone": "amber", "text": f"{dist:.2f}% from your stop ({stop:,.2f})."})
    if target:
        dt = (target - spot) / spot * 100 * d
        a["distance_to_target_pct"] = analytics.r2(dt)
        if dt <= 0:
            keep.append({"code": "target_reached", "tone": "mint", "text": f"The price has reached your target ({target:,.2f})."})
    g["warnings"] = keep


def apply_marks(groups: List[Dict[str, Any]], quotes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The groups with Kite's live price over every SHARE leg read from a live account (a stored read is never re-priced):
    the leg's price is the live one and its P&L the broker's figure moved by quantity × the price change. Futures and options
    legs keep the broker's price of their last read. The group's spot, distance to the stop and warnings follow. Pure."""
    if quotes.get("source") != "kite_live":
        return groups
    out = deepcopy(groups)
    by = quotes.get("quotes") or {}
    for g in out:
        q = by.get(g["underlying"])
        live = _num((q or {}).get("ltp"))
        if live is None or g["kind"] == "unmapped" or g.get("state") == "snapshot":
            continue
        for leg in g["legs"]:
            if leg.get("instrument") != "EQ" or leg.get("state") != "live":
                continue
            base, qty = leg.get("ltp0"), leg.get("quantity")
            leg["ltp"], leg["ltp_source"], leg["ltp_at"] = live, "Kite live", quotes.get("as_of")
            if leg.get("pnl0") is not None and base is not None and qty:
                leg["pnl_rs"] = analytics.r2(leg["pnl0"] + qty * (live - base))
                leg["pnl_basis"] = PNL_LIVE if leg.get("pnl_basis") == PNL_BROKER else leg.get("pnl_basis")
        g["price"] = {**g["price"], "spot": live, "source": quotes.get("source"), "as_of": quotes.get("as_of")}
        _sum_pnl(g)
        reflag(g)
    return out
