"""Stock Fundamentals Enricher — on-demand, Mongo-cached.

Fetches `market_cap`, `pe_ratio`, `roe`, `debt_to_equity` from Groww's public
stock detail API for a list of NSE symbols. Caches results in MongoDB
(`stock_fundamentals_cache`) for 24 hours. Adds SEBI market-cap classification
and a β/σ heuristic that the Portfolio-Health engine consumes when real
primitives are missing.

This module is deliberately dependency-light (no redis), so it stays reliable
even if scraping fails — the caller always receives a classification + β/σ.

Usage (called from /api/insights/v3-portfolio):

    from services.stock_enricher import enrich_stocks_for_user
    enriched = await enrich_stocks_for_user(user_id, force_refresh=False)
    # → {nse_symbol: {market_cap_cr, cap_bucket, beta, vol_annual_pct,
    #                  pe_ratio, roe, debt_to_equity, source, cached_at}}
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from deps import db

logger = logging.getLogger(__name__)

# ── SEBI market-cap thresholds (₹ crores) ─────────────────────────────
# SEBI classifies by rank among listed companies but most Indian brokers
# use the AMFI half-yearly thresholds. These approximate AMFI Dec-2025.
CAP_THRESHOLDS_CR = {
    "large_min": 67000.0,     # top-100 typically have mcap ≥ ₹67,000 Cr
    "mid_min":   20000.0,     # 101-250 typically ≥ ₹20,000 Cr
    # anything below 20,000 Cr → small-cap
}

# β / σ heuristic table (annualised, decimal % for σ)
CAP_HEURISTICS = {
    "large": {"beta": 0.9, "vol_annual_pct": 18.0},
    "mid":   {"beta": 1.1, "vol_annual_pct": 22.0},
    "small": {"beta": 1.3, "vol_annual_pct": 30.0},
    # Unknown bucket → Mid-cap defaults (conservative), flagged low_confidence.
    "unknown": {"beta": 1.0, "vol_annual_pct": 20.0},
}

CACHE_TTL_HOURS = 24
GROWW_STOCK_API = "https://groww.in/v1/api/stocks_data/v1/accord_points/stock/{symbol}"
HTTP_TIMEOUT_S = 8


def classify_market_cap(market_cap_cr: Optional[float]) -> str:
    """Classify an Indian-listed stock by AMFI-style market-cap thresholds.
    Returns 'large' | 'mid' | 'small' | 'unknown'."""
    if market_cap_cr is None or market_cap_cr <= 0:
        return "unknown"
    if market_cap_cr >= CAP_THRESHOLDS_CR["large_min"]:
        return "large"
    if market_cap_cr >= CAP_THRESHOLDS_CR["mid_min"]:
        return "mid"
    return "small"


def stock_primitives_from_bucket(bucket: str) -> Dict[str, float]:
    """Return heuristic β/σ for the given cap bucket."""
    return dict(CAP_HEURISTICS.get(bucket, CAP_HEURISTICS["unknown"]))


# ── Mongo cache helpers ────────────────────────────────────────────────
async def _get_cached(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not symbols:
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    cursor = db.stock_fundamentals_cache.find(
        {"nse_symbol": {"$in": symbols}, "cached_at": {"$gte": cutoff}},
        {"_id": 0},
    )
    async for doc in cursor:
        sym = doc.get("nse_symbol")
        if sym:
            out[sym] = doc
    return out


async def _upsert_cached(entry: Dict[str, Any]) -> None:
    sym = entry.get("nse_symbol")
    if not sym:
        return
    try:
        await db.stock_fundamentals_cache.update_one(
            {"nse_symbol": sym},
            {"$set": entry},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"stock_fundamentals_cache upsert failed for {sym}: {e}")


# ── Groww fetch ────────────────────────────────────────────────────────
def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


async def _fetch_groww(symbol: str, session: aiohttp.ClientSession) -> Optional[Dict[str, Any]]:
    url = GROWW_STOCK_API.format(symbol=symbol)
    try:
        async with session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        logger.info(f"Groww fetch failed for {symbol}: {e}")
        return None

    stock_data = data.get("stockData") or data.get("data") or {}
    mcap = _safe_float(stock_data.get("marketCap"))
    # Groww returns mcap in ₹ (rupees). Convert to crores (÷ 1e7).
    if mcap is not None and mcap > 1e6:
        mcap_cr = mcap / 1e7
    else:
        # Already in crores (or too small / missing)
        mcap_cr = mcap
    return {
        "market_cap_cr": mcap_cr,
        "pe_ratio": _safe_float(stock_data.get("peRatio")),
        "roe": _safe_float(stock_data.get("roe")),
        "debt_to_equity": _safe_float(stock_data.get("debtToEquity")),
        "eps": _safe_float(stock_data.get("eps")),
        "pb_ratio": _safe_float(stock_data.get("pbRatio")),
    }


def _build_entry(symbol: str, groww: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    groww = groww or {}
    mcap_cr = groww.get("market_cap_cr")
    bucket = classify_market_cap(mcap_cr)
    heur = stock_primitives_from_bucket(bucket)
    return {
        "nse_symbol": symbol,
        "market_cap_cr": mcap_cr,
        "cap_bucket": bucket,
        "beta": heur["beta"],
        "vol_annual_pct": heur["vol_annual_pct"],
        "pe_ratio": groww.get("pe_ratio"),
        "roe": groww.get("roe"),
        "debt_to_equity": groww.get("debt_to_equity"),
        "eps": groww.get("eps"),
        "pb_ratio": groww.get("pb_ratio"),
        "source": "groww" if groww else "heuristic",
        "cached_at": datetime.now(timezone.utc),
    }


# ── Public API ─────────────────────────────────────────────────────────
async def get_fundamentals(
    symbols: List[str],
    *,
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Get fundamentals for a list of NSE symbols (Mongo-cached, 24h TTL).

    - Fetches from cache first unless `force_refresh=True`.
    - Missing/stale symbols are fetched from Groww in parallel.
    - Always returns an entry for each symbol (falls back to heuristic).
    """
    symbols = [s for s in {s.upper() for s in symbols if s}]
    if not symbols:
        return {}

    cached = {} if force_refresh else await _get_cached(symbols)
    missing = [s for s in symbols if s not in cached]

    fetched: Dict[str, Optional[Dict[str, Any]]] = {}
    if missing:
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [_fetch_groww(s, session) for s in missing]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, res in zip(missing, results):
                fetched[sym] = res if isinstance(res, dict) else None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"bulk Groww fetch failed: {e}")
            for sym in missing:
                fetched[sym] = None

    # Build entries + persist newly fetched ones
    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        if sym in cached:
            out[sym] = cached[sym]
            continue
        entry = _build_entry(sym, fetched.get(sym))
        await _upsert_cached(entry)
        out[sym] = entry
    return out


async def enrich_stocks_for_user(
    user_id: str,
    *,
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Convenience wrapper: pulls the user's equity holdings from Mongo,
    enriches each via Groww + heuristic, returns {nse_symbol: entry}."""
    cursor = db.holdings.find(
        {"user_id": user_id, "asset_type": "equity"},
        {"_id": 0, "nse_symbol": 1, "ticker": 1, "name": 1},
    )
    symbols: List[str] = []
    async for h in cursor:
        sym = h.get("nse_symbol")
        if sym:
            symbols.append(sym)
    if not symbols:
        return {}
    return await get_fundamentals(symbols, force_refresh=force_refresh)
