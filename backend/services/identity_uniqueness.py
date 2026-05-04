"""Cross-collection identity uniqueness checks.

A single client / user may show up in three places:
  - `users`     : real signed-up users + advisor "shadow" users
  - `profiles`  : advisor client profiles (one per client per workspace)

We treat email, mobile (last-10 digits) and PAN as identity keys. When
an advisor adds or edits a client, we refuse the operation if any of
those keys already exists on a *different* row anywhere in the system.

This stops the "ghost user" pattern where the same person shows up
twice with different names because the second insert went via a flow
that didn't check.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from deps import db

logger = logging.getLogger(__name__)


# ── Normalisation ──────────────────────────────────────────────────────
def normalise_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    e = email.strip().lower()
    return e or None


def normalise_mobile(mobile: Optional[str]) -> Optional[str]:
    """Reduce mobile to its last 10 digits — that uniquely identifies an
    Indian number regardless of country code / formatting (`+91 98xxx`,
    `098xxx`, `91-98xxx` all collapse to the same key)."""
    if not mobile:
        return None
    digits = re.sub(r"\D", "", str(mobile))
    if len(digits) < 10:
        return None
    return digits[-10:]


_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def normalise_pan(pan: Optional[str]) -> Optional[str]:
    if not pan:
        return None
    p = re.sub(r"\s", "", str(pan)).upper()
    if not _PAN_RE.match(p):
        return None
    return p


# ── Types ──────────────────────────────────────────────────────────────
@dataclass
class IdentityConflict:
    """One conflicting row found in users / profiles."""
    field: str                       # "email" | "mobile" | "pan"
    value: str                       # the matched value (lowercased / digits-only / upper PAN)
    collection: str                  # "users" | "profiles"
    record_id: str                   # user_id or profile_id
    record_name: Optional[str]       # name on the existing row
    workspace_id: Optional[str]      # for profiles
    owner_user_id: Optional[str]     # for profiles (advisor who owns the client)


@dataclass
class IdentityCheckResult:
    ok: bool
    conflicts: List[IdentityConflict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "conflicts": [
                {
                    "field": c.field,
                    "value": c.value,
                    "collection": c.collection,
                    "record_id": c.record_id,
                    "record_name": c.record_name,
                    "workspace_id": c.workspace_id,
                    "owner_user_id": c.owner_user_id,
                }
                for c in self.conflicts
            ],
        }


# ── Core check ────────────────────────────────────────────────────────
async def check_identity_uniqueness(
    *,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    pan: Optional[str] = None,
    exclude_profile_id: Optional[str] = None,
    exclude_user_id: Optional[str] = None,
) -> IdentityCheckResult:
    """Return all rows in `users` + `profiles` whose email / mobile / PAN
    matches any of the passed identifiers, excluding the profile or user
    being edited (so update flows don't conflict with themselves).

    Lookup keys are matched on a normalised form (`mobile_norm`,
    `email_norm`, `pan_norm`) which we maintain as denormalised columns
    for fast index lookup. We *also* fall back to the raw fields so this
    works on legacy rows that haven't been backfilled yet.
    """
    e_norm = normalise_email(email)
    m_norm = normalise_mobile(mobile)
    p_norm = normalise_pan(pan)
    if not (e_norm or m_norm or p_norm):
        return IdentityCheckResult(ok=True)

    conflicts: List[IdentityConflict] = []

    # ── profiles ───────────────────────────────────────────────────────
    profile_filters: List[Dict[str, Any]] = []
    if e_norm:
        profile_filters.append({"$or": [{"email_norm": e_norm}, {"email": e_norm}]})
    if m_norm:
        profile_filters.append({"mobile_norm": m_norm})
    if p_norm:
        profile_filters.append({"pan_norm": p_norm})
    if profile_filters:
        q: Dict[str, Any] = {"$or": profile_filters}
        if exclude_profile_id:
            q["profile_id"] = {"$ne": exclude_profile_id}
        async for p in db.profiles.find(
            q,
            {"_id": 0, "profile_id": 1, "name": 1, "workspace_id": 1,
             "owner_user_id": 1, "shadow_owner_user_id": 1,
             "email": 1, "email_norm": 1,
             "mobile": 1, "mobile_norm": 1,
             "pan": 1, "pan_norm": 1},
        ):
            for fld, key, want in (
                ("email",  "email_norm",  e_norm),
                ("mobile", "mobile_norm", m_norm),
                ("pan",    "pan_norm",    p_norm),
            ):
                if not want:
                    continue
                got = p.get(key)
                if not got and fld == "email":
                    got = (p.get("email") or "").strip().lower() or None
                if got == want:
                    conflicts.append(IdentityConflict(
                        field=fld,
                        value=want,
                        collection="profiles",
                        record_id=p.get("profile_id") or "",
                        record_name=p.get("name"),
                        workspace_id=p.get("workspace_id"),
                        owner_user_id=p.get("owner_user_id") or p.get("shadow_owner_user_id"),
                    ))

    # ── users ──────────────────────────────────────────────────────────
    user_filters: List[Dict[str, Any]] = []
    if e_norm:
        user_filters.append({"$or": [{"email_norm": e_norm}, {"email": e_norm}]})
    if m_norm:
        user_filters.append({"mobile_norm": m_norm})
    if p_norm:
        user_filters.append({"pan_norm": p_norm})
    if user_filters:
        q = {"$or": user_filters}
        if exclude_user_id:
            q["user_id"] = {"$ne": exclude_user_id}
        async for u in db.users.find(
            q,
            {"_id": 0, "user_id": 1, "name": 1, "is_shadow": 1,
             "shadow_owner_user_id": 1,
             "email": 1, "email_norm": 1,
             "mobile": 1, "mobile_norm": 1,
             "pan": 1, "pan_norm": 1},
        ):
            for fld, key, want in (
                ("email",  "email_norm",  e_norm),
                ("mobile", "mobile_norm", m_norm),
                ("pan",    "pan_norm",    p_norm),
            ):
                if not want:
                    continue
                got = u.get(key)
                if not got and fld == "email":
                    got = (u.get("email") or "").strip().lower() or None
                if got == want:
                    conflicts.append(IdentityConflict(
                        field=fld,
                        value=want,
                        collection="users",
                        record_id=u.get("user_id") or "",
                        record_name=u.get("name"),
                        workspace_id=None,
                        owner_user_id=u.get("shadow_owner_user_id"),
                    ))

    return IdentityCheckResult(ok=not conflicts, conflicts=conflicts)


# ── Helpers callers use after a successful check ──────────────────────
def stamped_identity_fields(
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    pan: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a dict of `{email, email_norm, mobile, mobile_norm, pan, pan_norm}`
    suitable for `$set` on an insert / update. Use after `check_identity_uniqueness`
    has passed so we keep the denormalised-key index in sync."""
    out: Dict[str, Any] = {}
    if email is not None:
        clean = (email or "").strip().lower() or None
        out["email"] = clean
        out["email_norm"] = clean
    if mobile is not None:
        norm = normalise_mobile(mobile)
        out["mobile"] = re.sub(r"\D", "", str(mobile or "")) or None
        out["mobile_norm"] = norm
    if pan is not None:
        norm = normalise_pan(pan)
        out["pan"] = norm or (pan or "").strip().upper() or None
        out["pan_norm"] = norm
    return out


# ── One-shot duplicate scan (admin tool) ──────────────────────────────
async def scan_existing_duplicates() -> Dict[str, Any]:
    """Walk both collections and report every identifier (email / mobile /
    PAN) that maps to more than one record. Used to surface ghost users
    that pre-date the uniqueness gate."""
    results: Dict[str, Any] = {"email": [], "mobile": [], "pan": []}

    for col_name, id_field in (("profiles", "profile_id"), ("users", "user_id")):
        col = db[col_name]
        for fld in ("email_norm", "mobile_norm", "pan_norm"):
            pipeline = [
                {"$match": {fld: {"$ne": None, "$exists": True}}},
                {"$group": {"_id": f"${fld}", "rows": {
                    "$push": {"id": f"${id_field}", "name": "$name", "collection": col_name},
                }, "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 200},
            ]
            short_fld = fld.replace("_norm", "")
            async for d in col.aggregate(pipeline):
                results[short_fld].append({
                    "value": d["_id"],
                    "count": d["n"],
                    "rows": d["rows"],
                })
    return results


async def ensure_identity_indexes() -> None:
    """Create sparse-unique indexes on the normalised identity columns.
    Called from server startup. Sparse so legacy rows without these
    fields don't trip the index, but two rows with the same value WILL
    collide at write time as a backstop to the route-level check."""
    for coll in (db.profiles, db.users):
        try:
            await coll.create_index("email_norm", sparse=True, unique=False)
            await coll.create_index("mobile_norm", sparse=True, unique=False)
            await coll.create_index("pan_norm", sparse=True, unique=False)
        except Exception:  # noqa: BLE001
            logger.warning("identity index create failed", exc_info=True)
