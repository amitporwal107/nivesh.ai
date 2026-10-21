"""The platform's daily Kite session: login handshake, storage and lookup.

Kite has no supported way to log in without a human (2FA), and none is attempted here. Once a day an admin taps a login
link; everything after that is automatic:

  1. POST /api/live/kite/login-url (admin) -> `create_login_state()` stores a SIGNED, SINGLE-USE, SHORT-TTL state in Mongo
     (`kite_platform_login_states`) and returns Kite's login URL carrying it in `redirect_params`.
  2. Zerodha redirects the browser to /api/broker/native/callback?broker=zerodha&request_token=...&state=kp.<...>.
     routes/broker_native.py hands a `kp.` state to `handle_callback()`; every other state keeps the per-user flow.
  3. `handle_callback()` consumes the state (replay/expiry/forgery rejected), exchanges the request_token with the API key and
     secret, REQUIRES the returned Kite user_id to equal KITE_PLATFORM_USER_ID (a stranger's login must never become the
     platform session), and stores the access token (AES-256-GCM via services.pii_security) in `kite_platform_token`
     with expires_at = next 06:00 IST. No API ever returns the token.

`default_token()` (services/providers/kite_adapter.py) prefers `cached_token()`; the feed refreshes that cache from Mongo
every pass, so a token obtained on any container reaches the leader without a restart.

Neither the token, the request_token, the API key nor the secret is ever logged or returned: only reason codes are.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets as _pysecrets
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
COL_STATES, COL_TOKEN = "kite_platform_login_states", "kite_platform_token"
TOKEN_DOC_ID = "platform"
STATE_PREFIX = "kp."
STATE_TTL_ENV, STATE_TTL_DEFAULT_MIN = "KITE_LOGIN_STATE_TTL_MIN", 30
PLATFORM_USER_ENV = "KITE_PLATFORM_USER_ID"
LOGIN_BASE = "https://kite.zerodha.com/connect/login"
SUCCESS_REDIRECT = "/dashboard?kite=connected"

# in-process view of the stored token: (token, expires_at). Refreshed from Mongo by the feed each pass and set by the callback.
_cache: Tuple[str, Optional[datetime]] = ("", None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def next_expiry(now: datetime) -> datetime:
    """Kite access tokens die at ~06:00 IST: the next 06:00 IST strictly after `now`."""
    t = now.astimezone(IST)
    d = t.date() if t.time() < dtime(6, 0) else t.date() + timedelta(days=1)
    return datetime.combine(d, dtime(6, 0), tzinfo=IST).astimezone(timezone.utc)


def state_ttl_minutes() -> int:
    try:
        return max(2, min(120, int(float(os.environ.get(STATE_TTL_ENV, STATE_TTL_DEFAULT_MIN)))))
    except (TypeError, ValueError):
        return STATE_TTL_DEFAULT_MIN


# ── credentials (never logged) ───────────────────────────────────────────────

def _conf(*keys: str) -> str:
    for k in keys:
        try:
            from helpers import secrets
            v = (secrets.get(k) or "").strip()
        except Exception:  # noqa: BLE001
            v = ""
        v = v or os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def api_secret() -> str:
    """KITE_API_SECRET, else BROKER_ZERODHA_API_SECRET (the same Kite Connect app the broker hub uses). Never read from a file."""
    return _conf("KITE_API_SECRET", "BROKER_ZERODHA_API_SECRET")


def platform_user_id() -> str:
    return _conf(PLATFORM_USER_ENV).upper()


def _signing_key() -> bytes:
    from services import pii_security
    return hashlib.sha256(b"kite-platform-login-state|" + pii_security._get_key()).digest()  # noqa: SLF001 — one key for the app


def _sign(nonce: str) -> str:
    return hmac.new(_signing_key(), nonce.encode(), hashlib.sha256).hexdigest()[:24]


def _id(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


# ── login state ──────────────────────────────────────────────────────────────

async def ensure_indexes(db) -> None:
    await db[COL_STATES].create_index("purge_at", expireAfterSeconds=0, background=True)


def login_url(api_key: str, state: str) -> str:
    return f"{LOGIN_BASE}?v=3&api_key={quote(api_key, safe='')}&redirect_params={quote('state=' + state, safe='')}"


async def create_login_state(db, created_by: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A new signed, single-use state. Returns {state, expires_at}. Only a hash of it is stored."""
    now = now or _now()
    nonce = _pysecrets.token_urlsafe(18)
    state = f"{STATE_PREFIX}{nonce}.{_sign(nonce)}"
    exp = now + timedelta(minutes=state_ttl_minutes())
    await db[COL_STATES].insert_one({"_id": _id(state), "created_by": created_by, "created_at": now, "expires_at": exp,
                                     "purge_at": exp + timedelta(hours=1), "used_at": None})
    return {"state": state, "expires_at": exp}


def is_platform_state(state: str) -> bool:
    return isinstance(state, str) and state.startswith(STATE_PREFIX)


async def consume_state(db, state: str, now: Optional[datetime] = None) -> Optional[str]:
    """None when the state is good (and now spent); otherwise a reason code: invalid_state | state_expired | state_used."""
    now = now or _now()
    if not is_platform_state(state) or "." not in state[len(STATE_PREFIX):]:
        return "invalid_state"
    nonce, sig = state[len(STATE_PREFIX):].rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(nonce)):
        return "invalid_state"
    doc = await db[COL_STATES].find_one({"_id": _id(state)})
    if not doc:
        return "invalid_state"
    if doc.get("used_at") is not None:
        return "state_used"
    exp = aware(doc.get("expires_at"))
    if exp is None or now > exp:
        return "state_expired"
    res = await db[COL_STATES].update_one({"_id": _id(state), "used_at": None}, {"$set": {"used_at": now}})
    return None if res.matched_count else "state_used"          # lost a race with a replay


# ── token store ──────────────────────────────────────────────────────────────

async def store_token(db, token: str, user_id: str, now: Optional[datetime] = None) -> datetime:
    from services import pii_security
    global _cache
    now = now or _now()
    exp = next_expiry(now)
    await db[COL_TOKEN].replace_one(
        {"_id": TOKEN_DOC_ID},
        {"_id": TOKEN_DOC_ID, "token_enc": pii_security.encrypt(token), "user_id": user_id, "obtained_at": now, "expires_at": exp},
        upsert=True)
    _cache = (token, exp)
    return exp


async def refresh_cache(db, now: Optional[datetime] = None) -> bool:
    """Reload the stored token into this process. True when a non-expired platform token is held afterwards."""
    global _cache
    now = now or _now()
    doc = await db[COL_TOKEN].find_one({"_id": TOKEN_DOC_ID})
    token, exp = "", None
    if doc:
        from services import pii_security
        exp = aware(doc.get("expires_at"))
        token = (pii_security.decrypt(doc.get("token_enc") or "") or "") if exp and now < exp else ""
    _cache = (token, exp if token else None)
    return bool(token)


def cached_token(now: Optional[datetime] = None) -> str:
    """The platform token if one is held and not past its 06:00 IST expiry; "" otherwise. Sync and cheap."""
    token, exp = _cache
    return token if token and exp is not None and (now or _now()) < exp else ""


def clear_cache() -> None:
    global _cache
    _cache = ("", None)


async def token_status(db, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Non-secret facts about the stored token, for status and alert texts."""
    now = now or _now()
    doc = await db[COL_TOKEN].find_one({"_id": TOKEN_DOC_ID}, {"token_enc": 0})
    exp = aware((doc or {}).get("expires_at"))
    return {"stored": bool(doc), "valid_until": exp.isoformat() if exp else None, "expired": bool(exp and now >= exp)}


# ── callback ─────────────────────────────────────────────────────────────────

def _default_exchange(api_key: str, secret: str, request_token: str) -> Dict[str, Any]:
    from kiteconnect import KiteConnect
    return KiteConnect(api_key=api_key).generate_session(request_token, secret)


async def handle_callback(db, params: Dict[str, str], *, exchange: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
                          get_api_key: Optional[Callable[[], str]] = None, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Finish a platform login. Returns (ok, reason). `reason` is a fixed code, never a provider message."""
    from . import config as cfg
    now = now or _now()
    state = params.get("state") or ""
    reason = await consume_state(db, state, now)
    if reason:
        return False, reason
    err = params.get("error") or ("" if params.get("status") in (None, "success") else params.get("status", ""))
    if err:
        return False, "denied"
    code = params.get("request_token") or params.get("code") or ""
    if not code:
        return False, "missing_params"
    expected = platform_user_id()
    if not expected:
        logger.warning("kite platform login refused: %s is not configured", PLATFORM_USER_ENV)
        return False, "platform_user_not_configured"
    key, secret = (get_api_key or cfg.get_api_key)(), api_secret()
    if not key or not secret:
        return False, "credentials_missing"
    try:
        data = await asyncio.get_event_loop().run_in_executor(None, lambda: (exchange or _default_exchange)(key, secret, code))
    except Exception as e:  # noqa: BLE001 — SDK errors can echo request fields: only the class is kept
        logger.error("kite platform login: token exchange failed (%s)", type(e).__name__)
        return False, "token_exchange_failed"
    token = (data or {}).get("access_token") or ""
    if not token:
        return False, "token_exchange_failed"
    got = str((data or {}).get("user_id") or "").strip().upper()
    if got != expected:
        logger.warning("kite platform login rejected: the Zerodha account is not the platform account")
        return False, "wrong_account"
    try:
        await store_token(db, token, got, now)
    except Exception as e:  # noqa: BLE001
        logger.error("kite platform login: token could not be stored (%s)", type(e).__name__)
        return False, "server_error"
    logger.info("kite platform login: platform token stored")
    return True, "connected"
