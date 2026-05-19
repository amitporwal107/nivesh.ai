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
import threading
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("cas_api_client")

# ── Env ────────────────────────────────────────────────────────
# Secrets (CASPARSER_API_KEY, CASPARSER_BASE_URL) resolved via helpers.secrets
# which checks DB overrides first then env. Other config stays as env-only.
from helpers import secrets as _secrets

SANDBOX_KEY = os.environ.get("CASPARSER_SANDBOX_KEY", "sandbox-with-json-responses")
USE_SANDBOX = os.environ.get("CASPARSER_USE_SANDBOX", "false").lower() == "true"
TIMEOUT_S = float(os.environ.get("CASPARSER_TIMEOUT", "120"))
API_SIZE_LIMIT = 1_800_000

# Admin overrides for sandbox toggle (legacy — key override now goes via helpers.secrets)
_override_sandbox: Optional[bool] = None

# ── Rotating key pool ──────────────────────────────────────────
# Pool sources (merged, deduped, file ordering preserved first):
#   1. File at CASPARSER_KEYS_FILE — one key per line, '#' comments ok
#   2. DB-backed admin secret CASPARSER_API_KEYS — newline or
#      comma-separated (admin console can paste it)
# Head of the pool is the active key. On 401/402/403 (or a body
# indicating expiry / quota), the key is retired in-memory and, if it
# came from disk, the file is atomically rewritten. DB-sourced keys
# are only retired in-process (the admin must clean the DB string when
# convenient — we log a warning so it's visible).
CASPARSER_KEYS_FILE = os.environ.get("CASPARSER_KEYS_FILE", "/app/.gcp/.casparser_key")
_pool_lock = threading.Lock()
_pool_cache: Optional[List[str]] = None  # None = not yet loaded
_pool_file_keys: set = set()  # subset of _pool_cache that came from disk


def _load_pool_from_disk() -> List[str]:
    try:
        with open(CASPARSER_KEYS_FILE) as f:
            return [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except FileNotFoundError:
        return []
    except OSError as e:
        logger.warning("CAS Parser key pool unreadable (%s): %s", CASPARSER_KEYS_FILE, e)
        return []


def _load_pool_from_secret() -> List[str]:
    raw = _secrets.get("CASPARSER_API_KEYS") or ""
    if not raw.strip():
        return []
    # Accept newline OR comma separation
    parts = raw.replace(",", "\n").splitlines()
    out: List[str] = []
    for p in parts:
        k = p.strip()
        if k and not k.startswith("#"):
            out.append(k)
    return out


def _persist_pool_to_disk(keys: List[str]) -> None:
    tmp = CASPARSER_KEYS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            if keys:
                f.write("\n".join(keys) + "\n")
        os.replace(tmp, CASPARSER_KEYS_FILE)
    except OSError as e:
        logger.warning("Failed to persist CAS Parser key pool: %s", e)


def _build_pool() -> List[str]:
    """Merge disk + DB sources, preserving order, deduping."""
    global _pool_file_keys
    disk = _load_pool_from_disk()
    db   = _load_pool_from_secret()
    _pool_file_keys = set(disk)
    seen: set = set()
    merged: List[str] = []
    for k in disk + db:
        if k not in seen:
            seen.add(k)
            merged.append(k)
    return merged


def _get_pool() -> List[str]:
    global _pool_cache
    with _pool_lock:
        if _pool_cache is None:
            _pool_cache = _build_pool()
        return list(_pool_cache)


def reload_pool() -> int:
    """Drop the in-process pool cache so the next call rebuilds it from
    file + DB. Returns the new pool size. Useful after the admin updates
    CASPARSER_API_KEYS via the secrets UI."""
    global _pool_cache
    with _pool_lock:
        _pool_cache = _build_pool()
        return len(_pool_cache)


def _retire_pool_key(bad_key: str) -> None:
    """Remove a dead key from the in-process pool. Persist to disk if
    the key came from the file; otherwise just log so the admin can
    clean it from the DB secret when convenient."""
    global _pool_cache
    with _pool_lock:
        if _pool_cache is None:
            _pool_cache = _build_pool()
        if bad_key not in _pool_cache:
            return
        _pool_cache.remove(bad_key)
        from_disk = bad_key in _pool_file_keys
        if from_disk:
            _pool_file_keys.discard(bad_key)
            # Rewrite file with only file-sourced survivors
            survivors = [k for k in _pool_cache if k in _pool_file_keys]
            _persist_pool_to_disk(survivors)
        logger.warning(
            "CAS Parser key retired (expired/exhausted, source=%s): %s — %d remaining",
            "file" if from_disk else "db_secret",
            _secrets.mask(bad_key), len(_pool_cache),
        )


def _base_url() -> str:
    return _secrets.get("CASPARSER_BASE_URL") or "https://api.casparser.in"


# Legacy shim — kept so existing admin endpoint call sites still work.
def set_override(prod_key: Optional[str] = None, use_sandbox: Optional[bool] = None) -> None:
    global _override_sandbox
    if prod_key is not None:
        _secrets.set_override("CASPARSER_API_KEY", prod_key.strip() or None)
    if use_sandbox is not None:
        _override_sandbox = bool(use_sandbox)


def get_effective_config() -> Dict:
    prod = _secrets.get("CASPARSER_API_KEY")
    use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    pool = _get_pool()
    active_key = _active_key()
    disk_count = len(_load_pool_from_disk())
    db_count   = len(_load_pool_from_secret())
    return {
        "prod_key_masked": _secrets.mask(prod),
        "prod_key_configured": bool(prod),
        "use_sandbox": use_sb,
        "active_key_masked": _secrets.mask(active_key),
        "source_override": "CASPARSER_API_KEY" in _secrets._cache or _override_sandbox is not None,
        "base_url": _base_url(),
        "pool_size": len(pool),
        "pool_file": CASPARSER_KEYS_FILE,
        "pool_from_file": disk_count,
        "pool_from_db_secret": db_count,
    }


def _mask(s: Optional[str]) -> str:
    return _secrets.mask(s)


def _active_key() -> str:
    """Resolve the key to use for the next upstream call.

    Order: sandbox toggle → pool head (rotating file) → single secret
    (CASPARSER_API_KEY from DB/env) → sandbox key as last-resort.
    """
    use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    if use_sb:
        return SANDBOX_KEY
    pool = _get_pool()
    if pool:
        return pool[0]
    prod = _secrets.get("CASPARSER_API_KEY")
    if prod:
        return prod
    return SANDBOX_KEY


# Body fragments that signal the key itself is dead (vs. a transient/PDF error).
_KEY_DEAD_FRAGMENTS = (
    "expired", "invalid api key", "invalid key", "unauthorized",
    "quota", "credits", "exhausted", "limit reached", "forbidden",
)


def _looks_like_dead_key(status_code: int, body: str) -> bool:
    if status_code in (401, 402, 403):
        return True
    lowered = (body or "").lower()
    return any(frag in lowered for frag in _KEY_DEAD_FRAGMENTS)


def is_configured() -> bool:
    """True iff a production or sandbox key is available."""
    return bool(_active_key())


def is_sandbox_active() -> bool:
    """True when the upload flow would currently hit casparser.in's
    sandbox endpoint (which returns canned mock holdings regardless of
    PDF contents). The auto-fallback chain skips casparser.in entirely
    in this state to prevent silent false successes.
    """
    return bool(_override_sandbox if _override_sandbox is not None else USE_SANDBOX)


def generate_access_token(expiry_minutes: int = 60) -> Optional[dict]:
    """
    Mint a short-lived `at_` token from the production API key. Returned to the
    frontend so the Portfolio Connect widget can call CAS Parser without ever
    seeing the raw production key.

    Returns {"access_token": "at_...", "expires_in": seconds} or None on failure.
    Sandbox mode: returns the sandbox key as a pseudo-token (widget accepts it).
    Rotates through the key pool on auth/quota failures.
    """
    use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX

    # Loop over the pool (or run once for sandbox/single-secret path).
    attempts = 0
    while True:
        api_key = _active_key()
        if not api_key:
            return None

        # Sandbox key doubles as a fake access token — the widget accepts
        # sandbox tokens directly without a /v1/token call.
        if use_sb or api_key.startswith("sandbox-"):
            return {"access_token": api_key, "expires_in": expiry_minutes * 60}

        attempts += 1
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{_base_url()}/v1/token",
                    headers={"x-api-key": api_key},
                    json={"expiry_minutes": max(5, min(expiry_minutes, 60))},
                )
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("CAS Parser token mint failed: %s", e)
            return None

        body_preview = resp.text[:200] if resp.text else ""
        if resp.status_code >= 400:
            if _looks_like_dead_key(resp.status_code, body_preview) and api_key in _get_pool():
                _retire_pool_key(api_key)
                if attempts < 8:  # safety cap
                    continue
            logger.warning("CAS Parser token mint HTTP %s: %s", resp.status_code, body_preview)
            return None

        try:
            data = resp.json()
        except Exception:
            return None

        token = data.get("access_token")
        if not token:
            return None
        return {
            "access_token": token,
            "expires_in": expiry_minutes * 60,
        }


# ══════════════════════════════════════════════════════════════
# HTTP calls
# ══════════════════════════════════════════════════════════════

def parse_cas_pdf(content: bytes, password: str = "", endpoint: str = "/v4/smart/parse") -> Optional[dict]:
    """
    Parse CAS PDF via CAS Parser API. Returns raw API JSON dict or None on failure.

    The CAS Parser API only handles text-based digital CAS PDFs (nginx caps
    upload at ~1.9 MiB and the parser rejects image-only PDFs). Scanned/large
    PDFs must fall through to the local OCR path in the caller.
    """
    if not _active_key():
        logger.warning("CAS Parser API key not configured")
        return None

    # Skip API for oversized PDFs — its backend only parses text-based CAS.
    # Sandbox mode bypasses the size gate since it returns sample data regardless.
    _use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    if not _use_sb and len(content) > API_SIZE_LIMIT:
        logger.info(
            f"PDF {len(content)/1e6:.1f}MB exceeds CAS Parser API cap "
            f"({API_SIZE_LIMIT/1e6:.1f}MB); skipping API, caller will use local OCR"
        )
        return None

    attempts = 0
    while True:
        api_key = _active_key()
        if not api_key:
            return None

        attempts += 1
        try:
            with httpx.Client(timeout=TIMEOUT_S) as client:
                resp = client.post(
                    f"{_base_url()}{endpoint}",
                    headers={"x-api-key": api_key},
                    files={"file": ("cas.pdf", io.BytesIO(content), "application/pdf")},
                    data={"password": password or ""},
                )
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("CAS Parser API network error: %s", e)
            return None

        body_preview = resp.text[:300] if resp.text else ""
        if resp.status_code >= 400:
            if (
                not _use_sb
                and _looks_like_dead_key(resp.status_code, body_preview)
                and api_key in _get_pool()
                and attempts < 8
            ):
                _retire_pool_key(api_key)
                continue
            logger.warning("CAS Parser API HTTP %s: %s", resp.status_code, body_preview)
            return None

        try:
            data = resp.json()
        except Exception as e:
            logger.warning("CAS Parser API non-JSON response: %s", e)
            return None

        # The API uses {"status": "failed", "msg": "..."} for logical errors
        if isinstance(data, dict) and data.get("status") == "failed":
            msg = data.get("msg") or ""
            if (
                not _use_sb
                and _looks_like_dead_key(200, msg)
                and api_key in _get_pool()
                and attempts < 8
            ):
                _retire_pool_key(api_key)
                continue
            logger.warning("CAS Parser API failed: %s", msg)
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


def _extract_buy_date_from_transactions(row: dict) -> Optional[str]:
    """Scan the `transactions` array on a CAS scheme/holding and return the
    earliest purchase/investment date in ISO YYYY-MM-DD form.

    casparser.in emits per-scheme transactions with fields:
      date, description, type, amount, units, nav, balance
    Purchase-side txn types include 'PURCHASE', 'PURCHASE_SIP', etc.
    We also accept any txn where `units > 0` AND `amount > 0` as a purchase.
    """
    txns = row.get("transactions") or []
    if not isinstance(txns, list) or not txns:
        return None
    earliest: Optional[str] = None
    for t in txns:
        if not isinstance(t, dict):
            continue
        t_date = t.get("date") or t.get("txn_date") or t.get("transaction_date")
        if not t_date:
            continue
        t_type = (t.get("type") or t.get("description") or "").upper()
        # Skip explicit redemption / sell / tax / stamp duty
        if any(k in t_type for k in ("REDEMPTION", "REDEEM", "SELL", "SALE", "STT", "STAMP", "REVERSAL", "CANCEL")):
            continue
        try:
            units = float(t.get("units") or 0)
            amt = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            units = 0.0
            amt = 0.0
        # Keep only txns that look like a buy (positive units OR positive amount)
        if units <= 0 and amt <= 0:
            continue
        # Normalise date to YYYY-MM-DD
        t_date_str = str(t_date)[:10]
        if earliest is None or t_date_str < earliest:
            earliest = t_date_str
    return earliest


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
    bd = _extract_buy_date_from_transactions(row) or row.get("buy_date") or row.get("purchase_date")
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "equity",
        "quantity": round(units, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": _classify_sector(name) if is_etf else "Other",
        "parsed_by": "api",
        "buy_date": bd,
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
    bd = _extract_buy_date_from_transactions(row) or row.get("buy_date") or row.get("purchase_date")
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
        "parsed_by": "api",
        "buy_date": bd,
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
    bd = _extract_buy_date_from_transactions(row) or row.get("buy_date") or row.get("allotment_date") or row.get("purchase_date")
    return {
        "name": name,
        "ticker": isin,
        "asset_type": final_type,
        "quantity": round(units, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": "Gold" if final_type == "gold" else "Debt",
        "buy_date": bd,
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
    bd = _extract_buy_date_from_transactions(row) or row.get("buy_date") or row.get("purchase_date")
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
        "parsed_by": "api",
        "buy_date": bd,
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

    logger.info("CAS API → %s holdings mapped", len(holdings))
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


def normalize_api_response_for_transactions(data: dict) -> dict:
    """Convert the casparser.in API response into the
    `{mutual_funds: [{amc, folio_number, schemes: [{scheme_name, isin,
    transactions: [...]}]}]}` shape that
    `services.cas_transactions.extract_transactions()` expects.

    The API delivers transactions in TWO places:
      (a) `data.mutual_funds[]`        — non-demat CAMS/KFintech folios
      (b) `data.demat_accounts[].holdings.demat_mutual_funds[]` — demat MFs

    Both expose per-scheme `transactions: [{date, type/description, amount,
    units, nav, balance}]`. We merge them into a single mutual_funds list.
    """
    out_folios: List[Dict] = []

    # (a) Non-demat folios — already in the right shape, just normalise keys
    for folio in data.get("mutual_funds") or []:
        schemes_in = folio.get("schemes") or folio.get("holdings") or []
        schemes_out = []
        for sch in schemes_in:
            txns = sch.get("transactions") or []
            if not txns:
                continue
            schemes_out.append({
                "scheme_name": (sch.get("scheme_name") or sch.get("name") or sch.get("scheme") or "").strip(),
                "isin": (sch.get("isin") or "").strip(),
                "transactions": txns,
            })
        if schemes_out:
            out_folios.append({
                "amc": (folio.get("amc") or "").strip(),
                "folio_number": (folio.get("folio_number") or folio.get("folio") or "").strip(),
                "schemes": schemes_out,
            })

    # (b) Demat MF holdings — synthesize a folio per demat account
    for account in data.get("demat_accounts") or []:
        dp_id = (account.get("dp_id") or account.get("client_id") or account.get("dp_name") or "DEMAT").strip()
        hold_section = account.get("holdings") or {}
        schemes_out = []
        for mf in hold_section.get("demat_mutual_funds") or []:
            txns = mf.get("transactions") or []
            if not txns:
                continue
            name = (mf.get("scheme_name") or mf.get("name") or "").strip()
            schemes_out.append({
                "scheme_name": name,
                "isin": (mf.get("isin") or "").strip(),
                "transactions": txns,
            })
        if schemes_out:
            out_folios.append({
                "amc": (account.get("dp_name") or "Demat").strip(),
                "folio_number": dp_id,
                "schemes": schemes_out,
            })

    return {"mutual_funds": out_folios}


def parse_cas_via_api_with_data(content: bytes, password: str = "") -> tuple:
    """Like `parse_cas_via_api` but ALSO returns:
      • the raw API JSON (for archival / "view parsed statement" UI)
      • a normalized `{mutual_funds: [...]}` dict suitable for
        `cas_transactions.extract_transactions()`

    Returns: (holdings: list, raw_api_data: dict | None,
              normalized_for_txns: dict | None)
    """
    data = parse_cas_pdf(content, password)
    if not data:
        return [], None, None
    holdings = map_api_response_to_holdings(data)
    normalized = normalize_api_response_for_transactions(data)
    return holdings, data, normalized


