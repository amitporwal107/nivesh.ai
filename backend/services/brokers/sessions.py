"""Broker session lifecycle for native (direct-login) broker accounts.

A native `broker_accounts` row holds the session token the broker handed
back after the user signed in on the BROKER'S OWN page. Nivesh never sees
the broker password / PIN / TOTP, and the token is read-only in our hands.

A session is alive until the broker's session expires OR the user signs out
of Nivesh, whichever comes first. When it ends the token and extras are
wiped but the row and its synced holdings stay, so the account remains
listed and needs a one-tap reconnect.

Fields this module adds to a native row (every pre-existing field keeps its
meaning, so the OpenAlgo path in `routes/broker_connect.py` is unaffected):

    broker_user_key       sha256 hex of "<slug>:<client id>" — matches a
                          reconnect to its row. The raw client id is never
                          stored in the clear (it lives in `extras_encrypted`).
    broker_user_masked    display form of the client id, most of it hidden
    session_started_at    ISO-8601 UTC
    session_expires_at    ISO-8601 UTC, or None when the expiry is not known
    session_ended_reason  "expired" | "logout" | "broker_rejected" | None

`session_expires_at` is our best knowledge, not the last word: the broker
refusing the token is the authoritative signal, and callers report that
with `end_session(..., "broker_rejected")`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import unquote

from services import pii_security as _pii

from .base import AccessToken

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"     # session ended (broker expiry, logout, or broker rejected the token) -> reconnect needed

END_REASONS = ("expired", "logout", "broker_rejected")


class SessionEnded(RuntimeError):
    """The account holds no usable token — the user has to reconnect."""


# ── return_to validation ─────────────────────────────────────────────────
_RETURN_TO_MAX_LEN = 512
_RETURN_TO_DECODE_ROUNDS = 3


def safe_return_to(value: str | None) -> str | None:
    """Accept only a same-site relative path, e.g. `/v5/app/page/brokers`
    or `/v5/app/onboarding?step=broker`. Anything else -> None.

    Rules: starts with a single "/", printable ASCII only (so no control
    characters or whitespace), no "//" and no backslash anywhere, at most
    512 characters. The same checks run on every percent-decoded form, so
    `/%2F%2Fevil.com` and `/%5Cevil.com` are refused as well.
    """
    if not isinstance(value, str) or not value or len(value) > _RETURN_TO_MAX_LEN:
        return None
    if not value.startswith("/") or any(not ("!" <= ch <= "~") for ch in value):
        return None
    decoded = value
    for _ in range(_RETURN_TO_DECODE_ROUNDS + 1):
        if "//" in decoded or "\\" in decoded:
            return None
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in decoded):
            return None
        further = unquote(decoded)
        if further == decoded:
            return value
        decoded = further
    return None  # still changing after several rounds of decoding — not a plain path


# ── Session expiry ───────────────────────────────────────────────────────
# Fixed daily cut-offs, used ONLY when the token itself carries no expiry.
# Each entry is taken from the broker's official API documentation:
#
#   zerodha    06:00  "it'll expire at 6 AM on the next day (regulatory requirement)"
#                     https://kite.trade/docs/connect/v3/user/
#   upstox     03:30  "lasts until 3:30 AM the following day, regardless of the
#                     time it was generated" (a token made at 2:30 AM expires
#                     at 3:30 AM the same day)
#                     https://upstox.com/developer/api-documentation/get-token/
#   fivepaisa  23:59  "Token expires every day at 11:59 PM."
#                     https://xstream.5paisa.com/dev-docs/user-authentication-system/access-token
#
# None of those pages names a timezone; the times are read as IST because
# these are Indian brokers. The cut-off is applied as the NEXT occurrence
# after the sign-in (Upstox states this outright; Kite's wording is "next
# day", but its tokens are flushed once every morning).
#
# Deliberately absent — no fixed time in the official API docs, so the answer
# is None unless the token itself says more:
#   fyers      docs not retrievable; a FYERS staff forum reply says 6:30 AM
#   aliceblue  https://ant.aliceblueonline.com/productdocumentation/Authentication/ gives no validity
#   angel      docs page not retrievable; forum answers disagree (midnight vs 5 AM)
#   dhan       24 hours from generation, but the user pastes a token whose
#              generation time we do not know — https://dhanhq.co/docs/v2/authentication/
_IST = timezone(timedelta(hours=5, minutes=30))
_DAILY_EXPIRY_IST: Dict[str, time] = {
    "zerodha": time(6, 0),
    "upstox": time(3, 30),
    "fivepaisa": time(23, 59),
}
_EXPIRES_IN_MAX_S = 366 * 24 * 3600  # anything larger is not a lifetime in seconds


def _utc(value: Optional[datetime]) -> datetime:
    """Aware UTC datetime; None means now, a naive value is taken as UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """ISO-8601 string (or datetime) -> aware UTC datetime. None if unusable."""
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip()))
    except ValueError:
        return None


def _jwt_exp(raw: str) -> Optional[datetime]:
    """`exp` claim of a JWT, read WITHOUT verifying the signature — we only
    want the expiry the broker itself wrote into the token. The payload is
    never logged. None when `raw` is not a JWT or carries no usable `exp`.
    """
    parts = (raw or "").strip().removeprefix("Bearer ").split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= 0:
            return None
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _expires_in(value: Any, now: datetime) -> Optional[datetime]:
    """OAuth `expires_in`: lifetime in seconds from issue (RFC 6749 §5.1)."""
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 < seconds <= _EXPIRES_IN_MAX_S:
        return None
    return now + timedelta(seconds=seconds)


def session_expiry(slug: str, token: AccessToken, now: datetime) -> datetime | None:
    """Best-known moment the broker session ends (UTC). None when not known.

    `now` is the moment of sign-in. Generic conventions come first, so a new
    adapter needs no per-broker code here:
      1. `token.extras["expires_at"]` — ISO-8601, UTC
      2. the `exp` claim when the token is a JWT
      3. `token.extras["expires_in"]` — seconds from `now`
      4. the broker's documented fixed daily expiry (`_DAILY_EXPIRY_IST`)
    """
    now = _utc(now)
    extras = token.extras or {}
    known = _parse_dt(extras.get("expires_at")) or _jwt_exp(token.token) or _expires_in(extras.get("expires_in"), now)
    if known:
        return known
    cutoff = _DAILY_EXPIRY_IST.get(slug)
    if cutoff is None:
        return None
    local = now.astimezone(_IST)
    ends = local.replace(hour=cutoff.hour, minute=cutoff.minute, second=0, microsecond=0)
    if ends <= local:
        ends += timedelta(days=1)
    return ends.astimezone(timezone.utc)


# ── Broker client id ─────────────────────────────────────────────────────
# Adapters that keep the broker's client id under their own key in `extras`.
# Every other slug uses the generic `user_id` (zerodha, upstox, aliceblue and
# all new adapters). Fyers stores none today, so it has no client id here.
_CLIENT_ID_KEY: Dict[str, str] = {
    "angel": "client_code",
    "fivepaisa": "client_code",
    "dhan": "client_id",
}


def broker_user_id(slug: str, token: AccessToken) -> str | None:
    """The broker's own client id for this login, from `token.extras`."""
    extras = token.extras or {}
    for key in (_CLIENT_ID_KEY.get(slug), "user_id"):
        value = extras.get(key) if key else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _user_key(slug: str, client_id: str) -> str:
    return hashlib.sha256(f"{slug}:{client_id}".encode()).hexdigest()


def _mask_user(client_id: str) -> str:
    """Display form — only the tail stays readable: 'AB1234' -> '••••34'."""
    keep = 2 if len(client_id) >= 6 else 1 if len(client_id) >= 3 else 0
    hidden = len(client_id) - keep
    return "•" * hidden + client_id[hidden:]


def storage_ready() -> bool:
    """True when a session token can be encrypted for storage. Outside a dev
    environment that needs PII_ENCRYPTION_KEY; without it no sign-in can be
    completed, so none should be started."""
    try:
        _pii.encrypt("probe")
        return True
    except Exception:  # noqa: BLE001
        return False


# ── Reading a row ────────────────────────────────────────────────────────
def is_live(doc: dict, now: datetime | None = None) -> bool:
    """Status active, token present, not past `session_expires_at`."""
    if doc.get("status") != STATUS_ACTIVE or not doc.get("api_key_encrypted"):
        return False
    expires = _parse_dt(doc.get("session_expires_at"))
    return expires is None or _utc(now) < expires


def load_token(doc: dict) -> AccessToken:
    """Decrypt the stored token + extras. Raises `SessionEnded` when the row
    holds no token (session ended) or it can no longer be decrypted.
    """
    raw = _pii.decrypt(doc.get("api_key_encrypted") or "")
    if not raw:
        raise SessionEnded("Broker session has ended — reconnect needed.")
    extras: Dict[str, Any] = {}
    blob = _pii.decrypt(doc.get("extras_encrypted") or "")
    if blob:
        try:
            parsed = json.loads(blob)
        except ValueError:
            logger.warning("broker account %s: stored extras are not valid JSON", doc.get("account_id"))
            parsed = None
        if isinstance(parsed, dict):
            extras = parsed
    return AccessToken(token=raw, extras=extras)


def public_fields(doc: dict, now: datetime | None = None) -> dict:
    """Session fields that are safe to return to the client.

    `session_expires_at` is reported only while the session is live; a
    session past its expiry that has not been swept yet already reads as
    ended ("expired", needs reconnect).
    """
    native = bool(doc.get("native"))
    live = is_live(doc, now)
    reason = doc.get("session_ended_reason")
    if native and not live and not reason:
        expires = _parse_dt(doc.get("session_expires_at"))
        if expires is not None and _utc(now) >= expires:
            reason = "expired"
    return {
        "native": native,
        "broker_user_masked": doc.get("broker_user_masked"),
        "session_expires_at": doc.get("session_expires_at") if live else None,
        "session_ended_reason": reason,
        "needs_reconnect": native and not live,
    }


# ── Writing ──────────────────────────────────────────────────────────────
def _extras_json(extras: Optional[Dict[str, Any]]) -> str:
    """Serialise `extras` for encryption; non-JSON-able values are stringified."""
    try:
        return json.dumps(extras or {}, default=str)
    except (TypeError, ValueError):
        logger.warning("broker extras could not be serialised — stored empty")
        return "{}"


async def upsert_native_account(db, *, user_id: str, slug: str, display: str, token: AccessToken, now: datetime | None = None) -> dict:
    """Store a fresh broker session and return the stored document.

    Reconnecting the SAME broker login (same `broker_user_key`) refreshes
    that row — new token, status active, expiry reset, `last_error` cleared —
    and keeps its `account_id` and holdings. A DIFFERENT login at the same
    broker creates a second row.

    No client id from the broker: the login cannot be told apart, so the
    user gets at most ONE such row per broker (`broker_user_key` = None) and
    every reconnect refreshes it instead of adding a duplicate. Two logins at
    a broker that reports no client id therefore share one row.
    """
    now = _utc(now)
    now_iso = now.isoformat()
    client_id = broker_user_id(slug, token)
    key = _user_key(slug, client_id) if client_id else None
    expires = session_expiry(slug, token, now)
    session = {
        "native": True,  # marks this row as following the native path
        "api_key_encrypted": _pii.encrypt(token.token),
        # This field goes back to the client in the accounts list. A session
        # token is a bearer secret, so none of it is shown.
        "api_key_masked": "",
        "extras_encrypted": _pii.encrypt(_extras_json(token.extras)),
        "broker_user_key": key,
        "broker_user_masked": _mask_user(client_id) if client_id else None,
        "status": STATUS_ACTIVE,
        "session_started_at": now_iso,
        "session_expires_at": expires.isoformat() if expires else None,
        "session_ended_reason": None,
        "last_error": None,
        "updated_at": now_iso,
    }

    # `broker_user_key: None` also matches rows that have no such field.
    existing = await db.broker_accounts.find_one(
        {"user_id": user_id, "broker": slug, "native": True, "broker_user_key": key},
        {"_id": 0},
        sort=[("updated_at", -1)],
    )
    if existing:
        await db.broker_accounts.update_one({"account_id": existing["account_id"]}, {"$set": session})
        return {**existing, **session}

    # Same shape as the OpenAlgo path so /accounts, /disconnect, etc. work uniformly.
    doc = {
        "account_id": f"ba_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "broker": slug,
        "label": display,
        "openalgo_url": "",
        "openalgo_hosted": False,
        "openalgo_per_account_instance": False,
        **session,
        "created_at": now_iso,
        "last_sync_at": None,
        "last_sync_count": 0,
    }
    await db.broker_accounts.insert_one(dict(doc))  # copy: Mongo adds `_id` to what it is given
    return doc


async def end_session(db, account_id: str, reason: str, *, error: str | None = None) -> None:
    """End a native account's session: wipe the encrypted token and extras,
    set status expired + `session_ended_reason`. The row and its synced
    holdings stay. `error`, when given, is stored (shortened) in `last_error`.

    Only native rows are touched — an OpenAlgo row's key is not a broker
    session and is left alone.
    """
    if reason not in END_REASONS:
        raise ValueError(f"Unknown session end reason {reason!r}")
    changes: Dict[str, Any] = {
        "api_key_encrypted": "",
        "api_key_masked": "",
        "extras_encrypted": "",
        "status": STATUS_EXPIRED,
        "session_ended_reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        changes["last_error"] = str(error)[:300]
    await db.broker_accounts.update_one({"account_id": account_id, "native": True}, {"$set": changes})
    logger.info("broker session ended: account=%s reason=%s", account_id, reason)


async def end_sessions_for_user(db, user_id: str, reason: str) -> int:
    """End every native session the user still holds a token for. Returns
    how many were ended. OpenAlgo rows are not touched.
    """
    rows = await db.broker_accounts.find(
        {"user_id": user_id, "native": True}, {"_id": 0, "account_id": 1, "api_key_encrypted": 1},
    ).to_list(length=None)
    ended = 0
    for row in rows:
        if row.get("api_key_encrypted"):
            await end_session(db, row["account_id"], reason)
            ended += 1
    return ended


async def expire_due_sessions(db, *, user_id: str | None = None, now: datetime | None = None) -> int:
    """End native sessions that are past `session_expires_at` (all users, or
    one). Rows whose expiry is not known are left for the broker to reject.
    """
    now = _utc(now)
    query: Dict[str, Any] = {"native": True, "status": STATUS_ACTIVE}
    if user_id:
        query["user_id"] = user_id
    rows = await db.broker_accounts.find(
        query, {"_id": 0, "account_id": 1, "session_expires_at": 1},
    ).to_list(length=None)
    ended = 0
    for row in rows:
        expires = _parse_dt(row.get("session_expires_at"))
        if expires is not None and expires <= now:
            await end_session(db, row["account_id"], "expired")
            ended += 1
    return ended
