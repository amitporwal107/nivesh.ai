"""Groww MF data fetcher + deterministic parser.

Fetches groww.in/mutual-funds/{slug} and parses:
  - top holdings (name, sector, %)
  - sector allocation (name, %)
  - equity/debt/cash split
  - ratios (P/E, P/B, Alpha, Beta, Sharpe, Sortino)
  - metadata (AUM, NAV, expense ratio, rating, category)

Polite fetching: custom User-Agent, 3s timeout, no retries (caller handles).
"""
from __future__ import annotations
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "nivesh.ai portfolio tracker (contact: support@nivesh.ai)"
BASE_URL = "https://groww.in/mutual-funds"
TIMEOUT_S = 15.0


def scheme_name_to_slug(name: str) -> str:
    """Convert 'Nippon India Multi Cap Fund - Direct - Growth' → 'nippon-india-multi-cap-fund-direct-growth'."""
    s = name.lower().strip()
    # Strip common suffixes/junk
    s = re.sub(r"\(.*?\)", " ", s)  # remove parenthesised
    s = re.sub(r"\bplan\b", " ", s)  # strip 'plan' tokens
    s = re.sub(r"[^a-z0-9]+", "-", s)  # non-alphanum → hyphens
    s = re.sub(r"-+", "-", s).strip("-")
    return s


async def fetch_page(slug: str) -> Optional[str]:
    """Fetch raw HTML. Returns None on any error."""
    url = f"{BASE_URL}/{slug}"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 404:
                logger.info(f"groww slug not found: {slug}")
                return None
            r.raise_for_status()
            return r.text
    except Exception as e:
        logger.warning(f"groww fetch failed for {slug}: {e}")
        return None


# ── Parsers (lightweight regex on HTML text) ─────────────────────────────

_HOLDING_ROW_RE = re.compile(
    r'<tr[^>]*>.*?'                                   # row start
    r'(?:<td[^>]*>.*?<a[^>]*href="(/stocks/[^"]+)"[^>]*>([^<]+)</a>|<td[^>]*>([^<]+))</td>'  # col 1: name (linked) or plain
    r'.*?<td[^>]*>([^<]+)</td>'                        # col 2: sector
    r'.*?<td[^>]*>([^<]+)</td>'                        # col 3: instrument type
    r'.*?<td[^>]*>([0-9.]+)\s*%?</td>'                 # col 4: %
    r'.*?</tr>',
    re.DOTALL | re.IGNORECASE,
)

_AUM_RE = re.compile(r"Fund\s*size[^0-9]*\u20b9?\s*([0-9,\.]+)\s*Cr", re.IGNORECASE)
_NAV_RE = re.compile(r"NAV:\s*[^\u20b9]*\u20b9\s*([0-9,\.]+)", re.IGNORECASE)
_EXPENSE_RE = re.compile(r"Expense\s*ratio[^0-9]*([0-9\.]+)\s*%", re.IGNORECASE)
_RATING_RE = re.compile(r"Rating\s*[^0-9]*([0-5])", re.IGNORECASE)
_SPLIT_RE = re.compile(r"Equity\s*([0-9\.]+)\s*%.*?Debt\s*([0-9\.]+)\s*%.*?Cash\s*([0-9\.]+)\s*%", re.DOTALL | re.IGNORECASE)
_SECTOR_RE = re.compile(r"([A-Z][A-Za-z &]+?)\s*([0-9\.]+)\s*%", re.IGNORECASE)


def parse_page(html: str) -> Optional[Dict[str, Any]]:
    """Parse Groww HTML → structured dict. Returns None if table not found."""
    if not html or "Holdings" not in html:
        return None

    # --- Holdings ---
    holdings: List[Dict[str, Any]] = []
    for m in _HOLDING_ROW_RE.finditer(html):
        linked_slug, linked_name, plain_name, sector, instr_type, pct = m.groups()
        name = (linked_name or plain_name or "").strip()
        if not name or name.lower() in ("name", "total"):
            continue
        try:
            pct_f = float(pct.strip())
        except (ValueError, AttributeError):
            continue
        holdings.append({
            "name": name,
            "stock_slug": linked_slug.strip("/") if linked_slug else None,
            "sector": (sector or "").strip(),
            "instrument_type": (instr_type or "").strip(),
            "pct": pct_f,
        })

    if not holdings:
        return None

    # --- Metadata ---
    def _first(re_obj, default=None):
        m = re_obj.search(html)
        return m.group(1).replace(",", "") if m else default

    aum = _first(_AUM_RE)
    nav = _first(_NAV_RE)
    expense = _first(_EXPENSE_RE)
    rating = _first(_RATING_RE)

    # --- Equity/Debt/Cash split ---
    split = None
    sm = _SPLIT_RE.search(html)
    if sm:
        try:
            split = {
                "equity": float(sm.group(1)),
                "debt": float(sm.group(2)),
                "cash": float(sm.group(3)),
            }
        except ValueError:
            split = None

    # --- Sector allocation (from "Equity sector allocation" region) ---
    sectors: List[Dict[str, Any]] = []
    sec_region = html
    m = re.search(r"Equity sector allocation(.*?)(?:Advanced ratios|Min\. investments|Minimum investments)", html, re.DOTALL | re.IGNORECASE)
    if m:
        sec_region = m.group(1)
    for match in _SECTOR_RE.finditer(sec_region):
        sec_name = match.group(1).strip()
        try:
            pct = float(match.group(2))
        except ValueError:
            continue
        if 0 < pct < 100 and len(sec_name) > 2:
            sectors.append({"name": sec_name, "pct": pct})
    # dedupe by name, keep max
    sector_map: Dict[str, float] = {}
    for s in sectors:
        sector_map[s["name"]] = max(sector_map.get(s["name"], 0), s["pct"])
    sectors = [{"name": k, "pct": v} for k, v in sector_map.items()]
    sectors.sort(key=lambda x: x["pct"], reverse=True)

    return {
        "holdings": holdings,
        "sectors": sectors[:15],  # cap noise
        "split": split,
        "metadata": {
            "aum_cr": float(aum) if aum else None,
            "nav": float(nav) if nav else None,
            "expense_ratio": float(expense) if expense else None,
            "rating": int(rating) if rating else None,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "groww",
    }


def validate(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Sanity checks — returns parsed dict with 'valid': bool + reasons[]."""
    reasons: List[str] = []
    h = parsed.get("holdings", [])
    if not h:
        reasons.append("no holdings parsed")
    tot = sum(x["pct"] for x in h)
    if not (80 <= tot <= 110):
        reasons.append(f"holdings sum {tot:.1f}% out of expected 80-110 range")
    if len(h) < 5:
        reasons.append(f"only {len(h)} holdings (likely partial)")
    parsed["valid"] = not reasons
    parsed["validation_issues"] = reasons
    return parsed


async def fetch_fund(scheme_name: str, explicit_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Convenience wrapper — name → slug → fetch → parse → validate."""
    slug = explicit_slug or scheme_name_to_slug(scheme_name)
    html = await fetch_page(slug)
    if not html:
        return None
    parsed = parse_page(html)
    if not parsed:
        return None
    parsed["slug"] = slug
    parsed["scheme_name"] = scheme_name
    return validate(parsed)
