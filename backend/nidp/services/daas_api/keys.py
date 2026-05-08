"""DaaS API-key issuance + lookup.

Tokens are minted as `nvd_<32-char-base32>` and stored only as their
SHA-256 hex digest. The cleartext token is shown to the issuer once
and never persisted — a leak of nidp.daas_api_keys does not, on its
own, grant API access.

The hash → key-record lookup is cached in-process for short windows
(see auth.py). This module is the cold-path (issue / list / revoke)
plus the verification helper used by auth.py.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from nidp.shared.storage.pg import get_pool


_TOKEN_PREFIX = "nvd_"
_TOKEN_BYTES = 24                    # → 32 chars base32 → 36 chars total
_PLAN_DEFAULTS: Dict[str, Dict[str, Optional[int]]] = {
    # rate_limit_rpm = per-process-minute soft cap (token bucket)
    # daily_quota    = hard 24h cap (DB-counted; null = unlimited)
    "free":     {"rate_limit_rpm": 60,   "daily_quota": 1_000},
    "standard": {"rate_limit_rpm": 300,  "daily_quota": 50_000},
    "pro":      {"rate_limit_rpm": 1500, "daily_quota": 500_000},
    "internal": {"rate_limit_rpm": 6000, "daily_quota": None},
}


@dataclass(frozen=True)
class KeyRecord:
    key_id:         str
    key_prefix:     str
    name:           str
    owner_email:    str
    plan:           str
    rate_limit_rpm: int
    daily_quota:    Optional[int]
    status:         str
    expires_at:     Optional[datetime]


def known_plans() -> List[str]:
    return list(_PLAN_DEFAULTS.keys())


def _generate_token() -> str:
    raw = secrets.token_bytes(_TOKEN_BYTES)
    # urlsafe base64 without padding — 32 chars for 24 bytes.
    body = secrets.token_urlsafe(_TOKEN_BYTES)
    # secrets.token_urlsafe length is approximate; trim to a fixed width.
    body = body[:32]
    return f"{_TOKEN_PREFIX}{body}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _prefix(token: str) -> str:
    # First 12 visible chars: nvd_ + 8 random — enough to grep logs
    # without leaking the secret. Includes the leading nvd_.
    return token[:12]


async def issue_key(
    *,
    name: str,
    owner_email: str,
    plan: str,
    rate_limit_rpm: Optional[int] = None,
    daily_quota: Optional[int] = None,
    expires_at: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Mint a new API key. Returns dict with the cleartext token —
    caller MUST surface it once and then discard. The DB stores only
    the hash."""
    if plan not in _PLAN_DEFAULTS:
        raise ValueError(f"unknown plan {plan!r}; allowed: {known_plans()}")
    defaults = _PLAN_DEFAULTS[plan]
    rate = rate_limit_rpm if rate_limit_rpm is not None else defaults["rate_limit_rpm"]
    quota = daily_quota if daily_quota is not None else defaults["daily_quota"]

    token = _generate_token()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO nidp.daas_api_keys
                (key_prefix, key_hash, name, owner_email, plan,
                 rate_limit_rpm, daily_quota, expires_at, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING key_id, created_at
            """,
            _prefix(token), hash_token(token),
            name, owner_email, plan,
            rate, quota, expires_at, notes,
        )
    return {
        "token":         token,                 # SHOW ONCE
        "key_id":        str(row["key_id"]),
        "key_prefix":    _prefix(token),
        "name":          name,
        "owner_email":   owner_email,
        "plan":          plan,
        "rate_limit_rpm": rate,
        "daily_quota":   quota,
        "created_at":    row["created_at"].isoformat(),
        "expires_at":    expires_at.isoformat() if expires_at else None,
    }


async def lookup_by_hash(token_hash: str) -> Optional[KeyRecord]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT key_id, key_prefix, name, owner_email, plan,
                   rate_limit_rpm, daily_quota, status, expires_at
              FROM nidp.daas_api_keys
             WHERE key_hash = $1
            """,
            token_hash,
        )
    if row is None:
        return None
    return KeyRecord(
        key_id=str(row["key_id"]),
        key_prefix=row["key_prefix"],
        name=row["name"],
        owner_email=row["owner_email"],
        plan=row["plan"],
        rate_limit_rpm=row["rate_limit_rpm"],
        daily_quota=row["daily_quota"],
        status=row["status"],
        expires_at=row["expires_at"],
    )


async def list_keys() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key_id, key_prefix, name, owner_email, plan,
                   rate_limit_rpm, daily_quota, status,
                   created_at, expires_at, last_used_at
              FROM nidp.daas_api_keys
             ORDER BY created_at DESC
            """
        )
    return [
        {
            "key_id":         str(r["key_id"]),
            "key_prefix":     r["key_prefix"],
            "name":           r["name"],
            "owner_email":    r["owner_email"],
            "plan":           r["plan"],
            "rate_limit_rpm": r["rate_limit_rpm"],
            "daily_quota":    r["daily_quota"],
            "status":         r["status"],
            "created_at":     r["created_at"].isoformat() if r["created_at"] else None,
            "expires_at":     r["expires_at"].isoformat() if r["expires_at"] else None,
            "last_used_at":   r["last_used_at"].isoformat() if r["last_used_at"] else None,
        }
        for r in rows
    ]


async def revoke_key(*, key_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE nidp.daas_api_keys
               SET status = 'revoked',
                   revoked_at = NOW()
             WHERE key_id = $1
               AND status <> 'revoked'
            """,
            key_id,
        )
    # 'UPDATE 0' if no row changed
    return not result.endswith(" 0")


async def touch_last_used(key_id: str) -> None:
    """Best-effort update of last_used_at — non-blocking errors swallowed."""
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE nidp.daas_api_keys SET last_used_at = NOW() WHERE key_id = $1",
                key_id,
            )
    except Exception:                                                  # noqa: BLE001
        pass


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
