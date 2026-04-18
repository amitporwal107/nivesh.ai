"""Groww MF data fetcher + deterministic HTML parser.

Fetches https://groww.in/mutual-funds/{slug} and extracts:
  - Holdings table (name, sector, instrument_type, pct, stock slug)
  - Sector allocation (aggregated from holdings)
  - Metadata: AUM (Cr), NAV, expense ratio
  - Validation flags + issues

Polite fetching: realistic UA, 15s timeout, follow redirects. Caller handles
retries. Parsing is tightly scoped to `holdings_row__*` CSS classes so we
don't pick up nav / sector-chart rows.
"""
from __future__ import annotations
import re
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from html import unescape
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "nivesh.ai portfolio tracker (contact: support@nivesh.ai)"
BASE_URL = "https://groww.in/mutual-funds"
TIMEOUT_S = 15.0

# Coalesce concurrent search_slug calls for the same query
_search_locks: Dict[str, asyncio.Lock] = {}
_search_cache: Dict[str, Optional[str]] = {}


def scheme_name_to_slug(name: str) -> str:
    """'Nippon India Multi Cap Fund - Direct - Growth' → 'nippon-india-multi-cap-fund-direct-growth'."""
    s = name.lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)            # remove parenthetical
    s = re.sub(r"\bplan\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


async def fetch_page(slug: str) -> Optional[str]:
    url = f"{BASE_URL}/{slug}"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 404:
                logger.info(f"groww slug not found: {slug}")
                return None
            r.raise_for_status()
            return r.text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"groww fetch failed for {slug}: {e}")
        return None


async def search_slug(scheme_name: str) -> Optional[str]:
    """Resolve scheme_name → Groww slug via their public search API.

    Returns the `search_id` of the top matching Scheme result, or None.
    Used as a fallback when deterministic slug 404s.

    Concurrent calls for the same query are coalesced (single in-flight
    request per scheme_name) and the result is memoised for the process
    lifetime to avoid tripping Groww's WAF on cold-cache bursts.
    """
    key = (scheme_name or "").strip().lower()
    if not key:
        return None
    if key in _search_cache:
        return _search_cache[key]
    lock = _search_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if key in _search_cache:  # double-check after acquiring lock
            return _search_cache[key]
        url = "https://groww.in/v1/api/search/v3/query/global/st_query"
        params = {"q": scheme_name, "from": "0", "size": "5"}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        slug: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
                r = await c.get(url, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()
            hits = (data.get("data") or {}).get("content") or []
            for h in hits:
                if h.get("sub_entity_type") == "Scheme" and h.get("search_id"):
                    slug = h["search_id"]
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"groww search failed for {scheme_name!r}: {e}")
        _search_cache[key] = slug
        return slug


# ── Regexes ──────────────────────────────────────────────────────────────
_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*holdings_row__[^"]*"[^>]*>(.*?)</tr>',
    re.DOTALL,
)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_STOCK_LINK_RE = re.compile(
    r'href="(/stocks/[^"]+)"[^>]*>(?:<span[^>]*>)?([^<]+)',
    re.IGNORECASE,
)
_TAG_STRIP = re.compile(r"<[^>]+>")

_AUM_RE = re.compile(r"Fund size \(AUM\)</div><div[^>]*>\u20b9\s*([\d,\.]+)\s*Cr", re.IGNORECASE)
_NAV_RE = re.compile(r"NAV[:\s][^<]{0,40}</div><div[^>]*>\u20b9\s*([\d,\.]+)", re.IGNORECASE)
_EXPENSE_RE = re.compile(r"Expense ratio[^0-9]{0,60}?([\d\.]+)\s*%", re.IGNORECASE)


def _clean(s: str) -> str:
    return unescape(_TAG_STRIP.sub("", s)).strip()


def parse_page(html: str) -> Optional[Dict[str, Any]]:
    """Parse Groww HTML → structured dict. Returns None if holdings missing."""
    if not html:
        return None

    # ── Holdings (scoped to holdings_row__) ──
    holdings: List[Dict[str, Any]] = []
    seen: set = set()
    for row_html in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row_html)
        if len(cells) < 4:
            continue
        c_name, c_sector, c_type, c_pct = cells[0], cells[1], cells[2], cells[3]
        m = _STOCK_LINK_RE.search(c_name)
        if m:
            slug = m.group(1).strip("/")
            name = unescape(m.group(2)).strip()
        else:
            slug = None
            name = _clean(c_name)
        if not name or name.lower() in ("name", "total"):
            continue
        if name in seen:
            continue
        seen.add(name)
        pct_txt = _clean(c_pct).replace("%", "").replace(",", "")
        try:
            pct = float(pct_txt)
        except ValueError:
            continue
        holdings.append({
            "name": name,
            "stock_slug": slug,
            "sector": _clean(c_sector),
            "instrument_type": _clean(c_type),
            "pct": pct,
        })

    if not holdings:
        return None

    # ── Sector allocation (aggregated from holdings) ──
    sector_map: Dict[str, float] = {}
    for h in holdings:
        sec = h["sector"] or "Unclassified"
        sector_map[sec] = sector_map.get(sec, 0.0) + h["pct"]
    sectors = sorted(
        [{"name": k, "pct": round(v, 2)} for k, v in sector_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # ── Equity/Debt/Cash split (aggregated from holdings instrument_type) ──
    split_map: Dict[str, float] = {}
    for h in holdings:
        t = (h["instrument_type"] or "Other").strip()
        split_map[t] = split_map.get(t, 0.0) + h["pct"]
    equity = split_map.get("Equity", 0.0)
    debt = sum(v for k, v in split_map.items() if k in ("Debt", "Corporate Bonds", "Government Securities", "Treasury Bills"))
    cash = split_map.get("Cash", 0.0) + split_map.get("Cash Equivalents", 0.0)
    split = {"equity": round(equity, 2), "debt": round(debt, 2), "cash": round(cash, 2)}

    # ── Metadata ──
    def _first(pat):
        m = pat.search(html)
        return m.group(1).replace(",", "") if m else None

    aum = _first(_AUM_RE)
    nav = _first(_NAV_RE)
    expense = _first(_EXPENSE_RE)

    return {
        "holdings": holdings,
        "sectors": sectors,
        "split": split,
        "metadata": {
            "aum_cr": float(aum) if aum else None,
            "nav": float(nav) if nav else None,
            "expense_ratio": float(expense) if expense else None,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "groww",
    }


def validate(parsed: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    h = parsed.get("holdings", [])
    if not h:
        reasons.append("no holdings parsed")
    tot = sum(x["pct"] for x in h)
    if not (70 <= tot <= 115):
        reasons.append(f"holdings sum {tot:.1f}% out of expected 70-115 range")
    if len(h) < 5:
        reasons.append(f"only {len(h)} holdings (likely partial)")
    meta = parsed.get("metadata", {}) or {}
    aum = meta.get("aum_cr")
    nav = meta.get("nav")
    if aum is not None and aum <= 0:
        reasons.append(f"metadata AUM non-positive: {aum}")
    if nav is not None and nav <= 0:
        reasons.append(f"metadata NAV non-positive: {nav}")
    parsed["valid"] = not reasons
    parsed["validation_issues"] = reasons
    return parsed


async def fetch_fund(scheme_name: str, explicit_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch + parse a fund. Resolution order:

    1. `explicit_slug` (passed by caller / cached slug)
    2. Deterministic slug from `scheme_name_to_slug`
    3. Search API fallback — Groww public `st_query`
    """
    slug = explicit_slug or scheme_name_to_slug(scheme_name)
    html = await fetch_page(slug)
    if not html and not explicit_slug:
        # Fall back to Groww search API
        resolved = await search_slug(scheme_name)
        if resolved and resolved != slug:
            slug = resolved
            html = await fetch_page(slug)
    if not html:
        return None
    parsed = parse_page(html)
    if not parsed:
        return None
    parsed["slug"] = slug
    parsed["scheme_name"] = scheme_name
    return validate(parsed)
