"""Chartink hits: the grouped view for the desk, and the index the Strategy Builder merges into the AI opportunities.

Hits are what the last refresh stored; nothing is fetched here. Every answer carries the scan date and the fetch time, and says whether the
data is an end-of-day snapshot (fetched after the close) or a fetch-time reading (fetched during the session). An old scan date is flagged, never
presented as today's.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from services.strategy_plan.rules import RULES

from . import store

logger = logging.getLogger(__name__)

# A fetch at or after EOD_AFTER_IST (market close 15:30 plus a margin) holds the closed session's candles; hits older than STALE_AFTER_CALENDAR_DAYS
# are not merged into the AI opportunities (a weekend plus one holiday). Both live in the strategy rules (rules.RULES["chartink"]).
EOD_AFTER_IST = RULES["chartink"]["eod_after_ist"]
STALE_AFTER_CALENDAR_DAYS = RULES["chartink"]["stale_after_calendar_days"]
MAX_UNKNOWN_LISTED = 12
SUGGESTION_KEYS = ("symbol", "name", "isin", "match", "has_prices", "last_price_date", "fno_eligible")


def _fetched_ist(s: str) -> Optional[datetime]:
    t = store.parse_ts(s)
    return t.astimezone(store.IST) if t else None


def is_eod(scan_date: str, fetched_at: Optional[str]) -> bool:
    t = _fetched_ist(fetched_at or "")
    if t is None:
        return False
    h, m = (int(x) for x in EOD_AFTER_IST.split(":"))
    return t.date().isoformat() > scan_date or (t.date().isoformat() == scan_date and (t.hour, t.minute) >= (h, m))


async def latest_hits(db, user_id: str, scan_date: Optional[str]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(scan date, hit documents of that date). Without a date, the user's latest stored date."""
    if scan_date is None:
        top = await db[store.HITS].find({"user_id": user_id}).sort("scan_date", -1).limit(1).to_list(1)
        if not top:
            return None, []
        scan_date = top[0]["scan_date"]
    return scan_date, await db[store.HITS].find({"user_id": user_id, "scan_date": scan_date}).to_list(None)


def group(docs: List[Dict[str, Any]], scans: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """symbol -> {scans: [{id, name, direction}], count, close, pct_change, volume}, over the scans that are enabled now (the user's current direction)."""
    live = {s["id"]: s for s in scans if s.get("enabled") and s.get("supported")}
    by: Dict[str, Dict[str, Any]] = {}
    for d in sorted(docs, key=lambda x: (x.get("fetched_at") or "", x["scan_id"])):
        s = live.get(d["scan_id"])
        if s is None:
            continue
        e = by.setdefault(d["symbol"], {"scans": [], "close": None, "pct_change": None, "volume": None})
        e["scans"].append({"id": s["id"], "name": s["name"], "direction": s.get("direction")})
        for k in ("close", "pct_change", "volume"):
            if d.get(k) is not None:
                e[k] = d[k]            # the latest fetched hit wins (docs are in fetch order)
    for e in by.values():
        e["count"] = len(e["scans"])
    return by


async def hits_view(db, user_id: str, scan_date: Optional[str], today: date, scanner_scores: Optional[Dict[str, Optional[float]]], scanner_failures: List[str],
                    universe: Optional[Dict[str, Dict[str, Any]]], universe_failure: Optional[str], suggest) -> Dict[str, Any]:
    """The GET /api/desk/chartink/hits body. `scanner_scores`: symbol -> AI score for every symbol in the merged scanner list (None when unreadable);
    `universe`: the NSE symbol universe by symbol (None when unreadable); `suggest(symbol)` -> async list of suggestions for a symbol not in it."""
    src = await store.get_source(db, user_id)
    base: Dict[str, Any] = {"as_of_date": None, "fetched_at": None, "mode": None, "is_today": None, "age_days": None, "dashboard_id": (src or {}).get("dashboard_id"),
                            "scans": [], "symbols": [], "unknown_symbols": [], "source_failures": list(scanner_failures), "empty_reason": None}
    if universe_failure:
        base["source_failures"].append(universe_failure)
    if src is None:
        base["empty_reason"] = "No Chartink dashboard is connected."
        return base
    sd, docs = await latest_hits(db, user_id, scan_date)
    scans = src.get("scans") or []
    live = [s for s in scans if s.get("enabled") and s.get("supported")]
    if sd is None or not docs:
        base["scans"] = [_scan_row(s, 0) for s in live]
        base["empty_reason"] = "No scan has been refreshed yet." if sd is None else f"No hits are stored for {sd}."
        base["as_of_date"] = sd
        return base
    by = group(docs, scans)
    counts: Dict[str, int] = {}
    for d in docs:
        counts[d["scan_id"]] = counts.get(d["scan_id"], 0) + 1
    fetched = [d.get("fetched_at") for d in docs if d.get("fetched_at")]
    oldest, newest = min(fetched, default=None), max(fetched, default=None)
    age = (today - date.fromisoformat(sd)).days
    base.update(as_of_date=sd, fetched_at=newest, mode="end_of_day_snapshot" if oldest and is_eod(sd, oldest) else "fetched_at",
                is_today=age == 0, age_days=age, scans=[_scan_row(s, counts.get(s["id"], 0)) for s in live])
    if age > 0:
        base["stale_note"] = f"These hits are from {sd}, {age} day(s) before today: refresh to update them."
    unknown, symbols = [], []
    for sym, e in sorted(by.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        u = universe.get(sym) if universe is not None else None
        if universe is not None and u is None:
            unknown.append({"symbol": sym, "scans": e["scans"], "count": e["count"], "close": e["close"], "pct_change": e["pct_change"], "volume": e["volume"]})
            continue
        symbols.append({"symbol": sym, "name": (u or {}).get("name"), "scans": e["scans"], "count": e["count"], "close": e["close"], "pct_change": e["pct_change"],
                        "volume": e["volume"], "in_ai_scanner": (sym in scanner_scores) if scanner_scores is not None else None,
                        "ai_score": scanner_scores.get(sym) if scanner_scores is not None else None, "fno_eligible": (u or {}).get("fno_eligible")})
    for x in unknown[:MAX_UNKNOWN_LISTED]:
        sg = await suggest(x["symbol"])
        x["suggestions"], x["suggested"] = sg["suggestions"], sg["suggested"]
        x["note"] = "Not an NSE symbol in the symbol master: Chartink may have sent a code that is not a ticker."
    base.update(symbols=symbols, unknown_symbols=unknown)
    return base


def _scan_row(s: Dict[str, Any], hits: int) -> Dict[str, Any]:
    lr = s.get("last_run") or {}
    return {"id": s["id"], "name": s["name"], "direction": s.get("direction"), "hits": hits, "ok": lr.get("ok") if lr else None, "error": lr.get("error") if lr else None,
            "uses_intraday_candles": bool(s.get("uses_intraday_candles")), "last_run_at": lr.get("at") if lr else None}


# ── what the Strategy Builder merges ─────────────────────────────────────────

async def read_index(db, user_id: str, today: date) -> Dict[str, Any]:
    """The hit index for the merge: {"state": no_source | no_hits | stale | ok, "reason": text|None, "dashboard_id", "scan_date", "fetched_at", "symbols": {SYM: {...}},
    "scans": [...]}. `symbols` is over the enabled scans of every direction; callers pick the directions they need. Raises on a storage failure."""
    src = await store.get_source(db, user_id)
    if src is None:
        return {"state": "no_source", "reason": "No Chartink dashboard is connected.", "symbols": {}, "scans": []}
    live = [s for s in src.get("scans") or [] if s.get("enabled") and s.get("supported")]
    runs = [s["last_run"] for s in live if s.get("last_run")]
    ok_runs = [r for r in runs if r.get("ok")]
    out = {"state": "ok", "reason": None, "dashboard_id": src.get("dashboard_id"), "scan_date": None, "fetched_at": None, "symbols": {}, "scans": [_scan_row(s, 0) for s in live]}
    if not live:
        return {**out, "state": "not_refreshed", "reason": "No Chartink scan is enabled."}
    if runs and not ok_runs:
        return {**out, "state": "failed", "reason": "The last refresh of every enabled Chartink scan failed: " + str(runs[0].get("error") or "unknown error")}
    sd, docs = await latest_hits(db, user_id, None)
    if sd is None:
        if not ok_runs:
            return {**out, "state": "not_refreshed", "reason": "No Chartink scan has been refreshed yet."}
        last = max(ok_runs, key=lambda r: r.get("at") or "")
        sd, docs = store.ist_date(store.parse_ts(last["at"])), []          # the scans ran and listed no stock
    age = (today - date.fromisoformat(sd)).days
    if age > STALE_AFTER_CALENDAR_DAYS:
        return {**out, "scan_date": sd, "state": "stale", "reason": f"The latest Chartink hits are from {sd}, {age} days ago: refresh the scans."}
    fetched = [d.get("fetched_at") for d in docs if d.get("fetched_at")] or [r.get("at") for r in ok_runs if r.get("at")]
    out.update(scan_date=sd, symbols=group(docs, src.get("scans") or []), fetched_at=max(fetched, default=None),
               mode="end_of_day_snapshot" if fetched and is_eod(sd, min(fetched)) else "fetched_at")
    return out
