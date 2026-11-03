"""Scan dashboard: the "Index stats" widget (docs/scan_builder/DESIGN.md §7.4, IndexResult).

Index quotes come from Kite by the owner's rule of 29 Oct (services/kite_live_feed/day_quote.day_quotes): in the session the live
feed, after the close the saved Kite close. % chg is against the quote's `close`, which is Kite's PREVIOUS close. An index with
no quote that day is left out and named in the warnings; nothing is filled in from an older day. Reads only.

Why not day_quotes() itself: Kite sends no volume for an index, and day_quotes' traded_on() requires a positive day volume, so it
drops every index (seen on staging 3 Nov: the saved 2 Nov close holds NIFTY 50 at 23,440.8 with volume None).
index_day_quotes() below applies the same live → Kite close selection with an index rule: a positive price stamped that day.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from services.kite_live_feed import day_quote as dq
from services.kite_live_feed import gateway as gw
from services.kite_live_feed import config as kcfg
from services.kite_live_feed.config import IST

logger = logging.getLogger(__name__)

SHORT = {"NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FIN SERVICE": "FINNIFTY", "NIFTY MID SELECT": "MIDCPNIFTY"}
COLUMNS = [{"id": "ltp", "alias": "LTP", "format": "price"}, {"id": "chg", "alias": "% chg", "format": "pct"}]
_MODE = {"kite_live": "live", "kite_close": "kite_close"}
_WHY = {
    "feed_not_live": "the Kite live feed is not running",
    "no_saved_close": "no Kite close was saved for that day",
    "unreadable": "the quotes could not be read",
}


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _ist_time(stamp: Any) -> Optional[str]:
    """'10:15:32 IST' from an ISO timestamp (UTC when it carries no zone)."""
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(IST).strftime("%H:%M:%S IST")


def _day_text(day: Any) -> str:
    try:
        return date.fromisoformat(str(day)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(day or "")


def _index_traded(q: Optional[dict], day: Optional[str]) -> bool:
    """An index quote counts for `day` when its price is positive and Kite's stamp (if any) is on that day. Indices carry no
    volume, so day_quote.traded_on cannot be used."""
    if not isinstance(q, dict) or (_num(q.get("ltp")) or 0) <= 0:
        return False
    stamp = dq._ist_day(q.get("exchange_ts"))
    return stamp is None or stamp == day


async def index_day_quotes(symbols: Sequence[str], *, now: Optional[datetime] = None, feed: Any = None) -> Dict[str, Any]:
    """day_quote.day_quotes' answer shape and live → Kite close rule, for indices (see the module docstring). Never raises."""
    from services.kite_live_feed import quote_cache as qc
    from services.kite_live_feed.feed import get_feed

    now = now or datetime.now(timezone.utc)
    syms = [s for s in dict.fromkeys(gw.canon(x) for x in symbols) if s]
    want = set(syms)
    out: Dict[str, Any] = {"source": None, "day": None, "as_of": None, "quotes": {}, "why": None}
    try:
        feed = feed or get_feed()
        if dq.in_session(now):
            out["day"] = now.astimezone(IST).date().isoformat()
            status = await feed.read_status() or {}
            snap = await feed.read_snapshot() or {}
            if not dq._fresh(snap, status, now):
                out["why"] = "feed_not_live"
                return out
            by = {q.get("symbol"): q for q in snap.get("quotes", []) if q.get("symbol") in want}
            cached = await qc.read_quotes(syms) if syms else {}
            for s, row in (cached or {}).items():
                have, new = by.get(s), qc.as_quote(row)
                if have is None or str(new.get("received_at") or "") >= str(have.get("received_at") or ""):
                    by[s] = {**new, "symbol": s}
            out.update(source="kite_live", as_of=snap.get("data_at"))
        else:
            out["day"] = kcfg.last_close(now).astimezone(IST).date().isoformat()
            doc = await feed.read_close(out["day"])
            if not doc:
                out["why"] = "no_saved_close"
                return out
            by = {q.get("symbol"): q for q in doc.get("quotes", []) if q.get("symbol") in want}
            out.update(source="kite_close", as_of=doc.get("data_at"))
    except Exception as e:  # noqa: BLE001 — the widget then says the quotes could not be read
        logger.warning("index quotes: unreadable (%s)", type(e).__name__)
        out["why"] = "unreadable"
        return out
    out["quotes"] = {s: by[s] for s in syms if _index_traded(by.get(s), out["day"])}
    return out


async def index_result(names: Sequence[str], *, day_quotes: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """IndexResult for the Kite index names `names` (e.g. "NIFTY 50", "NIFTY BANK"), rows in the order given."""
    wanted = [n for n in dict.fromkeys(gw.canon(x) for x in names) if n]   # the feed's own keys ("NIFTY BANK")
    got = await (day_quotes or index_day_quotes)(wanted, now=now)
    mode = _MODE.get(got.get("source") or "", "none")
    quotes: Dict[str, Any] = got.get("quotes") or {}
    day = got.get("day")
    warnings: List[str] = []
    if mode == "live":
        clock = _ist_time(got.get("as_of"))
        text = f"Kite live {clock}" if clock else "Kite live"
    elif mode == "kite_close":
        text = f"Kite close, {_day_text(day)}"
    else:
        why = _WHY.get(got.get("why") or "", "no Kite quotes were found")
        text = f"Index quotes are not available ({why})"
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    for name in wanted:
        q = quotes.get(name)
        ltp = _num(q.get("ltp")) if isinstance(q, dict) else None
        if ltp is None:
            missing.append(name)
            continue
        prev = _num(q.get("close"))
        chg = round((ltp - prev) / prev * 100.0, 2) if prev else None
        rows.append({"symbol": SHORT.get(name, name), "name": name, "values": [ltp, chg], "today": mode})
    if missing and mode != "none":
        warnings.append(f"No Kite quote for {', '.join(missing)} on {_day_text(day)}; left out.")
    return {
        "ok": True,
        "kind": "indices",
        "group_by": "symbol",
        "basis": {"mode": mode, "day": day, "quote_as_of": got.get("as_of"), "text": text},
        "columns": [dict(c) for c in COLUMNS],
        "rows": rows,
        "counts": {"matched": len(rows)},
        "warnings": warnings,
    }
