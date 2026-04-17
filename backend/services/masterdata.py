"""
Masterdata for ISIN validation, name-based fallback matching, and NAV cross-reference.
Sources: AMFI NAV (mutual funds), NSE Bhav Copy (equities/ETFs/SGBs).
"""
import csv
import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz, process

logger = logging.getLogger("masterdata")

# Paths
AMFI_NAV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "NAVAll.txt")
NSE_BHAV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bhav_copy.csv")

# Caches
_amfi_cache: Optional[Dict] = None
_nse_cache: Optional[Dict] = None
_name_index: Optional[Dict] = None


def _load_amfi() -> Dict[str, dict]:
    """Load AMFI NAV data: ISIN → {name, nav, scheme_code}"""
    global _amfi_cache
    if _amfi_cache is not None:
        return _amfi_cache

    _amfi_cache = {}
    if not os.path.exists(AMFI_NAV_PATH):
        logger.warning(f"AMFI NAV file not found: {AMFI_NAV_PATH}")
        return _amfi_cache

    with open(AMFI_NAV_PATH, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split(";")
            if len(parts) >= 5:
                scheme_code = parts[0].strip()
                isin_growth = parts[1].strip()
                isin_reinv = parts[2].strip()
                name = parts[3].strip()
                try:
                    nav = float(parts[4].strip())
                except (ValueError, IndexError):
                    nav = 0.0

                entry = {"name": name, "nav": nav, "scheme_code": scheme_code}
                if isin_growth and isin_growth.startswith("INF"):
                    _amfi_cache[isin_growth] = entry
                if isin_reinv and isin_reinv.startswith("INF"):
                    _amfi_cache[isin_reinv] = entry

    logger.info(f"Loaded {len(_amfi_cache)} AMFI MF ISINs")
    return _amfi_cache


def _load_nse() -> Dict[str, dict]:
    """Load NSE Bhav Copy: ISIN → {name, symbol, price, series}"""
    global _nse_cache
    if _nse_cache is not None:
        return _nse_cache

    _nse_cache = {}
    if not os.path.exists(NSE_BHAV_PATH):
        logger.warning(f"NSE Bhav file not found: {NSE_BHAV_PATH}")
        return _nse_cache

    with open(NSE_BHAV_PATH, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            isin = row.get("ISIN", "").strip()
            if not isin.startswith("IN"):
                continue
            name = row.get("FinInstrmNm", "").strip()
            symbol = row.get("TckrSymb", "").strip()
            series = row.get("SctySrs", "").strip()
            try:
                price = float(row.get("ClsPric", 0))
            except (ValueError, TypeError):
                price = 0.0

            _nse_cache[isin] = {
                "name": name,
                "symbol": symbol,
                "price": price,
                "series": series,
            }

    logger.info(f"Loaded {len(_nse_cache)} NSE securities")
    return _nse_cache


def _build_name_index() -> Dict[str, List[Tuple[str, str]]]:
    """Build name → [(isin, source)] index for fuzzy matching."""
    global _name_index
    if _name_index is not None:
        return _name_index

    _name_index = {}
    amfi = _load_amfi()
    nse = _load_nse()

    for isin, info in amfi.items():
        key = _normalize_name(info["name"])
        _name_index.setdefault(key, []).append((isin, "amfi"))

    for isin, info in nse.items():
        key = _normalize_name(info["name"])
        _name_index.setdefault(key, []).append((isin, "nse"))
        # Also index by symbol
        if info["symbol"]:
            sym_key = info["symbol"].lower()
            _name_index.setdefault(sym_key, []).append((isin, "nse"))

    logger.info(f"Name index: {len(_name_index)} unique names")
    return _name_index


def _normalize_name(name: str) -> str:
    """Normalize company/scheme name for matching."""
    name = name.lower()
    # Remove common suffixes
    for suffix in ["limited", "ltd", "ltd.", "- growth", "- direct plan", "- regular plan",
                   "direct plan", "regular plan", "growth option", "growth", "- idcw", "idcw"]:
        name = name.replace(suffix, "")
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def lookup_isin(isin: str) -> Optional[dict]:
    """Look up an ISIN in masterdata. Returns {name, price/nav, source}."""
    amfi = _load_amfi()
    nse = _load_nse()

    if isin in amfi:
        info = amfi[isin]
        return {"name": info["name"], "price": info["nav"], "source": "amfi"}
    if isin in nse:
        info = nse[isin]
        return {"name": info["name"], "price": info["price"], "source": "nse"}
    return None


def find_isin_by_name(name: str, asset_type: str = "") -> Optional[Tuple[str, dict]]:
    """Fuzzy match a holding name to find its ISIN from masterdata."""
    amfi = _load_amfi()
    nse = _load_nse()

    normalized = _normalize_name(name)
    if not normalized or len(normalized) < 3:
        return None

    best_match = None
    best_score = 0

    # Search in appropriate source based on asset type
    search_pool = []
    if asset_type in ("mutual_fund", "etf", ""):
        for isin, info in amfi.items():
            search_pool.append((isin, info["name"], info["nav"], "amfi"))
    if asset_type in ("equity", "etf", "gold", ""):
        for isin, info in nse.items():
            search_pool.append((isin, info["name"], info["price"], "nse"))

    # Use rapidfuzz for efficient matching
    choices = {f"{isin}|{src}": _normalize_name(sname) for isin, sname, _, src in search_pool}
    if not choices:
        return None

    results = process.extract(normalized, choices, scorer=fuzz.token_sort_ratio, limit=3)
    for key, score, _ in results:
        if score >= 70:
            parts = key.split("|", 1)
            if len(parts) != 2:
                continue
            isin, src = parts
            for pool_isin, pool_name, pool_price, pool_src in search_pool:
                if pool_isin == isin and pool_src == src:
                    if score > best_score:
                        best_score = score
                        best_match = (isin, {"name": pool_name, "price": pool_price, "source": src, "score": score})
                    break

    return best_match


def validate_and_enrich_holdings(holdings: list) -> list:
    """Validate parsed holdings against masterdata. Fix ISINs and enrich with correct names/prices."""
    amfi = _load_amfi()
    nse = _load_nse()
    enriched = []

    for h in holdings:
        isin = h.get("ticker", "")
        name = h.get("name", "")
        asset_type = h.get("asset_type", "")

        # 1. Check if ISIN exists in masterdata
        master = lookup_isin(isin)
        if master:
            # ISIN validated — enrich with masterdata name if current name is short/garbled
            if len(name) < 5 or not any(c.isalpha() for c in name):
                h["name"] = master["name"]
            # Cross-reference price (NAV for MFs)
            if asset_type == "mutual_fund" and master["source"] == "amfi":
                master_nav = master["price"]
                parsed_nav = h.get("current_price", 0)
                if master_nav > 0 and parsed_nav > 0:
                    # If parsed NAV is way off from AMFI NAV, use AMFI NAV
                    if abs(master_nav - parsed_nav) / max(master_nav, 1) > 0.1:
                        # Recalculate using AMFI NAV
                        old_val = h["quantity"] * parsed_nav
                        h["current_price"] = round(master_nav, 4)
                        logger.info(f"NAV corrected: {name[:30]} OCR={parsed_nav} → AMFI={master_nav}")
            enriched.append(h)
            continue

        # 2. ISIN not found — try fuzzy name matching
        if name and len(name) >= 3:
            match = find_isin_by_name(name, asset_type)
            if match:
                new_isin, info = match
                logger.info(f"Name match: '{name[:30]}' → {new_isin} ({info['name'][:30]}) score={info['score']}")
                h["ticker"] = new_isin
                h["name"] = info["name"]
                # Use masterdata price if parsed price is 0 or way off
                if info["price"] > 0 and (h["current_price"] == 0 or h["buy_price"] == 0):
                    h["current_price"] = round(info["price"], 4)
                    h["buy_price"] = round(info["price"], 4)
                enriched.append(h)
                continue

        # 3. No match found — keep as-is
        enriched.append(h)

    return enriched
