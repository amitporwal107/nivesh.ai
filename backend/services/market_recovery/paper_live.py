"""Market Recovery › live paper trades (docs/market_recovery/DESIGN.md §10 C and D; owner, 4 Nov 2026).

The owner asked to paper-trade the recovery candidates with "real time quotes and … a real time p&l for each valid trade
setup", and chose live entries AND live exits for these trades. The desk's paper engine marks and closes on end-of-day bars
only; this module adds, for trades tagged market_recovery only:

  * live marks and P&L      shares and underlyings from services/kite_live_feed/day_quote.day_quotes (live Kite quote in the
                            session, the saved Kite close after it); option / future legs from Kite REST quote() for the named
                            contracts (`option_quotes`, the logic of POST /api/live/fno-quotes without the HTTP request)
  * live exits              shares: live price ≤ the trade's Stop loss → closed at that price, reason `stop_live`; ≥ its
                            Target 1 → `target_live`. Structures: the underlying's live price through `stop_underlying` /
                            `target_underlying` (by direction) → every leg closed at its live price. Only with LIVE quotes
                            (source kite_live, in the session); a leg without a live quote blocks the close and is flagged.
                            Never a fallback to an older price (the owner's no-stale rule). The desk's end-of-day exits still
                            apply on later sessions.

Closes go through the desk's own writers (desk_trading.close_trade, desk_strategy_trades.close_strategy_trade), so the paper
account, the lifecycle events and the journal are exactly as for any other close. `run_live_exits` is run every minute in market
hours by services/mf_scheduler.py (one leader process) and on every GET /api/market-recovery/paper-trades/live. Reads quotes
only; nothing is sent to a broker.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from services import desk_trading as desk
from services import desk_strategy_trades as strat

logger = logging.getLogger(__name__)

SOURCE_KIND = "market_recovery"
EXIT_STOP, EXIT_TARGET = "stop_live", "target_live"
INSTRUMENTS_TTL_S = 6 * 3600.0           # Kite's NFO instrument list, read once per process per 6 h (a multi-MB download)
QuoteReader = Callable[..., Awaitable[Dict[str, Any]]]


# ── quotes (the coordinator's interface for paper_plan.py) ───────────────────────────────────────────────────────────

async def stock_quotes(symbols: Sequence[str]) -> Dict[str, Any]:
    """services/kite_live_feed/day_quote.day_quotes(symbols), unchanged: {"source": "kite_live" | "kite_close" | None,
    "day", "as_of", "quotes": {SYMBOL: {ltp, open, high, low, close (= previous close), volume, ...}}, "why"}."""
    from services.kite_live_feed import day_quote
    return await day_quote.day_quotes(list(symbols))


_instruments: Dict[str, Any] = {"at": float("-inf"), "map": None}
_instruments_lock = asyncio.Lock()


async def _nfo_instruments(kite: Any) -> Dict[Tuple[str, str, Optional[float], str], str]:
    from services.kite_live_feed import fno_quotes as fq
    async with _instruments_lock:
        if _instruments["map"] is not None and time.monotonic() - _instruments["at"] < INSTRUMENTS_TTL_S:
            return _instruments["map"]
        rows = await asyncio.to_thread(kite.instruments, "NFO")
        _instruments.update(map=fq.index_instruments(rows), at=time.monotonic())
        return _instruments["map"]


async def option_quotes(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Live premiums for named F&O contracts — the answer of POST /api/live/fno-quotes (routes/live_quotes.py) without the
    HTTP request: {"available", "reason", "quotes": {"<leg index>": {key, last_price, previous_close?, oi?, volume?,
    last_trade_time?, exchange_timestamp?}}, "unresolved": [{index, reason}], "as_of", "source", "read_only"}.

    `legs`: services/kite_live_feed/fno_quotes.resolve's format — {"underlying", "expiry" (YYYY-MM-DD), "strike",
    "kind" ("option" | "future"), "option_type" ("call" | "put" | "CE" | "PE")}. Up to fq.MAX_LEGS per call (more are
    read in chunks). Never raises: no feed, no token or a Kite failure answers available false with the reason and no prices.
    Two differences from the route, both read-only: the platform token is reloaded into this process first (a Kite REST
    call outside the feed leader otherwise carries a stale token), and Kite's NFO instrument list is cached for 6 hours."""
    from services import market_freshness
    from services.kite_live_feed import config as cfg
    from services.kite_live_feed import fno_quotes as fq
    from services.kite_live_feed import gateway as gw
    from services.kite_live_feed import platform_token as pt
    from services.kite_live_feed.feed import get_feed

    def off(reason: str) -> Dict[str, Any]:
        return {"available": False, "reason": reason, "quotes": {}, "unresolved": [], "source": None, "read_only": True}

    legs = list(legs or [])
    if not legs:
        return off("no legs were named")
    try:
        if not cfg.enabled():
            return off("the live feed is disabled")
        feed = get_feed()
        token = await pt.token_status(feed.db)
        if not token.get("stored") or token.get("expired"):
            return off("no Kite access token is stored for the platform feed")
        await pt.refresh_cache(feed.db)
        key, access = cfg.get_api_key(), cfg.get_token()
        if not key or not access:
            return off("the Kite API key or access token is not configured")
        kite = gw.default_kite_factory(key, access)
        instruments = await _nfo_instruments(kite)
    except Exception as e:  # noqa: BLE001 — an unreachable upstream is reported, never guessed around
        logger.warning("market recovery option quotes: instruments unavailable (%s)", type(e).__name__)
        return off(f"the contract list could not be read ({type(e).__name__})")
    keys, unresolved = fq.resolve(legs, instruments)
    if not keys:
        return {"available": False, "reason": "none of the legs named a listed contract", "quotes": {}, "unresolved": unresolved,
                "source": "kite", "read_only": True}
    priced: Dict[int, Dict[str, Any]] = {}
    try:
        floor = (await market_freshness.window()).floor
        names = sorted(set(keys.values()))
        answer: Dict[str, Any] = {}
        for i in range(0, len(names), fq.MAX_LEGS):
            answer.update(await asyncio.to_thread(kite.quote, names[i:i + fq.MAX_LEGS]) or {})
        priced = fq.prices_from(answer, keys, floor=floor)
    except Exception as e:  # noqa: BLE001
        logger.warning("market recovery option quotes: quote() failed (%s)", type(e).__name__)
        return off(f"the quote request failed ({type(e).__name__})")
    return {
        "available": bool(priced),
        "reason": None if priced else "None of these contracts has traded today or in the previous session",
        "quotes": {str(i): v for i, v in priced.items()},
        "unresolved": unresolved,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "kite REST quote (live when the market is open; the last traded price otherwise)",
        "read_only": True,
    }


# ── which trades ──────────────────────────────────────────────────────────────────────────────────────────────────────

def is_recovery_trade(doc: Dict[str, Any]) -> bool:
    if doc.get("kind") == strat.KIND:
        refs = (doc.get("signal") or {}).get("source_refs") or []
        return any(isinstance(r, dict) and r.get("kind") == SOURCE_KIND for r in refs)
    return ((doc.get("source") or {}).get("kind")) == SOURCE_KIND


def _ist_day(now: datetime) -> date:
    return now.astimezone(desk.IST).date()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if v == v else None


def _r(x: Optional[float], dp: int = 2) -> Optional[float]:
    return None if x is None else round(x + 0.0, dp)


# ── marks (pure once the quotes are read) ─────────────────────────────────────────────────────────────────────────────

def _fq_leg(trade: Dict[str, Any], leg: Dict[str, Any]) -> Dict[str, Any]:
    return {"underlying": trade.get("underlying") or trade.get("symbol"), "expiry": leg.get("expiry"), "strike": leg.get("strike"),
            "kind": leg.get("kind"), "option_type": leg.get("option_type")}


def _stock_ltp(stock: Dict[str, Any], symbol: Optional[str]) -> Optional[float]:
    q = (stock.get("quotes") or {}).get(symbol or "") if isinstance(stock, dict) else None
    return _num((q or {}).get("ltp"))


def mark(trades: Sequence[Dict[str, Any]], stock: Dict[str, Any], options: Dict[str, Any],
         leg_index: Dict[Tuple[str, int], int]) -> List[Dict[str, Any]]:
    """Each trade with its live marks: {trade, live, legs: [mark | None], pnl_rs, risk_rs, flags}. `leg_index` maps
    (trade id, leg i) → the index of that leg in the option_quotes request."""
    oq = (options or {}).get("quotes") or {}
    out = []
    for t in trades:
        flags: List[str] = []
        if t.get("kind") == strat.KIND:
            und = _stock_ltp(stock, t.get("underlying") or t.get("symbol"))
            marks: List[Optional[float]] = []
            for i, leg in enumerate(t.get("legs") or []):
                if leg.get("kind") == "cash":
                    marks.append(und)
                else:
                    q = oq.get(str(leg_index.get((t["_id"], i), -1)))
                    marks.append(_num((q or {}).get("last_price")))
            if any(m is None for m in marks):
                flags.append("no_live_quote")
            pnl = None if any(m is None for m in marks) else round(sum(strat._leg_pnl(l, m) for l, m in zip(t["legs"], marks)), 2)
            risk = _num(t.get("paper_reserved_rs"))
            if not risk:
                try:
                    risk = _num(strat.exposure_rs(t))
                except Exception:  # noqa: BLE001 — a bound that cannot be worked out leaves the % unknown
                    risk = None
            out.append({"trade": t, "live": und, "legs": marks, "pnl_rs": pnl, "risk_rs": risk, "flags": flags})
        else:
            ltp = _stock_ltp(stock, t.get("symbol"))
            if ltp is None:
                flags.append("no_live_quote")
            entry, qty, stop = float(t["entry_price"]), int(t["quantity"]), _num(t.get("stop_price"))
            pnl = None if ltp is None else round((ltp - entry) * qty, 2)
            risk = None if stop is None else round((entry - stop) * qty, 2)
            out.append({"trade": t, "live": ltp, "legs": [], "pnl_rs": pnl, "risk_rs": risk, "flags": flags})
    return out


def exit_for(m: Dict[str, Any], *, live: bool) -> Optional[Dict[str, Any]]:
    """The live exit a marked open trade calls for, or None: {"reason", "price" (shares) | None, "note"}. Only with live
    quotes; a structure needs every leg's live price."""
    t = m["trade"]
    if not live or t.get("status") != "open" or m["live"] is None:
        return None
    px = m["live"]
    if t.get("kind") == strat.KIND:
        if any(x is None for x in m["legs"]):
            return None
        stop, target = _num(t.get("stop_underlying")), _num(t.get("target_underlying"))
        up = t.get("direction") != "bearish"
        if t.get("direction") == "neutral":
            return None                              # no underlying levels for a neutral structure
        hit_stop = stop is not None and (px <= stop if up else px >= stop)
        hit_target = target is not None and (px >= target if up else px <= target)
        if hit_stop:
            return {"reason": EXIT_STOP, "price": None,
                    "note": f"The underlying's live Kite price {px:,.2f} reached the plan's Stop loss level ({stop:,.2f}); every leg "
                            f"closed at its live price."}
        if hit_target:
            return {"reason": EXIT_TARGET, "price": None,
                    "note": f"The underlying's live Kite price {px:,.2f} reached the plan's Target 1 level ({target:,.2f}); every "
                            f"leg closed at its live price."}
        return None
    stop, target = _num(t.get("stop_price")), _num(t.get("target_price"))
    if stop is not None and px <= stop:
        return {"reason": EXIT_STOP, "price": px,
                "note": f"The live Kite price {px:,.2f} reached the Stop loss ({stop:,.2f}); closed at the live price."}
    if target is not None and px >= target:
        return {"reason": EXIT_TARGET, "price": px,
                "note": f"The live Kite price {px:,.2f} reached Target 1 ({target:,.2f}); closed at the live price."}
    return None


# ── reads ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

async def read_marks(trades: Sequence[Dict[str, Any]], *, stock_reader: QuoteReader = None,
                     option_reader: QuoteReader = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(marked trades, market) with one stock read and one option read for all the trades given."""
    stock_reader = stock_reader or stock_quotes
    option_reader = option_reader or option_quotes
    symbols = sorted({str(t.get("underlying") or t.get("symbol")) for t in trades if t.get("symbol") or t.get("underlying")})
    fq_legs: List[Dict[str, Any]] = []
    index: Dict[Tuple[str, int], int] = {}
    for t in trades:
        if t.get("kind") != strat.KIND or t.get("status") != "open":
            continue
        for i, leg in enumerate(t.get("legs") or []):
            if leg.get("kind") in ("option", "future"):
                index[(t["_id"], i)] = len(fq_legs)
                fq_legs.append(_fq_leg(t, leg))
    stock = await stock_reader(symbols) if symbols else {"source": None, "quotes": {}, "why": None}
    options = await option_reader(fq_legs) if fq_legs else {"available": False, "reason": None, "quotes": {}}
    market = {"live": stock.get("source") == "kite_live", "source": stock.get("source"), "why": stock.get("why"),
              "as_of": stock.get("as_of"), "day": stock.get("day"),
              "options_live": bool(options.get("available")) if fq_legs else None,
              "options_why": None if not fq_legs else options.get("reason")}
    return mark(trades, stock, options, index), market


async def _close(db, m: Dict[str, Any], ex: Dict[str, Any], now: datetime) -> bool:
    t = m["trade"]
    day = _ist_day(now)
    if t.get("kind") == strat.KIND:
        legs = t["legs"]
        states = [{"mark": mk, "mark_date": day, "mark_basis": "kite_live"} for mk in m["legs"]]
        gross = round(sum(strat._leg_pnl(l, mk) for l, mk in zip(legs, m["legs"])), 2)
        sim = {"legs": states, "gross_pnl_rs": gross, "mfe_rs": t.get("mfe_rs"), "mae_rs": t.get("mae_rs"),
               "observations": t.get("observations"), "held_sessions": t.get("held_sessions"), "flags": [],
               "checked_through": day, "structure_value_per_unit": None, "exit_rules_version": None}
        _, closed = await strat.close_strategy_trade(db, t, exit_reason=ex["reason"], exit_session=day, exit_note=ex["note"],
                                                     sim=sim, now=now, exit_basis="kite_live")
        return closed
    _, closed = await desk.close_trade(db, t, exit_reason=ex["reason"], exit_price=ex["price"], exit_session=day,
                                       exit_note=ex["note"], now=now)
    return closed


async def apply_live_exits(db, marked: List[Dict[str, Any]], market: Dict[str, Any], *, now: Optional[datetime] = None,
                           persist: bool = True) -> List[str]:
    """Close the marked open trades a live exit calls for (ids closed by THIS call). Nothing without live quotes."""
    now = now or desk.utcnow()
    closed: List[str] = []
    for m in marked:
        ex = exit_for(m, live=bool(market.get("live")))
        if ex is None:
            continue
        m["exit"] = ex
        if not persist:
            continue
        try:
            if await _close(db, m, ex, now):
                closed.append(m["trade"]["_id"])
        except Exception as e:  # noqa: BLE001 — one trade's failed close must not stop the others
            logger.exception("market recovery live exit: closing %s failed: %r", m["trade"].get("_id"), e)
    return closed


async def _open_recovery_trades(db, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"status": "open"}
    if user_id is not None:
        query["user_id"] = user_id
    docs = await db[desk.TRADES].find(query).to_list(None)
    return [d for d in docs if is_recovery_trade(d)]


async def run_live_exits(db, *, now: Optional[datetime] = None, stock_reader: QuoteReader = None,
                         option_reader: QuoteReader = None) -> Dict[str, Any]:
    """The scheduler job (every minute, 09:15–15:30 IST): live exits for every user's open market_recovery trades."""
    from services.kite_live_feed import day_quote
    now = now or desk.utcnow()
    if not day_quote.in_session(now):
        return {"skipped": "outside market hours"}
    trades = await _open_recovery_trades(db)
    if not trades:
        return {"open": 0, "closed": []}
    marked, market = await read_marks(trades, stock_reader=stock_reader, option_reader=option_reader)
    closed = await apply_live_exits(db, marked, market, now=now)
    return {"open": len(trades), "closed": closed, "live": market["live"], "why": market["why"]}


# ── the live book (GET /api/market-recovery/paper-trades/live) ────────────────────────────────────────────────────────

def _label(t: Dict[str, Any]) -> str:
    if t.get("kind") == strat.KIND:
        return strat.FAMILIES.get(t.get("family") or "", "Structure")
    return "Shares"


def _row(m: Dict[str, Any]) -> Dict[str, Any]:
    t = m["trade"]
    strategy = t.get("kind") == strat.KIND
    legs = []
    for i, leg in enumerate(t.get("legs") or []):
        mk = m["legs"][i] if i < len(m["legs"]) else None
        legs.append({"action": "Buy" if leg.get("side") == "buy" else "Sell",
                     "instrument": {"option": "Call" if leg.get("option_type") == "call" else "Put", "future": "Future",
                                    "cash": "Shares"}.get(leg.get("kind"), leg.get("kind")),
                     "strike": leg.get("strike"), "expiry": leg.get("expiry"), "lots": leg.get("lots"), "lot_size": leg.get("lot_size"),
                     "entry": leg.get("entry_price"), "live": mk, "pnl_rs": strat._leg_pnl(leg, mk)})
    pnl, risk = m["pnl_rs"], m["risk_rs"]
    return {
        "id": t["_id"], "symbol": t.get("symbol"), "kind": "strategy" if strategy else "shares", "label": _label(t),
        "status": t.get("status"), "opened_at": t.get("opened_at"),
        "quantity": None if strategy else t.get("quantity"),
        "lots": (t.get("legs") or [{}])[0].get("lots") if strategy else None,
        "entry": t.get("reference_price") if strategy else t.get("entry_price"),
        "live": _r(m["live"]),
        "stop": t.get("stop_underlying") if strategy else t.get("stop_price"),
        "target": t.get("target_underlying") if strategy else t.get("target_price"),
        "legs": legs, "pnl_rs": pnl, "risk_rs": risk,
        "pnl_pct": None if pnl is None or not risk else _r(100.0 * pnl / risk),
        "exit": None, "flags": m["flags"], "price_source": t.get("price_source"),
    }


def _closed_row(t: Dict[str, Any]) -> Dict[str, Any]:
    strategy = t.get("kind") == strat.KIND
    pnl = _num(t.get("net_pnl_rs"))
    if pnl is None:
        pnl = _num(t.get("realized_pnl_rs"))
    return {"id": t["_id"], "symbol": t.get("symbol"), "kind": "strategy" if strategy else "shares", "label": _label(t),
            "status": t.get("status"), "opened_at": t.get("opened_at"),
            "quantity": None if strategy else t.get("quantity"),
            "lots": (t.get("legs") or [{}])[0].get("lots") if strategy else None,
            "entry": t.get("reference_price") if strategy else t.get("entry_price"), "live": None,
            "stop": t.get("stop_underlying") if strategy else t.get("stop_price"),
            "target": t.get("target_underlying") if strategy else t.get("target_price"),
            "legs": [], "pnl_rs": pnl, "risk_rs": None, "pnl_pct": None,
            "exit": {"reason": t.get("exit_reason"), "price": t.get("exit_price"), "at": t.get("closed_at"), "note": t.get("exit_note")},
            "flags": [], "price_source": t.get("price_source")}


async def live_book(db, user_id: str, *, now: Optional[datetime] = None, stock_reader: QuoteReader = None,
                    option_reader: QuoteReader = None) -> Dict[str, Any]:
    """The user's market_recovery paper trades (open, and closed today) at live marks, after applying the live exits."""
    now = now or desk.utcnow()
    today = _ist_day(now)
    docs = await db[desk.TRADES].find({"user_id": user_id}).to_list(None)
    docs = [d for d in docs if is_recovery_trade(d)]
    open_docs = [d for d in docs if d.get("status") == "open"]
    marked, market = await read_marks(open_docs, stock_reader=stock_reader, option_reader=option_reader)
    closed_now = await apply_live_exits(db, marked, market, now=now)
    rows = []
    for m in marked:
        if m["trade"]["_id"] in closed_now:
            fresh = await db[desk.TRADES].find_one({"_id": m["trade"]["_id"], "user_id": user_id})
            rows.append(_closed_row(fresh or m["trade"]))
        else:
            rows.append(_row(m))
    for d in docs:
        if d.get("status") != "open" and d["_id"] not in closed_now and d.get("closed_at") and desk.ist_date(d["closed_at"]) == today:
            rows.append(_closed_row(d))
    open_rows = [r for r in rows if r["status"] == "open"]
    closed_rows = [r for r in rows if r["status"] != "open"]
    return {
        "as_of": now.isoformat(), "market": market,
        "trades": rows,
        "totals": {"open_pnl_rs": _r(sum(r["pnl_rs"] for r in open_rows if r["pnl_rs"] is not None)) if open_rows else 0.0,
                   "open_pnl_complete": all(r["pnl_rs"] is not None for r in open_rows),
                   "realised_today_rs": _r(sum(r["pnl_rs"] for r in closed_rows if r["pnl_rs"] is not None)) if closed_rows else 0.0,
                   "open_count": len(open_rows), "closed_today_count": len(closed_rows)},
        "closed_now": closed_now,
        "notes": [
            "Live marks: Kite live quotes in the session (the saved Kite close after it); option legs from Kite quotes of the named "
            "contracts. A trade without a live quote shows no P&L rather than an older price.",
            "Live closes: a live price through the Stop loss or Target 1 closes the trade at that live price (shares) or every leg at "
            "its live price (structures). P&L here is before costs; the closed trade's net P&L includes the desk's cost estimate.",
        ],
    }
