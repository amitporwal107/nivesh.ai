"""
Morningstar India stock rating client.

Strategy:
1. Use Playwright to load morningstar.in once to capture the Bearer JWT token
   that their website uses against the apac-api.morningstar.com screener.
2. Cache the token (~1 hour TTL) and make lightweight HTTP calls for all
   subsequent lookups — no browser overhead per stock.
3. Store results in stock_scores.morningstar_rating for the portfolio engine.
"""

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token cache (in-process; refreshed automatically when near expiry)
# ---------------------------------------------------------------------------
_TOKEN_CACHE: Dict[str, Any] = {"token": None, "expires_at": 0}

_SCREENER_URL = "https://www.apac-api.morningstar.com/ecint/v1/screener"
_DATA_POINTS   = (
    "secId,name,legalName,exchangeId,"
    "quantitativeStarRating,closePrice,peRatio,marketCap"
)
_UNIVERSE = "E0EXG$XBOM|E0EXG$XNSE"   # BSE + NSE India


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

async def _fetch_fresh_token() -> Optional[str]:
    """Launch headless Chromium, intercept the Bearer token from the
    Morningstar India quickrank page, and return it."""
    try:
        from playwright.async_api import async_playwright  # noqa: PLC0415

        captured: Dict[str, Optional[str]] = {"token": None}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                executable_path="/pw-browsers/chromium-1208/chrome-linux/chrome",
            )
            page = await browser.new_page()

            def _on_request(req: Any) -> None:
                if "apac-api.morningstar.com" in req.url:
                    auth = req.headers.get("authorization", "")
                    if auth.startswith("Bearer ") and not captured["token"]:
                        captured["token"] = auth[7:]

            page.on("request", _on_request)

            await page.goto(
                "https://www.morningstar.in/tools/stock-quickrank.aspx",
                timeout=30_000,
                wait_until="networkidle",
            )
            await page.wait_for_timeout(4_000)
            await browser.close()

        token = captured["token"]
        if token:
            logger.info("Morningstar token refreshed successfully")
        else:
            logger.warning("Morningstar token not found in intercepted requests")
        return token

    except Exception as exc:
        logger.error(f"Failed to refresh Morningstar token via Playwright: {exc}")
        return None


async def get_ms_token() -> Optional[str]:
    """Return a valid cached token, refreshing if within 60 s of expiry."""
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] > now + 60:
        return _TOKEN_CACHE["token"]

    token = await _fetch_fresh_token()
    if not token:
        return None

    # Parse JWT expiry
    try:
        payload_b64 = token.split(".")[1] + "=="
        payload = json.loads(base64.b64decode(payload_b64))
        expires_at = payload.get("exp", now + 3_300)
    except Exception:
        expires_at = now + 3_300  # 55-minute safety margin

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = expires_at
    return token


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    """Strip common legal suffixes so the search term matches better."""
    name = re.sub(
        r"\b(LIMITED|LTD\.?|CORPORATION|CORP\.?|INDUSTRIES|INDUSTRY|"
        r"PRIVATE|PVT\.?|LLP|INC\.?|BANK)\b",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    # Remove extra whitespace / punctuation
    return re.sub(r"[^a-zA-Z0-9 ]", " ", name).strip()


def _name_similarity(a: str, b: str) -> float:
    """Simple word-overlap score (0–1)."""
    aw = set(_clean_name(a).lower().split())
    bw = set(_clean_name(b).lower().split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / max(len(aw), len(bw))


async def search_stock_morningstar(
    company_name: str,
    token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Search the Morningstar screener and return the best-matched row."""
    token = token or await get_ms_token()
    if not token:
        return None

    term = _clean_name(company_name)
    params = {
        "languageId":         "en-IN",
        "currencyId":         "BAS",
        "universeIds":        _UNIVERSE,
        "outputType":         "json",
        "version":            "1",
        "page":               "1",
        "pageSize":           "10",
        "sortOrder":          "name asc",
        "securityDataPoints": _DATA_POINTS,
        "term":               term,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Referer":       "https://www.morningstar.in/",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":        "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(_SCREENER_URL, params=params, headers=headers)
            if resp.status_code == 401:
                # Token expired mid-session — clear cache and bail
                _TOKEN_CACHE["token"] = None
                _TOKEN_CACHE["expires_at"] = 0
                logger.warning("Morningstar token expired (401) — will refresh on next call")
                return None
            if resp.status_code != 200:
                logger.warning(f"Morningstar screener HTTP {resp.status_code} for '{term}'")
                return None

            data   = resp.json()
            rows   = data.get("rows") or []
    except Exception as exc:
        logger.error(f"Morningstar search error for '{term}': {exc}")
        return None

    if not rows:
        return None

    # Prefer NSE-listed, then pick the row with the highest name similarity
    nse_rows = [r for r in rows if "XNSE" in (r.get("exchangeId") or "")]
    pool     = nse_rows if nse_rows else rows

    best = max(pool, key=lambda r: _name_similarity(company_name, r.get("name") or ""))

    if not best.get("quantitativeStarRating"):
        return None

    return {
        "sec_id":             best.get("secId"),
        "ms_name":            best.get("name"),
        "morningstar_rating": int(best["quantitativeStarRating"]),
        "ms_close_price":     best.get("closePrice"),
        "ms_pe_ratio":        best.get("peRatio"),
    }


# ---------------------------------------------------------------------------
# Batch refresh
# ---------------------------------------------------------------------------

async def batch_refresh_stock_morningstar(
    holdings: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch Morningstar ratings for a list of equity holdings.

    Each item in `holdings` must have at minimum:
        nse_symbol (str) — used as the key in the returned dict
        company_name (str) — used for the search query

    Returns: {nse_symbol: {morningstar_rating, ...}}
    """
    # Get token once upfront
    token = await get_ms_token()
    if not token:
        logger.error("Cannot refresh Morningstar ratings: token unavailable")
        return {}

    results: Dict[str, Dict[str, Any]] = {}

    for h in holdings:
        sym  = (h.get("nse_symbol") or "").upper().strip()
        name = h.get("company_name") or h.get("name") or sym
        if not sym:
            continue

        try:
            data = await search_stock_morningstar(name, token=token)
            if data:
                results[sym] = data
                logger.info(f"  MS {sym}: {data['morningstar_rating']}★ ({data['ms_name']})")
            else:
                logger.debug(f"  MS {sym}: no rating found")

            await asyncio.sleep(0.3)   # polite delay between calls
        except Exception as exc:
            logger.warning(f"  MS {sym}: error — {exc}")

    logger.info(f"Morningstar refresh complete: {len(results)}/{len(holdings)} rated")
    return results
