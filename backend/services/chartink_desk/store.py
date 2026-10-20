"""Mongo storage of the user's Chartink source (one document per user) and its views. No Chartink credential is stored.

Collections: `desk_chartink_sources` (`_id` = user_id) and `desk_chartink_hits` (one document per user, scan date, scan and symbol).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import dashboard as dash

SOURCES = "desk_chartink_sources"
HITS = "desk_chartink_hits"
IST = ZoneInfo("Asia/Kolkata")
MAX_SCANS_STORED = 60               # scans kept from one dashboard (a dashboard has a few dozen widgets at most)
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
COOLDOWN_S = 600                    # per user, between two refreshes
DIRECTIONS = ("bullish", "bearish", "neutral")


class ChartinkError(Exception):
    """A typed route error: `code`, `message`, HTTP `status`, and optional extra fields (e.g. retry_after_s)."""

    def __init__(self, code: str, message: str, status: int = 422, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra

    @property
    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime(TS_FORMAT)


def parse_ts(s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s), TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ist_date(d: datetime) -> str:
    return d.astimezone(IST).date().isoformat()


def public_scan(s: Dict[str, Any], include_clauses: bool = False) -> Dict[str, Any]:
    out = {k: s.get(k) for k in ("id", "name", "description", "kind", "supported", "unsupported_reason", "uses_intraday_candles", "enabled", "direction", "last_run")}
    if include_clauses:
        out["clause"] = s.get("clause")
    return out


def public_source(doc: Optional[Dict[str, Any]], include_clauses: bool = False, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The source document as the API sends it: no _id, no clauses unless asked for, and the refresh cooldown state."""
    if not doc:
        return None
    now = now or utcnow()
    claimed = parse_ts(doc.get("refresh_claimed_at"))
    left = max(0, int((claimed + timedelta(seconds=COOLDOWN_S) - now).total_seconds())) if claimed else 0
    scans = doc.get("scans") or []
    return {"dashboard_id": doc.get("dashboard_id"), "url": doc.get("url"), "title": doc.get("title"), "fetched_at": doc.get("fetched_at"),
            "scans": [public_scan(s, include_clauses) for s in scans],
            "summary": {"scans": len(scans), "stock_scans": sum(1 for s in scans if s.get("kind") == "stock_scan"),
                        "supported": sum(1 for s in scans if s.get("supported")), "enabled": sum(1 for s in scans if s.get("enabled") and s.get("supported"))},
            "refresh": {"last_started_at": doc.get("refresh_claimed_at"), "retry_after_s": left}}



async def get_source(db, user_id: str) -> Optional[Dict[str, Any]]:
    return await db[SOURCES].find_one({"_id": user_id})


async def put_source(db, user_id: str, dashboard_url: Any, fetch=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Validate, fetch and store the dashboard. Raises dash.DashboardError (typed). Re-importing the same dashboard keeps the user's enabled/direction choices."""
    url, dash_id = dash.validate_url(dashboard_url)
    page = await asyncio.to_thread(fetch or dash.fetch_page, url)
    title, widgets = dash.parse_page(page)
    old = await get_source(db, user_id)
    previous = (old or {}).get("scans") if old and str(old.get("dashboard_id")) == dash_id else None
    scans = dash.build_scans(widgets, previous)[:MAX_SCANS_STORED]
    if not scans:
        raise dash.DashboardError("dashboard_empty", "The dashboard has no widgets that could be read.", 422)
    if not any(s["kind"] == "stock_scan" for s in scans):
        raise dash.DashboardError("dashboard_empty", "The dashboard has no stock scans (only market statistics or unreadable widgets).", 422)
    carry = {k: old[k] for k in ("refresh_claimed_at",) if old and old.get(k)}
    if previous is not None:
        for s in scans:
            p = next((x for x in previous if x["id"] == s["id"]), None)
            if p and p.get("last_run"):
                s["last_run"] = p["last_run"]
    doc = {"_id": user_id, "user_id": user_id, "dashboard_id": dash_id, "url": url, "title": title, "fetched_at": ts(now or utcnow()), "scans": scans, **carry}
    if old and str(old.get("dashboard_id")) != dash_id:
        await db[HITS].delete_many({"user_id": user_id})           # hits of another dashboard's scans must not outlive it
    await db[SOURCES].replace_one({"_id": user_id}, doc, upsert=True)
    return doc


async def patch_scan(db, user_id: str, scan_id: str, body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict) or not body or set(body) - {"enabled", "direction"}:
        raise ChartinkError("invalid_body", "Send enabled (true or false) and/or direction (bullish, bearish or neutral).")
    doc = await get_source(db, user_id)
    scan = next((s for s in (doc or {}).get("scans") or [] if s["id"] == str(scan_id)), None)
    if scan is None:
        raise ChartinkError("scan_not_found", "No such scan on your Chartink dashboard.", 404)
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise ChartinkError("invalid_enabled", "enabled must be true or false.")
        if body["enabled"] and not scan.get("supported"):
            raise ChartinkError("scan_unsupported", f"This scan cannot be run: {scan.get('unsupported_reason')}", 409)
    if "direction" in body and body["direction"] not in DIRECTIONS:
        raise ChartinkError("invalid_direction", "direction must be bullish, bearish or neutral.")
    idx = doc["scans"].index(scan)
    sets = {f"scans.{idx}.{k}": body[k] for k in body}
    await db[SOURCES].update_one({"_id": user_id, f"scans.{idx}.id": str(scan_id)}, {"$set": sets})
    return public_scan({**scan, **body})


async def delete_source(db, user_id: str) -> Dict[str, Any]:
    r = await db[SOURCES].delete_one({"_id": user_id})
    h = await db[HITS].delete_many({"user_id": user_id})
    return {"deleted": bool(r.deleted_count), "hits_deleted": h.deleted_count}
