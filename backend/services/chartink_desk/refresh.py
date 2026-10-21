"""Running the user's enabled Chartink scans and storing today's hits.

Politeness (Chartink publishes no API; this is its public screener endpoint): at most MAX_SCANS scans per run, CONCURRENCY at a time, MIN_GAP_S between
the starts of two scans, SCAN_TIMEOUT_S per scan, one run per user per COOLDOWN_S (store.COOLDOWN_S). A scan that fails never fails the others; a failed
scan keeps no result as fresh (its hits of the day, if an earlier run stored some, stay labelled with their own fetched_at and the scan reports ok false).
Never places an order; reads only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services.positional_engine import chartink_api
from services.positional_engine.chartink_loader import _norm_symbol

from . import store

logger = logging.getLogger(__name__)

CONCURRENCY = 2
MIN_GAP_S = 1.0
SCAN_TIMEOUT_S = 30.0
HTTP_TIMEOUT_S = 15                 # each of the two requests of a scan (page, then scan); the scan as a whole is cut at SCAN_TIMEOUT_S
MAX_SCANS = 25
MAX_HITS_PER_SCAN = 500
ERROR_TEXT = {
    "bootstrap_failed": "the Chartink screener page could not be loaded",
    "no_session": "Chartink gave no session cookie (the page may have changed)",
    "scan_failed": "the scan request failed",
    "non_json": "Chartink answered with something that is not a scan result (the endpoint may have changed)",
    "scan_rejected": "Chartink refused this scan clause (an unsupported indicator, universe or syntax)",
    "timeout": f"the scan took longer than {SCAN_TIMEOUT_S:g} seconds",
    "http_403": "Chartink refused the request (403)",
    "http_429": "Chartink is rate limiting this server (429); try again later",
    "unexpected": "an unexpected error",
}

ScanFn = Callable[[str], Awaitable[Tuple[Optional[List[dict]], Optional[str]]]]


async def default_scan(clause: str) -> Tuple[Optional[List[dict]], Optional[str]]:
    return await asyncio.to_thread(chartink_api.run_scan_sync_typed, clause, timeout=HTTP_TIMEOUT_S)


def error_text(code: str) -> str:
    base = code if code in ERROR_TEXT else ("http_error" if code.startswith("http_") else code)
    return f"{code}: {ERROR_TEXT.get(code) or ('Chartink answered HTTP ' + code[5:] if code.startswith('http_') else base)}"


class Spacer:
    """Keeps at least `gap` seconds between the starts of two scans, however many run at once. Injectable clock and sleep for tests."""

    def __init__(self, gap: Optional[float] = None, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.gap, self.clock, self.sleep = MIN_GAP_S if gap is None else gap, clock, sleep
        self._last: Optional[float] = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            if self._last is not None:
                left = self._last + self.gap - self.clock()
                if left > 0:
                    await self.sleep(left)
            self._last = self.clock()


def to_hits(rows: List[dict]) -> List[Dict[str, Any]]:
    """Distinct hits {symbol, close, pct_change, volume} from the parsed screener rows; the symbol is normalised like chartink_loader."""
    out, seen = [], set()
    for r in rows or []:
        sym = _norm_symbol(str(r.get("symbol") or ""))
        if not sym or sym == "-" or sym in seen:
            continue
        seen.add(sym)
        x = r.get("extra") or {}
        out.append({"symbol": sym, "close": _num(x.get("close")), "pct_change": _num(x.get("per_chg")), "volume": _num(x.get("volume"))})
        if len(out) >= MAX_HITS_PER_SCAN:
            break
    return out


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


async def claim(db, user_id: str, now: datetime) -> None:
    """Take the user's refresh slot, or raise 429 with retry_after_s. Atomic: the filter holds the cooldown test."""
    cutoff = store.ts(now.replace(microsecond=0) - timedelta(seconds=store.COOLDOWN_S))
    r = await db[store.SOURCES].update_one({"_id": user_id, "$or": [{"refresh_claimed_at": None}, {"refresh_claimed_at": {"$lte": cutoff}}]},
                                           {"$set": {"refresh_claimed_at": store.ts(now)}})
    if r.matched_count:
        return
    doc = await store.get_source(db, user_id)
    if doc is None:
        raise store.ChartinkError("no_source", "No Chartink dashboard is connected.", 404)
    at = store.parse_ts(doc.get("refresh_claimed_at"))
    left = max(1, int(store.COOLDOWN_S - (now - at).total_seconds())) if at else store.COOLDOWN_S
    raise store.ChartinkError("refresh_cooldown", f"Scans were refreshed less than {store.COOLDOWN_S // 60} minutes ago. Try again in {left} seconds.", 429, retry_after_s=left)


async def refresh_user(db, user_id: str, *, scan_fn: ScanFn = default_scan, now: Optional[datetime] = None, spacer: Optional[Spacer] = None,
                       cooldown: bool = True) -> Dict[str, Any]:
    """Run the user's enabled, supported stock scans and store today's hits. Raises ChartinkError only for no_source (404) and the cooldown (429)."""
    now = now or store.utcnow()
    doc = await store.get_source(db, user_id)
    if doc is None:
        raise store.ChartinkError("no_source", "No Chartink dashboard is connected.", 404)
    if cooldown:
        await claim(db, user_id, now)
    runnable = [s for s in doc.get("scans") or [] if s.get("enabled") and s.get("supported") and s.get("kind") == "stock_scan" and s.get("clause")]
    skipped = max(0, len(runnable) - MAX_SCANS)
    runnable = runnable[:MAX_SCANS]
    scan_date = store.ist_date(now)
    out: Dict[str, Any] = {"ran_at": store.ts(now), "scan_date": scan_date, "scans": [], "ok_count": 0, "failed_count": 0, "skipped_over_cap": skipped,
                           "uses_intraday_candles": any(s.get("uses_intraday_candles") for s in runnable), "degraded": None, "dashboard_id": doc.get("dashboard_id")}
    if not runnable:
        if cooldown:
            await db[store.SOURCES].update_one({"_id": user_id}, {"$set": {"refresh_claimed_at": None}})     # nothing ran: the slot is not used up
        out["degraded"] = "No scan is enabled: nothing was fetched. Enable a stock scan first."
        return out
    sem, spacer = asyncio.Semaphore(CONCURRENCY), spacer or Spacer()

    async def one(s: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            await spacer.wait()
            t0 = time.monotonic()
            rows, err = None, None
            try:
                rows, err = await asyncio.wait_for(scan_fn(s["clause"]), SCAN_TIMEOUT_S)
            except asyncio.TimeoutError:
                err = "timeout"
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one scan failing never fails the others; the clause is not logged
                logger.warning("chartink scan %s failed: %s", s["id"], type(e).__name__)
                err = "unexpected"
            if rows is None and err is None:
                err = "scan_failed"
            hits = to_hits(rows) if rows is not None else []
            return {"id": s["id"], "name": s["name"], "direction": s.get("direction"), "ok": rows is not None, "hits": len(hits),
                    "error": error_text(err) if err else None, "error_code": err, "seconds": round(time.monotonic() - t0, 2), "_rows": hits}

    results = await asyncio.gather(*(one(s) for s in runnable))
    docs_by_scan = {r["id"]: [{"user_id": user_id, "scan_date": scan_date, "scan_id": r["id"], "scan_name": r["name"], "direction": r["direction"], **h,
                               "fetched_at": store.ts(now)} for h in r["_rows"]] for r in results if r["ok"]}
    for sid, docs in docs_by_scan.items():
        try:
            await db[store.HITS].delete_many({"user_id": user_id, "scan_date": scan_date, "scan_id": sid})     # the same scan and day: replaced, so a rerun is idempotent
            if docs:
                await db[store.HITS].insert_many(docs)
        except Exception as e:  # noqa: BLE001 — a storage failure for one scan is reported on that scan
            logger.warning("chartink hits for scan %s not stored: %s", sid, type(e).__name__)
            r = next(x for x in results if x["id"] == sid)
            r.update(ok=False, error="storage_failed: the hits could not be saved", error_code="storage_failed")
    await _write_last_runs(db, user_id, results, now)
    out["scans"] = [{k: v for k, v in r.items() if k != "_rows"} for r in results]
    out["ok_count"] = sum(1 for r in results if r["ok"])
    out["failed_count"] = len(results) - out["ok_count"]
    if out["ok_count"] == 0:
        out["degraded"] = "Every scan failed, so no Chartink hits are available; the AI scanner list is unaffected."
    return out


async def _write_last_runs(db, user_id: str, results: List[Dict[str, Any]], now: datetime) -> None:
    """Each scan's last_run, written by the scan's current position (the dashboard may have been re-imported meanwhile)."""
    try:
        doc = await store.get_source(db, user_id)
        pos = {s["id"]: i for i, s in enumerate((doc or {}).get("scans") or [])}
        sets = {f"scans.{pos[r['id']]}.last_run": {"at": store.ts(now), "ok": r["ok"], "hits": r["hits"], "error": r["error"], "seconds": r["seconds"]}
                for r in results if r["id"] in pos}
        if sets:
            await db[store.SOURCES].update_one({"_id": user_id}, {"$set": sets})
    except Exception as e:  # noqa: BLE001
        logger.warning("chartink last_run not stored: %s", type(e).__name__)


async def refresh_all(db, *, scan_fn: ScanFn = default_scan, now: Optional[datetime] = None, dry_run: bool = False) -> Dict[str, Any]:
    """The scheduler's run: every user with a source, one after another (the scan pacing applies per user, and users are not run in parallel).
    The per-user cooldown is not applied (a cron run at 16:05 and another at 20:10 are hours apart); the manual refresh route keeps it."""
    users = [d["user_id"] for d in await db[store.SOURCES].find({}).to_list(None) if d.get("user_id")]
    out: Dict[str, Any] = {"users": len(users), "dry_run": dry_run, "scans_ok": 0, "scans_failed": 0, "per_user": []}
    spacer = Spacer()                  # one pacing clock for all users: the gap between two scans holds across users too
    for uid in users:
        if dry_run:
            doc = await store.get_source(db, uid)
            n = sum(1 for s in (doc or {}).get("scans") or [] if s.get("enabled") and s.get("supported"))
            out["per_user"].append({"user_id_hash": _h(uid), "would_run": min(n, MAX_SCANS)})
            continue
        try:
            r = await refresh_user(db, uid, scan_fn=scan_fn, now=now, spacer=spacer, cooldown=False)
        except Exception as e:  # noqa: BLE001 — one user must not stop the others
            logger.warning("chartink refresh for one user failed: %s", type(e).__name__)
            out["per_user"].append({"user_id_hash": _h(uid), "error": type(e).__name__})
            continue
        out["scans_ok"] += r["ok_count"]
        out["scans_failed"] += r["failed_count"]
        out["per_user"].append({"user_id_hash": _h(uid), "ok": r["ok_count"], "failed": r["failed_count"], "errors": sorted({s["error_code"] for s in r["scans"] if s["error_code"]})})
    return out


def _h(uid: str) -> str:
    import hashlib
    return hashlib.sha256(uid.encode()).hexdigest()[:8]
