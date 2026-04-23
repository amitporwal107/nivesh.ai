"""DPDP-compliant PII encryption.

Provides AES-256-GCM encryption/decryption helpers for sensitive fields
(PAN, Aadhaar, bank account numbers, etc.) at rest. Also offers masked-
display utilities for logs and UI readbacks.

Key sources (in priority order):
    1. PII_ENCRYPTION_KEY env var (base64-encoded 32 bytes)
    2. db secret `PII_ENCRYPTION_KEY` via helpers.secrets
    3. dev-only deterministic fallback (SHA-256 of a fixed label + APP_ENV)
       — logged loudly so prod misconfigs are caught.

Format on disk:
    base64(nonce[12] || ciphertext || tag)   — a single opaque string.

DPDP Act 2023 alignment:
    - Consent-based processing: see services/consents.py
    - Data minimisation: store only encrypted form
    - Right to erasure: plaintext never written; revoke = delete ciphertext
    - Audit: every encrypt/decrypt can be audited via services/audit.py
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12
_KEY_BYTES = 32  # AES-256

_cached_key: Optional[bytes] = None


def _derive_dev_key() -> bytes:
    """Deterministic fallback so dev/test environments always work.
    Production MUST set PII_ENCRYPTION_KEY — a warning is logged otherwise.
    """
    env = os.environ.get("APP_ENV", "local")
    material = f"nivesh-dpdp-dev-fallback::{env}".encode()
    return hashlib.sha256(material).digest()  # 32 bytes


def _get_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    # 1. env var
    raw = os.environ.get("PII_ENCRYPTION_KEY")
    if not raw:
        try:
            from helpers import secrets as _s
            raw = _s.get("PII_ENCRYPTION_KEY")
        except Exception:  # noqa: BLE001
            raw = ""
    if raw:
        try:
            k = base64.b64decode(raw)
            if len(k) != _KEY_BYTES:
                logger.warning(
                    "PII_ENCRYPTION_KEY has wrong length (%d, want 32); "
                    "falling back to dev key.", len(k),
                )
                k = _derive_dev_key()
        except Exception as e:  # noqa: BLE001
            logger.warning("PII_ENCRYPTION_KEY base64 decode failed: %s", e)
            k = _derive_dev_key()
    else:
        logger.warning(
            "PII_ENCRYPTION_KEY not configured — using deterministic dev key "
            "(INSECURE; must be set in prod).",
        )
        k = _derive_dev_key()
    _cached_key = k
    return k


def encrypt(plaintext: str) -> str:
    """AES-256-GCM encrypt a UTF-8 string. Returns base64(nonce||ct)."""
    if plaintext is None:
        return ""
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    pt = plaintext.encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(_get_key()).encrypt(nonce, pt, None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(ciphertext_b64: str) -> Optional[str]:
    """Decrypt a previously-encrypted string. Returns None on failure."""
    if not ciphertext_b64:
        return None
    try:
        blob = base64.b64decode(ciphertext_b64)
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        pt = AESGCM(_get_key()).decrypt(nonce, ct, None)
        return pt.decode("utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("decrypt failed: %s", e)
        return None


# ── Masking helpers ──────────────────────────────────────────────────────
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_AADHAAR_RE = re.compile(r"^\d{12}$")


def mask_pan(pan: Optional[str]) -> str:
    """XXXXX1234X-style masked display — SEBI-approved 4-char reveal."""
    if not pan:
        return ""
    p = pan.strip().upper()
    if _PAN_RE.match(p):
        return f"{'X' * 5}{p[5:9]}{'X'}"
    return "X" * max(len(p) - 4, 4) + p[-4:]


def mask_aadhaar(n: Optional[str]) -> str:
    """Return only last 4 digits (UIDAI masking guidelines)."""
    if not n:
        return ""
    d = "".join(ch for ch in n if ch.isdigit())
    return ("X" * 8) + d[-4:] if len(d) >= 4 else "X" * len(d)


def validate_pan(pan: str) -> Tuple[bool, str]:
    """Return (ok, reason). SEBI/CBDT PAN format: AAAAA9999A."""
    if not pan:
        return False, "empty"
    p = pan.strip().upper()
    if not _PAN_RE.match(p):
        return False, "invalid_format"
    return True, "ok"
