"""GET /api/desk/pnl/exits and POST /api/desk/pnl/exits/seen (docs/paper_pnl_dashboard/EXIT_WATCH.md "API").

The GET reads the book the P&L dashboard reads: paper_pnl.live.read_broker_book, the positions workspace's broker read,
cached 60 s. It uses the stored levels where they exist. A position the watcher has not stored yet gets its level worked
out in memory (`stored: false`).

The GET writes nothing to the exit watch collections or to position_levels. The broker read itself keeps the positions
workspace's snapshot, as the dashboard's own read does.

Price shown, first that applies:
    - the live feed's quote in the session (kite_live);
    - after the session, the saved Kite close (kite_close), unless NSE's end-of-day bar for that day is in, which wins
      (eod);
    - otherwise the latest NSE close (eod).
Alerts fire only in the watcher, on live quotes and on NSE end-of-day bars.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import book as book_mod
from . import rules, runner, store, view

logger = logging.getLogger(__name__)

BARS_TTL_S = 600.0
_BARS: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
PAPER_ACCOUNT_ID = "paper"


async def cached_bars(symbol: str, start: date) -> List[Dict[str, Any]]:
    """End-of-day bars, kept per symbol and start for BARS_TTL_S (the screen refetches every 30 s)."""
    key = (symbol, start.isoformat())
    hit = _BARS.get(key)
    if hit and time.monotonic() - hit[0] < BARS_TTL_S:
        return hit[1]
    bars = await runner.default_bars(symbol, start)
    _BARS[key] = (time.monotonic(), bars)
    return bars


async def read_quotes(symbols: List[str], now: datetime) -> Dict[str, Any]:
    return await runner.default_quotes(symbols, now)


async def read_own_levels(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    return await runner.default_own_levels(db, user_id)


def _price(u: str, got: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    q = (got.get("quotes") or {}).get(u) or {}
    px = book_mod._num(q.get("ltp"))
    if px is not None and px > 0 and got.get("source") == "kite_live":
        return px, "kite_live", q.get("received_at") or got.get("as_of")
    last_day = rules._day(bars[-1]) if bars else None
    if px is not None and px > 0 and got.get("source") == "kite_close":
        if not (last_day and got.get("day") and last_day >= str(got["day"])):
            return px, "kite_close", got.get("as_of")
    if bars:
        return float(bars[-1]["close"]), "eod", last_day
    return None, None, None


def _public_alert(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": d.get("_id"), "at": d.get("at"), "day": d.get("day"), "kind": d.get("kind"), "severity": d.get("severity"),
            "key": d.get("key"), "underlying": d.get("underlying"), "account": d.get("account"), "text": d.get("text"),
            "price": d.get("price"), "level": d.get("level"), "source": d.get("source"), "seen": bool(d.get("seen"))}


def _stored_level(doc: Dict[str, Any], bars: List[Dict[str, Any]], side: str) -> Optional[Dict[str, Any]]:
    """The stored level as a level answer, or None when it cannot stand (no stop, or a series break after its day)."""
    if not doc or book_mod._num(doc.get("stop")) is None:
        return None
    ev = rules.evaluate(bars, side) if bars else {"break_day": None, "support": None}
    if ev.get("break_day") and str(ev["break_day"]) > str(doc.get("day") or ""):
        return None
    return {"stop": doc.get("stop"), "day": doc.get("day"), "atr": doc.get("atr"), "atr_pct": doc.get("atr_pct"),
            "support": ev.get("support") if ev.get("support") is not None else doc.get("support"),
            "history": doc.get("history") or [], "why": None}


async def build(request: Any, db, uid: str, account: str = "ALL", *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The GET body. ValueError("invalid_account") for an account id that is not one of the user's broker accounts."""
    from services.paper_pnl import live
    now = now or datetime.now(timezone.utc)
    bb = await live.read_broker_book(request, db, uid)
    accts = live.accounts(bb, now)
    if account not in ("ALL", PAPER_ACCOUNT_ID) and account not in {a["account_id"] for a in accts}:
        raise ValueError("invalid_account")
    rows = [] if account == PAPER_ACCOUNT_ID else [r for r in bb.rows if account == "ALL" or str(r.get("_account_id")) == account]
    watched, not_watched = book_mod.group(rows)
    unders = sorted({w.underlying for w in watched})
    today = runner.ist_day(now)
    got: Dict[str, Any] = {}
    if unders:
        try:
            got = await read_quotes(unders, now) or {}
        except Exception as e:  # noqa: BLE001 — prices fall back to the NSE close, labelled so
            logger.warning("exit_watch: quotes unreadable (%s)", type(e).__name__)
    bars_by: Dict[str, List[Dict[str, Any]]] = {}
    bar_errors: Dict[str, str] = {}
    for u in unders:
        try:
            bars_by[u] = await cached_bars(u, today - timedelta(days=runner.BARS_LOOKBACK_DAYS))
        except Exception as e:  # noqa: BLE001 — that position shows NO_STOP with the reason
            logger.warning("exit_watch: bars for %s unreadable (%s)", u, type(e).__name__)
            bar_errors[u] = type(e).__name__
    stored = await store.read_levels(db, uid)
    try:
        own = await read_own_levels(db, uid) or {}
    except Exception as e:  # noqa: BLE001 — the rule's stop is shown instead, and that is logged
        logger.warning("exit_watch: own levels unreadable (%s)", type(e).__name__)
        own = {}
    positions: List[Dict[str, Any]] = []
    for w in watched:
        bars = bars_by.get(w.underlying) or []
        lvl = _stored_level(stored.get(w.key) or {}, bars, w.side)
        is_stored = lvl is not None
        if lvl is None:
            lvl = rules.advance_level(None, bars, w.side)
            if w.underlying in bar_errors:
                lvl["why"] = f"NSE end-of-day prices could not be read ({bar_errors[w.underlying]})"
        price, source, as_of = _price(w.underlying, got, bars)
        positions.append(view.position_view(w, lvl, own.get(w.underlying), price=price, source=source, as_of=as_of,
                                            stored=is_stored))
    since = (today - timedelta(days=runner.ALERT_DAYS)).isoformat()
    alerts = [_public_alert(d) for d in await store.recent_alerts(db, uid, since)
              if account == "ALL" or d.get("account_id") == account]
    st = await store.read_state(db)
    return {
        "as_of": now.astimezone(runner.IST).isoformat(),
        "session": "open" if runner.in_session(now) else "closed",
        "rule": {"id": rules.RULE_ID, "text": rules.RULE_TEXT},
        "watcher": {"enabled": runner.enabled(), "live_round_at": (st.get("live") or {}).get("at"),
                    "eod_day": (st.get("eod") or {}).get("day"), "feed_why": (st.get("live") or {}).get("feed_why")},
        "positions": positions,
        "not_watched": [{"label": n["label"], "why": n["why"]} for n in not_watched],
        "alerts": alerts,
        "unseen": await store.unseen_count(db, uid),
        "accounts": [{"account_id": a["account_id"], "name": a["name"], "state": a["state"]} for a in accts],
    }


async def mark_seen(db, uid: str, ids: Optional[List[str]]) -> int:
    return await store.mark_seen(db, uid, ids)


def clean_seen_body(body: Any) -> Optional[List[str]]:
    """None (mark all) for {}, the ids for {"ids": [...]}; ValueError("invalid_body") otherwise."""
    if not isinstance(body, dict) or set(body) - {"ids"}:
        raise ValueError("invalid_body")
    if "ids" not in body:
        return None
    ids = body["ids"]
    if not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(i, str) and 0 < len(i) <= 64 for i in ids):
        raise ValueError("invalid_body")
    return ids
