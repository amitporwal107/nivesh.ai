"""
Masterdata for ISIN validation, name-based fallback matching, and NAV cross-reference.

Sources (all local, DPDP-compliant, no cloud calls):
  - AMFI CSV (amfi_data.csv)      → Mutual Fund NAV, plan (Direct/Regular),
                                    option (Growth/IDCW/Dividend), scheme name, date.
                                    Growth/Direct/IDCW are treated as SEPARATE classifications.
  - NSE BhavCopy (bhav_copy.csv)  → Daily close price for Equity/ETF/SGB (keyed by ISIN).
  - NSE Equity List (equity_list.csv) → Equity master: ISIN ↔ Symbol ↔ Company name ↔
                                    Face value ↔ Series. Used when BhavCopy has no row.
  - NSE SGB Market Watch (sgb_data.csv) → SGB LTP / issue price by symbol.
                                    Merged with BhavCopy for ISIN enrichment.
"""
import csv
import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz, process

logger = logging.getLogger("masterdata")

# ── Paths ──────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
AMFI_CSV_PATH = os.path.join(_DATA_DIR, "amfi_data.csv")
NSE_BHAV_PATH = os.path.join(_DATA_DIR, "bhav_copy.csv")
EQUITY_LIST_PATH = os.path.join(_DATA_DIR, "equity_list.csv")
SGB_CSV_PATH = os.path.join(_DATA_DIR, "sgb_data.csv")
# Legacy path (fallback)
AMFI_LEGACY_PATH = os.path.join(_DATA_DIR, "NAVAll.txt")

# ── Caches ─────────────────────────────────────────────────────
_amfi_cache: Optional[Dict] = None
_nse_cache: Optional[Dict] = None
_equity_master_cache: Optional[Dict] = None
_sgb_cache: Optional[Dict] = None
_name_index: Optional[Dict] = None


# ══════════════════════════════════════════════════════════════
# Loaders
# ══════════════════════════════════════════════════════════════

def _classify_mf_scheme(name: str) -> Tuple[str, str]:
    """
    Extract (plan, option) from scheme name.
    plan: 'Direct' | 'Regular' | 'Unknown'
    option: 'Growth' | 'IDCW' | 'Dividend Payout' | 'Dividend Reinvestment' | 'Unknown'
    """
    n = name.lower()
    plan = "Direct" if "direct" in n else ("Regular" if "regular" in n else "Unknown")

    if "growth" in n:
        option = "Growth"
    elif "idcw" in n:
        if "reinv" in n:
            option = "IDCW Reinvestment"
        elif "payout" in n:
            option = "IDCW Payout"
        else:
            option = "IDCW"
    elif "dividend" in n:
        option = "Dividend Reinvestment" if "reinv" in n else "Dividend Payout"
    elif "bonus" in n:
        option = "Bonus"
    else:
        option = "Growth"  # sensible default for schemes without explicit suffix
    return plan, option


def _load_amfi() -> Dict[str, dict]:
    """
    Load AMFI NAV CSV. Each ISIN → entry with NAV, plan, option, scheme name.
    Treats Growth/Direct/IDCW as separate classifications (distinct ISINs already
    in source file), but annotates each with structured plan/option metadata.
    """
    global _amfi_cache
    if _amfi_cache is not None:
        return _amfi_cache

    _amfi_cache = {}

    # Prefer the new AMFI CSV
    if os.path.exists(AMFI_CSV_PATH):
        try:
            with open(AMFI_CSV_PATH, encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    scheme_code = (row.get("Scheme Code") or "").strip()
                    isin_growth = (row.get("ISIN Div Payout/ ISIN Growth") or "").strip()
                    isin_reinv = (row.get("ISIN Div Reinvestment") or "").strip()
                    name = (row.get("Scheme Name") or "").strip()
                    nav_str = (row.get("Net Asset Value") or "").strip()
                    date = (row.get("Date") or "").strip()
                    try:
                        nav = float(nav_str)
                    except (ValueError, TypeError):
                        nav = 0.0

                    if nav <= 0 or not name:
                        continue

                    plan, option = _classify_mf_scheme(name)
                    entry = {
                        "name": name,
                        "nav": nav,
                        "scheme_code": scheme_code,
                        "plan": plan,
                        "option": option,
                        "date": date,
                        "isin_growth": isin_growth if isin_growth.startswith("INF") else "",
                        "isin_reinv": isin_reinv if isin_reinv.startswith("INF") else "",
                    }
                    if isin_growth.startswith("INF"):
                        _amfi_cache[isin_growth] = entry
                    if isin_reinv.startswith("INF"):
                        _amfi_cache[isin_reinv] = entry
            logger.info(f"Loaded {len(_amfi_cache)} AMFI MF ISINs from CSV")
            return _amfi_cache
        except Exception as e:
            logger.warning(f"AMFI CSV load failed: {e}. Falling back to legacy format.")

    # Legacy fallback: semicolon-separated NAVAll.txt
    if os.path.exists(AMFI_LEGACY_PATH):
        with open(AMFI_LEGACY_PATH, encoding="utf-8", errors="ignore") as f:
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
                    if nav <= 0:
                        continue
                    plan, option = _classify_mf_scheme(name)
                    entry = {
                        "name": name, "nav": nav, "scheme_code": scheme_code,
                        "plan": plan, "option": option, "date": "",
                        "isin_growth": isin_growth if isin_growth.startswith("INF") else "",
                        "isin_reinv": isin_reinv if isin_reinv.startswith("INF") else "",
                    }
                    if isin_growth.startswith("INF"):
                        _amfi_cache[isin_growth] = entry
                    if isin_reinv.startswith("INF"):
                        _amfi_cache[isin_reinv] = entry
        logger.info(f"Loaded {len(_amfi_cache)} AMFI MF ISINs from legacy NAVAll.txt")
    else:
        logger.warning("No AMFI masterdata source found")

    return _amfi_cache


def _load_nse() -> Dict[str, dict]:
    """Load NSE BhavCopy: ISIN → {name, symbol, price, series}."""
    global _nse_cache
    if _nse_cache is not None:
        return _nse_cache

    _nse_cache = {}
    if not os.path.exists(NSE_BHAV_PATH):
        logger.warning(f"NSE BhavCopy not found: {NSE_BHAV_PATH}")
        return _nse_cache

    with open(NSE_BHAV_PATH, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            isin = (row.get("ISIN") or "").strip()
            if not isin.startswith("IN"):
                continue
            name = (row.get("FinInstrmNm") or "").strip()
            symbol = (row.get("TckrSymb") or "").strip()
            series = (row.get("SctySrs") or "").strip()
            try:
                price = float(row.get("ClsPric") or 0)
            except (ValueError, TypeError):
                price = 0.0
            _nse_cache[isin] = {
                "name": name, "symbol": symbol, "price": price, "series": series,
            }

    logger.info(f"Loaded {len(_nse_cache)} NSE securities (BhavCopy)")
    return _nse_cache


def _load_equity_master() -> Dict[str, dict]:
    """
    Load NSE Equity List: ISIN → {symbol, company, series, face_value}.
    Provides equity master data independent of daily BhavCopy (static list).
    """
    global _equity_master_cache
    if _equity_master_cache is not None:
        return _equity_master_cache

    _equity_master_cache = {}
    if not os.path.exists(EQUITY_LIST_PATH):
        logger.warning(f"NSE Equity List not found: {EQUITY_LIST_PATH}")
        return _equity_master_cache

    with open(EQUITY_LIST_PATH, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        # Header has stray spaces e.g. " SERIES"
        for row in reader:
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            isin = row.get("ISIN NUMBER", "")
            if not isin.startswith("INE"):
                continue
            try:
                face_value = float(row.get("FACE VALUE") or 0)
            except (ValueError, TypeError):
                face_value = 0.0
            _equity_master_cache[isin] = {
                "symbol": row.get("SYMBOL", ""),
                "company": row.get("NAME OF COMPANY", ""),
                "series": row.get("SERIES", ""),
                "face_value": face_value,
            }

    logger.info(f"Loaded {len(_equity_master_cache)} NSE equity master rows")
    return _equity_master_cache


def _load_sgb() -> Dict[str, dict]:
    """
    Load SGB Market Watch CSV. Key by symbol → {issue_price, ltp, prev_close}.
    BhavCopy provides ISIN↔symbol for SGBs; this adds LTP & issue price.
    """
    global _sgb_cache
    if _sgb_cache is not None:
        return _sgb_cache

    _sgb_cache = {}
    if not os.path.exists(SGB_CSV_PATH):
        logger.warning(f"SGB CSV not found: {SGB_CSV_PATH}")
        return _sgb_cache

    def _num(s: str) -> float:
        if not s or s.strip() in ("-", ""):
            return 0.0
        try:
            return float(s.replace(",", "").strip())
        except ValueError:
            return 0.0

    with open(SGB_CSV_PATH, encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)
        # Normalize column keys (stripped of newlines/spaces)
        for raw in reader:
            row = {re.sub(r'\s+', ' ', (k or '').strip()).rstrip(':'): (v or '').strip()
                   for k, v in raw.items()}
            symbol = row.get("SYMBOL", "")
            if not symbol:
                continue
            _sgb_cache[symbol] = {
                "symbol": symbol,
                "issue_price": _num(row.get("ISSUE PRICE", "")),
                "ltp": _num(row.get("LTP", "")),
                "prev_close": _num(row.get("PREV. CLOSE", "")),
                "high_52w": _num(row.get("52W H", "")),
                "low_52w": _num(row.get("52W L", "")),
            }

    logger.info(f"Loaded {len(_sgb_cache)} SGB rows")
    return _sgb_cache


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

def _normalize_name(name: str) -> str:
    """Normalize company/scheme name for matching."""
    name = name.lower()
    for suffix in ["limited", "ltd", "ltd.", "- growth", "- direct plan", "- regular plan",
                   "direct plan", "regular plan", "growth option", "growth", "- idcw", "idcw"]:
        name = name.replace(suffix, "")
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _build_name_index() -> Dict[str, List[Tuple[str, str]]]:
    """Build name → [(isin, source)] index for fuzzy matching."""
    global _name_index
    if _name_index is not None:
        return _name_index

    _name_index = {}
    amfi = _load_amfi()
    nse = _load_nse()
    eq_master = _load_equity_master()

    for isin, info in amfi.items():
        key = _normalize_name(info["name"])
        _name_index.setdefault(key, []).append((isin, "amfi"))

    for isin, info in nse.items():
        key = _normalize_name(info["name"])
        _name_index.setdefault(key, []).append((isin, "nse"))
        if info["symbol"]:
            _name_index.setdefault(info["symbol"].lower(), []).append((isin, "nse"))

    for isin, info in eq_master.items():
        key = _normalize_name(info["company"])
        _name_index.setdefault(key, []).append((isin, "eq_master"))
        if info["symbol"]:
            _name_index.setdefault(info["symbol"].lower(), []).append((isin, "eq_master"))

    logger.info(f"Name index: {len(_name_index)} unique names")
    return _name_index


def lookup_isin(isin: str) -> Optional[dict]:
    """
    Look up an ISIN in masterdata. Returns {name, price, source, ...meta}.
    Priority: AMFI (MF) → NSE BhavCopy (equity/ETF/SGB) → Equity Master (no price).
    """
    amfi = _load_amfi()
    nse = _load_nse()
    eq_master = _load_equity_master()
    sgb = _load_sgb()

    if isin in amfi:
        info = amfi[isin]
        return {
            "name": info["name"], "price": info["nav"], "source": "amfi",
            "plan": info.get("plan"), "option": info.get("option"),
            "scheme_code": info.get("scheme_code"), "date": info.get("date"),
        }

    if isin in nse:
        info = nse[isin]
        result = {
            "name": info["name"], "price": info["price"], "source": "nse",
            "symbol": info["symbol"], "series": info["series"],
        }
        # Enrich SGB with issue price & LTP from market-watch CSV
        if info["series"] == "GB" and info["symbol"] in sgb:
            sgb_info = sgb[info["symbol"]]
            result["issue_price"] = sgb_info["issue_price"]
            if sgb_info["ltp"] > 0:
                result["price"] = sgb_info["ltp"]
        return result

    if isin in eq_master:
        info = eq_master[isin]
        return {
            "name": info["company"], "price": 0.0, "source": "equity_master",
            "symbol": info["symbol"], "series": info["series"],
            "face_value": info["face_value"],
        }

    return None


def find_isin_by_name(name: str, asset_type: str = "") -> Optional[Tuple[str, dict]]:
    """Fuzzy match a holding name to find its ISIN from masterdata."""
    amfi = _load_amfi()
    nse = _load_nse()
    eq_master = _load_equity_master()

    normalized = _normalize_name(name)
    if not normalized or len(normalized) < 3:
        return None

    search_pool = []
    if asset_type in ("mutual_fund", "etf", ""):
        for isin, info in amfi.items():
            search_pool.append((isin, info["name"], info["nav"], "amfi"))
    if asset_type in ("equity", "etf", "gold", ""):
        for isin, info in nse.items():
            search_pool.append((isin, info["name"], info["price"], "nse"))
        # Equity master fills in companies absent from today's BhavCopy
        for isin, info in eq_master.items():
            if isin not in nse:  # don't duplicate
                search_pool.append((isin, info["company"], 0.0, "eq_master"))

    choices = {f"{isin}|{src}": _normalize_name(sname) for isin, sname, _, src in search_pool}
    if not choices:
        return None

    best_match = None
    best_score = 0
    results = process.extract(normalized, choices, scorer=fuzz.token_sort_ratio, limit=3)
    for matched_text, score, key in results:
        if score >= 70:
            parts = key.split("|", 1)
            if len(parts) != 2:
                continue
            isin, src = parts
            for pool_isin, pool_name, pool_price, pool_src in search_pool:
                if pool_isin == isin and pool_src == src:
                    if score > best_score:
                        best_score = score
                        best_match = (isin, {
                            "name": pool_name, "price": pool_price,
                            "source": src, "score": score,
                        })
                    break

    return best_match


def validate_and_enrich_holdings(holdings: list) -> list:
    """Validate parsed holdings against masterdata. Fix ISINs, names, prices, and quantities."""
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

            # Attach MF classification metadata (plan/option)
            if master.get("source") == "amfi":
                if master.get("plan"):
                    h["plan"] = master["plan"]
                if master.get("option"):
                    h["option"] = master["option"]

            master_price = master.get("price", 0)

            # Fix MF NAV/units using AMFI data
            if asset_type == "mutual_fund" and master["source"] == "amfi" and master_price > 0:
                if parsed_price > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.2:
                    if qty > 0 and abs(qty - master_price) / max(master_price, 1) < 0.1:
                        old_qty, old_price = qty, parsed_price
                        h["current_price"] = round(master_price, 4)
                        h["quantity"] = round(parsed_value / master_price, 4) if master_price > 0 else 0
                        logger.info(f"Fixed swap: {name[:30]} qty={old_qty}→{h['quantity']:.3f} nav={old_price}→{master_price}")
                    else:
                        old_price = parsed_price
                        h["current_price"] = round(master_price, 4)
                        if parsed_value > 0:
                            h["quantity"] = round(parsed_value / master_price, 4)
                        logger.info(f"NAV corrected: {name[:30]} nav={old_price}→{master_price}")

            # Fix equity price using NSE data
            if asset_type == "equity" and master["source"] == "nse" and master_price > 0:
                if parsed_price > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.3:
                    if parsed_value > 0:
                        new_qty = round(parsed_value / master_price)
                        h["quantity"] = new_qty
                        h["current_price"] = round(master_price, 2)
                        h["buy_price"] = round(master_price, 2)
                        logger.info(f"Equity price fix: {name[:30]} price→{master_price}, qty→{new_qty}")
                elif parsed_price == 0 and parsed_value == 0 and qty == 0:
                    h["current_price"] = round(master_price, 2)
                    h["buy_price"] = round(master_price, 2)

            # SGB: use LTP from market-watch if available
            if asset_type == "gold" and master.get("series") == "GB" and master_price > 0:
                if parsed_price == 0 or abs(master_price - parsed_price) / max(master_price, 1) > 0.3:
                    h["current_price"] = round(master_price, 2)

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
                    if parsed_value > 0 and abs(master_price - parsed_price) / max(master_price, 1) > 0.3:
                        h["current_price"] = round(master_price, 4)
                        h["buy_price"] = round(master_price, 4)
                        h["quantity"] = round(parsed_value / master_price, 4) if master_price > 0 else qty
                    elif parsed_price == 0:
                        h["current_price"] = round(master_price, 4)
                        h["buy_price"] = round(master_price, 4)
                # Also attach MF classification if fuzzy-matched to AMFI
                if info.get("source") == "amfi":
                    meta = lookup_isin(new_isin) or {}
                    if meta.get("plan"):
                        h["plan"] = meta["plan"]
                    if meta.get("option"):
                        h["option"] = meta["option"]
                enriched.append(h)
                continue

        # 3. No match found — keep as-is
        enriched.append(h)

    return enriched
