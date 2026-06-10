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
import re
import threading
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("cas_api_client")

# ── Env ────────────────────────────────────────────────────────
# CASPARSER_BASE_URL still resolves via helpers.secrets (admin-tunable).
# CAS Parser API KEYS now live in Google Secret Manager only — no env-var
# fallback, no admin-console editing. See helpers/gsm.py.
from helpers import secrets as _secrets
from helpers import gsm as _gsm

SANDBOX_KEY = os.environ.get("CASPARSER_SANDBOX_KEY", "sandbox-with-json-responses")
USE_SANDBOX = os.environ.get("CASPARSER_USE_SANDBOX", "false").lower() == "true"
TIMEOUT_S = float(os.environ.get("CASPARSER_TIMEOUT", "120"))
API_SIZE_LIMIT = 1_800_000

# Admin overrides for sandbox toggle (sandbox is a config flag, not a secret).
_override_sandbox: Optional[bool] = None

# ── Hardcoded fallback key (bypasses GSM when billing/access issues occur) ──
# GSM is the authoritative source; this key is used when GSM returns empty.
# Remove once GSM billing is restored.
_HARDCODED_FALLBACK_KEY = "sk_1ce512b2acb259cd75d4e5c86f5a3091"

# ── Rotating key pool ─────────────────────────────────────────────────────
_pool_lock = threading.Lock()
_pool_cache: Optional[List[str]] = None  # None = not yet loaded


def _secret_name() -> str:
    env = _secrets.current_env()  # "production" | "preview"
    return f"casparser-api-keys-{env}"


def _env_pool() -> str:
    """Key pool supplied via the deploy environment (e.g. staging .env), used
    when GSM is empty/unavailable. Accepts newline- or comma-separated keys.
    `CASPARSER_API_KEYS` is canonical; the singular forms are conveniences."""
    return (
        os.environ.get("CASPARSER_API_KEYS")
        or os.environ.get("CASPARSER_API_KEY")
        or os.environ.get("PI_CASPARSER_API_KEY")
        or ""
    )


def _load_pool() -> List[str]:
    raw = _gsm.get(_secret_name()) or ""
    if not raw.strip():
        # GSM empty/unavailable → prefer an env-provided pool (lets ops rotate
        # keys via the deploy env without a code change while GSM is down),
        # then the hardcoded fallback as a last resort.
        env_raw = _env_pool()
        if env_raw.strip():
            logger.info(
                "CAS Parser key pool loaded from env (GSM %s empty/unavailable)",
                _secret_name(),
            )
            raw = env_raw
        else:
            logger.warning(
                "CAS Parser API key pool empty from GSM (%s) and env — using hardcoded fallback key",
                _secret_name(),
            )
            return [_HARDCODED_FALLBACK_KEY]
    # then split each remaining line on any whitespace or comma so admins
    # can shape the GSM payload however is convenient.
    out: List[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for k in re.split(r"[\s,]+", stripped):
            if k:
                out.append(k)
    # Dedupe while preserving order
    seen: set = set()
    return [k for k in out if not (k in seen or seen.add(k))]


def _get_pool() -> List[str]:
    global _pool_cache
    with _pool_lock:
        if _pool_cache is None:
            _pool_cache = _load_pool()
        return list(_pool_cache)


def reload_pool() -> int:
    """Drop the in-process pool cache so the next call re-reads the
    GSM-hosted secret. Returns the new pool size. Call after publishing a
    new secret version with ``gcloud secrets versions add``."""
    global _pool_cache
    with _pool_lock:
        _gsm.reload(_secret_name())
        _pool_cache = _load_pool()
        return len(_pool_cache)


def _retire_pool_key(bad_key: str) -> None:
    """Drop a dead key from the in-process pool. Persisting the cleaned
    list back to GSM is intentionally an operator action — logs the next
    step so it's visible."""
    global _pool_cache
    with _pool_lock:
        if _pool_cache is None:
            _pool_cache = _load_pool()
        if bad_key not in _pool_cache:
            return
        _pool_cache.remove(bad_key)
        logger.warning(
            "CAS Parser key retired (expired/exhausted): %s — %d remaining in-process. "
            "Publish a cleaned version to GSM secret %s to make this survive a restart.",
            _secrets.mask(bad_key), len(_pool_cache), _secret_name(),
        )


def _base_url() -> str:
    return _secrets.get("CASPARSER_BASE_URL") or "https://api.casparser.in"


def set_override(use_sandbox: Optional[bool] = None, **_ignored) -> None:
    """Sandbox toggle is admin-tunable (it's a config flag, not a secret).
    Accepts kwargs for back-compat with old callers — any other kwargs are
    silently ignored (the legacy ``prod_key`` knob is gone; CAS keys now
    live in GSM only)."""
    global _override_sandbox
    if use_sandbox is not None:
        _override_sandbox = bool(use_sandbox)


def get_effective_config() -> Dict:
    use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    pool = _get_pool()
    active_key = _active_key()
    return {
        "use_sandbox": use_sb,
        "active_key_masked": _secrets.mask(active_key),
        "base_url": _base_url(),
        "pool_size": len(pool),
        "pool_source": "gsm",
        "gsm_secret_name": _secret_name(),
        "gsm_project": _gsm.project_id(),
    }


def _mask(s: Optional[str]) -> str:
    return _secrets.mask(s)


def _active_key() -> str:
    """Resolve the key to use for the next upstream call.

    Order: sandbox toggle → GSM-sourced pool head → sandbox key as
    last-resort (so calls fail loudly with sandbox data rather than
    sending an empty x-api-key header).
    """
    use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    if use_sb:
        return SANDBOX_KEY
    pool = _get_pool()
    if pool:
        return pool[0]
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

# Parse-error categories surfaced to callers (and ultimately the user).
#   password → the PAN/password didn't unlock the PDF (re-prompt for PAN)
#   service  → casparser unreachable / key / token / non-JSON (retry later)
#   parse    → casparser ran but rejected the PDF (scanned/unsupported/etc.)
def _is_password_error(text: str) -> bool:
    return bool(re.search(r"password|incorrect\s*pan|invalid\s*pan|wrong\s*pan|decrypt", text or "", re.I))


def _sdk_parse_ex(content: bytes, password: str = ""):
    """Core SDK-flow parse. Returns (data | None, error | None) where error is
    {"kind": "password"|"service"|"parse", "message": str, "detail": str}.
    `parse_cas_via_sdk_flow` wraps this and drops the error for back-compat."""
    api_key = _active_key()
    if not api_key:
        logger.warning("CAS Parser: no API key available (GSM empty, fallback missing)")
        return None, {"kind": "service", "message": "CAS parser is not configured.", "detail": "no_api_key"}

    _use_sb = _override_sandbox if _override_sandbox is not None else USE_SANDBOX
    if _use_sb or api_key.startswith("sandbox-"):
        logger.info("CAS Parser SDK flow: sandbox mode — returning None (no real parse)")
        return None, {"kind": "service", "message": "CAS parser is in sandbox mode.", "detail": "sandbox"}

    # Step 1: mint a short-lived access token
    try:
        with httpx.Client(timeout=30) as client:
            tok_resp = client.post(
                f"{_base_url()}/v1/token",
                headers={"x-api-key": api_key},
                json={"expiry_minutes": 10},
            )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning("CAS Parser SDK flow: token mint failed: %s", e)
        return None, {"kind": "service", "message": "Couldn't reach the CAS parser — try again.", "detail": str(e)}

    if tok_resp.status_code >= 400:
        logger.warning("CAS Parser SDK flow: token mint HTTP %s", tok_resp.status_code)
        if _looks_like_dead_key(tok_resp.status_code, tok_resp.text[:200]):
            _retire_pool_key(api_key)
        return None, {"kind": "service", "message": "CAS parser auth failed — try again.",
                      "detail": f"token_http_{tok_resp.status_code}"}

    try:
        at_token = tok_resp.json().get("access_token")
    except Exception:
        at_token = None

    if not at_token:
        logger.warning("CAS Parser SDK flow: no access_token in mint response")
        return None, {"kind": "service", "message": "CAS parser auth failed — try again.", "detail": "no_token"}

    # Step 2: parse the PDF using the access token (same call the SDK widget makes)
    try:
        with httpx.Client(timeout=120) as client:
            parse_resp = client.post(
                f"{_base_url()}/v4/smart/parse",
                headers={
                    "Authorization": f"Bearer {at_token}",
                    "accept": "application/json",
                },
                files={"file": ("cas.pdf", io.BytesIO(content), "application/pdf")},
                data={"password": password or ""},
            )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning("CAS Parser SDK flow: parse request failed: %s", e)
        return None, {"kind": "service", "message": "Couldn't reach the CAS parser — try again.", "detail": str(e)}

    if parse_resp.status_code >= 400:
        body = parse_resp.text[:300]
        logger.warning("CAS Parser SDK flow: parse HTTP %s: %s", parse_resp.status_code, body)
        if parse_resp.status_code in (401, 403) and _is_password_error(body):
            return None, {"kind": "password", "message": "That PAN didn't unlock the statement.", "detail": body}
        return None, {"kind": "parse", "message": "The CAS statement couldn't be read.", "detail": body}

    try:
        data = parse_resp.json()
    except Exception:
        logger.warning("CAS Parser SDK flow: non-JSON parse response")
        return None, {"kind": "service", "message": "CAS parser returned an unexpected response.", "detail": "non_json"}

    if isinstance(data, dict) and data.get("status") == "failed":
        msg = str(data.get("msg") or "")
        logger.warning("CAS Parser SDK flow: parse failed: %s", msg)
        if _is_password_error(msg):
            return None, {"kind": "password", "message": "That PAN didn't unlock the statement.", "detail": msg}
        return None, {"kind": "parse", "message": "The CAS statement couldn't be read.", "detail": msg}

    logger.info("CAS Parser SDK flow: parsed successfully (%.1f MB)", len(content) / 1e6)
    return data, None


def parse_cas_via_sdk_flow(content: bytes, password: str = "") -> Optional[dict]:
    """Parse CAS PDF replicating the SDK's internal flow — no popup, no branding.

    Two-step server-side call (POST /v1/token → POST /v4/smart/parse), same as
    the @cas-parser/connect widget. No artificial size gate.
    Returns raw casparser.in JSON dict or None on failure (see `_sdk_parse_ex`
    for the error-bearing variant)."""
    data, _err = _sdk_parse_ex(content, password)
    return data


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
    avg_cost_nav = _num(row.get("avg_cost") or row.get("average_cost") or row.get("nav") or row.get("price"))
    value = _num(row.get("value") or row.get("market_value"))
    # current_price = current market NAV = market_value / units (authoritative)
    # buy_price     = avg cost NAV (cost basis)
    current_nav = round(value / units, 4) if units > 0 and value > 0 else avg_cost_nav
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
        "buy_price": round(avg_cost_nav, 4),
        "current_price": round(current_nav, 4),
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
    # current_price = current market NAV derived from market value (authoritative).
    # `nav` from casparser may be the average cost NAV, not the current NAV.
    current_nav = round(value / units, 4) if units > 0 and value > 0 else nav
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
        "current_price": round(current_nav, 4),
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

        # sovereign_gold_bonds — output key from nivesh_cas_normalizer.
        # Field names differ from government_securities: num_units / market_price_per_unit_inr /
        # value_inr / face_value_per_unit_inr.  Map to the shape _holding_from_bond expects.
        for g in hold_section.get("sovereign_gold_bonds") or []:
            mapped = {
                "isin":   g.get("isin"),
                "issuer": g.get("series") or g.get("issuer") or "Sovereign Gold Bond",
                "units":  g.get("num_units"),
                "price":  g.get("market_price_per_unit_inr"),
                "value":  g.get("value_inr"),
            }
            h = _holding_from_bond(mapped, asset_type="gold")
            if h:
                # Use RBI issue price as cost basis when available
                if g.get("face_value_per_unit_inr"):
                    h["buy_price"] = round(float(g["face_value_per_unit_inr"]), 4)
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


def extract_statement_period(data: dict) -> Optional[str]:
    """Return statement end-date as 'MMM/YYYY' from a raw casparser.in response.

    Probes all known field paths — the API layout varies across CAS types
    (NSDL / CDSL / CAMS / KFintech). Returns None if nothing is found.
    """
    if not data:
        return None

    def _dig(src: dict, *keys: str) -> Optional[str]:
        cur = src
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur if isinstance(cur, str) else None

    meta    = data.get("meta") or {}
    summary = data.get("summary") or {}

    candidates = [
        _dig(meta,    "statement_period", "to"),
        _dig(summary, "statement_period", "to"),
        _dig(data,    "statement_period", "to"),
        _dig(meta,    "to_date"),
        _dig(meta,    "period_to"),
        _dig(meta,    "statement_to"),
        _dig(data,    "period"),  # some SDK versions hoist "Feb/2026" here
    ]

    date_fmts = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y")
    from datetime import datetime as _dt
    for raw in candidates:
        if not raw:
            continue
        if len(raw) <= 8 and "/" in raw:  # already "Feb/2026"
            return raw
        for fmt in date_fmts:
            try:
                return _dt.strptime(raw.strip(), fmt).strftime("%b/%Y")
            except ValueError:
                continue
    return None


def parse_cas_via_sdk_flow_with_data(content: bytes, password: str = "") -> tuple:
    """SDK-flow wrapper returning (holdings, raw_data, normalized) — same
    signature as parse_cas_via_api_with_data so callers can swap them.
    Uses parse_cas_via_sdk_flow (access-token path, no size gate).
    """
    data = parse_cas_via_sdk_flow(content, password)
    if not data:
        return [], None, None
    holdings = map_api_response_to_holdings(data)
    normalized = normalize_api_response_for_transactions(data)
    return holdings, data, normalized


def parse_cas_via_sdk_flow_with_error(content: bytes, password: str = "") -> tuple:
    """Like `parse_cas_via_sdk_flow_with_data` but also returns the parse error
    so callers can tell the user *why* it failed (esp. a wrong PAN).
    Returns (holdings, raw_data, normalized, error) — error is None on success,
    else {"kind": "password"|"service"|"parse", "message": str, "detail": str}."""
    data, err = _sdk_parse_ex(content, password)
    if not data:
        return [], None, None, err
    holdings = map_api_response_to_holdings(data)
    if not holdings:
        return [], data, None, {
            "kind": "parse",
            "message": "The statement was read but contained no holdings.",
            "detail": "empty_holdings",
        }
    normalized = normalize_api_response_for_transactions(data)
    return holdings, data, normalized, None


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


