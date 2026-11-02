"""CAS unlock secrets at rest: the PAN and a user-entered statement password.

A consolidated account statement (CAS) arrives as a password-locked PDF. NSDL
and CDSL eCAS are locked with the upper-cased PAN; a CAMS / KFintech mailback
statement can be locked with a password the user chose. Nivesh keeps whichever
the user gave so later imports (manual, Gmail, the daily sweep) can unlock the
file. Both are secrets, so they are stored AES-256-GCM encrypted through
`services.pii_security`, never in the clear:

    pan_encrypted               ciphertext of the upper-cased PAN
    pan_last4                   the four digits of a PAN-shaped value, for a masked display
    cas_pdf_password_encrypted  ciphertext of the statement password, verbatim (case-sensitive)

on `user_profiles`, mirrored on `gmail_tokens` for the auto-import scheduler.

Rows written before this module hold the same values in the clear: `pan`,
`cas_password` (a PAN mirror) and `cas_pdf_password`. They are still READ as a
fallback until `scripts/encrypt_cas_secrets.py` has encrypted them, and every
write through this module unsets them.

Encryption fails closed. Outside a dev environment, with no PII_ENCRYPTION_KEY,
`pii_security.encrypt` raises, and nothing is stored in the clear instead.

The advisor side (`users.pan`, `profiles.pan` and their `pan_norm` lookup keys)
is a separate store and is not handled here.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from services import pii_security

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

PAN_FIELD = "pan_encrypted"
PAN_LAST4_FIELD = "pan_last4"
PDF_PASSWORD_FIELD = "cas_pdf_password_encrypted"

#: Plaintext fields of the old shape. Read as a fallback, unset on every write.
LEGACY_PAN_FIELDS = ("pan", "cas_password")
LEGACY_PDF_PASSWORD_FIELD = "cas_pdf_password"
LEGACY_FIELDS = LEGACY_PAN_FIELDS + (LEGACY_PDF_PASSWORD_FIELD,)

#: `$unset` documents that go with each write.
UNSET_PAN: Dict[str, str] = {name: "" for name in LEGACY_PAN_FIELDS}
UNSET_PDF_PASSWORD: Dict[str, str] = {LEGACY_PDF_PASSWORD_FIELD: ""}

#: Matches a `gmail_tokens` row that holds a PAN, encrypted or (until the
#: backfill has run) in the clear. The daily sweep selects on it.
TOKEN_HAS_PAN_FILTER: Dict[str, Any] = {
    "$or": [
        {PAN_FIELD: {"$exists": True, "$ne": ""}},
        {"cas_password": {"$exists": True, "$ne": ""}},
    ],
}


def _clean_pan(pan: str) -> str:
    return (pan or "").strip().upper()


def pan_fields(pan: str) -> Dict[str, str]:
    """`$set` fields for a PAN. Raises ValueError for an empty value and
    RuntimeError (from pii_security) when no encryption key is configured."""
    value = _clean_pan(pan)
    if not value:
        raise ValueError("empty PAN")
    fields = {PAN_FIELD: pii_security.encrypt(value)}
    if PAN_RE.match(value):
        fields[PAN_LAST4_FIELD] = value[5:9]
    return fields


def pdf_password_fields(password: str) -> Dict[str, str]:
    """`$set` fields for a statement password, kept verbatim (case-sensitive)."""
    value = (password or "").strip()
    if not value:
        raise ValueError("empty statement password")
    return {PDF_PASSWORD_FIELD: pii_security.encrypt(value)}


def stored_pan(doc: Optional[Mapping[str, Any]]) -> str:
    """The PAN a row holds, upper-cased, or "" when it holds none."""
    doc = doc or {}
    encrypted = doc.get(PAN_FIELD)
    if encrypted:
        return _clean_pan(pii_security.decrypt(encrypted) or "")
    for name in LEGACY_PAN_FIELDS:
        if doc.get(name):
            return _clean_pan(str(doc[name]))
    return ""


def stored_pdf_password(doc: Optional[Mapping[str, Any]]) -> str:
    """The statement password a row holds, verbatim, or ""."""
    doc = doc or {}
    encrypted = doc.get(PDF_PASSWORD_FIELD)
    if encrypted:
        return (pii_security.decrypt(encrypted) or "").strip()
    return str(doc.get(LEGACY_PDF_PASSWORD_FIELD) or "").strip()


def unlock_password(*docs: Optional[Mapping[str, Any]]) -> str:
    """The password to unlock a CAS PDF, from the given rows in order.

    A saved statement password wins (from the first row that has one), because
    the PAN does not open a statement locked with a user-chosen password.
    Otherwise the PAN, from the first row that has one. "" when neither exists.
    """
    for doc in docs:
        custom = stored_pdf_password(doc)
        if custom:
            return custom
    for doc in docs:
        pan = stored_pan(doc)
        if pan:
            return pan
    return ""


def has_pan(doc: Optional[Mapping[str, Any]]) -> bool:
    """True when the row holds a PAN, encrypted or legacy. Does not decrypt."""
    doc = doc or {}
    return bool(doc.get(PAN_FIELD) or any(doc.get(name) for name in LEGACY_PAN_FIELDS))


def legacy_update(doc: Mapping[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """The update that encrypts a row's plaintext secrets and removes them, or
    None when the row holds none. Used by the backfill script.

    When a row already has the encrypted field, the encrypted value is kept and
    the plaintext copy is only removed: after this change ships, every write
    goes through this module, so the encrypted field is the newer one.
    """
    present = [name for name in LEGACY_FIELDS if name in doc]
    if not present:
        return None
    to_set: Dict[str, str] = {}
    if not doc.get(PAN_FIELD):
        pan = next((str(doc[n]) for n in LEGACY_PAN_FIELDS if doc.get(n)), "")
        if pan.strip():
            to_set.update(pan_fields(pan))
    if not doc.get(PDF_PASSWORD_FIELD) and str(doc.get(LEGACY_PDF_PASSWORD_FIELD) or "").strip():
        to_set.update(pdf_password_fields(str(doc[LEGACY_PDF_PASSWORD_FIELD])))
    update: Dict[str, Dict[str, str]] = {"$unset": {name: "" for name in present}}
    if to_set:
        update["$set"] = to_set
    return update
