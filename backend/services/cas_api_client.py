"""
CAS Parser API client (casparser.in).

Hosted CAS parsing service that extracts structured portfolio data from
NSDL / CDSL / CAMS / KFintech Consolidated Account Statements.

Used as the PRIMARY parsing path; local OCR fallback remains in place.

Endpoints used:
  POST /v4/smart/parse     — auto-detects CAS type (preferred)
  POST /v4/nsdl/parse      — NSDL eCAS only
  POST /v4/cdsl/parse      — CDSL eCAS only

Auth: `x-api-key` header. Sandbox key returns deterministic sample data
(no PDF required, no credits consumed).
"""
import io
import logging
import os
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("cas_api_client")

# ── Env ────────────────────────────────────────────────────────
BASE_URL = os.environ.get("CASPARSER_BASE_URL", "https://api.casparser.in")
PROD_KEY = os.environ.get("CASPARSER_API_KEY", "")
SANDBOX_KEY = os.environ.get("CASPARSER_SANDBOX_KEY", "sandbox-with-json-responses")
USE_SANDBOX = os.environ.get("CASPARSER_USE_SANDBOX", "false").lower() == "true"
TIMEOUT_S = float(os.environ.get("CASPARSER_TIMEOUT", "60"))


def _active_key() -> str:
    if USE_SANDBOX or not PROD_KEY:
        return SANDBOX_KEY
    return PROD_KEY


def is_configured() -> bool:
    """True iff a production or sandbox key is available."""
    return bool(_active_key())


# ══════════════════════════════════════════════════════════════
# HTTP calls
# ══════════════════════════════════════════════════════════════

def parse_cas_pdf(content: bytes, password: str = "", endpoint: str = "/v4/smart/parse") -> Optional[dict]:
    """
    Parse CAS PDF via CAS Parser API. Returns raw API JSON dict or None on failure.

    Sync wrapper (httpx.Client) — safe to call from FastAPI sync endpoints and
    from within `run_in_threadpool` contexts.
    """
    api_key = _active_key()
    if not api_key:
        logger.warning("CAS Parser API key not configured")
        return None

    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            resp = client.post(
                f"{BASE_URL}{endpoint}",
                headers={"x-api-key": api_key},
                files={"file": ("cas.pdf", io.BytesIO(content), "application/pdf")},
                data={"password": password or ""},
            )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"CAS Parser API network error: {e}")
        return None

    if resp.status_code >= 400:
        logger.warning(f"CAS Parser API HTTP {resp.status_code}: {resp.text[:300]}")
        return None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning(f"CAS Parser API non-JSON response: {e}")
        return None

    # The API uses {"status": "failed", "msg": "..."} for logical errors
    if isinstance(data, dict) and data.get("status") == "failed":
        logger.warning(f"CAS Parser API failed: {data.get('msg')}")
        return None

    return data


# ══════════════════════════════════════════════════════════════
# Mapping to internal Holding dict (same shape as local OCR parser)
# ══════════════════════════════════════════════════════════════

def _classify_sector(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ["index", "nifty", "sensex", "bees"]): return "Index"
    if any(k in n for k in ["small cap", "smallcap"]): return "Small Cap"
    if any(k in n for k in ["mid cap", "midcap"]): return "Mid Cap"
    if any(k in n for k in ["large cap", "largecap", "bluechip", "frontline", "large & mid"]): return "Large Cap"
    if any(k in n for k in ["flexi cap", "flexicap", "multi cap", "multicap"]): return "Flexi Cap"
    if any(k in n for k in ["balanced", "hybrid", "advantage", "dynamic"]): return "Balanced"
    if any(k in n for k in ["elss", "tax"]): return "ELSS"
    if any(k in n for k in ["debt", "bond", "gilt", "liquid", "money market", "overnight", "short", "credit", "arbitrage"]): return "Debt"
    if any(k in n for k in ["gold", "sgb"]): return "Gold"
    if any(k in n for k in ["international", "global", "us ", "nasdaq", "fang", "nyse"]): return "International"
    if any(k in n for k in ["contra", "value"]): return "Value"
    if any(k in n for k in ["focused", "opportunities"]): return "Focused"
    return "Other"


def _classify_mf(name: str) -> tuple:
    """Returns (plan, option) — Direct/Regular × Growth/IDCW/Dividend."""
    n = (name or "").lower()
    plan = "Direct" if "direct" in n else ("Regular" if "regular" in n else "Unknown")
    if "growth" in n:
        option = "Growth"
    elif "idcw" in n:
        option = "IDCW Reinvestment" if "reinv" in n else ("IDCW Payout" if "payout" in n else "IDCW")
    elif "dividend" in n:
        option = "Dividend Reinvestment" if "reinv" in n else "Dividend Payout"
    else:
        option = "Growth"
    return plan, option


def _num(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _holding_from_equity(row: dict) -> Optional[Dict]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("name") or row.get("company_name") or "").strip()
    units = _num(row.get("units") or row.get("quantity"))
    value = _num(row.get("value") or row.get("market_value"))
    price = _num(row.get("price") or row.get("market_price"))
    if price == 0 and units > 0 and value > 0:
        price = round(value / units, 4)
    if not isin or not name:
        return None
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "equity",
        "quantity": round(units, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": _classify_sector(name) if is_etf else "Other",
    }


def _holding_from_demat_mf(row: dict) -> Optional[Dict]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("scheme_name") or row.get("name") or "").strip()
    units = _num(row.get("units") or row.get("quantity"))
    nav = _num(row.get("nav") or row.get("price"))
    value = _num(row.get("value") or row.get("market_value"))
    if nav == 0 and units > 0 and value > 0:
        nav = round(value / units, 4)
    if not isin or not name:
        return None
    plan, option = _classify_mf(name)
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "mutual_fund",
        "quantity": round(units, 4),
        "buy_price": round(nav, 4),
        "current_price": round(nav, 4),
        "sector": _classify_sector(name),
        "plan": plan,
        "option": option,
    }


def _holding_from_bond(row: dict, asset_type: str = "bond") -> Optional[Dict]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("issuer") or row.get("name") or "").strip() or asset_type.title()
    units = _num(row.get("units") or row.get("quantity"))
    value = _num(row.get("value") or row.get("market_value"))
    price = _num(row.get("price"))
    if price == 0 and units > 0 and value > 0:
        price = round(value / units, 4)
    if not isin:
        return None
    # SGBs classified as "gold"
    if "gold" in name.lower() or "sgb" in name.lower() or asset_type == "gold":
        final_type = "gold"
    else:
        final_type = asset_type
    return {
        "name": name,
        "ticker": isin,
        "asset_type": final_type,
        "quantity": round(units, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": "Gold" if final_type == "gold" else "Debt",
    }


def _holding_from_mf_scheme(row: dict) -> Optional[Dict]:
    """Non-demat MF scheme from a CAMS/KFintech folio."""
    isin = (row.get("isin") or "").strip()
    name = (row.get("name") or row.get("scheme_name") or "").strip()
    units = _num(row.get("units") or row.get("closing_balance") or row.get("balance"))
    nav = _num(row.get("nav"))
    value = _num(row.get("value") or row.get("market_value"))
    # API returns `cost` as TOTAL invested amount, not per-unit
    total_cost = _num(row.get("cost") or row.get("total_cost"))
    avg_cost = _num(row.get("avg_cost") or row.get("average_cost"))
    if avg_cost == 0 and total_cost > 0 and units > 0:
        avg_cost = round(total_cost / units, 4)
    if nav == 0 and units > 0 and value > 0:
        nav = round(value / units, 4)
    if not isin or not name:
        return None
    plan, option = _classify_mf(name)
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "mutual_fund",
        "quantity": round(units, 4),
        "buy_price": round(avg_cost or nav, 4),
        "current_price": round(nav, 4),
        "sector": _classify_sector(name),
        "plan": plan,
        "option": option,
    }


def map_api_response_to_holdings(data: dict) -> List[Dict]:
    """
    Transform raw CAS Parser API JSON → list of internal holding dicts.
    Structure per https://casparser.in/docs/guides/parsing.
    """
    holdings: List[Dict] = []
    if not isinstance(data, dict):
        return holdings

    # Demat accounts → equities, demat_mutual_funds, corporate_bonds, g-secs, aifs
    for account in data.get("demat_accounts") or []:
        hold_section = account.get("holdings") or {}

        for eq in hold_section.get("equities") or []:
            h = _holding_from_equity(eq)
            if h:
                holdings.append(h)

        for mf in hold_section.get("demat_mutual_funds") or []:
            h = _holding_from_demat_mf(mf)
            if h:
                holdings.append(h)

        for b in hold_section.get("corporate_bonds") or []:
            h = _holding_from_bond(b, asset_type="bond")
            if h:
                holdings.append(h)

        for g in hold_section.get("government_securities") or []:
            h = _holding_from_bond(g, asset_type="gold")  # SGBs come here per NSDL/CDSL
            if h:
                holdings.append(h)

        for a in hold_section.get("aifs") or []:
            h = _holding_from_bond(a, asset_type="other")
            if h:
                holdings.append(h)

        for etf in hold_section.get("etfs") or []:
            h = _holding_from_equity(etf)
            if h:
                h["asset_type"] = "etf"
                holdings.append(h)

    # Non-demat mutual funds (CAMS / KFintech folios)
    for folio in data.get("mutual_funds") or []:
        for scheme in folio.get("schemes") or folio.get("holdings") or []:
            h = _holding_from_mf_scheme(scheme)
            if h:
                holdings.append(h)

    # NPS holdings
    for nps in data.get("nps") or []:
        pran = (nps.get("pran") or "NPS").strip()
        tier = (nps.get("tier") or "").strip()
        for scheme in nps.get("schemes") or [nps]:
            isin = (scheme.get("isin") or pran).strip()
            name = (scheme.get("scheme_name") or scheme.get("fund") or f"NPS {tier}").strip()
            units = _num(scheme.get("units"))
            nav = _num(scheme.get("nav"))
            value = _num(scheme.get("value"))
            if nav == 0 and units > 0 and value > 0:
                nav = round(value / units, 4)
            if not name or (units == 0 and value == 0):
                continue
            holdings.append({
                "name": name,
                "ticker": isin,
                "asset_type": "nps",
                "quantity": round(units, 4),
                "buy_price": round(nav, 4),
                "current_price": round(nav, 4),
                "sector": "Retirement",
            })

    logger.info(f"CAS API → {len(holdings)} holdings mapped")
    return holdings


def parse_cas_via_api(content: bytes, password: str = "") -> List[Dict]:
    """
    Convenience: call API and return holdings in internal format.
    Returns [] on any failure (caller falls back to local OCR).
    """
    data = parse_cas_pdf(content, password)
    if not data:
        return []
    return map_api_response_to_holdings(data)
