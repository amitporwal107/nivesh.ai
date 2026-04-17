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
    """Validate parsed holdings against masterdata. Fix ISINs, names, prices, and quantities."""
    amfi = _load_amfi()
    nse = _load_nse()
    enriched = []

    for h in holdings:
        isin = h.get("ticker", "")
        name = h.get("name", "")
        asset_type = h.get("asset_type", "")
        qty = h.get("quantity", 0)
        parsed_price = h.get("current_price", 0)
        parsed_value = qty * parsed_price

        # 1. Check if ISIN exists in masterdata
        master = lookup_isin(isin)
        if master:
            # Enrich garbled names
            if len(name) < 5 or not any(c.isalpha() for c in name):
                h["name"] = master["name"]

            master_price = master["price"]

            # Fix MF NAV/units using AMFI data
            if asset_type == "mutual_fund" and master["source"] == "amfi" and master_price > 0:
                # If parsed price is way off from AMFI NAV, the parser likely swapped units/NAV
                if parsed_price > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.2:
                    # Check if the parsed "units" is actually the NAV and vice versa
                    if qty > 0 and abs(qty - master_price) / max(master_price, 1) < 0.1:
                        # Swap: what parser called "units" is actually the NAV
                        old_qty, old_price = qty, parsed_price
                        h["current_price"] = round(master_price, 4)
                        h["quantity"] = round(parsed_value / master_price, 4) if master_price > 0 else 0
                        logger.info(f"Fixed swap: {name[:30]} qty={old_qty}→{h['quantity']:.3f} nav={old_price}→{master_price}")
                    else:
                        # Just correct the NAV and recalc units from the parsed value
                        old_price = parsed_price
                        h["current_price"] = round(master_price, 4)
                        if parsed_value > 0:
                            h["quantity"] = round(parsed_value / master_price, 4)
                        logger.info(f"NAV corrected: {name[:30]} nav={old_price}→{master_price}")

            # Fix equity price using NSE data
            if asset_type == "equity" and master["source"] == "nse" and master_price > 0:
                if parsed_price > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.3:
                    # Price is wrong — recalculate qty from value/nse_price
                    if parsed_value > 0:
                        new_qty = round(parsed_value / master_price)
                        h["quantity"] = new_qty
                        h["current_price"] = round(master_price, 2)
                        h["buy_price"] = round(master_price, 2)
                        logger.info(f"Equity price fix: {name[:30]} price→{master_price}, qty→{new_qty}")
                elif parsed_price == 0 and parsed_value == 0 and qty == 0:
                    # Holding with no value — just set the price
                    h["current_price"] = round(master_price, 2)
                    h["buy_price"] = round(master_price, 2)

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
                if info["price"] > 0:
                    master_price = info["price"]
                    # Fix price and recalculate qty
                    if parsed_value > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.3:
                        h["current_price"] = round(master_price, 4)
                        h["buy_price"] = round(master_price, 4)
                        h["quantity"] = round(parsed_value / master_price, 4) if master_price > 0 else qty
                    elif parsed_price == 0:
                        h["current_price"] = round(master_price, 4)
                        h["buy_price"] = round(master_price, 4)
                enriched.append(h)
                continue

        # 3. No match found — keep as-is
        enriched.append(h)

    return enriched
