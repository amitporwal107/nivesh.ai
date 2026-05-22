"""SHA-256 helpers — checksum + PAN hash."""
from __future__ import annotations

import hashlib


def pan_hash(pan: str) -> str:
    """Canonical PAN hash (PRD §6.2).

    Uppercases + strips the PAN before hashing so case / whitespace don't
    create distinct user records for the same legal entity.
    """
    cleaned = (pan or "").strip().upper()
    if len(cleaned) != 10:
        raise ValueError(f"PAN must be 10 characters; got {len(cleaned)}")
    return hashlib.sha256(cleaned.encode("ascii")).hexdigest()


def is_pan_hash(value: str | None) -> bool:
    return bool(value) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )
