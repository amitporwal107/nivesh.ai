"""NIDP market context builder for Copilot prompt injection.

Fetches live market data from the NIDP DaaS API and formats it as a
compact, LLM-safe context block.  Cached in Redis to stay within the
700–1200ms latency budget per chat request.

Feature-gated: only runs when NIDP_COPILOT_ENABLED=true.
Fails open — any error returns an empty string so chat still works.

Usage:
    from services.nidp_context import get_market_context
    ctx = await get_market_context()   # → compact string or ""
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

_ENABLED = os.environ.get("NIDP_COPILOT_ENABLED", "").lower() in ("1", "true", "yes")
_DAAS_BASE = os.environ.get("NIDP_DAAS_API_URL", "http://34.93.60.254:8083").rstrip("/")
_DAAS_KEY  = os.environ.get("NIDP_DAAS_API_KEY", "")
_TIMEOUT   = float(os.environ.get("NIDP_CONTEXT_TIMEOUT_S", "1.5"))

# Redis cache TTL — 10 min for market data (refreshes every ~15 min at source)
_CACHE_KEY = "nivesh:nidp:market_ctx"
_CACHE_TTL = 600


# ── DaaS helper ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    h = {"Accept": "application/json"}
    if _DAAS_KEY:
        h["X-API-Key"] = _DAAS_KEY
    return h


async def _fetch(path: str, params: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Single DaaS GET with short timeout. Returns None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_DAAS_BASE}{path}",
                params=params or {},
                headers=_headers(),
            )
        if resp.status_code == 200:
            return resp.json()
        logger.debug("NIDP context: %s → %s", path, resp.status_code)
        return None
    except Exception as exc:
        logger.debug("NIDP context fetch %s: %s", path, exc)
        return None


# ── Data assemblers ──────────────────────────────────────────────────────────

def _regime(nifty_chg: Optional[float], fii_net: Optional[float]) -> str:
    """Derive a simple market regime label from available signals."""
    if nifty_chg is None:
        return "unknown"
    if nifty_chg > 0.5 and (fii_net is None or fii_net >= 0):
        return "risk_on"
    if nifty_chg < -0.5 and (fii_net is None or fii_net <= 0):
        return "risk_off"
    return "neutral"


def _format_indices(data: Optional[Dict]) -> str:
    if not data:
        return ""
    rows: List[str] = []
    for idx in (data.get("indices") or data.get("rows") or [])[:5]:
        name = idx.get("index_name") or idx.get("name") or "?"
        close = idx.get("close") or idx.get("last_close")
        chg = idx.get("change_pct") or idx.get("chg_1d_pct")
        if close is not None:
            chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
            rows.append(f"{name}: {close:,.2f}{chg_str}")
    return "  " + " | ".join(rows) if rows else ""


def _format_flows(data: Optional[Dict]) -> str:
    if not data:
        return ""
    fii = data.get("fii_net_cr") or (data.get("rows") or [{}])[0].get("fii_net_cr")
    dii = data.get("dii_net_cr") or (data.get("rows") or [{}])[0].get("dii_net_cr")
    if fii is None and dii is None:
        return ""
    parts = []
    if fii is not None:
        parts.append(f"FII ₹{fii:+,.0f}Cr")
    if dii is not None:
        parts.append(f"DII ₹{dii:+,.0f}Cr")
    return "  " + " | ".join(parts)


def _format_macro(data: Optional[Dict]) -> List[str]:
    if not data:
        return []
    lines = []
    rows = data.get("rows") or data.get("indicators") or []
    for row in rows[:4]:
        name = row.get("indicator") or row.get("name") or "?"
        val  = row.get("value")
        unit = row.get("unit") or ""
        if val is not None:
            lines.append(f"{name}: {val}{unit}")
    return lines


def _format_events(data: Optional[Dict]) -> List[str]:
    if not data:
        return []
    rows = data.get("rows") or data.get("events") or []
    out = []
    for r in rows[:3]:
        desc = r.get("event_description") or r.get("event") or r.get("description") or ""
        date = (r.get("event_date") or r.get("date") or "")[:10]
        if desc:
            out.append(f"{date}: {desc[:80]}" if date else desc[:80])
    return out


# ── Public API ────────────────────────────────────────────────────────────────

async def get_market_context(symbols: Optional[List[str]] = None) -> str:
    """Return a compact NIDP market context string for prompt injection.

    Returns "" when the feature flag is off, DaaS is unreachable, or an
    error occurs — callers must treat the empty string as optional context.

    Args:
        symbols: optional list of NSE ticker symbols to enrich (from the
                 user's portfolio or query) — skipped if empty/None.
    """
    if not _ENABLED:
        return ""

    # Check Redis cache first
    cache_hit = False
    cached: Optional[str] = None
    try:
        from services import redis_client as _rc
        cached = await _rc.cache_get(_CACHE_KEY)
        if cached:
            cache_hit = True
    except Exception:
        pass

    if cache_hit and cached:
        logger.debug("NIDP context: cache hit")
        return cached

    # Fetch concurrently with a hard wall-clock budget
    try:
        indices_task = asyncio.create_task(_fetch("/v1/indices/summary"))
        flows_task   = asyncio.create_task(_fetch("/v1/flows/fii-dii"))
        macro_task   = asyncio.create_task(_fetch("/v1/macro/latest"))
        events_task  = asyncio.create_task(_fetch("/v1/events/calendar", {"horizon_days": 7}))

        indices_raw, flows_raw, macro_raw, events_raw = await asyncio.gather(
            indices_task, flows_task, macro_task, events_task,
            return_exceptions=True,
        )
        # Exceptions from gather → treat as None
        if isinstance(indices_raw, Exception): indices_raw = None
        if isinstance(flows_raw, Exception):   flows_raw = None
        if isinstance(macro_raw, Exception):   macro_raw = None
        if isinstance(events_raw, Exception):  events_raw = None
    except Exception as exc:
        logger.warning("NIDP context gather failed: %s", exc)
        return ""

    # Derive regime from whatever we have
    nifty_chg: Optional[float] = None
    fii_net:   Optional[float] = None
    if isinstance(indices_raw, dict):
        for idx in (indices_raw.get("indices") or indices_raw.get("rows") or []):
            if "nifty 50" in (idx.get("index_name") or idx.get("name") or "").lower():
                nifty_chg = idx.get("change_pct") or idx.get("chg_1d_pct")
                break
    if isinstance(flows_raw, dict):
        fii_net = flows_raw.get("fii_net_cr") or (flows_raw.get("rows") or [{}])[0].get("fii_net_cr")

    regime = _regime(nifty_chg, fii_net)

    # Build compact context block
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"── NIDP_CONTEXT ({as_of}) ──", f"regime: {regime}"]

    idx_line = _format_indices(indices_raw if isinstance(indices_raw, dict) else None)
    if idx_line:
        lines.append(f"indices: {idx_line}")

    flows_line = _format_flows(flows_raw if isinstance(flows_raw, dict) else None)
    if flows_line:
        lines.append(f"flows: {flows_line}")

    macro_lines = _format_macro(macro_raw if isinstance(macro_raw, dict) else None)
    if macro_lines:
        lines.append("macro: " + " | ".join(macro_lines))

    event_lines = _format_events(events_raw if isinstance(events_raw, dict) else None)
    if event_lines:
        lines.append("events: " + " | ".join(event_lines))

    lines.append("── end NIDP_CONTEXT ──")

    result = "\n".join(lines)

    # Cache for 10 min
    try:
        from services import redis_client as _rc
        await _rc.cache_set(_CACHE_KEY, result, ttl_s=_CACHE_TTL)
    except Exception:
        pass

    logger.debug("NIDP context: built %d chars (regime=%s)", len(result), regime)
    return result


async def invalidate_cache() -> None:
    """Force-expire the market context cache (call after manual data refresh)."""
    try:
        from services import redis_client as _rc
        await _rc.cache_delete(_CACHE_KEY)
    except Exception:
        pass
