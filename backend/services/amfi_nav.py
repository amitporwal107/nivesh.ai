"""AMFI NAV Service — fetches and caches live NAV data from AMFI India."""
import httpx
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Updated URL - AMFI redirects to portal subdomain
AMFI_NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"

# In-memory cache
_nav_cache = {}
_cache_timestamp = 0
CACHE_TTL = 3600  # 1 hour

# ETF detection: AMFI NAVAll.txt includes ETFs (Gold ETF, Nifty ETF, Bank ETF, etc.)
# because SEBI requires AMFI to publish their iNAV. However ETFs are equity instruments
# that trade on NSE/BSE — their prices come from prices_eod (security_master), not
# from AMFI NAV. Any holding matching an ETF scheme must use the equity price path.
# Substring matching on scheme_name is sufficient — AMFI always includes "ETF" in the name.
_ETF_NAME_MARKERS = ("ETF", "EXCHANGE TRADED FUND", " BEES", " BEES ")


def _is_etf_scheme(scheme_name: str) -> bool:
    """Return True if the AMFI scheme is a true ETF equity instrument.

    A Fund of Funds (FoF) that *invests in* ETFs is still a mutual fund —
    it has AMFI NAV, AMFI ISIN, and belongs in the MF benchmark pipeline.
    e.g. "Mirae Asset NYSE FANG+ ETF Fund of Fund" → MF, NOT an ETF.
    Only schemes that ARE the exchange-traded instrument itself are ETFs.
    """
    name_upper = scheme_name.upper()
    # FoF schemes contain "FUND OF FUND" — exclude them regardless of other keywords
    if "FUND OF FUND" in name_upper or "FOF" in name_upper:
        return False
    return any(marker in name_upper for marker in _ETF_NAME_MARKERS)


async def fetch_nav_data() -> dict:
    """Fetch and parse all NAV data from AMFI. Returns dict keyed by ISIN and scheme name."""
    global _nav_cache, _cache_timestamp

    if _nav_cache and (time.time() - _cache_timestamp) < CACHE_TTL:
        return _nav_cache

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(AMFI_NAV_URL)
            resp.raise_for_status()

        nav_map = {}
        for line in resp.text.split("\n"):
            parts = line.strip().split(";")
            if len(parts) < 6:
                continue
            try:
                scheme_code = parts[0].strip()
                isin_growth = parts[1].strip()
                isin_reinvest = parts[2].strip()
                scheme_name = parts[3].strip()
                nav_str = parts[4].strip()
                nav_date = parts[5].strip()

                if not nav_str or nav_str == "N.A." or nav_str == "N/A":
                    continue

                nav = float(nav_str)
                if nav <= 0:
                    continue

                entry = {
                    "scheme_code": scheme_code,
                    "scheme_name": scheme_name,
                    "nav": nav,
                    "date": nav_date,
                    "isin_growth": isin_growth,
                    "isin_reinvest": isin_reinvest,
                    # ETF flag — callers must route ETF ISINs to the equity price
                    # pipeline (security_master → prices_eod), not to MF NAV logic.
                    "is_etf": _is_etf_scheme(scheme_name),
                }

                # Key by ISIN (both growth and reinvest)
                if isin_growth and isin_growth != "-":
                    nav_map[isin_growth.upper()] = entry
                if isin_reinvest and isin_reinvest != "-":
                    nav_map[isin_reinvest.upper()] = entry

                # Also key by normalized scheme name
                nav_map[scheme_name.lower()] = entry

            except (ValueError, IndexError):
                continue

        _nav_cache = nav_map
        _cache_timestamp = time.time()
        logger.info("AMFI NAV loaded: %d entries", len(nav_map))
        return nav_map

    except Exception as e:
        logger.error("Failed to fetch AMFI NAV: %s", e)
        return _nav_cache  # Return stale cache if available


def _normalize_name(name: str) -> str:
    """Normalize fund name for matching."""
    return name.lower().replace(" - ", " ").replace("  ", " ").strip()


async def lookup_nav(isin: str = "", name: str = "") -> Optional[dict]:
    """Look up NAV by ISIN or fund name. Returns {nav, date, scheme_name} or None."""
    nav_map = await fetch_nav_data()
    if not nav_map:
        return None

    # Try exact ISIN match
    if isin:
        isin_upper = isin.upper().strip()
        if isin_upper in nav_map:
            return nav_map[isin_upper]

    # Try name match
    if name:
        name_lower = _normalize_name(name)
        if name_lower in nav_map:
            return nav_map[name_lower]

        # Fuzzy: try partial match
        for key, entry in nav_map.items():
            if isinstance(key, str) and not key.startswith("INF"):
                if name_lower[:30] in key or key[:30] in name_lower:
                    return entry

    return None


async def update_holdings_nav(holdings: list) -> list:
    """Update holdings with live NAV from AMFI where possible. Returns updated holdings."""
    nav_map = await fetch_nav_data()
    if not nav_map:
        return holdings

    updated = []
    for h in holdings:
        if h.get("asset_type") != "mutual_fund":
            updated.append(h)
            continue

        isin = (h.get("ticker") or "").upper().strip()
        name = h.get("name", "")

        nav_entry = None
        if isin and isin in nav_map:
            nav_entry = nav_map[isin]
        elif name:
            norm = _normalize_name(name)
            if norm in nav_map:
                nav_entry = nav_map[norm]
            else:
                for key, entry in nav_map.items():
                    if isinstance(key, str) and not key.startswith("INF"):
                        if norm[:25] in key:
                            nav_entry = entry
                            break

        if nav_entry:
            h["current_price"] = nav_entry["nav"]
            h["nav_date"] = nav_entry["date"]
            h["nav_source"] = "AMFI"

        updated.append(h)

    return updated
