"""The engine's inputs: each source a rule may read, with its own as-of date. Read-only.

Market inputs are the same for every user and are cached in-process for MARKET_TTL seconds; they are read through the
visual-answer readers (services/copilot_visual/readers.py), so a card and the answer it opens read the same source.
Personal inputs are read per user on each evaluation.

    market_snapshot       DaaS /snapshots/market (prices_as_of / as_of_date)
    fii_dii               DaaS market-pulse FII/DII (NSE cash), the newest day's FII and DII net
    chain_NIFTY / _BANKNIFTY  routes.fno.chain (NSE F&O bhavcopy): summary as_of, nearest expiry, expected move
    positional_watchlist  routes.positional.get_watchlist: scan date, confirmed-breakout count
    scan_snapshot         routes.positional._scan_snapshot + setup_rules: scan date, unusual-volume count
    ai_watchlist          services.ai_watchlist_store.get_day: the AI scanner's newest Top 10 cash + F&O lists
    holdings              Mongo holdings: the user's rows; as of the newest price/upload stamp
    portfolio_rules       routes.insights._deterministic_insights over those holdings (computed, never stored here)
    portfolio_facts       routes.copilot_prompts._build_context (overlap, allocation, plan actions)
    user_symbols          the user's stock holdings and personal watchlists (user_watchlists)
    paper_trades          open desk paper trades (cash) marked at the newest end-of-day close; the desk's own
                          simulate() for the entry status and current stop. Never runs the exit job (no write).
    risk_book             services.risk_book.read: today's paper P&L and the account's limits
    brokers               broker_accounts: which native connections need a reconnect (notices only)

A reader that fails gives an Input with `error` set: the gate then treats it as missing and says so.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MARKET_TTL = 600
READ_TIMEOUT = 12.0

LABELS: Dict[str, str] = {
    "market_snapshot": "Market snapshot",
    "fii_dii": "NSE FII/DII cash flows",
    "chain_NIFTY": "NIFTY option chain (NSE F&O bhavcopy)",
    "chain_BANKNIFTY": "BANKNIFTY option chain (NSE F&O bhavcopy)",
    "positional_watchlist": "Positional scanner",
    "scan_snapshot": "Stock scan (features + NSE bhavcopy)",
    "ai_watchlist": "AI scanner daily list",
    "holdings": "Your holdings",
    "portfolio_rules": "Portfolio checks",
    "portfolio_facts": "Portfolio facts",
    "user_symbols": "Your holdings and watchlists",
    "paper_trades": "Your paper trades",
    "risk_book": "Your paper account",
}
PERSONAL = {"holdings", "portfolio_rules", "portfolio_facts", "user_symbols", "paper_trades", "risk_book"}
MARKET = ("market_snapshot", "fii_dii", "chain_NIFTY", "chain_BANKNIFTY", "positional_watchlist", "scan_snapshot",
          "ai_watchlist")


@dataclass
class Input:
    name: str
    as_of: Optional[str] = None            # ISO date or timestamp of the data itself, never of the read
    value: Any = None
    facts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    empty: bool = False                    # read fine, nothing there (no trades, no holdings)

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)

    def public(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "as_of": self.as_of, "error": self.error, "empty": self.empty}


def _why(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return f"no answer within {READ_TIMEOUT:g} s"
    return f"{type(exc).__name__}: {str(exc)[:140]}"


async def _guard(name: str, fn: Callable[[], Awaitable[Input]]) -> Input:
    try:
        return await asyncio.wait_for(fn(), timeout=READ_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — a source that fails is reported missing, never guessed
        logger.info("suggestions: input %s unavailable: %s", name, _why(exc))
        return Input(name=name, error=_why(exc))


# ── market (shared, cached) ──────────────────────────────────────────────────

_cache: Dict[str, Any] = {}


def clear_market_cache() -> None:
    _cache.clear()


async def _market_snapshot(request: Any) -> Input:
    from services.copilot_visual import readers as rd
    snap = await rd.market_snapshot()
    return Input("market_snapshot", as_of=snap.get("prices_as_of") or snap.get("as_of_date"))


async def _fii_dii(request: Any) -> Input:
    from services.copilot_visual import readers as rd
    from services.copilot_visual.payload import crore, iso_day
    flows = await rd.fii_dii(10)
    days = sorted((d for d in flows.get("daily") or [] if isinstance(d, dict) and iso_day(d.get("date"))),
                  key=lambda d: iso_day(d["date"]))
    last = days[-1] if days else {}
    as_of = iso_day(last.get("date")) or iso_day(flows.get("as_of"))
    return Input("fii_dii", as_of=as_of, facts={"fii_net": crore(last.get("fii_net")) or "not reported",
                                                 "dii_net": crore(last.get("dii_net")) or "not reported"})


def _chain_reader(sym: str) -> Callable[[Any], Awaitable[Input]]:
    async def read(request: Any) -> Input:
        from services.copilot_visual import readers as rd
        from services.copilot_visual.payload import day_text, iso_day
        ch = await rd.chain(request, sym)
        s = (ch or {}).get("summary") or {}
        return Input(f"chain_{sym}", as_of=iso_day(s.get("as_of")),
                     facts={"expiry": day_text(s.get("expiry")) or "the nearest expiry"})
    return read


async def _positional_watchlist(request: Any) -> Input:
    from services.copilot_visual import readers as rd
    from services.copilot_visual.payload import iso_day
    wl = await rd.positional_watchlist(request)
    if not isinstance(wl, dict) or not iso_day(wl.get("as_of_date")):
        return Input("positional_watchlist", error=(wl or {}).get("_reason") if isinstance(wl, dict) else "no scan date")
    items = (wl.get("buckets") or {}).get("breakout_confirmed") or []
    return Input("positional_watchlist", as_of=iso_day(wl["as_of_date"]), facts={"count": len(items)})


async def _scan_snapshot(request: Any) -> Input:
    from datetime import date as _date
    from services.copilot_visual import readers as rd
    from services.copilot_visual.payload import iso_day
    from services.positional_engine import setup_rules
    snap = await rd.scan_snapshot()
    as_of = iso_day((snap or {}).get("as_of"))
    if not as_of:
        return Input("scan_snapshot", error="the scan has no date")
    ev = setup_rules.evaluate(snap.get("rows") or [], _date.fromisoformat(as_of))
    return Input("scan_snapshot", as_of=as_of, facts={"count": len(ev["categories"]["unusual_volume"]["symbols"])})


async def _ai_watchlist(request: Any) -> Input:
    from services import ai_watchlist_store
    day = await ai_watchlist_store.get_day(None)
    if not day:
        return Input("ai_watchlist", empty=True)
    return Input("ai_watchlist", as_of=day.get("list_date"), value=day)


MARKET_READERS: Dict[str, Callable[[Any], Awaitable[Input]]] = {
    "market_snapshot": _market_snapshot,
    "fii_dii": _fii_dii,
    "chain_NIFTY": _chain_reader("NIFTY"),
    "chain_BANKNIFTY": _chain_reader("BANKNIFTY"),
    "positional_watchlist": _positional_watchlist,
    "scan_snapshot": _scan_snapshot,
    "ai_watchlist": _ai_watchlist,
}


async def market(request: Any, names: List[str], *, fresh_read: bool = False) -> Dict[str, Input]:
    """The market inputs named, from the in-process cache when younger than MARKET_TTL (a failed read is not cached)."""
    now = time.monotonic()
    out: Dict[str, Input] = {}
    todo = []
    for n in names:
        hit = None if fresh_read else _cache.get(n)
        if hit and hit[0] > now:
            out[n] = hit[1]
        else:
            todo.append(n)
    got = await asyncio.gather(*(_guard(n, lambda n=n: MARKET_READERS[n](request)) for n in todo))
    for n, inp in zip(todo, got):
        out[n] = inp
        if not inp.error:
            _cache[n] = (now + MARKET_TTL, inp)
    return out


# ── personal ─────────────────────────────────────────────────────────────────

HOLDING_FIELDS = {"_id": 0, "name": 1, "ticker": 1, "isin": 1, "asset_type": 1, "category": 1, "sector": 1,
                  "quantity": 1, "buy_price": 1, "current_price": 1, "source": 1, "broker": 1, "broker_account_id": 1,
                  "price_updated_at": 1, "uploaded_at": 1, "created_at": 1}
STOCK_TYPES = ("stock", "equity")


def _stamp(h: Dict[str, Any]) -> Optional[str]:
    stamps = [str(h[k]) for k in ("price_updated_at", "uploaded_at", "created_at") if h.get(k)]
    return max(stamps) if stamps else None


async def _holdings(db: Any, uid: str) -> Input:
    rows = await db.holdings.find({"user_id": uid}, HOLDING_FIELDS).to_list(2000)
    rows = [r for r in rows if float(r.get("quantity") or 0) > 0]
    if not rows:
        return Input("holdings", empty=True, value=[])
    stamps = [s for s in (_stamp(r) for r in rows) if s]
    value = sum(float(r.get("quantity") or 0) * float(r.get("current_price") or 0) for r in rows)
    return Input("holdings", as_of=max(stamps) if stamps else None, value=rows,
                 facts={"count": len(rows), "value_rs": round(value, 2)})


async def _portfolio_rules(uid: str, holdings: Input) -> Input:
    """The insights route's deterministic rules over the same holdings, computed and not stored (the route stores)."""
    if holdings.empty or holdings.error:
        return Input("portfolio_rules", empty=holdings.empty, error=holdings.error, value=[])
    from deps import db
    from services.equity_sectors import enrich_holdings_with_sectors
    from routes.insights import _deterministic_insights
    from services import rules_config as _rc
    rows = [{**r, "name": r.get("name") or r.get("ticker") or "", "quantity": float(r.get("quantity") or 0),
             "current_price": float(r.get("current_price") or 0), "buy_price": float(r.get("buy_price") or 0)}
            for r in holdings.value]
    rows = enrich_holdings_with_sectors(rows)
    deep = await db.portfolio_analysis_deep.find_one({"user_id": uid}, {"_id": 0})
    cache = await db.allocation_analysis_cache.find_one({"user_id": uid}, {"_id": 0})
    try:
        cfg = await _rc.get_config()
    except Exception:  # noqa: BLE001 — the route falls back the same way
        cfg = _rc.DEFAULTS
    intelligence = None
    try:
        from services.portfolio_intelligence import compute_portfolio_intelligence
        intelligence = await compute_portfolio_intelligence(uid)
    except Exception as exc:  # noqa: BLE001 — the route goes on without it, as here
        logger.info("suggestions: portfolio intelligence unavailable: %s", _why(exc))
    analysis = _deterministic_insights(rows, deep, (cache or {}).get("data"), cfg, intelligence)
    return Input("portfolio_rules", as_of=holdings.as_of, value=analysis.get("insights") or [])


async def _portfolio_facts(uid: str, holdings: Input) -> Input:
    if holdings.empty or holdings.error:
        return Input("portfolio_facts", empty=holdings.empty, error=holdings.error, value={})
    from routes.copilot_prompts import _build_context
    ctx = await _build_context(uid)
    return Input("portfolio_facts", as_of=holdings.as_of, value=ctx)


async def _user_symbols(db: Any, uid: str, holdings: Input) -> Input:
    where: Dict[str, str] = {}
    for h in holdings.value or []:
        t = (h.get("ticker") or "").strip().upper()
        if t and (h.get("asset_type") or "").lower() in STOCK_TYPES:
            where.setdefault(t, "holdings")
    lists = await db.user_watchlists.find({"user_id": uid}, {"_id": 0, "symbols": 1}).to_list(50)
    for wl in lists:
        for s in wl.get("symbols") or []:
            sym = (s.get("symbol") if isinstance(s, dict) else s) or ""
            if sym.strip():
                where.setdefault(sym.strip().upper(), "watchlist")
    # The user's own lists are current by definition: stamped now.
    return Input("user_symbols", as_of=datetime.now(timezone.utc).isoformat(), value=where, empty=not where)


async def _paper_trades(db: Any, uid: str) -> Input:
    from services import desk_trading as desk
    from services.copilot_visual.payload import iso_day
    docs = await db[desk.TRADES].find({"user_id": uid, "status": "open"}).to_list(desk.MAX_OPEN_TRADES * 2)
    docs = [d for d in docs if d.get("kind") in (None, "cash")]
    if not docs:
        return Input("paper_trades", empty=True, value=[])
    bars, errors = await desk.fetch_bars_many(desk.fetch_starts(docs, "opened_at"))
    trades: List[Dict[str, Any]] = []
    for d in docs:
        sym = d["symbol"]
        mark, err = desk.mark_for(sym, bars, errors)
        sim = desk.simulate(d, bars.get(sym) or []) if not err else None
        trades.append({
            "trade_id": d["_id"], "symbol": sym, "entry": float(d["entry_price"]),
            "stop": float((sim or {}).get("current_stop") or d["stop_price"]),
            "target": float(d["target_price"]) if d.get("target_price") is not None else None,
            "last": float(mark["close"]) if mark and mark.get("close") is not None else None,
            "last_date": iso_day(mark["date"]) if mark else None,
            "entered": (sim or {}).get("entry_status") in desk.ENTERED,
            "exited": bool((sim or {}).get("exit")),
            "mark_error": err,
        })
    dates = [t["last_date"] for t in trades if t["last_date"]]
    return Input("paper_trades", as_of=max(dates) if dates else None, value=trades, facts={"count": len(trades)})


async def _risk_book(db: Any, uid: str, paper: Input) -> Input:
    """Read only when the user has paper trades; otherwise there is no day to measure."""
    if paper.empty:
        return Input("risk_book", empty=True)
    from services import risk_book as rb
    book = await rb.read(db, uid)
    return Input("risk_book", as_of=(book.get("equity") or {}).get("marks_as_of"), value=book)


async def _brokers(db: Any, uid: str) -> List[Dict[str, Any]]:
    from services.brokers import sessions
    from services.brokers.hub_reads import display_name
    docs = await db.broker_accounts.find({"user_id": uid}, {"_id": 0, "broker": 1, "native": 1, "status": 1,
                                                           "session_expires_at": 1, "session_ended_reason": 1,
                                                           "last_sync_at": 1, "label": 1}).to_list(20)
    out = []
    for d in docs:
        pub = sessions.public_fields(d)
        out.append({"broker": d.get("broker"), "name": display_name(d.get("broker")), "native": pub["native"],
                    "needs_reconnect": pub["needs_reconnect"], "last_sync_at": d.get("last_sync_at")})
    return out


async def personal(db: Any, uid: str) -> Dict[str, Any]:
    """Every personal input, plus `brokers` (a plain list, used for notices)."""
    holdings = await _guard("holdings", lambda: _holdings(db, uid))
    paper = await _guard("paper_trades", lambda: _paper_trades(db, uid))
    rules, facts, symbols, book = await asyncio.gather(
        _guard("portfolio_rules", lambda: _portfolio_rules(uid, holdings)),
        _guard("portfolio_facts", lambda: _portfolio_facts(uid, holdings)),
        _guard("user_symbols", lambda: _user_symbols(db, uid, holdings)),
        _guard("risk_book", lambda: _risk_book(db, uid, paper)))
    try:
        brokers = await _brokers(db, uid)
    except Exception as exc:  # noqa: BLE001 — no broker notice is better than a wrong one
        logger.info("suggestions: broker accounts unreadable: %s", _why(exc))
        brokers = []
    return {"holdings": holdings, "portfolio_rules": rules, "portfolio_facts": facts, "user_symbols": symbols,
            "paper_trades": paper, "risk_book": book, "brokers": brokers}
