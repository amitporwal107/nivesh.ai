"""Chartink API client.

Chartink does NOT publish an official API. This client wraps their
internal `/screener/process` endpoint, which is the same endpoint their
public scanner page uses. Stable in practice, but unofficial — treat it
as best-effort and always fall back to manual CSV upload if it breaks.

Flow:
  1. GET a scanner page to obtain the `XSRF-TOKEN` and Laravel session
     cookie (the response also sets `XSRF-TOKEN` decoded via urldecode).
  2. POST `scan_clause=...` to /screener/process with the
     `X-XSRF-TOKEN` header. Returns JSON with a `data` array of hits.

Each scan definition stored by the operator is:
    {
      "name":   "atlas.trend_up",        # used as scan_name in chartink_scan_hits
      "clause": "( {cash} ( latest close > latest sma( latest close , 50 ) ) )",
      "enabled": True,
    }

The clause is the same string Chartink lets you copy from a scan's
"Conditions" tab. Multi-line clauses must be normalised to a single
line and wrapped in `( {cash} ... )` (or `{45603}` for an existing
group). Operators paste these in via the admin endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

CHARTINK_BASE = "https://chartink.com"
SCREENER_PROCESS = f"{CHARTINK_BASE}/screener/process"
BOOTSTRAP_PAGE = f"{CHARTINK_BASE}/screener/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": CHARTINK_BASE,
    "Referer": CHARTINK_BASE + "/screener/",
    "X-Requested-With": "XMLHttpRequest",
}


# ── Pure-function parser (testable without network) ──────────────────────
def parse_response(payload: dict) -> List[dict]:
    """Extract symbols from a /screener/process JSON response.

    Returns a list of {symbol, extra} matching chartink_loader's shape.
    Tolerates partial payloads — Chartink sometimes returns aborted=True
    with a partial `data` array; we just take what's there.
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    out: List[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        sym = row.get("nsecode") or row.get("name")
        if not sym:
            continue
        sym = str(sym).strip().upper()
        if not sym or sym == "-":
            continue
        out.append({
            "symbol": sym,
            "extra": {
                "name": row.get("name"),
                "close": row.get("close"),
                "per_chg": row.get("per_chg"),
                "volume": row.get("volume"),
                "bsecode": row.get("bsecode"),
            },
        })
    return out


# ── Network layer (sync, run via to_thread) ──────────────────────────────
def _run_scan_sync(clause: str, *, timeout: int = 30) -> Optional[List[dict]]:
    """Bootstrap session → POST scan clause → parse. Returns None on failure."""
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # 1. Bootstrap: GET the screener page to populate cookies.
    try:
        req = urllib.request.Request(BOOTSTRAP_PAGE, headers=_HEADERS)
        with opener.open(req, timeout=timeout) as resp:
            resp.read()
    except Exception as e:  # noqa: BLE001
        logger.warning("chartink bootstrap failed: %s", e)
        return None

    # 2. Find XSRF-TOKEN cookie (URL-encoded by Laravel).
    xsrf = None
    for c in jar:
        if c.name == "XSRF-TOKEN":
            xsrf = urllib.parse.unquote(c.value)
            break
    if not xsrf:
        logger.warning("chartink: no XSRF-TOKEN cookie returned")
        return None

    # 3. POST the scan clause.
    body = urllib.parse.urlencode({"scan_clause": clause}).encode("utf-8")
    headers = dict(_HEADERS)
    headers["X-XSRF-TOKEN"] = xsrf
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    try:
        req = urllib.request.Request(SCREENER_PROCESS, data=body, headers=headers, method="POST")
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.warning("chartink scan POST failed: %s", e)
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("chartink: non-JSON response (%s): %.200s", e, raw)
        return None

    return parse_response(payload)


async def run_scan(clause: str, *, timeout: int = 30) -> Optional[List[dict]]:
    """Async wrapper — runs the sync urllib path in a thread."""
    return await asyncio.to_thread(_run_scan_sync, clause, timeout=timeout)


# ── Multi-scan orchestration ─────────────────────────────────────────────
async def run_scans(scans: Iterable[dict], *, timeout: int = 30) -> dict:
    """Run a batch of {name, clause, enabled?} scans. Returns:
       {scan_name: [{symbol, extra}, ...], ..., "_errors": {scan_name: msg}}
    """
    results: dict = {"_errors": {}}
    for s in scans:
        if s.get("enabled") is False:
            continue
        name = (s.get("name") or "").strip()
        clause = (s.get("clause") or "").strip()
        if not name or not clause:
            continue
        rows = await run_scan(clause, timeout=timeout)
        if rows is None:
            results["_errors"][name] = "fetch_failed_or_no_session"
            continue
        results[name] = rows
    return results
