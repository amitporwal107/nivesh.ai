"""DPDP Act 2023 consent ledger.

Users must explicitly grant consent for each processing purpose (data
fiduciary obligation). Each grant is immutable and timestamped; withdrawals
write a NEW row (status=withdrawn) rather than mutating the original, so
the full consent history is preserved for audit.

Purposes (PURPOSES dict):
    data_processing  : Mandatory — store holdings for analysis.
    advice_ai        : Optional — send anonymised portfolio to LLM for advice.
    scraping_fetch   : Optional — fetch live prices/ratings from third parties
                       (Groww, Moneycontrol) using only public data.
    marketing_comms  : Optional — email/SMS communications, product updates.
    partner_sharing  : Optional — share with vetted partners (e.g. distributors).

Schema:
    _id, consent_id, user_id, purpose, version, status (granted|withdrawn),
    granted_at / withdrawn_at, ip, ua, notes.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CURRENT_VERSION = "1.0"

# Privacy-notice text pinned to a version — changing text forces re-consent.
PURPOSES: Dict[str, Dict[str, str]] = {
    "data_processing": {
        "title": "Store and analyse portfolio data",
        "description": (
            "nivesh.ai stores your mutual fund and stock holdings (parsed from "
            "CAS) to run health analytics, tax insights, and rebalancing "
            "recommendations. Data is retained only while your account is "
            "active. You can revoke this any time and we will delete all "
            "holdings within 30 days."
        ),
        "required": "true",
    },
    "advice_ai": {
        "title": "AI-powered advice via third-party LLM",
        "description": (
            "We send anonymised portfolio composition (fund names, weights, "
            "sectors — never PAN / email / bank info) to OpenAI's GPT-4o-mini "
            "to generate personalised advice. Refusing means you won't see "
            "Copilot AI recommendations but all other features keep working."
        ),
        "required": "false",
    },
    "scraping_fetch": {
        "title": "Fetch live prices and ratings",
        "description": (
            "Fetch live NAV, stock prices, and Morningstar ratings from public "
            "sources (Groww, Moneycontrol, AMFI). No user data leaves our servers."
        ),
        "required": "false",
    },
    "marketing_comms": {
        "title": "Product emails and notifications",
        "description": (
            "Receive product updates, new-feature announcements, and portfolio "
            "insights via email / SMS. Unsubscribe anytime."
        ),
        "required": "false",
    },
    "partner_sharing": {
        "title": "Share with partner distributors",
        "description": (
            "Share pseudonymised portfolio recommendations with regulated "
            "partner distributors to help you execute trades. Disabled by default."
        ),
        "required": "false",
    },
}


async def current_for_user(user_id: str) -> Dict[str, Dict[str, Any]]:
    """Return the latest consent row per purpose (None if never granted)."""
    from deps import db
    out: Dict[str, Dict[str, Any]] = {}
    cursor = db.consent_records.find(
        {"user_id": user_id}, {"_id": 0},
    ).sort("granted_at", -1)
    async for row in cursor:
        p = row.get("purpose")
        if p and p not in out:
            out[p] = row
    return out


async def grant(
    *,
    user_id: str,
    purpose: str,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a consent grant (or re-grant after withdrawal). Immutable row."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown_purpose:{purpose}")
    entry = {
        "consent_id": f"cns_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "purpose": purpose,
        "version": CURRENT_VERSION,
        "status": "granted",
        "granted_at": datetime.now(timezone.utc).isoformat(),
        "withdrawn_at": None,
        "ip": (ip or "")[:64],
        "ua": (ua or "")[:200],
        "notes": notes,
    }
    from deps import db
    await db.consent_records.insert_one(entry)
    # Mutated by mongo — strip _id before returning.
    entry.pop("_id", None)
    # Audit trail.
    from services import audit
    await audit.record(
        user_id=user_id, action="consent_grant", resource=purpose,
        ip=ip, ua=ua, details={"version": CURRENT_VERSION},
    )
    return entry


async def withdraw(
    *,
    user_id: str,
    purpose: str,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a withdrawal row. Previous `granted` rows remain — this is a
    new immutable record of the withdrawal action for audit."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown_purpose:{purpose}")
    if PURPOSES[purpose].get("required") == "true":
        raise ValueError(f"cannot_withdraw_required:{purpose}")
    entry = {
        "consent_id": f"cns_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "purpose": purpose,
        "version": CURRENT_VERSION,
        "status": "withdrawn",
        "granted_at": None,
        "withdrawn_at": datetime.now(timezone.utc).isoformat(),
        "ip": (ip or "")[:64],
        "ua": (ua or "")[:200],
    }
    from deps import db
    await db.consent_records.insert_one(entry)
    entry.pop("_id", None)
    from services import audit
    await audit.record(
        user_id=user_id, action="consent_withdraw", resource=purpose,
        ip=ip, ua=ua,
    )
    return entry


async def has_granted(user_id: str, purpose: str) -> bool:
    """Quick check used by endpoint guards."""
    latest = await current_for_user(user_id)
    row = latest.get(purpose)
    return bool(row and row.get("status") == "granted")
